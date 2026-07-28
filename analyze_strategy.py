"""
Strategy PayOff Analysis - Delta Exchange Demo
User ki Strategy: Sell C-64000-070826 + Buy P-64000-070826 + Buy BTCUSD Future
"""

# Strategy from screenshot
strategy = {
    'leg1': {'type': 'Short Call', 'strike': 64000, 'expiry': '07 Aug 26', 'lots': 100, 'premium_received': 265},  # approx from screenshot Ask ~$265
    'leg2': {'type': 'Long Put',   'strike': 64000, 'expiry': '07 Aug 26', 'lots': 100, 'premium_paid': 130},       # approx from screenshot Ask ~$130
    'leg3': {'type': 'Long Future','entry': 64130,  'lots': 100},
}

# Fees: ~0.05% taker per leg, contract size = 0.001 BTC
CONTRACT_SIZE = 0.001
LOTS = 100
TAKER_FEE = 0.0005  # 0.05%

call_premium_received = 265  # USD/BTC (market price approx from screenshot)
put_premium_paid = 130       # USD/BTC
future_entry = 64130         # BTC spot/future price

# Net credit from options
net_options_credit = (call_premium_received - put_premium_paid) * CONTRACT_SIZE * LOTS
print(f"Net Options Credit: ${net_options_credit:.2f}")

# Fees on 3 legs
fee_call = call_premium_received * TAKER_FEE * CONTRACT_SIZE * LOTS
fee_put  = put_premium_paid * TAKER_FEE * CONTRACT_SIZE * LOTS
fee_fut  = future_entry * TAKER_FEE * CONTRACT_SIZE * LOTS
total_fees = fee_call + fee_put + fee_fut
print(f"Total Fees (3 legs): ${total_fees:.2f}")

print()
print("=" * 60)
print("  PAYOFF ANALYSIS AT EXPIRY (various BTC prices)")
print("=" * 60)
print(f"  {'BTC Price':>12s} | {'Call P&L':>10s} | {'Put P&L':>10s} | {'Fut P&L':>10s} | {'Net (pre-fee)':>14s} | {'Net (after fee)':>15s}")
print("-" * 90)

scenarios = [60000, 61000, 62000, 63000, 63500, 64000, 64130, 64500, 65000, 66000, 67000, 68000]
for btc in scenarios:
    # Short Call P&L
    call_pnl = (call_premium_received - max(btc - 64000, 0)) * CONTRACT_SIZE * LOTS
    # Long Put P&L
    put_pnl = (max(64000 - btc, 0) - put_premium_paid) * CONTRACT_SIZE * LOTS
    # Long Future P&L
    fut_pnl = (btc - future_entry) * CONTRACT_SIZE * LOTS
    
    net_before_fee = call_pnl + put_pnl + fut_pnl
    net_after_fee  = net_before_fee - total_fees
    
    flag = " <<< PROFIT" if net_after_fee > 0 else " <<< LOSS" if net_after_fee < 0 else " <<< BREAKEVEN"
    print(f"  ${btc:>11,} | ${call_pnl:>9.2f} | ${put_pnl:>9.2f} | ${fut_pnl:>9.2f} | ${net_before_fee:>13.2f} | ${net_after_fee:>14.2f}{flag}")

print("=" * 60)
print()
print("CONCLUSION:")
net_at_any_price = (call_premium_received - put_premium_paid) * CONTRACT_SIZE * LOTS - total_fees
print(f"  Net P&L at ANY BTC price (approx): ${net_at_any_price:.2f}")
print()
print("NOTE: This is a CONVERSION strategy (synthetic neutral).")
print("Actual result depends on EXACT execution prices vs these estimates.")
print("If Call premium received > Put premium paid (after fees): PROFIT")
print("If Call premium received < Put premium paid (after fees): LOSS")
