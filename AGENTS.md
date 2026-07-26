# Delta Exchange Arbitrage Bot Rules & Strategy Guidelines

## Core Trading Rules (Saved Principles)

### 1. Strategy Definition & Contract Selection
- **Strategy:** Conversion & Reversal Arbitrage (Delta-Neutral).
- **Legs Combination:**
  - Leg 1: **BUY/SELL Futures** (`ETHUSD` / `BTCUSD`)
  - Leg 2: **SELL/BUY Call Option** (`C-ETH-*` / `C-BTC-*`)
  - Leg 3: **BUY/SELL Put Option** (`P-ETH-*` / `P-BTC-*`)

### 2. Exact Contract Sizing Unit
- Sizing Unit in Strategy Builder: **`Lot`**
- **Contract Value Equivalents:**
  - **1 Lot ETH = 0.01 ETH** (10 Lots = 0.1 ETH, 100 Lots = 1.0 ETH)
  - **1 Lot BTC = 0.001 BTC** (10 Lots = 0.01 BTC, 100 Lots = 0.1 BTC)

### 3. Empirical Fee Benchmark (Inc. GST)
- **1 Lot ETH (0.01 ETH):**
  - Futures Entry Fee: ~$0.011 USD
  - Call Option Fee: ~$0.002 USD
  - Put Option Fee: ~$0.002 USD
  - **Total Entry Fee Per 1 Lot (0.01 ETH):** **$0.015 USD (~1.5 Cents)**
- **10 Lots ETH (0.1 ETH):** Total Entry Fee = **$0.15 USD (~15 Cents)**
- **1 Lot BTC (0.001 BTC):** Total Entry Fee = **$0.05 USD (~5 Cents)**

### 4. Mandatory Filter: 50% Profit Retention Rule
- **Condition:** $\text{Gross Profit per 1 Lot} \ge 2 \times \text{Total Entry Fee}$
- **For 1 Lot ETH (0.01 ETH):**
  $$\text{Gross Profit per 1 Lot} \ge 2 \times \$0.015 = \mathbf{\$0.03 \text{ USD (3 Cents)}}$$
  $$\text{Net Profit per 1 Lot} = \text{Gross Profit} - \$0.015 \ge \$0.015 \text{ USD}$$
- **For 10 Lots ETH (0.1 ETH):**
  $$\text{Gross Profit per 10 Lots} \ge \mathbf{\$0.30 \text{ USD (30 Cents)}}$$
- **Trade Filter Decision:**
  - If Strategy Payoff Max Profit for 10 Lots $< \$0.30 \text{ USD} \implies$ **REJECT TRADE ❌**
  - If Strategy Payoff Max Profit for 10 Lots $\ge \$0.30 \text{ USD} \implies$ **ACCEPT TRADE ✅**

### 5. Execution & Settlement
- **Limit Orders (Maker):** Always place limit orders at orderbook Mid-Prices $\frac{\text{Bid} + \text{Ask}}{2}$ for best fill & fee rebates.
- **Auto Settlement:** Hold position until Expiry Date for zero-fee cash settlement.
