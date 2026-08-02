HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <title>Multi-Exchange Arbitrage Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(18, 26, 42, 0.75);
            --border: rgba(255, 255, 255, 0.08);
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-cyan: #06b6d4;
            --accent-purple: #8b5cf6;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            background-color: var(--bg);
            color: var(--text-main);
            font-family: 'Outfit', sans-serif;
            padding: 20px;
            min-height: 100vh;
            line-height: 1.5;
        }

        .container { max-width: 1450px; margin: 0 auto; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 25px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 14px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }

        .header-title h1 {
            font-size: 22px;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-title p {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .telegram-widget {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(255, 255, 255, 0.03);
            padding: 8px 14px;
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        .telegram-widget input {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border);
            color: #fff;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
            width: 140px;
        }

        .btn-tg {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            transition: all 0.2s;
        }

        .btn-tg:hover { opacity: 0.9; transform: translateY(-1px); }

        .grid-4 {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            padding: 18px;
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }

        .card-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .card-val {
            font-size: 24px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .section-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 25px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            background: rgba(255, 255, 255, 0.02);
            padding: 12px 16px;
            font-size: 11px;
            text-transform: uppercase;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
        }

        td {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-size: 13px;
        }

        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }

        .text-green { color: var(--accent-green); }
        .text-red { color: var(--accent-red); }
        .text-yellow { color: var(--accent-yellow); }
        .text-cyan { color: var(--accent-cyan); }
        .text-purple { color: var(--accent-purple); }

        .badge-action {
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .badge-ex {
            background: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        }

        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 25px;
        }

        .log-box {
            background: rgba(5, 8, 15, 0.9);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 15px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            height: 250px;
            overflow-y: auto;
            color: #d1d5db;
        }

        .log-entry { margin-bottom: 5px; line-height: 1.4; border-bottom: 1px solid rgba(255,255,255,0.02); padding-bottom: 3px; }

        .section-divider {
            border: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(59, 130, 246, 0.5), transparent);
            margin: 35px 0;
        }

        .engine-tag {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-left: 8px;
        }

        .tag-funding { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
        .tag-triangular { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); border: 1px solid rgba(139, 92, 246, 0.3); }
    </style>
</head>
<body>

    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="header-title">
                <h1>MULTI-ENGINE ARBITRAGE TERMINAL</h1>
                <p>Cross-Exchange Funding Rates & Binance Dynamic All-BTC Pairs Triangular Arbitrage</p>
            </div>

            <div style="display: flex; gap: 10px; align-items: center;">
                <button class="btn-tg" style="background: linear-gradient(135deg, #10b981, #059669);" onclick="document.getElementById('section-3-options').scrollIntoView({behavior: 'smooth'})">🎯 Jump to Options Parity</button>

                <div class="telegram-widget">
                    <span style="font-size: 12px; color: var(--text-muted);">CoinDCX Bal ($):</span>
                    <input type="number" id="input-coindcx-bal" placeholder="e.g. 15.00" step="0.5" style="width: 80px;">
                    <button class="btn-tg" onclick="saveCoinDCXBal()">Set</button>
                </div>

                <div class="telegram-widget">
                    <span style="font-size: 12px; color: var(--text-muted);">Telegram Alerts:</span>
                    <input type="text" id="tg-token" placeholder="Bot Token">
                    <input type="text" id="tg-chat" placeholder="Chat ID">
                    <button class="btn-tg" onclick="saveTelegram()">Save & Link</button>
                    <span id="val-tg-status" style="font-size: 11px; margin-left: 5px; font-weight: 600;" class="text-cyan">Checking...</span>
                </div>
            </div>
        </div>

        <!-- ============================================================================== -->
        <!-- SECTION 1: CROSS-EXCHANGE PERPETUAL FUNDING RATE ARBITRAGE -->
        <!-- ============================================================================== -->
        <div class="section-header">
            <div class="section-title">
                ⚡ SECTION 1: CROSS-EXCHANGE FUNDING RATE ARBITRAGE
                <span class="engine-tag tag-funding">DELTA INDIA VS COINDCX / BINANCE</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="val-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Delta Exchange Balance</div>
                <div class="card-val text-green" id="val-delta-bal">$7.94</div>
            </div>
            <div class="card">
                <div class="card-label">CoinDCX Futures Margin</div>
                <div class="card-val text-cyan" id="val-coindcx-bal">$9.26</div>
            </div>
            <div class="card">
                <div class="card-label">Safe Execution Margin (75%)</div>
                <div class="card-val text-yellow" id="val-margin-bal">$5.95</div>
            </div>
            <div class="card">
                <div class="card-label">Funding Net PnL (USD)</div>
                <div class="card-val text-green" id="val-pnl">+$0.0000</div>
            </div>
        </div>
        <div class="grid-4" style="margin-top: 0;">
            <div class="card">
                <div class="card-label">Top Funding Difference</div>
                <div class="card-val text-cyan" id="val-diff">0.0000%</div>
            </div>
            <div class="card" style="grid-column: span 2;">
                <div class="card-label">Next Settlement Countdown</div>
                <div class="card-val text-yellow" id="val-countdown" style="font-size: 16px; margin-top: 5px;">Calculating...</div>
            </div>
            <div class="card">
                <div class="card-label">Execution Mode</div>
                <div class="card-val" id="val-live-mode" style="font-size: 15px; margin-top: 5px; color: #ff4d4d;">PAPER 📄</div>
            </div>
        </div>

        <div class="grid-4" style="margin-top: 15px; margin-bottom: 20px;">
            <div class="card" style="border: 1px solid rgba(16, 185, 129, 0.3);">
                <div class="card-label">🛡️ Delta Neutral Hedge</div>
                <div class="card-val text-green" style="font-size: 12px; margin-top: 4px;">ACTIVE (0.00 Delta)</div>
            </div>
            <div class="card" style="border: 1px solid rgba(16, 185, 129, 0.3);">
                <div class="card-label">🛡️ Fee Guard Filter</div>
                <div class="card-val text-green" style="font-size: 12px; margin-top: 4px;">ACTIVE (&ge; 0.25%)</div>
            </div>
            <div class="card" style="border: 1px solid rgba(16, 185, 129, 0.3);">
                <div class="card-label">🛡️ Delta 0% Scalper Exit</div>
                <div class="card-val text-green" style="font-size: 12px; margin-top: 4px;">ARMED (&lt; 10s Window)</div>
            </div>
            <div class="card" style="border: 1px solid rgba(16, 185, 129, 0.3);">
                <div class="card-label">🛡️ 10% Drawdown Auto-Kill</div>
                <div class="card-val text-green" style="font-size: 12px; margin-top: 4px;">ARMED & READY</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Top 5 Live Funding Rate Arbitrage Opportunities</div>
            <span style="font-size: 11px; color: var(--text-muted);">Strict Fee Guard Gate: Spread &ge; 0.25%</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Coin</th>
                        <th>Delta Exchange Rate</th>
                        <th>CoinDCX Futures Rate</th>
                        <th>Spread (%)</th>
                        <th>Funding Countdown</th>
                        <th>Hedging Action</th>
                    </tr>
                </thead>
                <tbody id="top5-rows">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Scanning live exchange order books...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="grid-2">
            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Funding Event Logs</div>
                </div>
                <div class="log-box" id="logs-container">
                    <div class="log-entry">Initializing Funding Engine...</div>
                </div>
            </div>

            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Executed Scalp Trades History</div>
                </div>
                <div class="table-container" style="height: 250px; overflow-y: auto; margin-bottom: 0;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Time</th>
                                <th>Coin</th>
                                <th>Gross</th>
                                <th>Fees</th>
                                <th>Net PnL</th>
                            </tr>
                        </thead>
                        <tbody id="history-rows">
                            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Waiting for funding window execution...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ============================================================================== -->
        <!-- DIVIDER & SECTION 2: BINANCE ALL-BTC-COINS TRIANGULAR ARBITRAGE (SCROLL DOWN) -->
        <!-- ============================================================================== -->
        <hr class="section-divider">

        <div class="section-header">
            <div class="section-title">
                🔺 SECTION 2: BINANCE DYNAMIC ALL-BTC TRIANGULAR ARBITRAGE
                <span class="engine-tag tag-triangular">BINANCE EXCLUSIVE (ALL BTC PAIRS)</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="tri-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Virtual Paper Balance</div>
                <div class="card-val text-green" id="tri-val-balance">$10.0000</div>
            </div>
            <div class="card">
                <div class="card-label">Net Triangular PnL (USD)</div>
                <div class="card-val text-green" id="tri-val-pnl-usd">+$0.0000</div>
            </div>
            <div class="card">
                <div class="card-label">Active BTC Pairs Scanned</div>
                <div class="card-val text-purple" id="tri-val-count">0 Pairs</div>
            </div>
            <div class="card">
                <div class="card-label">Top Scanned Loop</div>
                <div class="card-val text-cyan" id="tri-val-loop" style="font-size: 15px; margin-top: 5px;">-</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Top Scanned Triangular Loops (Binance Spot L2 Order Book)</div>
            <span style="font-size: 11px; color: var(--text-muted);">Order Book Depth Walk (Top 10 Levels) for VWAP Slippage</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Triangular Loop</th>
                        <th>Direction</th>
                        <th>Step 1</th>
                        <th>Step 2</th>
                        <th>Step 3</th>
                        <th>Fees & Slippage</th>
                        <th>Net Profit %</th>
                    </tr>
                </thead>
                <tbody id="triangular-rows">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Scanning all active Binance BTC trading pairs...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="grid-2">
            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Triangular Scanner Logs</div>
                </div>
                <div class="log-box" id="triangular-logs-container">
                    <div class="log-entry">Initializing Binance All-BTC Scanner Engine...</div>
                </div>
            </div>

            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Triangular Executed Paper Trades</div>
                </div>
                <div class="table-container" style="height: 250px; overflow-y: auto; margin-bottom: 0;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Time</th>
                                <th>Loop</th>
                                <th>Fees</th>
                                <th>Net PnL</th>
                                <th>Updated Balance</th>
                            </tr>
                        </thead>
                        <tbody id="triangular-history-rows">
                            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Waiting for profitable Binance triangular loop (&ge; +0.10% Net)...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        <!-- ============================================================================== -->
        <!-- DIVIDER & SECTION 3: DELTA EXCHANGE INDIA OPTIONS PUT-CALL PARITY ARBITRAGE -->
        <!-- ============================================================================== -->
        <hr class="section-divider" id="section-3-options">

        <div class="section-header">
            <div class="section-title">
                🎯 SECTION 3: DELTA EXCHANGE INDIA OPTIONS PUT-CALL PARITY ARBITRAGE
                <span class="engine-tag tag-funding">DELTA INDIA (BTC, ETH, XAUT OPTIONS)</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="options-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Active Options Margin (75%)</div>
                <div class="card-val text-green" id="opt-val-margin">$5.95</div>
            </div>
            <div class="card">
                <div class="card-label">Max Leverage Cap</div>
                <div class="card-val text-cyan" id="opt-val-leverage">200x (BTC/ETH)</div>
            </div>
            <div class="card">
                <div class="card-label">Expiry Auto-Close Status</div>
                <div class="card-val text-yellow" id="opt-val-status" style="font-size: 15px; margin-top: 5px;">AUTOMATIC ⚡</div>
            </div>
            <div class="card">
                <div class="card-label">Supported Assets</div>
                <div class="card-val text-purple" style="font-size: 15px; margin-top: 5px;">BTC, ETH, XAUT</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Live Options Put-Call Parity Opportunities (C - P = S - K)</div>
            <span style="font-size: 11px; color: var(--text-muted);">Fee Gate: Net Spread &ge; 0.15% | Early Expiry Contracts</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Coin</th>
                        <th>Parity Type</th>
                        <th>Strike Price</th>
                        <th>Futures Mark</th>
                        <th>Call Ask / Put Bid</th>
                        <th>Net Parity Spread</th>
                        <th>Hours to Expiry</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="options-parity-rows">
                    <tr><td colspan="9" style="text-align: center; color: var(--text-muted);">Scanning live Delta Exchange India options & futures order books...</td></tr>
                </tbody>
            </table>
        </div>

    </div>

    <!-- DASHBOARD AUTO-REFRESH SCRIPT -->
    <script>
        async function saveTelegram() {
            const token = document.getElementById('tg-token').value.trim();
            const chat = document.getElementById('tg-chat').value.trim();
            if(!token) {
                alert("Please enter your Telegram Bot Token!");
                return;
            }
            const res = await fetch('/api/telegram', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({bot_token: token, chat_id: chat, enabled: true})
            });
            const d = await res.json();
            if(d.status === 'ok') {
                document.getElementById('tg-chat').value = d.chat_id;
                alert("🎉 Success! Telegram Trade Alerts Successfully Linked to Chat ID: " + d.chat_id);
            } else if(d.status === 'need_message') {
                alert("⚠️ Auto-Detect Hint: Please open your bot on Telegram and send 1 message (e.g. 'hi'), then click this button again!");
            } else {
                alert("Error linking Telegram. Please check your Bot Token!");
            }
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/state?t=' + new Date().getTime());
                const data = await res.json();

                if (!data || !data.state) return;

                // --- UPDATE ENGINE 1: FUNDING ARBITRAGE ---
                const dBal = data.state.delta_balance || 7.94;
                const cBal = data.state.coindcx_balance || 9.26;
                const mBal = data.state.active_margin_per_exchange || ('$' + (Math.min(dBal, cBal) * 0.75).toFixed(2));
                
                const dBalEl = document.getElementById('val-delta-bal');
                if (dBalEl) dBalEl.innerText = '$' + dBal.toFixed(2);
                
                const cBalEl = document.getElementById('val-coindcx-bal');
                if (cBalEl) cBalEl.innerText = '$' + cBal.toFixed(2);
                
                const mBalEl = document.getElementById('val-margin-bal');
                if (mBalEl) mBalEl.innerText = typeof mBal === 'string' && mBal.startsWith('$') ? mBal : ('$' + mBal);

                const pnl = data.state.net_pnl_usd || 0.0;
                const pnlEl = document.getElementById('val-pnl');
                pnlEl.innerText = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4);
                pnlEl.className = pnl >= 0 ? 'card-val text-green' : 'card-val text-red';

                const diffEl = document.getElementById('val-diff');
                if (diffEl) diffEl.innerText = data.state.active_funding_diff || '0.0000%';

                const liveModeEl = document.getElementById('val-live-mode');
                if (liveModeEl) {
                    const lm = data.state.live_mode || 'PAPER 📄';
                    liveModeEl.innerText = lm;
                    liveModeEl.style.color = lm.includes('LIVE') ? '#ff4d4d' : '#aaaaaa';
                }

                document.getElementById('val-scan-time').innerText = 'Last Scan: ' + (data.state.last_scan_time || 'Just Now');
                document.getElementById('val-countdown').innerText = data.state.next_funding_countdown || 'Calculating...';
                document.getElementById('val-tg-status').innerText = data.state.telegram_status || 'Not Configured';

                const top5Body = document.getElementById('top5-rows');
                if (data.state.top5_coins && data.state.top5_coins.length > 0) {
                    top5Body.innerHTML = data.state.top5_coins.map((item, idx) => `
                        <tr>
                            <td><strong>${idx + 1}</strong></td>
                            <td><strong class="text-cyan">${item.coin}</strong></td>
                            <td>${item.delta_sym} (<span class="text-green">${item.delta_rate}</span>)</td>
                            <td>${item.cdcx_sym} (<span class="text-yellow">${item.cdcx_rate}</span>)</td>
                            <td><strong class="text-green">${item.diff}</strong></td>
                            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${item.next_funding || '-'}</td>
                            <td><span class="badge-action">${item.action}</span></td>
                        </tr>
                    `).join('');
                }

                const logsBox = document.getElementById('logs-container');
                if (data.logs && data.logs.length > 0) {
                    logsBox.innerHTML = data.logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                    logsBox.scrollTop = logsBox.scrollHeight;
                }

                const tbody = document.getElementById('history-rows');
                if (data.history && data.history.length > 0) {
                    tbody.innerHTML = data.history.map(t => `
                        <tr>
                            <td>${t.id}</td>
                            <td>${t.timestamp.split(' ')[1] || t.timestamp}</td>
                            <td><strong class="text-cyan">${t.coin}</strong></td>
                            <td class="text-green">${t.gross_income}</td>
                            <td class="text-red">${t.fees}</td>
                            <td class="${t.net_pnl.includes('+') ? 'text-green' : 'text-red'}">${t.net_pnl}</td>
                        </tr>
                    `).join('');
                }

                // --- UPDATE ENGINE 2: BINANCE ALL-BTC TRIANGULAR ARBITRAGE ---
                document.getElementById('tri-scan-time').innerText = 'Last Scan: ' + (data.state.triangular_last_scan || 'Just Now');
                document.getElementById('tri-val-balance').innerText = '$' + (data.state.triangular_paper_balance || 10.0).toFixed(4);
                
                const triPnlUsd = data.state.triangular_net_pnl_usd || 0.0;
                const triPnlUsdEl = document.getElementById('tri-val-pnl-usd');
                if (triPnlUsdEl) {
                    triPnlUsdEl.innerText = (triPnlUsd >= 0 ? '+' : '') + '$' + triPnlUsd.toFixed(4);
                    triPnlUsdEl.className = triPnlUsd >= 0 ? 'card-val text-green' : 'card-val text-red';
                }

                document.getElementById('tri-val-count').innerText = (data.state.triangular_scanned_count || 0) + ' BTC Pairs';
                document.getElementById('tri-val-loop').innerText = data.state.triangular_top_loop || '-';

                const triBody = document.getElementById('triangular-rows');
                if (data.state.triangular_top5 && data.state.triangular_top5.length > 0) {
                    triBody.innerHTML = data.state.triangular_top5.map((item, idx) => `
                        <tr>
                            <td><strong>${idx + 1}</strong></td>
                            <td><strong class="text-purple">${item.label}</strong></td>
                            <td><span class="badge-ex">${item.loop_type}</span></td>
                            <td style="font-size:12px;">${item.step1}</td>
                            <td style="font-size:12px;">${item.step2}</td>
                            <td style="font-size:12px;">${item.step3}</td>
                            <td style="font-size:12px;"><span class="text-red">-$${item.total_fees.toFixed(4)}</span> | <span class="text-yellow">Slip -$${item.total_slip.toFixed(4)}</span></td>
                            <td><strong class="${item.net_pnl_pct.includes('-') ? 'text-red' : 'text-green'}">${item.net_pnl_pct}</strong></td>
                        </tr>
                    `).join('');
                }

                const triLogsBox = document.getElementById('triangular-logs-container');
                if (data.triangular_logs && data.triangular_logs.length > 0) {
                    triLogsBox.innerHTML = data.triangular_logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                    triLogsBox.scrollTop = triLogsBox.scrollHeight;
                }

                const triHistoryBody = document.getElementById('triangular-history-rows');
                if (data.triangular_history && data.triangular_history.length > 0) {
                    triHistoryBody.innerHTML = data.triangular_history.map(t => `
                        <tr>
                            <td>${t.id}</td>
                            <td>${t.timestamp.split(' ')[1] || t.timestamp}</td>
                            <td><strong class="text-purple">${t.loop}</strong></td>
                            <td class="text-red">${t.fees}</td>
                            <td class="text-green">${t.net_pnl}</td>
                            <td class="text-cyan">${t.balance}</td>
                        </tr>
                    `).join('');
                }

                // --- UPDATE ENGINE 3: DELTA EXCHANGE INDIA OPTIONS PUT-CALL PARITY ---
                const optScanEl = document.getElementById('options-scan-time');
                if (optScanEl) optScanEl.innerText = 'Last Scan: ' + (data.state.options_parity_last_scan || 'Just Now');

                const optMarginEl = document.getElementById('opt-val-margin');
                if (optMarginEl) optMarginEl.innerText = '$' + ((data.state.delta_balance || 7.94) * 0.75).toFixed(2);

                const optBody = document.getElementById('options-parity-rows');
                if (optBody && data.state.options_parity_opportunities) {
                    if (data.state.options_parity_opportunities.length > 0) {
                        optBody.innerHTML = data.state.options_parity_opportunities.map((item, idx) => `
                            <tr>
                                <td><strong>${idx + 1}</strong></td>
                                <td><strong class="text-cyan">${item.coin}</strong></td>
                                <td><span class="badge-action">${item.type}</span></td>
                                <td>$${item.strike.toFixed(2)}</td>
                                <td>$${item.futures_mark.toFixed(2)}</td>
                                <td style="font-size:12px;">Call $${item.call_ask.toFixed(2)} / Put $${item.put_bid.toFixed(2)}</td>
                                <td><strong class="text-green">+${item.net_pnl_pct.toFixed(4)}%</strong></td>
                                <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${item.hours_to_exp.toFixed(2)} Hours</td>
                                <td><span class="badge-ex">${item.action}</span></td>
                            </tr>
                        `).join('');
                    } else {
                        optBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted);">Scanning live Delta options order books (Fee Gate &ge; 0.15% Net)...</td></tr>';
                    }
                }

            } catch (err) {
                console.error("Dashboard update error:", err);
            }
        }

        async function saveCoinDCXBal() {
            const val = parseFloat(document.getElementById('input-coindcx-bal').value);
            if (isNaN(val) || val <= 0) {
                alert("Please enter a valid CoinDCX balance amount in USD (e.g., 15.00)");
                return;
            }
            try {
                const res = await fetch('/api/balance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({coindcx_balance: val})
                });
                const data = await res.json();
                alert("✅ CoinDCX Balance updated to $" + val.toFixed(2) + " USD!");
                updateDashboard();
            } catch (e) {
                alert("Error saving balance: " + e);
            }
        }

        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>"""
