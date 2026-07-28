let ws = null;
let lastUpdateTimestamp = 0;

window.onerror = function(msg, url, lineNo, columnNo, error) {
    const log = document.getElementById('js-error-log');
    if (log) {
        log.style.display = 'block';
        log.innerText += `Error: ${msg}\nLine: ${lineNo}\nCol: ${columnNo}\n\n`;
    }
    return false;
};

// WebSocket Connection Logic
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/options_data`);
    
    ws.onopen = () => {
        console.log("WebSocket Connected");
        const banner = document.getElementById('api-glitch-banner');
        if(banner) {
            banner.style.display = 'none';
        }
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        
        if (msg.type === "live_update") {
            lastUpdateTimestamp = Date.now(); // Local time reference
            updateDashboard(msg);
            
            // Update live charts
            if (msg.server_time && msg.directional_setup) {
                // Lightweight charts uses unix timestamp in seconds. 
                // However, since it applies browser timezone, we should just pass the true unix epoch time.
                // But sometimes to force IST we can add offset if browser is not IST. Assume browser is IST.
                updateChartTick('nifty', msg.directional_setup.nifty_spot, msg.server_time);
                updateChartTick('bank', msg.directional_setup.banknifty_spot, msg.server_time);
                updateChartTick('sensex', msg.directional_setup.sensex_spot, msg.server_time);
            }
        }
    };
    
    ws.onclose = () => {
        console.log("WebSocket Disconnected. Reconnecting in 2 seconds...");
        const banner = document.getElementById('api-glitch-banner');
        if(banner) {
            banner.style.display = 'block';
            banner.innerHTML = '⚠️ DISCONNECTED FROM BACKEND. ATTEMPTING TO RECONNECT...';
            banner.style.background = '#ef5350';
            banner.style.color = 'white';
        }
        setTimeout(connectWebSocket, 2000);
    };
    
    ws.onerror = (err) => {
        console.error("WebSocket Error:", err);
        ws.close();
    };
}

// Stale Data Checker (checks every second)
setInterval(() => {
    if (lastUpdateTimestamp === 0 || !ws || ws.readyState !== WebSocket.OPEN) return;
    const diff = (Date.now() - lastUpdateTimestamp) / 1000;
    const banner = document.getElementById('api-glitch-banner');
    
    if (diff > 5) {
        if(banner) {
            banner.style.display = 'block';
            banner.innerHTML = `⚠️ STALE DATA: No updates received in ${Math.floor(diff)} seconds.`;
            banner.style.background = '#ffebee';
            banner.style.color = '#d32f2f';
        }
    } else {
        if(banner) banner.style.display = 'none';
    }
}, 1000);

function updateDashboard(data) {
    if (data.directional_setup) {
        const ds = data.directional_setup;
        
        // Nifty
        if(document.getElementById('nifty-live')) document.getElementById('nifty-live').innerText = ds.nifty_spot > 0 ? ds.nifty_spot.toFixed(2) : '--';
        if(document.getElementById('nifty-open')) document.getElementById('nifty-open').innerText = ds.nifty_day_open > 0 ? ds.nifty_day_open.toFixed(2) : '--';
        if(document.getElementById('nifty-low-val')) document.getElementById('nifty-low-val').innerText = ds.nifty_1d_low > 0 ? ds.nifty_1d_low.toFixed(2) : '--';
        const niftyEl = document.getElementById('nifty-low-status');
        if (niftyEl) {
            niftyEl.innerText = ds.nifty_1d_low_broken ? "BROKEN" : "SAFE";
            niftyEl.style.color = ds.nifty_1d_low_broken ? "#ef5350" : "#4caf50";
            niftyEl.style.background = ds.nifty_1d_low_broken ? "rgba(239, 83, 80, 0.1)" : "rgba(76, 175, 80, 0.1)";
        }
        
        // BankNifty
        if(document.getElementById('bank-live')) document.getElementById('bank-live').innerText = ds.banknifty_spot > 0 ? ds.banknifty_spot.toFixed(2) : '--';
        if(document.getElementById('bank-open')) document.getElementById('bank-open').innerText = ds.banknifty_day_open > 0 ? ds.banknifty_day_open.toFixed(2) : '--';
        const bTrend = document.getElementById('bank-trend');
        if (bTrend) {
            const val = ds.banknifty_1h_return;
            bTrend.innerText = (val > 0 ? "+" : "") + val.toFixed(2) + "%";
            bTrend.style.color = val >= 0 ? "#4caf50" : "#ef5350";
        }
        const bankEl = document.getElementById('bank-rs-status');
        if (bankEl) {
            bankEl.innerText = ds.banknifty_relative_weakness ? "WEAK" : "STRONG";
            bankEl.style.color = ds.banknifty_relative_weakness ? "#ef5350" : "#4caf50";
            bankEl.style.background = ds.banknifty_relative_weakness ? "rgba(239, 83, 80, 0.1)" : "rgba(76, 175, 80, 0.1)";
        }

        // Sensex
        if(document.getElementById('sensex-live')) document.getElementById('sensex-live').innerText = ds.sensex_spot > 0 ? ds.sensex_spot.toFixed(2) : '--';
        if(document.getElementById('sensex-open')) document.getElementById('sensex-open').innerText = ds.sensex_day_open > 0 ? ds.sensex_day_open.toFixed(2) : '--';
        if(document.getElementById('sensex-low-val')) document.getElementById('sensex-low-val').innerText = ds.sensex_1d_low > 0 ? ds.sensex_1d_low.toFixed(2) : '--';
        const sensexEl = document.getElementById('sensex-low-status');
        if (sensexEl) {
            // Only mark BROKEN if price is genuinely below the day low (not just startup where low == spot)
            let broken = ds.sensex_1d_low > 0 && ds.sensex_spot < ds.sensex_1d_low;
            sensexEl.innerText = broken ? "BROKEN" : "SAFE";
            sensexEl.style.color = broken ? "#ef5350" : "#4caf50";
            sensexEl.style.background = broken ? "rgba(239, 83, 80, 0.1)" : "rgba(76, 175, 80, 0.1)";
        }
        
        const badge = document.getElementById('dir-alert-badge');
        const container = document.getElementById('dir-card-container');
        if (badge && container) {
            if (ds.signal === "SELL") {
                badge.innerText = "🚨 SELL ALERT TRIGGERED";
                badge.style.background = "#ef5350";
                badge.style.color = "white";
                container.style.borderTopColor = "#ef5350";
            } else {
                badge.innerText = "NO SIGNAL";
                badge.style.background = "var(--border-color)";
                badge.style.color = "var(--text-primary)";
                container.style.borderTopColor = "#4caf50";
            }
        }
    }
}

// --- ECharts Logic ---
let charts = {};
let currentBars = {
    nifty: null,
    bank: null,
    sensex: null
};
let seriesData = {
    nifty: [],
    bank: [],
    sensex: []
};

function initCharts() {
    const commonOptions = {
        grid: { left: 0, right: 0, top: 5, bottom: 5 },
        xAxis: { type: 'category', show: false },
        yAxis: { type: 'value', scale: true, show: false, splitLine: { show: false } },
        series: [{
            type: 'candlestick',
            data: [],
            itemStyle: {
                color: '#4caf50', // up
                color0: '#ef5350', // down
                borderColor: '#4caf50',
                borderColor0: '#ef5350'
            }
        }]
    };
    
    ['nifty', 'bank', 'sensex'].forEach(id => {
        const container = document.getElementById(`${id}-chart`);
        if (container) {
            const chart = echarts.init(container);
            chart.setOption(commonOptions);
            charts[id] = chart;
        }
    });
}

function updateChartTick(id, price, timestamp) {
    if (!charts[id] || price <= 0) return;
    
    const coeff = 60;
    const roundedTime = Math.floor((timestamp + 19800) / coeff) * coeff - 19800;
    
    let bar = currentBars[id];
    
    if (!bar || bar.time !== roundedTime) {
        // [open, close, lowest, highest]
        bar = { time: roundedTime, open: price, close: price, low: price, high: price };
        currentBars[id] = bar;
        seriesData[id].push(bar);
        
        // Keep max 60 candles (1 hour) to avoid lag
        if (seriesData[id].length > 60) seriesData[id].shift();
    } else {
        bar.high = Math.max(bar.high, price);
        bar.low = Math.min(bar.low, price);
        bar.close = price;
    }
    
    const formattedData = seriesData[id].map(b => [b.open, b.close, b.low, b.high]);
    
    charts[id].setOption({
        series: [{ data: formattedData }]
    });
}

// Init
initCharts();
connectWebSocket();
