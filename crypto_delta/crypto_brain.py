"""
Delta Exchange India - BTC Hedging Strategies
=============================================
Multiple hedging approaches for daily expiry options.

Strategies:
1. Delta-Neutral Straddle - Sell ATM straddle, hedge delta
2. Vertical Spread Hedge - Limited risk spread
3. OTM Strangle - Sell both OTM call and put
4. Dynamic Delta Hedge - Continuous rebalancing

Target: $10 capital, 0.1% fees, daily expiry
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class OptionMath:
    """Option pricing and Greek calculations."""

    @staticmethod
    def calculate_greeks(spot: float, strike: float, time_to_expiry: float,
                         volatility: float = 0.8, risk_free: float = 0.0) -> Dict:
        """
        Calculate option Greeks using simplified Black-Scholes.

        Args:
            spot: Current BTC price
            strike: Option strike price
            time_to_expiry: Time to expiry in days
            volatility: Implied volatility (default 80% for BTC)
            risk_free: Risk-free rate

        Returns:
            Dict with delta, gamma, theta, vega
        """
        if time_to_expiry <= 0:
            # At expiry
            if spot > strike:
                return {'delta': 1.0, 'gamma': 0, 'theta': 0, 'vega': 0}
            elif spot < strike:
                return {'delta': 0.0, 'gamma': 0, 'theta': 0, 'vega': 0}
            else:
                return {'delta': 0.5, 'gamma': 0, 'theta': 0, 'vega': 0}

        T = time_to_expiry / 365.0  # Convert to years
        sigma = volatility
        S = spot
        K = strike
        r = risk_free

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        # Call delta
        delta_call = 0.5 + 0.5 * np.tanh(0.5 * d1)  # Approximation
        # Put delta
        delta_put = delta_call - 1

        # Gamma (same for call and put)
        gamma = np.exp(-d1**2 / 2) / (S * sigma * np.sqrt(2 * np.pi * T)) if T > 0 else 0

        # Theta (per day)
        theta_call = -S * gamma * sigma / (2 * np.sqrt(T)) if T > 0 else 0
        theta_call = theta_call / 365.0  # Per day

        # Vega (per 1% vol change)
        vega = S * np.sqrt(T) * np.exp(-d1**2 / 2) / np.sqrt(2 * np.pi) / 100.0 if T > 0 else 0

        return {
            'call_delta': delta_call,
            'put_delta': delta_put,
            'gamma': gamma,
            'theta': theta_call,
            'vega': vega
        }

    @staticmethod
    def black_scholes_price(spot: float, strike: float, time_to_expiry: float,
                            volatility: float = 0.8, risk_free: float = 0.0,
                            option_type: str = 'CE') -> float:
        """Simplified BS price."""
        if time_to_expiry <= 0:
            if option_type == 'CE':
                return max(0, spot - strike)
            else:
                return max(0, strike - spot)

        T = time_to_expiry / 365.0
        sigma = volatility
        S = spot
        K = strike
        r = risk_free

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == 'CE':
            price = S * 0.5 * (1 + np.tanh(0.5 * d1)) - K * np.exp(-r * T) * 0.5 * (1 + np.tanh(0.5 * d2))
        else:
            price = K * np.exp(-r * T) * 0.5 * (1 - np.tanh(0.5 * d2)) - S * 0.5 * (1 - np.tanh(0.5 * d1))

        return max(0.01, price)


class HedgingStrategy:
    """Base hedging strategy."""

    def __init__(self, capital: float = 10.0):
        self.capital = capital
        self.positions = []
        self.hedges = []
        self.total_delta = 0.0
        self.total_gamma = 0.0
        self.total_theta = 0.0
        self.total_vega = 0.0

    def calculate_portfolio_greeks(self) -> Dict:
        """Calculate total portfolio Greeks."""
        return {
            'delta': self.total_delta,
            'gamma': self.total_gamma,
            'theta': self.total_theta,
            'vega': self.total_vega
        }

    def check_hedge_needed(self) -> bool:
        """Check if portfolio needs rehedging."""
        return abs(self.total_delta) > 0.1

    def add_position(self, position: Dict):
        """Add position and update Greeks."""
        self.positions.append(position)
        self.total_delta += position.get('delta', 0) * position.get('size', 1)
        self.total_gamma += position.get('gamma', 0) * position.get('size', 1)
        self.total_theta += position.get('theta', 0) * position.get('size', 1)
        self.total_vega += position.get('vega', 0) * position.get('size', 1)

    def get_hedge_quantity(self, target_delta: float, hedge_delta: float) -> float:
        """Calculate hedge quantity to achieve target delta."""
        if hedge_delta == 0:
            return 0
        return (target_delta - self.total_delta) / hedge_delta


class DeltaNeutralStraddle(HedgingStrategy):
    """
    Delta-Neutral Straddle Strategy
    ===============================
    1. Sell ATM Call + ATM Put (straddle)
    2. Continuously hedge delta using spot or opposing options
    3. Collect theta while maintaining delta neutrality

    Pros:
    - Low directional risk
    - High theta collection
    - Works in sideways/choppy markets

    Cons:
    - High gamma risk near spot
    - Requires frequent rebalancing
    """

    name = "Delta-Neutral Straddle"

    def find_setup(self, spot: float, options: List[Dict]) -> Optional[Dict]:
        """Find ATM straddle opportunity."""
        if not options or spot <= 0:
            return None

        # Find ATM options
        atm_calls = [o for o in options if o.get('contract_type') == 'call_options']
        atm_puts = [o for o in options if o.get('contract_type') == 'put_options']

        if not atm_calls or not atm_puts:
            return None

        # Find closest to ATM
        best_call = min(atm_calls, key=lambda x: abs(float(x.get('strike_price', 0)) - spot))
        best_put = min(atm_puts, key=lambda x: abs(float(x.get('strike_price', 0)) - spot))

        call_strike = float(best_call.get('strike_price', 0))
        put_strike = float(best_put.get('strike_price', 0))

        # ATM = within 0.5% of spot
        if abs(call_strike - spot) / spot > 0.005:
            return None
        if abs(put_strike - spot) / spot > 0.005:
            return None

        # Get prices
        call_bid = float(best_call.get('bid_price', 0) or 0)
        put_bid = float(best_put.get('bid_price', 0) or 0)

        if call_bid <= 0 or put_bid <= 0:
            return None

        # Check if we can afford both + hedge
        total_cost = call_bid + put_bid  # We receive this premium
        if total_bid_premium < 2.0:  # Minimum premium threshold
            return None

        # Calculate initial Greeks
        ttm = self._get_ttm(best_call)
        call_greeks = OptionMath.calculate_greeks(spot, call_strike, ttm, volatility=0.8)
        put_greeks = OptionMath.calculate_greeks(spot, put_strike, ttm, volatility=0.8)

        return {
            'strategy': 'straddle',
            'call': best_call,
            'put': best_put,
            'call_strike': call_strike,
            'put_strike': put_strike,
            'call_bid': call_bid,
            'put_bid': put_bid,
            'total_premium': call_bid + put_bid,
            'initial_delta': call_greeks['call_delta'] + put_greeks['put_delta'],
            'initial_gamma': call_greeks['gamma'] + put_greeks['gamma'],
            'initial_theta': call_greeks['theta'] + put_greeks['theta'],
            'initial_vega': call_greeks['vega'] + put_greeks['vega']
        }

    def calculate_hedge(self, setup: Dict, spot: float) -> Dict:
        """Calculate hedge to maintain delta neutrality."""
        current_delta = setup['initial_delta']

        # Target: delta between -0.05 and +0.05
        if abs(current_delta) < 0.05:
            return {'action': 'none', 'reason': 'Already delta-neutral'}

        # Hedge direction
        if current_delta > 0.05:
            # Too bullish, need to short spot or buy puts
            hedge_side = 'short_spot' if current_delta > 0.1 else 'buy_put'
            hedge_qty = current_delta  # Delta of spot = 1
        else:
            # Too bearish, need to long spot or buy calls
            hedge_side = 'long_spot' if current_delta < -0.1 else 'buy_call'
            hedge_qty = abs(current_delta)

        return {
            'action': hedge_side,
            'quantity': hedge_qty,
            'reason': f'Portfolio delta: {current_delta:.3f}'
        }


class VerticalSpread(HedgingStrategy):
    """
    Vertical Spread Hedge Strategy
    ==============================
    1. Sell 1 OTM option (higher premium)
    2. Buy 1 further OTM option (protection)
    3. Net credit = max profit
    4. Max loss = spread width - net credit

    Pros:
    - Defined max loss
    - Lower margin requirement
    - Works in trending markets

    Cons:
    - Lower premium than straddle
    - Capped profit
    """

    name = "Vertical Spread"

    def find_setup(self, spot: float, options: List[Dict], signal: str) -> Optional[Dict]:
        """Find vertical spread opportunity."""
        if not options or spot <= 0:
            return None

        # For bearish signal: Sell call spread
        # For bullish signal: Sell put spread
        if signal == 'BEARISH':
            candidates = [o for o in options if o.get('contract_type') == 'call_options']
        else:
            candidates = [o for o in options if o.get('contract_type') == 'put_options']

        if len(candidates) < 2:
            return None

        # Sort by strike
        candidates.sort(key=lambda x: float(x.get('strike_price', 0)))

        # Find spread: sell near ATM, buy further OTM
        for i, sell_opt in enumerate(candidates):
            sell_strike = float(sell_opt.get('strike_price', 0))
            sell_bid = float(sell_opt.get('bid_price', 0) or 0)

            if sell_bid <= 0:
                continue

            # Find hedge leg (further OTM)
            for buy_opt in candidates[i+1:]:
                buy_strike = float(buy_opt.get('strike_price', 0))
                buy_ask = float(buy_opt.get('ask_price', 0) or 0)

                if buy_ask <= 0:
                    continue

                spread_width = abs(buy_strike - sell_strike)
                net_credit = sell_bid - buy_ask

                if net_credit <= 0:
                    continue

                max_loss = spread_width - net_credit
                if max_loss > 5.0:  # Max $5 loss per spread
                    continue

                return {
                    'strategy': 'vertical_spread',
                    'sell_leg': sell_opt,
                    'buy_leg': buy_opt,
                    'sell_strike': sell_strike,
                    'buy_strike': buy_strike,
                    'net_credit': net_credit,
                    'max_loss': max_loss,
                    'spread_width': spread_width,
                    'signal': signal
                }

        return None


class DynamicDeltaHedge(HedgingStrategy):
    """
    Dynamic Delta Hedging Strategy
    ==============================
    1. Start with directional position based on trend
    2. Continuously hedge delta using spot/futures
    3. Rebalance when delta exceeds threshold

    Pros:
    - Market neutral
    - Profits from volatility
    - Works in all market conditions

    Cons:
    - Frequent trades (fee sensitive)
    - Requires constant monitoring
    - Slippage risk
    """

    name = "Dynamic Delta Hedge"

    def __init__(self, capital: float = 10.0, rebalance_threshold: float = 0.15):
        super().__init__(capital)
        self.rebalance_threshold = rebalance_threshold
        self.last_hedge_time = None

    def needs_rebalance(self, current_time: datetime) -> bool:
        """Check if rebalancing is needed."""
        if self.last_hedge_time is None:
            return True

        time_since_hedge = (current_time - self.last_hedge_time).total_seconds()
        return (time_since_hedge >= 300 or  # 5 minutes
                abs(self.total_delta) > self.rebalance_threshold)

    def calculate_hedge(self, spot: float, futures_price: float) -> Optional[Dict]:
        """Calculate hedge quantity."""
        if abs(self.total_delta) < 0.05:
            return None

        # Use futures for hedging (cheaper, no expiry)
        hedge_qty = -self.total_delta  # Opposite sign to neutralize
        hedge_price = futures_price if futures_price > 0 else spot

        return {
            'action': 'hedge_futures',
            'side': 'buy' if hedge_qty > 0 else 'sell',
            'quantity': abs(hedge_qty),
            'price': hedge_price,
            'reason': f'Delta: {self.total_delta:.3f}'
        }


class IronCondorLite(HedgingStrategy):
    """
    Iron Condor Lite - $10 Friendly
    =================================
    1. Sell 1 OTM Call + 1 OTM Put (collect premium)
    2. Buy 1 further OTM Call + 1 further OTM Put (protection)
    3. Net credit with defined max loss

    Pros:
    - Defined risk
    - High probability of profit
    - Works in sideways markets

    Cons:
    - Lower premium
    - Requires all 4 legs
    """

    name = "Iron Condor Lite"

    def find_setup(self, spot: float, options: List[Dict]) -> Optional[Dict]:
        """Find iron condor opportunity."""
        if not options or spot <= 0:
            return None

        calls = [o for o in options if o.get('contract_type') == 'call_options']
        puts = [o for o in options if o.get('contract_type') == 'put_options']

        if len(calls) < 2 or len(puts) < 2:
            return None

        # Sort by strike
        calls.sort(key=lambda x: float(x.get('strike_price', 0)))
        puts.sort(key=lambda x: float(x.get('strike_price', 0)))

        # Find OTM options (1-3% away from spot)
        otm_calls = [c for c in calls if float(c.get('strike_price', 0)) > spot * 1.01]
        otm_puts = [p for p in puts if float(p.get('strike_price', 0)) < spot * 0.99]

        if len(otm_calls) < 2 or len(otm_puts) < 2:
            return None

        # Sell nearest OTM, buy further OTM
        sell_call = otm_calls[0]
        buy_call = otm_calls[1]
        sell_put = otm_puts[-1]  # Closest to spot from below
        buy_put = otm_puts[-2]   # Further below

        sell_call_bid = float(sell_call.get('bid_price', 0) or 0)
        buy_call_ask = float(buy_call.get('ask_price', 0) or 0)
        sell_put_bid = float(sell_put.get('bid_price', 0) or 0)
        buy_put_ask = float(buy_put.get('ask_price', 0) or 0)

        if any(p <= 0 for p in [sell_call_bid, buy_call_ask, sell_put_bid, buy_put_ask]):
            return None

        net_credit = sell_call_bid + sell_put_bid - buy_call_ask - buy_put_ask
        if net_credit <= 0:
            return None

        call_width = float(buy_call.get('strike_price', 0)) - float(sell_call.get('strike_price', 0))
        put_width = float(sell_put.get('strike_price', 0)) - float(buy_put.get('strike_price', 0))
        max_loss = max(call_width, put_width) - net_credit

        return {
            'strategy': 'iron_condor_lite',
            'sell_call': sell_call,
            'buy_call': buy_call,
            'sell_put': sell_put,
            'buy_put': buy_put,
            'net_credit': net_credit,
            'max_loss': max_loss,
            'prob_profit': 0.65  # Estimated
        }


# ============================================================
# STRATEGY SELECTOR
# ============================================================
class StrategySelector:
    """Select best hedging strategy based on market conditions."""

    def __init__(self):
        self.strategies = {
            'straddle': DeltaNeutralStraddle(),
            'vertical_spread': VerticalSpread(),
            'dynamic_hedge': DynamicDeltaHedge(),
            'iron_condor': IronCondorLite()
        }

    def select(self, market_state: Dict) -> Tuple[str, HedgingStrategy]:
        """
        Select strategy based on market conditions.

        Args:
            market_state: Dict with spot, volatility, trend, etc.

        Returns:
            (strategy_name, strategy_instance)
        """
        volatility = market_state.get('volatility', 0.8)
        trend = market_state.get('trend', 'neutral')
        spot = market_state.get('spot', 0)

        # High volatility + neutral trend = Iron Condor
        if volatility > 1.0 and trend == 'neutral':
            return 'iron_condor', self.strategies['iron_condor']

        # Strong trend = Vertical Spread
        if trend in ['bullish', 'bearish']:
            return 'vertical_spread', self.strategies['vertical_spread']

        # Low volatility = Straddle
        if volatility < 0.6:
            return 'straddle', self.strategies['straddle']

        # Default: Dynamic Hedge
        return 'dynamic_hedge', self.strategies['dynamic_hedge']
