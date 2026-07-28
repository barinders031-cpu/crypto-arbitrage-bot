// ============================================================
// ANTIGRAVITY — Dashboard App.js v4
// Sensibull-Style OI Panel with Expiry Sidebar
// ============================================================

let lastState = {};
let tickChart = null;
let oiChart = null;
const MAX_TICKS = 100;
let tickData = [];
let tickLabels = [];

// ---- UI State for OI Panel ----
let _atmWindow = 10;          // FIXED 10 up/10 down as requested
let _minStrikeFilter = 0;     // 0 = no filter
let _maxStrikeFilter = 0;     // 0 = no filter
let _allStrikes = [];         // Full strikes array from last state
let _atmStrike = 0;
let _strikeGap = 50;

// ============================================================
// CHART INITIALIZATION
// ============================================================
function initCharts() {
    // 1. Live Tick Chart (Line + Annotations)
    const tickCtx = document.getElementById('live-tick-chart').getContext('2d');
    tickChart = new Chart(tickCtx, {
        type: 'line',
        data: {
            labels: tickLabels,
            datasets: [{
                label: 'Spot Price',
                data: tickData,
                borderColor: '#ffffff',
                borderWidth: 2,
                tension: 0.1,
                pointRadius: 0,
                fill: {
                    target: 'origin',
                    above: 'rgba(255,255,255,0.03)'
                }
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            scales: {
                x: { display: false },
                y: {
                    position: 'right',
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: '#8b95a8' }
                }
            },
            plugins: {
                legend: { display: false },
                annotation: { annotations: {} }
            }
        }
    });

    // 2. SENSIBULL STYLE OPEN INTEREST (Stacked Vertical Bar Chart)
    const oiCtx = document.getElementById('oi-bar-chart').getContext('2d');
    oiChart = new Chart(oiCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Put Increase',
                    data: [],
                    backgroundColor: '#10B981', // Solid for increase
                    stack: 'PE',
                    barPercentage: 1.0,
                    categoryPercentage: 0.85,
                },
                {
                    label: 'Put Decrease',
                    data: [],
                    backgroundColor: 'rgba(16,185,129,0.15)',
                    borderColor: '#10B981',
                    borderWidth: 1,
                    stack: 'PE',
                    barPercentage: 1.0,
                    categoryPercentage: 0.85,
                },
                {
                    label: 'Call Increase',
                    data: [],
                    backgroundColor: '#EF4444', // Solid for increase
                    stack: 'CE',
                    barPercentage: 1.0,
                    categoryPercentage: 0.85,
                },
                {
                    label: 'Call Decrease',
                    data: [],
                    backgroundColor: 'rgba(239,68,68,0.15)',
                    borderColor: '#EF4444',
                    borderWidth: 1,
                    stack: 'CE',
                    barPercentage: 1.0,
                    categoryPercentage: 0.85,
                }
            ]
        },
        options: {
            animation: false,
            normalized: true,
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: {
                    position: 'bottom',
                    grid: { display: false, drawBorder: true, borderColor: '#cbd5e1' },
                    ticks: {
                        display: true,
                        color: '#0f172a',
                        font: { size: 10, weight: 'bold' },
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 30
                    },
                    stacked: true
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        color: '#94A3B8',
                        font: { size: 11 },
                        maxTicksLimit: 8,
                        callback: function(value) {
                            if (value === 0) return '0';
                            const abs = Math.abs(value);
                            // Show in Crores only if truly above 1Cr (and round cleanly)
                            if (abs >= 10_000_000) {
                                return parseFloat((value / 10_000_000).toFixed(1)) + 'Cr';
                            }
                            // Show in Lakhs (most common Sensibull range)
                            return parseFloat((value / 100_000).toFixed(0)) + 'L';
                        }
                    },
                    stacked: true,
                    beginAtZero: true
                }
            },
            layout: {
                padding: {
                    bottom: 25
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#0B0E14',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    titleFont: { size: 13, weight: 'bold', family: 'JetBrains Mono' },
                    titleColor: '#ffffff',
                    bodyFont: { size: 12 },
                    callbacks: {
                        title: function(ctx) {
                            if (ctx.length > 0) return 'Strike: ' + ctx[0].label;
                            return '';
                        },
                        label: function(ctx) {
                            if (!ctx.raw || ctx.raw === 0) return null;
                            let valStr = fmtK(ctx.raw);
                            let prefix = '';
                            if (ctx.dataset.label.includes('Increase')) prefix = '▲ ';
                            if (ctx.dataset.label.includes('Decrease')) prefix = '▼ ';
                            return ctx.dataset.label + ': ' + prefix + valStr;
                        }
                    }
                },
                annotation: { annotations: {} }
            },
            onClick: function(evt, elements) {
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    const strikeLabel = this.data.labels[idx];
                    if (typeof showDrilldown === 'function') {
                        showDrilldown(strikeLabel);
                    }
                }
            }
        }
    });
}

// Creates diagonal stripe pattern for "Increase" bars (like Sensibull)
function createDiagonalPattern(ctx, fillColor, stripeColor) {
    try {
        const canvas = document.createElement('canvas');
        canvas.width = 10;
        canvas.height = 10;
        const pCtx = canvas.getContext('2d');
        pCtx.fillStyle = fillColor;
        pCtx.fillRect(0, 0, 10, 10);
        pCtx.strokeStyle = stripeColor;
        pCtx.lineWidth = 2;
        pCtx.beginPath();
        pCtx.moveTo(0, 10);
        pCtx.lineTo(10, 0);
        pCtx.stroke();
        return ctx.chart.ctx.createPattern(canvas, 'repeat');
    } catch (e) {
        return fillColor;
    }
}

// ============================================================
// EXPIRY SIDEBAR RENDERING
// ============================================================
function renderExpirySidebar(oc) {
    const listEl = document.getElementById('expiry-list');
    if (!listEl || !oc) return;

    const availableExpiries = oc.available_expiries || [];
    const selectedExpiry = (oc.selected_expiry || '').toUpperCase();
    const today = new Date();

    if (availableExpiries.length === 0) {
        listEl.innerHTML = '<div class="expiry-loading">Market closed / No data</div>';
        return;
    }

    let html = '';
    availableExpiries.forEach((exp, idx) => {
        const expUpper = exp.toUpperCase();
        let expDate;
        try {
            expDate = parseExpiry(expUpper);
        } catch (e) {
            return;
        }
        const diffDays = Math.round((expDate - today) / (1000 * 60 * 60 * 24));
        const isSelected = expUpper === selectedExpiry;
        const isWeekly = diffDays <= 7;
        const weeklyBadge = isWeekly ? '<span class="expiry-weekly-badge">W</span>' : '';
        const displayDate = formatExpiry(expDate);

        html += `
            <div class="expiry-row ${isSelected ? 'expiry-row-selected' : ''}" 
                 data-expiry="${expUpper}" 
                 id="expiry-row-${idx}"
                 onclick="selectExpiry('${expUpper}')">
                <span class="expiry-checkbox ${isSelected ? 'expiry-checkbox-checked' : ''}">
                    ${isSelected ? '✓' : ''}
                </span>
                <span class="expiry-date">${displayDate}</span>
                <span class="expiry-days">(${diffDays} days)</span>
                ${weeklyBadge}
            </div>`;
    });

    listEl.innerHTML = html;
}

function parseExpiry(expStr) {
    // e.g. "09JUN2026" → Date
    const months = {JAN:0,FEB:1,MAR:2,APR:3,MAY:4,JUN:5,JUL:6,AUG:7,SEP:8,OCT:9,NOV:10,DEC:11};
    const day = parseInt(expStr.substring(0, 2));
    const mon = expStr.substring(2, 5);
    const year = parseInt(expStr.substring(5));
    return new Date(year, months[mon], day);
}

function formatExpiry(expDate) {
    // e.g. "09 Jun"
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return String(expDate.getDate()).padStart(2, '0') + ' ' + months[expDate.getMonth()];
}

function selectExpiry(expiry) {
    fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_expiry', expiry: expiry })
    }).then(r => r.json()).then(() => {
        fetchState(); // Refresh immediately
    }).catch(e => console.warn('Expiry switch error:', e));
}

// ============================================================
// STRIKE FILTER LOGIC
// ============================================================
function getFilteredStrikes(allStrikes, atmStrike, atmWindow, minFilter, maxFilter) {
    if (!allStrikes || allStrikes.length === 0) return [];
    
    // Ignore UI slider overrides and return exactly what the backend calculated.
    // The backend is already hardcoded to send exactly 10 strikes UP and 10 strikes DOWN (21 total).
    return allStrikes;
}

function updateStrikeRangeInputs(allStrikes) {
    if (!allStrikes || allStrikes.length === 0) return;
    const strikes = allStrikes.map(s => s.strike);
    const minS = Math.min(...strikes);
    const maxS = Math.max(...strikes);

    const minEl = document.getElementById('min-strike-input');
    const maxEl = document.getElementById('max-strike-input');
    if (minEl && (!minEl.dataset.userSet || minEl.dataset.userSet === '0')) {
        minEl.value = minS;
        minEl.dataset.defaultVal = minS;
    }
    if (maxEl && (!maxEl.dataset.userSet || maxEl.dataset.userSet === '0')) {
        maxEl.value = maxS;
        maxEl.dataset.defaultVal = maxS;
    }

    _minStrikeFilter = parseInt(minEl.value) || 0;
    _maxStrikeFilter = parseInt(maxEl.value) || 0;
}

// ============================================================
// CHART UPDATE
// ============================================================
function updateCharts(d) {
    if (!tickChart || !oiChart) return;

    // --- Update Tick Chart ---
    if (d.nifty_spot) {
        tickLabels.push(d.timestamp);
        tickData.push(d.nifty_spot);
        if (tickData.length > MAX_TICKS) {
            tickData.shift();
            tickLabels.shift();
        }

        const annotations = {};
        let annCount = 0;

        if (d.ai_levels) {
            d.ai_levels.supports.forEach(sup => {
                annotations[`ai_sup_${annCount++}`] = {
                    type: 'line', yMin: sup, yMax: sup,
                    borderColor: '#00ff88', borderWidth: 2, borderDash: [5, 5],
                    label: { display: true, content: 'AI SUP', position: 'start', color: '#00ff88', backgroundColor: 'transparent' }
                };
            });
            d.ai_levels.resistances.forEach(res => {
                annotations[`ai_res_${annCount++}`] = {
                    type: 'line', yMin: res, yMax: res,
                    borderColor: '#ff4d4d', borderWidth: 2, borderDash: [5, 5],
                    label: { display: true, content: 'AI RES', position: 'start', color: '#ff4d4d', backgroundColor: 'transparent' }
                };
            });
        }

        if (d.ghost_grid_locked && d.ghost_grid && d.ghost_grid.anchor) {
            annotations[`ghost_anchor`] = {
                type: 'line', yMin: d.ghost_grid.anchor, yMax: d.ghost_grid.anchor,
                borderColor: '#9d00ff', borderWidth: 1.5,
                label: { display: true, content: 'GRID ANCHOR', position: 'end', color: '#9d00ff', backgroundColor: 'transparent' }
            };
        }

        tickChart.options.plugins.annotation.annotations = annotations;
        tickChart.update();
    }

    // --- Update SENSIBULL STYLE OI Chart ---
    const oc = d.option_chain;
    if (oc && oc.strikes && oc.strikes.length > 0) {
        _allStrikes = oc.strikes;
        _atmStrike = oc.atm_strike || 0;

        // Detect strike gap from data
        if (_allStrikes.length >= 2) {
            _strikeGap = Math.abs(_allStrikes[1].strike - _allStrikes[0].strike) || 50;
        }

        // Update ATM status badge
        const statusEl = document.getElementById('oi-data-status');
        if (statusEl) {
            const st = oc.status || 'UNKNOWN';
            statusEl.textContent = st;
            statusEl.className = 'oi-status-pill ' + (st === 'LIVE' ? 'oi-status-live' : st === 'SIMULATED' ? 'oi-status-sim' : '');
        }

        // Update strike range inputs if first load
        updateStrikeRangeInputs(_allStrikes);

        // Apply filters
        const filtered = getFilteredStrikes(_allStrikes, _atmStrike, _atmWindow, _minStrikeFilter, _maxStrikeFilter);
        renderOIChart(filtered, d.nifty_spot, _atmStrike);
        renderExpirySidebar(oc);

        // Update Total OI Badges
        updateOITotals(oc);
    }
}

function renderOIChart(strikesData, spotPrice, atmStrike) {
    if (!strikesData || strikesData.length === 0) return;

    const strikeLabels = strikesData.map(s => String(s.strike));
    const pe_inc = [], pe_dec = [];
    const ce_inc = [], ce_dec = [];

    strikesData.forEach(s => {
        // Use server-aggregated buckets (or fallback to client-side if missing)
        const c_inc = s.call_inc !== undefined ? s.call_inc : Math.max(0, s.ce_chg_oi);
        const c_dec = s.call_dec !== undefined ? s.call_dec : Math.abs(Math.min(0, s.ce_chg_oi));
        const p_inc = s.put_inc !== undefined ? s.put_inc : Math.max(0, s.pe_chg_oi);
        const p_dec = s.put_dec !== undefined ? s.put_dec : Math.abs(Math.min(0, s.pe_chg_oi));

        pe_inc.push(p_inc);
        pe_dec.push(p_dec > 0 ? -p_dec : 0); // draw decreases downwards

        ce_inc.push(c_inc);
        ce_dec.push(c_dec > 0 ? -c_dec : 0); // draw decreases downwards
    });

    oiChart.data.labels = strikeLabels;
    oiChart.data.datasets[0].data = pe_inc;
    oiChart.data.datasets[1].data = pe_dec;
    oiChart.data.datasets[2].data = ce_inc;
    oiChart.data.datasets[3].data = ce_dec;

    // Spot Price Vertical Marker + ATM annotation
    const annotations = {};
    if (spotPrice && strikeLabels.length > 0) {
        let closestIdx = 0;
        let minDiff = Math.abs(strikeLabels[0] - spotPrice);
        strikeLabels.forEach((s, i) => {
            const diff = Math.abs(s - spotPrice);
            if (diff < minDiff) { minDiff = diff; closestIdx = i; }
        });

        annotations.spotLine = {
            type: 'line',
            xMin: closestIdx,
            xMax: closestIdx,
            borderColor: 'rgba(0,0,0,0.5)',
            borderWidth: 1.5,
            borderDash: [5, 4],
            label: {
                display: true,
                content: 'ATM: ' + fmt(atmStrike),
                position: 'end',
                color: '#0B0E14',
                backgroundColor: '#E2E8F0',
                yAdjust: -10,
                font: { size: 11, weight: 'bold', family: 'JetBrains Mono' },
                borderRadius: 4,
                padding: { x: 6, y: 3 }
            }
        };
    }

    oiChart.options.plugins.annotation.annotations = annotations;
    oiChart.update();
}

function updateOITotals(oc) {
    const elCeTotal = document.getElementById('oi-chg-ce-total');
    const elPeTotal = document.getElementById('oi-chg-pe-total');
    if (!elCeTotal || !elPeTotal) return;

    const ceChg = oc.total_ce_chg_oi || 0;
    const peChg = oc.total_pe_chg_oi || 0;

    elCeTotal.textContent = (ceChg > 0 ? '+' : '') + fmtK(ceChg);
    elCeTotal.style.color = ceChg > 0 ? '#ef4444' : '#10B981';

    elPeTotal.textContent = (peChg > 0 ? '+' : '') + fmtK(peChg);
    elPeTotal.style.color = peChg > 0 ? '#10B981' : '#ef4444';
}

// ============================================================
// DATA FETCH
// ============================================================
async function fetchState() {
    try {
        const response = await fetch('/api/get_live_state');
        if (response.ok) {
            const data = await response.json();
            lastState = data;
            renderAll(data);
        }
    } catch (e) {
        console.warn("API fetch error:", e);
    }
}

function renderAll(d) {
    renderHeader(d);
    renderPCR(d);
    renderGhostGrid(d);
    renderVelocity(d);
    renderNewsAlerts(d);
    updateCharts(d);
}

// ============================================================
// RENDER FUNCTIONS
// ============================================================
function renderHeader(d) {
    document.getElementById('nifty-spot').textContent = fmt(d.nifty_spot);
    document.getElementById('system-time').textContent = d.timestamp || '--:--:--';

    // PCR in header
    const headerPcr = document.getElementById('header-pcr-val');
    if (headerPcr) {
        headerPcr.textContent = d.pcr_oi ? Number(d.pcr_oi).toFixed(2) : '--';
        headerPcr.style.color = d.pcr_oi > 1 ? '#10B981' : '#EF4444';
    }

    // Data status badge in header
    const statusBadge = document.getElementById('data-status-badge');
    if (statusBadge && d.option_chain) {
        const st = d.option_chain.status || 'UNKNOWN';
        statusBadge.textContent = st;
        statusBadge.className = st === 'LIVE' ? 'badge-active' : 'badge-neutral';
    }

    // Sync dropdown with backend selected_index
    const indexSelect = document.getElementById('index-switcher');
    if (indexSelect && d.selected_index && indexSelect.value !== d.selected_index) {
        indexSelect.value = d.selected_index;
    }

    // Update label
    const idxLabel = document.getElementById('index-label');
    if (idxLabel && d.selected_index) {
        idxLabel.textContent = (d.selected_index === 'SENSEX' ? 'BSE SENSEX SPOT' : 'NIFTY 50 SPOT');
    }

    // Dynamic OI header date
    const oiHeader = document.getElementById('oi-dynamic-header');
    if (oiHeader) {
        const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
        const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        const now = new Date();
        oiHeader.textContent = `OI Change on ${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]}`;
    }

    const moodEl = document.getElementById('pcr-mood-display');
    if (moodEl) {
        moodEl.textContent = d.pcr_mood || '🟡 RANGEBOUND';
        if (d.pcr_mood && d.pcr_mood.includes('BULLISH')) moodEl.className = 'mood-badge mood-bullish';
        else if (d.pcr_mood && d.pcr_mood.includes('BEARISH')) moodEl.className = 'mood-badge mood-bearish';
        else moodEl.className = 'mood-badge mood-neutral';
    }
}

function renderPCR(d) {
    document.getElementById('pcr-oi-val').textContent = fmt(d.pcr_oi);

    let chgPcr = 1.0;
    if (d.option_chain && d.option_chain.total_ce_chg_oi !== 0) {
        let pe_delta = d.option_chain.total_pe_chg_oi;
        let ce_delta = d.option_chain.total_ce_chg_oi;
        if (ce_delta < 0 && pe_delta < 0) {
            chgPcr = Math.abs(pe_delta) / Math.abs(ce_delta);
        } else if (ce_delta < 0) {
            chgPcr = 2.0;
        } else if (pe_delta < 0) {
            chgPcr = 0.5;
        } else {
            chgPcr = pe_delta / ce_delta;
        }
    }

    const chgEl = document.getElementById('pcr-chg-val');
    chgEl.textContent = fmt(chgPcr);
    chgEl.style.color = chgPcr > 1.0 ? '#10B981' : '#EF4444';
}

function renderGhostGrid(d) {
    const lockBadge = document.getElementById('ghost-lock-badge');
    const anchorEl = document.getElementById('ghost-anchor');
    const lockTimeEl = document.getElementById('ghost-lock-time');
    const ladderEl = document.getElementById('ghost-ladder');
    const activeZoneEl = document.getElementById('ghost-active-zone');

    if (!d.ghost_grid_locked) {
        lockBadge.textContent = 'AWAITING LOCK';
        lockBadge.className = 'badge-neutral';
        return;
    }

    lockBadge.textContent = 'LOCKED';
    lockBadge.className = 'badge-active';
    const grid = d.ghost_grid || {};
    anchorEl.textContent = fmt(grid.anchor);
    lockTimeEl.textContent = grid.capture_time || '--:--';

    const activeZone = d.active_zone || {};
    activeZoneEl.textContent = activeZone.zone_name || 'NO_ZONE';

    if (ladderEl.dataset.anchor === String(grid.anchor) && ladderEl.dataset.zone === activeZone.zone_name) return;
    ladderEl.dataset.anchor = grid.anchor;
    ladderEl.dataset.zone = activeZone.zone_name;

    const zones = grid.zones || {};
    let html = '';
    const order = ['R3', 'R2', 'R1', 'TRAP', 'S1', 'S2', 'S3'];
    for (const name of order) {
        if (!zones[name]) continue;
        const z = zones[name];
        const isActive = activeZone.zone_name === name ? ' active-zone-row' : '';
        html += `<div style="display:flex;justify-content:space-between;padding:5px;border-bottom:1px solid rgba(255,255,255,0.1);" class="${isActive}">`;
        html += `<span><strong>${name}</strong> (${fmt(z.center)})</span>`;
        html += `<span style="font-size:0.8rem;color:#8b95a8;">R: ${z.lower_resistance}-${z.upper_resistance} | S: ${z.lower_support}-${z.upper_support}</span>`;
        html += `</div>`;
    }
    ladderEl.innerHTML = html;
}

function renderVelocity(d) {
    const oi = d.oi_velocity || {};
    const ceD = oi.ce_deltas || {};
    const peD = oi.pe_deltas || {};
    setDelta('ce-delta-1m', ceD[1]);
    setDelta('ce-delta-3m', ceD[3]);
    setDelta('pe-delta-1m', peD[1]);
    setDelta('pe-delta-3m', peD[3]);
}

function renderNewsAlerts(d) {
    const ticker = document.getElementById('news-ticker');
    const headlines = d.latest_news || [];
    if (headlines.length === 0) {
        ticker.innerHTML = '<div class="news-placeholder">Scanning feeds...</div>';
        return;
    }
    let html = '';
    for (const h of headlines.slice(0, 5)) {
        html += `<div style="padding:5px;border-bottom:1px solid rgba(255,255,255,0.1);"><span style="color:#8b95a8;">${h.time || ''}</span> ${h.headline}</div>`;
    }
    ticker.innerHTML = html;
}

// ============================================================
// HELPERS
// ============================================================
function fmt(n) {
    if (n === null || n === undefined) return '--';
    return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtK(n) {
    if (n === null || n === undefined) return '--';
    const v = Number(n);
    if (Math.abs(v) >= 10000000) return (v / 10000000).toFixed(2) + ' Cr';
    if (Math.abs(v) >= 100000) return (v / 100000).toFixed(2) + ' L';
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1) + ' K';
    return v.toFixed(0);
}

function setDelta(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const v = val || 0;
    el.textContent = fmtK(v);
    el.style.color = v > 0 ? '#00ff88' : v < 0 ? '#ff4d4d' : '#8b95a8';
}

// ============================================================
// BUTTON BINDINGS
// ============================================================
function bindButtons() {
    // Index Switcher
    const indexSelect = document.getElementById('index-switcher');
    if (indexSelect) {
        indexSelect.addEventListener('change', (e) => {
            tickLabels = []; tickData = []; if (tickChart) tickChart.update();
            _allStrikes = []; _atmStrike = 0;
            fetch('/api/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'switch_index', index: e.target.value })
            });
        });
    }

    // Bhavcopy Upload
    const uploadInput = document.getElementById('bhavcopy-upload');
    if (uploadInput) {
        uploadInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(evt) {
                const content = evt.target.result;
                const idx = document.getElementById('index-switcher').value;
                fetch('/api/upload_bhavcopy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ index_name: idx, csv_content: content })
                }).then(r => r.json()).then(res => {
                    if (res.status === "success") {
                        alert(`Bhavcopy AI Sync!\nSupports: ${res.supports.join(', ')}\nResistances: ${res.resistances.join(', ')}`);
                    } else {
                        alert("Error: " + res.error);
                    }
                });
            };
            reader.readAsText(file);
        });
    }

    // ATM Buttons
    const atmGroup = document.getElementById('atm-btn-group');
    if (atmGroup) {
        atmGroup.querySelectorAll('.atm-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                atmGroup.querySelectorAll('.atm-btn').forEach(b => b.classList.remove('atm-btn-active'));
                btn.classList.add('atm-btn-active');
                _atmWindow = parseInt(btn.dataset.val);
                // Reset manual range filters when ATM window changes
                document.getElementById('min-strike-input').dataset.userSet = '0';
                document.getElementById('max-strike-input').dataset.userSet = '0';
                if (_allStrikes.length > 0) {
                    updateStrikeRangeInputs(_allStrikes);
                    const filtered = getFilteredStrikes(_allStrikes, _atmStrike, _atmWindow, 0, 0);
                    renderOIChart(filtered, lastState.nifty_spot, _atmStrike);
                }
            });
        });
    }

    // Strike Range — Min/Max inputs
    function setupStrikeInput(inputId, decBtnId, incBtnId, isMin) {
        const input = document.getElementById(inputId);
        const decBtn = document.getElementById(decBtnId);
        const incBtn = document.getElementById(incBtnId);
        if (!input || !decBtn || !incBtn) return;

        const applyFilter = () => {
            input.dataset.userSet = '1';
            _minStrikeFilter = parseInt(document.getElementById('min-strike-input').value) || 0;
            _maxStrikeFilter = parseInt(document.getElementById('max-strike-input').value) || 0;
            if (_allStrikes.length > 0) {
                const filtered = getFilteredStrikes(_allStrikes, _atmStrike, _atmWindow, _minStrikeFilter, _maxStrikeFilter);
                renderOIChart(filtered, lastState.nifty_spot, _atmStrike);
            }
        };

        decBtn.addEventListener('click', () => {
            input.value = parseInt(input.value) - _strikeGap;
            applyFilter();
        });
        incBtn.addEventListener('click', () => {
            input.value = parseInt(input.value) + _strikeGap;
            applyFilter();
        });
        input.addEventListener('change', applyFilter);
    }

    setupStrikeInput('min-strike-input', 'min-strike-dec', 'min-strike-inc', true);
    setupStrikeInput('max-strike-input', 'max-strike-dec', 'max-strike-inc', false);

    // Strike Range Reset
    const resetBtn = document.getElementById('strike-range-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            const minEl = document.getElementById('min-strike-input');
            const maxEl = document.getElementById('max-strike-input');
            minEl.dataset.userSet = '0';
            maxEl.dataset.userSet = '0';
            _minStrikeFilter = 0;
            _maxStrikeFilter = 0;
            if (_allStrikes.length > 0) {
                updateStrikeRangeInputs(_allStrikes);
                const filtered = getFilteredStrikes(_allStrikes, _atmStrike, _atmWindow, 0, 0);
                renderOIChart(filtered, lastState.nifty_spot, _atmStrike);
            }
        });
    }
}

// ============================================================
// NEW FEATURES
// ============================================================
function showDrilldown(strikeStr) {
    const strike = parseFloat(strikeStr);
    const modal = document.getElementById('drilldown-modal');
    if (!modal) return;
    
    // Find strike data
    const sData = _allStrikes.find(s => s.strike === strike);
    if (!sData) return;

    document.getElementById('drilldown-strike-title').textContent = 'Strike ' + strike;
    
    // Mock Greeks if not available
    const greeks = sData.greeks || { delta: (Math.random()).toFixed(2), theta: (-Math.random()*10).toFixed(2), gamma: '0.01', vega: (Math.random()*5).toFixed(2) };
    
    document.getElementById('drill-delta').textContent = greeks.delta || '--';
    document.getElementById('drill-theta').textContent = greeks.theta || '--';
    document.getElementById('drill-gamma').textContent = greeks.gamma || '--';
    document.getElementById('drill-vega').textContent = greeks.vega || '--';

    document.getElementById('drill-ce-oi').textContent = fmtK(sData.ce_oi);
    document.getElementById('drill-ce-chgoi').textContent = fmtK(sData.ce_chg_oi);
    document.getElementById('drill-ce-vol').textContent = fmtK(sData.ce_volume || 0);

    document.getElementById('drill-pe-oi').textContent = fmtK(sData.pe_oi);
    document.getElementById('drill-pe-chgoi').textContent = fmtK(sData.pe_chg_oi);
    document.getElementById('drill-pe-vol').textContent = fmtK(sData.pe_volume || 0);

    modal.classList.remove('hidden');
}

function bindNewButtons() {
    // Modal Close
    const modalClose = document.getElementById('drilldown-close');
    if (modalClose) {
        modalClose.addEventListener('click', () => {
            document.getElementById('drilldown-modal').classList.add('hidden');
        });
    }

    // Theme Toggle
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const card = document.getElementById('oi-chart-card');
            if (card) {
                if (card.classList.contains('sensibull-light')) {
                    card.classList.remove('sensibull-light');
                    themeBtn.textContent = '🌙';
                    updateChartTheme(false);
                } else {
                    card.classList.add('sensibull-light');
                    themeBtn.textContent = '☀️';
                    updateChartTheme(true);
                }
            }
        });
    }

    // Mode Toggle
    const modeToggle = document.getElementById('oi-mode-toggle');
    if (modeToggle) {
        modeToggle.addEventListener('click', () => {
            if (modeToggle.textContent === 'LIVE MODE') {
                modeToggle.textContent = 'SIMULATED';
                modeToggle.style.color = 'var(--accent-amber)';
            } else {
                modeToggle.textContent = 'LIVE MODE';
                modeToggle.style.color = 'var(--text-primary)';
            }
        });
    }

    // Exports
    const exportPng = document.getElementById('oi-export-png');
    if (exportPng) {
        exportPng.addEventListener('click', () => {
            const link = document.createElement('a');
            link.download = 'oi-chart.png';
            link.href = document.getElementById('oi-bar-chart').toDataURL();
            link.click();
        });
    }
    const exportCsv = document.getElementById('oi-export-csv');
    if (exportCsv) {
        exportCsv.addEventListener('click', () => {
            if (_allStrikes.length === 0) return;
            let csv = "Strike,CE_OI,CE_CHG,PE_OI,PE_CHG\\n";
            _allStrikes.forEach(s => {
                csv += `${s.strike},${s.ce_oi || 0},${s.ce_chg_oi || 0},${s.pe_oi || 0},${s.pe_chg_oi || 0}\\n`;
            });
            const blob = new Blob([csv], { type: 'text/csv' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'oi-data.csv';
            link.click();
        });
    }

    // Time Slider Mock
    const timeSlider = document.getElementById('oi-time-slider');
    const timeLabel = document.getElementById('oi-time-slider-label');
    if (timeSlider && timeLabel) {
        timeSlider.addEventListener('input', (e) => {
            const val = parseInt(e.target.value);
            if (val === 100) {
                timeLabel.textContent = 'LIVE';
                // Trigger full reload
                if (_allStrikes.length > 0) {
                    const filtered = getFilteredStrikes(_allStrikes, _atmStrike, _atmWindow, _minStrikeFilter, _maxStrikeFilter);
                    renderOIChart(filtered, lastState.nifty_spot, _atmStrike);
                }
            } else {
                // Mock historical interpolation
                const h = 9 + Math.floor((val / 100) * 6);
                const m = Math.floor(((val / 100) * 360) % 60);
                timeLabel.textContent = `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}`;
                
                // Scale values down slightly for visual effect
                if (_allStrikes.length > 0) {
                    const mockStrikes = _allStrikes.map(s => ({
                        ...s,
                        ce_chg_oi: s.ce_chg_oi * (val/100),
                        pe_chg_oi: s.pe_chg_oi * (val/100)
                    }));
                    const filtered = getFilteredStrikes(mockStrikes, _atmStrike, _atmWindow, _minStrikeFilter, _maxStrikeFilter);
                    renderOIChart(filtered, lastState.nifty_spot, _atmStrike);
                }
            }
        });
    }
}

function updateChartTheme(isLight) {
    if (!oiChart) return;
    const color = isLight ? '#0f172a' : '#cbd5e1';
    const gridColor = isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)';
    
    oiChart.options.scales.x.ticks.color = color;
    oiChart.options.scales.x.grid.borderColor = isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)';
    oiChart.options.scales.y.ticks.color = color;
    oiChart.options.scales.y.grid.color = gridColor;
    
    if (oiChart.options.plugins.tooltip) {
        oiChart.options.plugins.tooltip.backgroundColor = isLight ? '#ffffff' : '#0B0E14';
        oiChart.options.plugins.tooltip.titleColor = isLight ? '#0f172a' : '#ffffff';
        oiChart.options.plugins.tooltip.bodyColor = isLight ? '#475569' : '#ffffff';
        oiChart.options.plugins.tooltip.borderColor = isLight ? '#e2e8f0' : 'rgba(255,255,255,0.1)';
    }
    
    oiChart.update();
}

// ============================================================
// BOOT
// ============================================================
window.onload = () => {
    initCharts();
    bindButtons();
    bindNewButtons();
    setInterval(fetchState, 1500);
    fetchState();
};
