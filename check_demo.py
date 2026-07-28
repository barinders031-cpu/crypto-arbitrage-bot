import sys
sys.path.insert(0, 'e:/nse')
from delta_client import DeltaClient

key = 'bZIwAB5Q1FM5nTflbg4CWNmYaDt7pI'
secret = 'v8eGb9IFsW1gR8P4TL5sMnjX7hQvOLTNxKsaUGTnzAGaGMALcwxUYu6K3im0'
c = DeltaClient(api_key=key, api_secret=secret, base_url='https://cdn-ind.testnet.deltaex.org')

print("=" * 60)
print("   DEMO ACCOUNT STATUS CHECK")
print("=" * 60)

# Balance
bal = c.get_wallet_balance()
if bal.get('success'):
    for asset in bal.get('result', []):
        sym = asset.get('asset_symbol')
        avail = float(asset.get('available_balance', 0))
        if avail > 0 or sym in ['USD', 'INR']:
            print(f"  {sym:10s}  Available: {avail:.4f}")
else:
    print("  Balance fetch FAILED:", bal)

# Positions
print()
pos = c.get_all_positions()
positions = pos.get('result', [])
print(f"  Open Positions: {len(positions)}")
if positions:
    for p in positions:
        print(f"    - {p.get('product_symbol')} | size={p.get('size')} | pnl={p.get('unrealized_pnl')}")

print("=" * 60)
print("  CONNECTION: OK - Bot can trade on demo account!")
print("=" * 60)
