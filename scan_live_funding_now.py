import sys
import asyncio
import json
import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from hft_funding_arbitrage_engine import HFTFundingArbitrageEngine

async def main():
    engine = HFTFundingArbitrageEngine(paper_mode=False, target_notional_usd=37.32)
    await engine.init_session()

    print("=" * 80)
    print(f" 🔍 SCANNING LIVE FUNDING SPREADS AT {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} IST")
    print("=" * 80)

    best_opp = await engine.scan_top_opportunity()

    if best_opp:
        print("\n🏆 TOP #1 HIGHEST FUNDING ARBITRAGE OPPORTUNITY:")
        print(f"   Coin Symbol        : {best_opp['coin']}")
        print(f"   Delta Symbol       : {best_opp['delta_sym']} (Rate: {best_opp['delta_rate_pct']:+.4f}%)")
        print(f"   CoinDCX Symbol     : {best_opp['coindcx_sym']} (Rate: {best_opp['coindcx_rate_pct']:+.4f}%)")
        print(f"   Gross Spread       : {best_opp['gross_spread_pct']:.4f}%")
        print(f"   Net Profit (Spread-0.1416%): {best_opp['net_profit_pct']:+.4f}%")
        print(f"   Recommended Leg 1  : {best_opp['delta_side']} {best_opp['delta_sym']} on Delta")
        print(f"   Recommended Leg 2  : {best_opp['coindcx_side']} {best_opp['coindcx_sym']} on CoinDCX")
        print(f"   Net Profit Gate    : {best_opp['gate']} ✅")
    else:
        print("❌ No profitable funding spread detected above fee gate.")

    print("=" * 80)
    await engine.close_session()

if __name__ == "__main__":
    asyncio.run(main())
