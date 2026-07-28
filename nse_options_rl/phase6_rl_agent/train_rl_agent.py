"""
╔═══════════════════════════════════════════════════════════════╗
║   NIFTY OPTIONS REINFORCEMENT LEARNING (PPO) TRAINING SCRIPT  ║
║   Google Colab Ready — Copy and run in a single Colab cell.  ║
╚═══════════════════════════════════════════════════════════════╝

Colab Instructions:
1. Create a new notebook at: https://colab.research.google.com
2. Upload 'nifty_rl_data.zip' (from E:\\nse\\) using the Colab file upload icon.
3. Copy this ENTIRE file, paste it into a cell, and run!
"""

import os
import sys

# --- COLAB AUTO-ENVIRONMENT DETECT & SETUP ---
IN_COLAB = 'google.colab' in sys.modules

if IN_COLAB:
    print("[Colab Detect] Installing packages and extracting data...")
    # Install dependencies
    os.system("pip install -q gymnasium stable-baselines3 xgboost scikit-learn pandas numpy")
    # Unzip data
    if os.path.exists("nifty_rl_data.zip"):
        os.system("unzip -o nifty_rl_data.zip")
        print("[Colab Detect] Extraction complete.")
    else:
        print("[Colab Detect] ERROR: nifty_rl_data.zip not found! Please upload it first.")
        sys.exit(1)

import time
import zipfile
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO

# Config
PREM_LOW = 100.0
PREM_HIGH = 600.0
TARGET_PTS = 10.0
STOP_PTS = 5.0
QTY = 25
MAX_CANDLES = 12

print("="*65)
print("    NIFTY WEEKLY OPTIONS PPO AGENT TRAINING SESSION    ")
print("="*65)

# --- 1. PRE-PROCESSING & FEATURE ENGINEERING ---
def load_and_preprocess():
    print("\n[1/5] Loading datasets...")
    # Load files (looks in current dir which is Colab root or E:\nse)
    opts_path = 'live_data/NIFTY_options_60d.csv' if os.path.exists('live_data/NIFTY_options_60d.csv') else 'NIFTY_options_60d.csv'
    spot_path = 'live_data/NIFTY_spot_60d.csv' if os.path.exists('live_data/NIFTY_spot_60d.csv') else 'NIFTY_spot_60d.csv'
    vix_path = 'nifty_vix_1y_5min.csv'
    
    opts = pd.read_csv(opts_path)
    spot = pd.read_csv(spot_path)
    try:
        vix = pd.read_csv(vix_path)
    except:
        vix = pd.DataFrame({'timestamp': spot['timestamp'], 'close': 15.0})
        
    opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
    spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
    vix['timestamp'] = pd.to_datetime(vix['timestamp']).dt.tz_localize(None)
    
    print("[2/5] Performing mathematical feature engineering...")
    s = spot.copy()
    s['H'] = s['high']; s['L'] = s['low']; s['O'] = s['open']; s['C'] = s['close']
    s['range'] = s['H'] - s['L']
    s['atr_5'] = s['range'].rolling(5).mean()
    s['atr_20'] = s['range'].rolling(20).mean()
    s['VCS'] = np.where(s['atr_20'] > 0, s['atr_5'] / s['atr_20'], 1.0)
    s['TFS_bull'] = (s['C'] - s['L']) / s['range'].replace(0, 1)
    
    upper = s['H'] - s[['O','C']].max(axis=1)
    lower = s[['O','C']].min(axis=1) - s['L']
    s['WAC'] = np.where(s['range'] > 0, (upper - lower) / s['range'], 0)
    
    s['PDV_3'] = (s['C'] - s['C'].shift(3)) / s['atr_5'].replace(0, 1)
    s['PDV_5'] = (s['C'] - s['C'].shift(5)) / s['atr_5'].replace(0, 1)
    
    vix_s = vix.rename(columns={'close':'vix_val'}).sort_values('timestamp')
    s = pd.merge_asof(s.sort_values('timestamp'), vix_s[['timestamp', 'vix_val']], on='timestamp', direction='backward')
    s['vix_norm'] = s['vix_val'] / 20.0
    
    # Clean Spot
    s = s.dropna().reset_index(drop=True)
    
    print("[3/5] Precomputing Option ATM Premiums for O(1) step execution...")
    # Clean Options
    opts = opts.rename(columns={'close': 'close_opt'})
    
    # Build fast O(1) lookup
    opt_lookup = {}
    for _, row in opts.iterrows():
        # key: (timestamp, strike, type) -> (premium, expiry)
        key = (row['timestamp'], row['strike'], row['opt_type'])
        if key not in opt_lookup:
            opt_lookup[key] = (row['close_opt'], row['expiry'])
            
    # Map ATM CE/PE close to each Spot timestamp
    atm_ce_close = []
    atm_pe_close = []
    atm_ce_strike = []
    atm_pe_strike = []
    atm_ce_expiry = []
    atm_pe_expiry = []
    
    for idx, row in s.iterrows():
        S = row['C']
        K = round(S / 50.0) * 50.0 # Nifty strike step = 50
        t = row['timestamp']
        
        ce_key = (t, K, 'CE')
        pe_key = (t, K, 'PE')
        
        if ce_key in opt_lookup:
            atm_ce_close.append(opt_lookup[ce_key][0])
            atm_ce_expiry.append(opt_lookup[ce_key][1])
        else:
            atm_ce_close.append(np.nan)
            atm_ce_expiry.append(None)
            
        if pe_key in opt_lookup:
            atm_pe_close.append(opt_lookup[pe_key][0])
            atm_pe_expiry.append(opt_lookup[pe_key][1])
        else:
            atm_pe_close.append(np.nan)
            atm_pe_expiry.append(None)
            
        atm_ce_strike.append(K)
        atm_pe_strike.append(K)
        
    s['atm_ce_close'] = atm_ce_close
    s['atm_pe_close'] = atm_pe_close
    s['atm_ce_strike'] = atm_ce_strike
    s['atm_pe_strike'] = atm_pe_strike
    s['atm_ce_expiry'] = atm_ce_expiry
    s['atm_pe_expiry'] = atm_pe_expiry
    
    return s, opt_lookup

# Load datasets globally
spot_df, opt_lookup = load_and_preprocess()

# --- 2. CUSTOM GYMNASIUM ENVIRONMENT ---
class NiftyOptionsTradingEnv(gym.Env):
    def __init__(self, df, features_cols, transaction_cost=0.5):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.features_cols = features_cols
        self.transaction_cost = transaction_cost
        
        # Action space: 0 = Do Nothing, 1 = Buy ATM CE, 2 = Buy ATM PE
        self.action_space = spaces.Discrete(3)
        
        # Obs space: 7 features + position indicator + unrealized PnL + ATM CE Premium + ATM PE Premium = 11 float items
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(len(self.features_cols) + 4,),
            dtype=np.float32
        )
        self.reset()
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 20  # offset to prevent rolling NaN
        self.position = 0       # 0 = None, 1 = CE, 2 = PE
        self.entry_premium = 0.0
        self.held_strike = 0.0
        self.held_type = None
        self.held_expiry = None
        self.entry_step = 0
        
        obs = self._get_obs()
        return obs, {}
        
    def _get_obs(self):
        row = self.df.iloc[self.current_step]
        feat_vals = row[self.features_cols].values.astype(np.float32)
        
        current_pnl = 0.0
        if self.position != 0:
            current_pnl = self._get_held_option_premium() - self.entry_premium
            
        atm_ce = row['atm_ce_close'] if not pd.isna(row['atm_ce_close']) else 50.0
        atm_pe = row['atm_pe_close'] if not pd.isna(row['atm_pe_close']) else 50.0
        
        obs = np.concatenate([
            feat_vals,
            np.array([float(self.position), current_pnl, atm_ce, atm_pe], dtype=np.float32)
        ])
        return obs
        
    def _get_held_option_premium(self):
        row = self.df.iloc[self.current_step]
        key = (row['timestamp'], self.held_strike, self.held_type)
        return opt_lookup.get(key, (self.entry_premium, None))[0]
        
    def step(self, action):
        reward = 0.0
        terminated = False
        truncated = False
        
        row = self.df.iloc[self.current_step]
        
        trade_info = None
        
        if self.position == 0:
            # Try to enter a position
            if action == 1 and not pd.isna(row['atm_ce_close']) and PREM_LOW <= row['atm_ce_close'] <= PREM_HIGH:
                self.position = 1
                self.entry_premium = row['atm_ce_close']
                self.held_strike = row['atm_ce_strike']
                self.held_type = 'CE'
                self.held_expiry = row['atm_ce_expiry']
                self.entry_step = self.current_step
                reward -= self.transaction_cost
            elif action == 2 and not pd.isna(row['atm_pe_close']) and PREM_LOW <= row['atm_pe_close'] <= PREM_HIGH:
                self.position = 2
                self.entry_premium = row['atm_pe_close']
                self.held_strike = row['atm_pe_strike']
                self.held_type = 'PE'
                self.held_expiry = row['atm_pe_expiry']
                self.entry_step = self.current_step
                reward -= self.transaction_cost
        else:
            # We are holding. Check exits
            current_premium = self._get_held_option_premium()
            pnl = current_premium - self.entry_premium
            
            if pnl >= TARGET_PTS:
                reward += TARGET_PTS - self.transaction_cost
                self.position = 0
                trade_info = {
                    'pnl': TARGET_PTS - 2 * self.transaction_cost,
                    'type': self.held_type,
                    'entry_premium': self.entry_premium,
                    'exit_premium': current_premium,
                    'exit_reason': 'target_hit'
                }
            elif pnl <= -STOP_PTS:
                reward += -STOP_PTS - self.transaction_cost
                self.position = 0
                trade_info = {
                    'pnl': -STOP_PTS - 2 * self.transaction_cost,
                    'type': self.held_type,
                    'entry_premium': self.entry_premium,
                    'exit_premium': current_premium,
                    'exit_reason': 'stop_loss'
                }
            elif self.current_step - self.entry_step >= MAX_CANDLES:
                reward += pnl - self.transaction_cost
                self.position = 0
                trade_info = {
                    'pnl': pnl - 2 * self.transaction_cost,
                    'type': self.held_type,
                    'entry_premium': self.entry_premium,
                    'exit_premium': current_premium,
                    'exit_reason': 'max_candles'
                }
                
        # Advance step
        self.current_step += 1
        if self.current_step >= len(self.df) - 1:
            terminated = True
            if self.position != 0:
                current_premium = self._get_held_option_premium()
                pnl = current_premium - self.entry_premium
                reward += pnl - self.transaction_cost
                self.position = 0
                trade_info = {
                    'pnl': pnl - 2 * self.transaction_cost,
                    'type': self.held_type,
                    'entry_premium': self.entry_premium,
                    'exit_premium': current_premium,
                    'exit_reason': 'termination'
                }
                
        obs = self._get_obs()
        info = {}
        if trade_info is not None:
            info['trade'] = trade_info
            
        return obs, reward, terminated, truncated, info

# --- 3. TRAINING PPO AGENT WITH STABLE BASELINES3 ---
def train_rl():
    print("\n[4/5] Preparing training environment and starting PPO agent training...")
    
    # Chronological Split (80% Train, 20% Test)
    split_idx = int(len(spot_df) * 0.80)
    train_df = spot_df.iloc[:split_idx]
    test_df = spot_df.iloc[split_idx:]
    
    features_cols = ['VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'atr_5']
    
    # Initialize Environments
    train_env = NiftyOptionsTradingEnv(train_df, features_cols)
    test_env = NiftyOptionsTradingEnv(test_df, features_cols)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Training on Device: {device.upper()}")
    
    # Initialize PPO Agent
    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=0.0003,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        verbose=1,
        device=device
    )
    
    print("  Learning PPO Policy (100,000 steps)...")
    model.learn(total_timesteps=100000)
    print("  PPO Training complete.")
    
    # Save the trained policy
    model.save("nifty_ppo_agent")
    print("  Saved agent: nifty_ppo_agent.zip")
    
    # --- 4. EVALUATING AGENT ON UNSEEN DATA ---
    print("\n[5/5] Backtesting trained RL Agent on strictly unseen out-of-sample data...")
    
    obs, _ = test_env.reset()
    done = False
    
    trades = []
    pnl_history = []
    step_count = 0
    
    # Track statistics
    wins = 0
    losses = 0
    flat = 0
    
    while not done:
        # Predict action
        action, _states = model.predict(obs, deterministic=True)
        
        # Env step
        obs, reward, terminated, truncated, info = test_env.step(action)
        done = terminated or truncated
        
        # Track trades
        if test_env.position != 0 and step_count % 100 == 0:
            pnl_history.append((test_env.df.iloc[test_env.current_step]['timestamp'], reward))
            
        # PnL statistics are updated when reward is realized (when position goes back to 0)
        if 'trade' in info:
            net_trade_pnl = info['trade']['pnl'] * QTY
            trades.append(net_trade_pnl)
            if net_trade_pnl > 0:
                wins += 1
            else:
                losses += 1
                
        step_count += 1
        
    trades = np.array(trades)
    total_trades = len(trades)
    
    print("\n" + "="*50)
    print("      RL PPO AGENT OUT-OF-SAMPLE BACKTEST RESULTS")
    print("="*50)
    print(f"  Test Period       : {test_df.timestamp.min()} to {test_df.timestamp.max()}")
    print(f"  Total Trades Taken: {total_trades}")
    
    if total_trades > 0:
        win_rate = (wins / total_trades) * 100
        net_profit = trades.sum()
        avg_profit = trades.mean()
        
        print(f"  Win Rate          : {win_rate:.2f}%")
        print(f"  Net Profit (Rs.)  : Rs. {net_profit:,.2f}")
        print(f"  Avg PnL/Trade     : Rs. {avg_profit:,.2f}")
    else:
        print("  Agent took 0 trades during test period.")
    print("="*50)
    
    # Download helper for Colab
    if IN_COLAB:
        from google.colab import files
        try:
            files.download("nifty_ppo_agent.zip")
            print("[Colab Detect] Downloaded nifty_ppo_agent.zip to your local computer.")
        except Exception as e:
            print(f"[Colab Detect] Could not download file: {e}")

if __name__ == '__main__':
    train_rl()
