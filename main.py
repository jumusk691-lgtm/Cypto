import eventlet
eventlet.monkey_patch()

import os, time, requests, threading
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

# --- 1. CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global RAM state (Database ki jagah RAM use karenge fast speed ke liye)
master_symbol_list = [] # Search ke liye
subscribed_symbols = {} # { 'OANDA:EUR_USD': last_active_time }
price_cache = {}        # { 'OANDA:EUR_USD': {'p': '1.08542'} }

# ==============================================================================
# 2. MASTER SYMBOL DOWNLOAD (One-time)
# ==============================================================================
def download_master_symbols():
    """Finnhub se saare symbols RAM mein load karta hai (Search ke liye)"""
    global master_symbol_list
    print("🚀 Downloading Master Symbols from Finnhub...")
    try:
        # Forex (OANDA) & Crypto (Binance)
        f_data = requests.get(f"https://finnhub.io/api/v1/forex/symbol?exchange=oanda&token={FINNHUB_KEY}").json()
        c_data = requests.get(f"https://finnhub.io/api/v1/crypto/symbol?exchange=binance&token={FINNHUB_KEY}").json()
        
        master_symbol_list = [{"s": i['symbol'], "d": i['displaySymbol']} for i in f_data + c_data]
        print(f"✅ {len(master_symbol_list)} Symbols loaded in RAM.")
    except Exception as e:
        print(f"❌ Load Error: {e}")

# ==============================================================================
# 3. SEARCH & LIVE ENGINE
# ==============================================================================
@app.route('/api/search', methods=['POST'])
def search():
    query = request.json.get('query', '').upper()
    results = [s for s in master_symbol_list if query in s['d'].upper()][:20]
    return jsonify(results)

def fetch_batch(batch):
    """Finnhub API Pulse"""
    for sym in batch:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
            res = requests.get(url, timeout=1.5).json()
            if res.get('c'):
                price_cache[sym] = {"s": sym, "p": "{:.5f}".format(res['c']), "t": time.time()}
        except: continue

def run_global_engine():
    while True:
        active = list(subscribed_symbols.keys())
        if active:
            # Batching 50 (Point 5)
            for i in range(0, len(active), 50):
                threading.Thread(target=fetch_batch, args=(active[i:i+50],)).start()
            
            # Ek saath live update (Point 6)
            socketio.emit('live_ticks', price_cache)
        eventlet.sleep(1.5)

# ==============================================================================
# 4. SOCKET EVENTS & CLEANUP
# ==============================================================================
@socketio.on('subscribe')
def on_sub(data):
    sym = data.get('symbol')
    if sym:
        subscribed_symbols[sym] = time.time()
        if sym in price_cache: emit('instant_price', price_cache[sym])

def janitor():
    """5-sec Cleanup (Point 7)"""
    while True:
        now = time.time()
        expired = [s for s, t in subscribed_symbols.items() if now - t > 10]
        for s in expired:
            subscribed_symbols.pop(s, None)
            price_cache.pop(s, None)
        eventlet.sleep(5)

if __name__ == '__main__':
    download_master_symbols()
    socketio.start_background_task(run_global_engine)
    socketio.start_background_task(janitor)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
