"""
Delta Exchange India - BTC Hedging Runner
=========================================
Live hedging system for BTC daily expiry options.

Usage:
    python crypto_runner.py          # Live mode
    python crypto_runner.py --scan   # Scan only
    python crypto_runner.py --backtest  # Backtest
"""

import argparse
import time
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto_delta.options_scanner import OptionsScanner
from crypto_delta.crypto_brain import (
    DeltaNeutralStraddle, VerticalSpread, IronCondorLite
)
from crypto_delta.config_crypto import CAPITAL, MAX_POSITIONS


def run_live():
    """Live trading loop."""
    scanner = OptionsScanner()
    print("=" * 70)
    print("  BTC HEDGING SYSTEM - LIVE")
    print("  Delta Exchange India | Daily Expiry Options")
    print("=" * 70)
    print(f"  Capital: ${CAPITAL}")
    print(f"  Max Positions: {MAX_POSITIONS}")
    print("=" * 70)
    print("\n  Scanning for opportunities...\n")

    while True:
        try:
            opportunities = scanner.scan()
            scanner.print_opportunities(opportunities)

            if opportunities:
                print(f"\n  [{datetime.now().strftime('%H:%M:%S')}] Found {len(opportunities)} opportunities")
            else:
                print(f"\n  [{datetime.now().strftime('%H:%M:%S')}] No opportunities")

            time.sleep(60)  # Scan every minute

        except KeyboardInterrupt:
            print("\n\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)


def run_scan():
    """One-time scan."""
    scanner = OptionsScanner()
    print("Scanning for hedging opportunities...")
    opportunities = scanner.scan()
    scanner.print_opportunities(opportunities)

    if opportunities:
        print(f"\nFound {len(opportunities)} opportunities")
        for i, opp in enumerate(opportunities, 1):
            print(f"\n{i}. {opp['strategy'].upper()}")
            print(f"   Spot: ${opp['market']['spot']:,.2f}")
            print(f"   Trend: {opp['market']['trend']}")


def run_backtest():
    """Run backtest on historical data."""
    from crypto_delta.options_scanner import OptionsScanner
    from crypto_delta.crypto_brain import IronCondorLite

    print("Running backtest...")
    scanner = OptionsScanner()

    # Use existing BTC options data
    data_path = "live_data/BSM_Synthetic_BTC_options_60d.csv"
    if not os.path.exists(data_path):
        print(f"Data not found: {data_path}")
        return

    import pandas as pd
    opts = pd.read_csv(data_path)
    opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
    opts['expiry'] = opts['symbol'].str.extract(r'(\d{6})')[0]
    opts['expiry_date'] = pd.to_datetime(opts['expiry'], format='%y%m%d')
    opts['strike'] = opts['symbol'].str.extract(r'-(\d+)-')[0].astype(float)
    opts['type'] = opts['symbol'].str.extract(r'([CP])-')[0].map({'C': 'CE', 'P': 'PE'})
    opts['ttm'] = (opts['expiry_date'] - opts['timestamp']).dt.total_seconds() / 60

    # Daily only
    daily = opts[opts['ttm'] <= 1440].copy()
    print(f"Testing on {len(daily)} daily expiry rows")

    # Simple backtest: Iron Condor on last 20 days
    brain = IronCondorLite(capital=CAPITAL)
    results = []

    for date in daily['timestamp'].dt.date.unique()[-20:]:
        day_data = daily[daily['timestamp'].dt.date == date]
        if len(day_data) == 0:
            continue

        spot = day_data['strike'].median()  # Approximate spot
        options = day_data.to_dict('records')

        setup = brain.find_setup(spot, options)
        if setup:
            results.append({
                'date': date,
                'strategy': 'Iron Condor',
                'net_credit': setup['net_credit'],
                'max_loss': setup['max_loss'],
                'prob_profit': setup['prob_profit']
            })

    if results:
        df = pd.DataFrame(results)
        print(f"\nBacktest Results ({len(df)} days):")
        print(f"  Opportunities found: {len(df)}")
        print(f"  Avg Net Credit: ${df['net_credit'].mean():.2f}")
        print(f"  Avg Max Loss: ${df['max_loss'].mean():.2f}")
        print(f"  Risk/Reward: {df['net_credit'].mean() / df['max_loss'].mean():.2f}")
    else:
        print("No backtest results")


def main():
    parser = argparse.ArgumentParser(description='BTC Hedging System')
    parser.add_argument('--scan', action='store_true', help='One-time scan')
    parser.add_argument('--backtest', action='store_true', help='Run backtest')
    args = parser.parse_args()

    if args.scan:
        run_scan()
    elif args.backtest:
        run_backtest()
    else:
        run_live()


if __name__ == "__main__":
    main()
