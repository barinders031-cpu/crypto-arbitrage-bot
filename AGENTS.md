# Delta Exchange Arbitrage Bot Rules & Strategy Guidelines

## Core Trading Rules (Saved Principles)

### 1. Strategy Definition & Contract Selection
- **Strategy:** Cross-Exchange Perpetual Funding Rate Arbitrage (Delta-Neutral).
- **Legs Combination:**
  - Leg 1: **Perpetual Futures on Delta Exchange India** (Long/Short)
  - Leg 2: **Perpetual Futures on CoinDCX** (Short/Long - Exact Symmetrical Match)

### 2. Exact Contract Sizing Unit
- Sizing Unit in Strategy Builder: **`Lot` / Base Coin Quantity**
- **Contract Value Equivalents:**
  - **1 Lot ETH = 0.01 ETH** (10 Lots = 0.1 ETH, 100 Lots = 1.0 ETH)
  - **1 Lot BTC = 0.001 BTC** (10 Lots = 0.01 BTC, 100 Lots = 0.1 BTC)

### 3. Empirical Fee Benchmark & Scalper Protocol (Inc. 18% GST)
- **Delta Exchange Scalper Offer (0% Exit Fee):**
  - Trade duration is <10 seconds (`T-1` entry, `09:00:02` exit).
  - Triggers Delta's official **Scalper Offer**, waiving **100% of Delta exit fees ($0.00)** on every single trade!
- **Individual Fee Schedules (Inc. 18% GST):**
  - Delta Taker Entry: `0.059%` | Delta Scalper Exit: `0.000%` (FREE)
  - CoinDCX Taker Entry: `0.059%` | CoinDCX Maker Exit: `0.0236%` | CoinDCX Taker Exit: `0.059%`
- **Combined Dual-Leg Roundtrip Fee Scenarios:**
  - **Scenario 1 (Hybrid Taker Entry + Scalper & Maker Exit):** **`~0.1416%`** ($0.14 USD per $100 notional per exchange).
  - **Scenario 2 (Emergency Market Taker Exit):** **`~0.1770%`** ($0.18 USD per $100 notional per exchange).
  - **Scenario 3 (Pure Maker Entry & Exit):** **`~0.0708%`** ($0.07 USD per $100 notional per exchange).


### 4. Mandatory Filter: Fee-Adjusted Net Profit Gate
- **Funding Spread Arithmetic Formula:**
  - **Same-Sign Rates (Both `+` OR Both `-`):** **Subtract / Minus** to find difference: $|R_1 - R_2|$ (e.g. $+0.7\% \text{ and } +0.2\% \implies 0.7\% - 0.2\% = \mathbf{0.5\% \text{ Gross Spread}}$).
  - **Opposite-Sign Rates (One `+` AND One `-`):** **Add / Plus** both magnitudes: $|R_1| + |R_2|$ (e.g. $+0.7\% \text{ and } -0.2\% \implies 0.7\% + 0.2\% = \mathbf{0.9\% \text{ Gross Spread}}$).
- **Mandatory Fee Deduction Gate:**
  - $\text{Net Profit} = \text{Gross Spread} - \text{Total Roundtrip Fee (0.1416\%)}$
  - If $\text{Net Profit} > 0$ ($\text{Gross Spread} \ge 0.15\%$) $\implies$ **ACCEPT TRADE ✅**
  - If $\text{Net Profit} \le 0$ ($\text{Gross Spread} < 0.15\%$) $\implies$ **REJECT TRADE ❌ (DO NOT TRADE!)**

### 5. Cross-Exchange Perpetual Funding Arbitrage & Double-Yield Harvest Protocol
- **#1 Highest Funding Scanner:** Continuously scan all coins across exchanges and select ONLY the single **#1 highest funding rate difference coin** for execution.
- **Double Funding Yield Harvest Logic:**
  - **Case A (Delta Positive `+` & CoinDCX Negative `-`):** 
    - **SELL (SHORT) Delta** $\rightarrow$ Collects Positive Funding from Delta Longs!
    - **BUY (LONG) CoinDCX** $\rightarrow$ Collects Negative Funding from CoinDCX Shorts!
    - *Result:* Dual-exchange funding collection!
  - **Case B (Delta Negative `-` & CoinDCX Positive `+`):** 
    - **BUY (LONG) Delta** $\rightarrow$ Collects Negative Funding from Delta Shorts!
    - **SELL (SHORT) CoinDCX** $\rightarrow$ Collects Positive Funding from CoinDCX Longs!
  - **Case C (Same Sign `+/+` or `-/-`):** 
    - Open **SHORT** on Higher Positive Rate Exchange & **LONG** on Lower Rate Exchange $\rightarrow$ Collects Net Interest Difference!
- **Pre-Timestamp Entry Rule:** All entry operations MUST complete **1–2 minutes before** the exact funding timestamp.
- **Exact Quantity Leg Matching:**
  - When Leg 1 fills (on either Delta or CoinDCX), DO NOT CUT! Instantly execute Leg 2 with the **EXACT SAME QUANTITY** so both legs match 100%.
- **Symmetrical Market Fallback Protocol:**
  - If neither limit order fills by `T-45s`, cancel both limit orders $\rightarrow$ **Fire INSTANT MARKET ORDERS ON BOTH EXCHANGES SIMULTANEOUSLY** to guarantee 100% filled entry before funding!


### 6. Instant 2-3 Second Post-Funding Exit & PnL Neutrality (0.01% - 0.05%)
- **Exact Funding Snapshot:** Backend snapshot locks funding entitlement at exact `00.000` seconds of the funding hour.
- **Rapid 2–3 Second Exit Rule:** Exit BOTH exchanges simultaneously within **2 to 3 seconds after funding** (`09:00:02` – `09:00:03`).
- **Neutrality Constraint (0.01% - 0.05% Allowed Variation):**
  - Both legs MUST be entered and exited with strict priority on **Dual-Leg PnL Neutrality**.
  - Allowed PnL variation between Leg A (+1%) and Leg B (-1%) is strictly kept within **`0.01% - 0.05%`**.
  - **Purpose of Constraint:** Protect 100% of the earned Net Funding Profit (e.g. +$0.50 USD on 0.9% spread) from being eaten up by price slippage on exit, ensuring maximum retained cash profit!


### 7. 10% Balance Drawdown Emergency Safety Override
- **Balance PnL Safety Trigger:**
  - If position drawdown reaches **≥ 10% of total account/margin balance** during exit attempt:
  - **IMMEDIATE OVERRIDE:** Fire Instant Market Exit Orders on BOTH exchanges to preserve neutrality and eliminate liquidation risk.

### 8. Universal Base Asset Quantity Sizing Protocol (USD vs USDT Equalizer)
- **Core Principle:** Do NOT size by USD/USDT dollars! Size strictly by **Base Coin Quantity ($Q_{base}$)** (e.g. `ETH`, `BTC`, `AIOT`).
- **Standardized Sizing Algorithm:**
  1. Calculate Target Base Quantity: $Q_{base} = \frac{\text{Target Notional USD}}{\text{Mark Price}_{\text{Delta}}}$
  2. Convert to Delta Lots: $L_{\text{Delta}} = \text{round}\left(\frac{Q_{base}}{\text{Lot Size}_{\text{Delta}}}\right)$
  3. Calculate Exact Hedged Coin Quantity: $Q_{exact} = L_{\text{Delta}} \times \text{Lot Size}_{\text{Delta}}$
  4. Match CoinDCX Sizing: Set CoinDCX Order Quantity = $Q_{exact}$ down to 0.0001 precision.
- **Result:** $Q_{\text{Delta}} = +Q_{exact}$ and $Q_{\text{CoinDCX}} = -Q_{exact} \implies \text{Net Delta} = 0.0000$ (100% Perfect Market Price Protection).
- **Margin Equalizer:** Both exchanges maintain matching margin allocation because physical crypto asset quantity is 100% identical!

### 9. Dynamic 100% Full-Position Closure Protocol
- **Core Principle:** Exit execution MUST guarantee 100% position closure with ZERO residual lots left open on either exchange.
- **Dynamic Live Position Query Algorithm:**
  1. Query live positions via `GET /v2/positions` on Delta Exchange India and `POST /exchange/v1/derivatives/futures/positions` on CoinDCX.
  2. Extract exact active open sizes ($Q_{\text{open\_delta}}$ Lots, $Q_{\text{open\_coindcx}}$ Coins).
  3. Transmit `reduce_only` market exit orders for 100% of $Q_{\text{open}}$ on each exchange so no residual lots or fractional coins remain active.

