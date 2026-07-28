"""
Delta Exchange India - Options Scanner
=======================================
Scan for hedging opportunities across BTC daily expiry options.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from crypto_delta.delta_client import DeltaClient
from crypto_delta.crypto_brain import (
    OptionMath, DeltaNeutralStraddle, VerticalSpread,
    IronCondorLite, DynamicDeltaHedge, StrategySelector
)
from crypto_delta.config_crypto import API_KEY, API_SECRET, BASE_URL


class OptionsScanner:
    """Scan options for hedging opportunities."""

    def __init__(self):
        self.client = DeltaClient(API_KEY, API_SECRET)
        self.brain = StrategySelector()
        self.option_math = OptionMath()

    def get_market_state(self) -> Dict:
        """Get current market state."""
        ticker = self.client.get_ticker('BTCUSD')
        if 'error' in ticker:
            return {}

        result = ticker.get('result', {})
        spot = float(result.get('close', 0))

        # Estimate volatility from recent candles
        df = self.client.get_klines('BTCUSD', '5m', 100)
        volatility = 0.8  # Default
        if len(df) > 20:
            returns = df['close'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252 * 288)  # Annualized

        # Trend
        trend = 'neutral'
        if len(df) >= 20:
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1] if len(df) >= 50 else ema20

            if spot > ema20 and ema20 > ema50:
                trend = 'bullish'
            elif spot < ema20 and ema20 < ema50:
                trend = 'bearish'

        return {
            'spot': spot,
            'high': float(result.get('high', 0)),
            'low': float(result.get('low', 0)),
            'volume': float(result.get('volume', 0)),
            'volatility': volatility,
            'trend': trend,
            'timestamp': datetime.now()
        }

    def scan(self) -> List[Dict]:
        """Scan for opportunities."""
        market = self.get_market_state()
        if not market or market['spot'] <= 0:
            return []

        spot = market['spot']
        options = self.client.get_options_chain(expiry_days=2)

        if not options:
            return []

        # Select strategy
        strategy_name, strategy = self.brain.select(market)

        opportunities = []

        if strategy_name == 'straddle':
            setup = strategy.find_setup(spot, options)
            if setup:
                hedge = strategy.calculate_hedge(setup, spot)
                opportunities.append({
                    'strategy': strategy_name,
                    'setup': setup,
                    'hedge': hedge,
                    'market': market
                })

        elif strategy_name == 'vertical_spread':
            setup = strategy.find_setup(spot, options, market['trend'])
            if setup:
                opportunities.append({
                    'strategy': strategy_name,
                    'setup': setup,
                    'hedge': {'action': 'none'},
                    'market': market
                })

        elif strategy_name == 'iron_condor':
            setup = strategy.find_setup(spot, options)
            if setup:
                opportunities.append({
                    'strategy': strategy_name,
                    'setup': setup,
                    'hedge': {'action': 'none'},
                    'market': market
                })

        return opportunities

    def print_opportunities(self, opportunities: List[Dict]):
        """Print scan results."""
        if not opportunities:
            print("\n  No hedging opportunities found")
            return

        for opp in opportunities:
            print(f"\n  STRATEGY: {opp['strategy'].upper()}")
            print(f"  Spot: ${opp['market']['spot']:,.2f} | Trend: {opp['market']['trend']}")

            setup = opp['setup']
            if opp['strategy'] == 'straddle':
                print(f"  Call: ${setup['call_bid']:.2f} | Put: ${setup['put_bid']:.2f}")
                print(f"  Total Premium: ${setup['total_premium']:.2f}")
                print(f"  Initial Delta: {setup['initial_delta']:.3f}")
                print(f"  Theta: ${setup['initial_theta']:.2f}/day")
                hedge = opp['hedge']
                if hedge['action'] != 'none':
                    print(f"  HEDGE: {hedge['action']} - {hedge['reason']}")

            elif opp['strategy'] == 'vertical_spread':
                print(f"  Sell: ${setup['sell_strike']:,.0f} | Buy: ${setup['buy_strike']:,.0f}")
                print(f"  Net Credit: ${setup['net_credit']:.2f}")
                print(f"  Max Loss: ${setup['max_loss']:.2f}")

            elif opp['strategy'] == 'iron_condor':
                print(f"  Net Credit: ${setup['net_credit']:.2f}")
                print(f"  Max Loss: ${setup['max_loss']:.2f}")
                print(f"  Prob Profit: {setup['prob_profit']*100:.0f}%")
