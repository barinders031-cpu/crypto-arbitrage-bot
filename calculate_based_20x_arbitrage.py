"""
BASED Coin Arbitrage Calculator: Delta Exchange India vs CoinDCX
Capital: $10 on Delta + $10 on CoinDCX | Leverage: 20x | Total Notional: $200 each
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception as e:
        return []

# Fetch live rates for BASED
delta_tickers = fetch("https://api.india.delta.exchange/v2/tickers")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

delta_rate = 0.1172  # default fallback % per 4H
for t in delta_tickers:
    if t.get('symbol') == 'BASEDUSD':
        delta_rate = float(t.get('funding_rate') or 0)
        break

coindcx_rate = 0.0133  # default fallback % per 8H
for b in binance_funding:
    if b.get('symbol') == 'BASEDUSDT':
        coindcx_rate = float(b.get('lastFundingRate') or 0) * 100.0
        break

print("=" * 90)
print("   BASED COIN 20x LEVERAGE ARBITRAGE CALCULATOR (DELTA vs COINDCX)")
print("=" * 90)

capital_delta = 10.0   # $10 USD
capital_cdcx  = 10.0   # $10 USD
leverage      = 20.0   # 20x

notional_delta = capital_delta * leverage  # $200 USD
notional_cdcx  = capital_cdcx * leverage   # $200 USD

print(f"\n[+] TRADE SETUP:")
print(f"    - Capital / Margin: $10 USD (Delta) + $10 USD (CoinDCX) = $20 Total Margin")
print(f"    - Leverage: 20x")
print(f"    - Position Size (Notional): ${notional_delta:.2f} USD on Delta | ${notional_cdcx:.2f} USD on CoinDCX")

print(f"\n[+] LIVE RAW FUNDING RATES:")
print(f"    - Delta Exchange (`BASEDUSD`): {delta_rate:+.4f}% per 4H Payment")
print(f"    - CoinDCX (`B-BASEDUSDT`):     {coindcx_rate:+.4f}% per 8H Payment")

# Funding Calculations
# In 24 hours (1 day): Delta pays 6 times (every 4H). CoinDCX pays 3 times (every 8H).
delta_daily_income = notional_delta * (delta_rate / 100.0) * 6.0   # Short receives (+)
cdcx_daily_cost    = notional_cdcx  * (coindcx_rate / 100.0) * 3.0  # Long pays (-)

net_gross_daily = delta_daily_income - cdcx_daily_cost

# Trading Fees (0.05% Taker on $200 Notional for each exchange)
fee_delta_entry = notional_delta * 0.0005  # $0.10
fee_cdcx_entry  = notional_cdcx  * 0.0005  # $0.10
total_entry_fee = fee_delta_entry + fee_cdcx_entry  # $0.20

# Net Profit calculations
net_profit_1day = net_gross_daily - total_entry_fee
net_profit_7days = (net_gross_daily * 7.0) - total_entry_fee
net_profit_30days = (net_gross_daily * 30.0) - total_entry_fee

print("\n" + "=" * 90)
print("   EXACT MATHEMATICAL PROFIT / LOSS BREAKDOWN (AFTER ALL FEES)")
print("=" * 90)
print(f"1. Total Entry Trading Fee (Delta + CoinDCX):       -${total_entry_fee:.2f} USD")
print(f"2. Delta Funding Income Received (Short $200/day):  +${delta_daily_income:.4f} USD")
print(f"3. CoinDCX Funding Fee Paid (Long $200/day):        -${cdcx_daily_cost:.4f} USD")
print(f"4. Gross Daily Funding Spread:                      +${net_gross_daily:.4f} USD / Day")

print("-" * 90)
print(f"NET PROFIT AFTER 24 HOURS (Day 1):               +${net_profit_1day:.4f} USD  ({(net_profit_1day/20.0)*100:.1f}% on $20 capital)")
print(f"NET PROFIT AFTER 7 DAYS (Week 1):               +${net_profit_7days:.4f} USD  ({(net_profit_7days/20.0)*100:.1f}% on $20 capital)")
print(f"NET PROFIT AFTER 30 DAYS (Month 1):             +${net_profit_30days:.4f} USD  ({(net_profit_30days/20.0)*100:.1f}% on $20 capital)")
print("=" * 90)
