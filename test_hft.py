import asyncio
import sys
from hft_funding_arbitrage_engine import HFTFundingArbitrageEngine

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("=" * 80)
    print("⚡ TESTING HFT FUNDING ARBITRAGE ENGINE SCANNER & SIZING EQUALIZER")
    print("=" * 80)

    engine = HFTFundingArbitrageEngine(paper_mode=True, target_notional_usd=100.0)
    await engine.init_session()

    opp = await engine.scan_top_opportunity()
    if opp:
        print("\n🏆 Top Funding Opportunity Identified:")
        print(f"   Coin:                {opp['coin']}")
        print(f"   Delta Symbol:        {opp['delta_sym']} (Rate(8H norm): {opp['delta_rate_pct']:+.4f}%, Interval: {opp['delta_interval_h']:.0f}H, Mark: ${opp['delta_mark']:.6f})")
        print(f"   CoinDCX Symbol:      {opp['coindcx_sym']} (Rate(8H norm): {opp['coindcx_rate_pct']:+.4f}%, Interval: {opp['coindcx_interval_h']:.0f}H, Mark: ${opp['coindcx_mark']:.6f})")
        print(f"   Gross Spread (8H):   {opp['gross_spread_pct']:.4f}%")
        print(f"   Net Profit:          {opp['net_profit_pct']:+.4f}%")
        print(f"   Gate Action:         {opp['gate']}")
        print(f"   Delta Action:        {opp['delta_side']}")
        print(f"   CoinDCX Action:      {opp['coindcx_side']}")

        lots, qty, notional = engine.calculate_hft_sizing(opp['coin'], opp['delta_mark'])
        print(f"\n📏 Universal Base Sizing Calculation:")
        print(f"   Delta Order Lots:    {lots} Lots")
        print(f"   Exact Hedged Qty:    {qty} {opp['coin']}")
        print(f"   Matched Notional:    ${notional:.2f} USD")

        print("\n⚡ Testing Parallel HFT Simultaneous Execution...")
        exec_res = await engine.execute_hft_parallel_entry(opp)
        print(f"   Parallel Entry Status: {exec_res['status']} | Measured Latency: {exec_res['latency_ms']:.2f} ms")

        print("\n⚡ Testing Scalper Exit Trigger...")
        exit_res = await engine.execute_hft_parallel_exit(engine.active_positions)
        print(f"   Parallel Exit Status: {exit_res['status']}")
    else:
        print("[-] No funding opportunities found.")

    await engine.close_session()

if __name__ == "__main__":
    asyncio.run(main())
