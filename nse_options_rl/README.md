# NSE Options RL - Momentum Prediction System

## Project Overview
Reinforcement Learning based AI model for predicting 40-80 point momentum moves in Nifty 50 index for Option Buying strategies.

## Phases

### Phase 1: Data Architecture & Ingestion
- Fetch and clean NSE Nifty Spot data (1-min/5-min)
- Fetch F&O chain data (Open Interest, Implied Volatility)
- Local database storage (SQLite/Pandas)

### Phase 2: Exploratory Data Analysis (EDA) & Market Profiling
- Analyze historical bias: Call vs Put risk-reward
- Identify active timing windows
- Pre-breakout conditions analysis

### Phase 3: Feature Engineering & Greeks Calculation
- Dynamic Option Greeks via Black-Scholes
- Momentum, India VIX spikes, relative volume features
- Environment filters for Option Buying days

### Phase 4: Base Predictive Model (Supervised Learning)
- XGBoost/Random Forest classification model
- Backtesting engine

### Phase 5: Execution Logic & Hedge Fund Terminal
- Entry/Exit parameters
- Terminal dashboard interface

### Phase 6: Advanced Reinforcement Learning (RL)
- PPO/DQN agent training
- Live market optimization

## Status
Ready for Phase 1 implementation.