// BTC Hedging Terminal - Dashboard JS
let ws = null;

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => console.log('Connected');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateUI(data);
    };
    ws.onclose = () => setTimeout(connect, 3000);
}

function updateUI(data) {
    if (data.market) {
        document.getElementById('spot').textContent = '$' + data.market.spot.toFixed(2);
        document.getElementById('volatility').textContent = data.market.volatility.toFixed(2);
        document.getElementById('trend').textContent = data.market.trend;
    }

    if (data.greeks) {
        document.getElementById('delta').textContent = data.greeks.delta.toFixed(3);
        document.getElementById('gamma').textContent = data.greeks.gamma.toFixed(3);
        document.getElementById('theta').textContent = '$' + data.greeks.theta.toFixed(2) + '/day';
    }
}

document.addEventListener('DOMContentLoaded', connect);
