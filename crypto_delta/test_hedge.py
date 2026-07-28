"""Quick test of hedging scanner."""
import sys
sys.path.insert(0, '.')

from crypto_delta.options_scanner import OptionsScanner

scanner = OptionsScanner()
print("Scanning for hedging opportunities...")
opportunities = scanner.scan()
print(f"Found {len(opportunities)} opportunities")
for opp in opportunities:
    print(f"  - {opp['strategy']}: {opp['market']['trend']} trend")
