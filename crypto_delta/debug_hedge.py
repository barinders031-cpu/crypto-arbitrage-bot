"""Debug scanner."""
import sys
sys.path.insert(0, '.')

from crypto_delta.options_scanner import OptionsScanner
from crypto_delta.crypto_brain import IronCondorLite

scanner = OptionsScanner()
market = scanner.get_market_state()
print("Market:", market)

options = scanner.client.get_options_chain(expiry_days=2)
print(f"\nTotal options: {len(options)}")

if options:
    print("\nSample options:")
    for opt in options[:5]:
        print(f"  {opt.get('symbol')} | Strike: {opt.get('strike_price')} | Type: {opt.get('contract_type')} | Bid: {opt.get('bid_price')}")

    # Try iron condor directly
    brain = IronCondorLite()
    setup = brain.find_setup(market['spot'], options)
    print(f"\nIron Condor setup: {setup}")
