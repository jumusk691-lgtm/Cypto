# CRITICAL: Ye do lines sabse upar honi chahiye, kisi bhi aur import se pehle!
import eventlet
eventlet.monkey_patch()

import os
import time
import requests
import threading
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

# --- 1. CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# RAM State
master_symbol_list = [] 
subscribed_symbols = {} 
price_cache = {}

# --- 2. MASTER SYMBOL DOWNLOAD ---
def download_master_symbols():
    global master_symbol_list
    print("🚀 Downloading Master Symbols...")
    try:
        f_url = f"https://finnhub.io/api/v1/forex/symbol?exchange=oanda&token={FINNHUB_KEY}"
        c_url = f"https://finnhub.io/api/v1/crypto/symbol?exchange=binance&token={FINNHUB_KEY}"
        
        f_data = requests.get(f_url, timeout=10).json()
        c_data = requests.get(c_url, timeout=10).json()
        
        master_symbol_list = [{"s": i['symbol'], "d": i['displaySymbol']} for i in f_data + c_data]
        print(f"✅ {len(master_symbol_list)} symbols loaded.")
    except Exception as e:
        print(f"❌ Error: {e}")

# --- 3. ENGINE & CLEANUP ---
def fetch_batch(batch):
    for sym in batch:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
            res = requests.get(url, timeout=1.5).json()
            if res.get('c'):
                price_cache[sym] = {"s": sym, "p": "{:.5f}".format(res['c'])}
        except: continue

def engine():
    while True:
        active = list(subscribed_symbols.keys())
        if active:
            for i in range(0, len(active), 50):
                threading.Thread(target=fetch_batch, args=(active[i:i+50],)).start()
            socketio.emit('live_ticks', price_cache)
        eventlet.sleep(1.5)

def janitor():
    while True:
        now = time.time()
        expired = [s for s, t in subscribed_symbols.items() if now - t > 10]
        for s in expired:
            subscribed_symbols.pop(s, None)
            price_cache.pop(s, None)
        eventlet.sleep(5)

# --- 4. ROUTES & SOCKETS ---
@app.route('/api/search', methods=['POST'])
def search():
    query = request.json.get('query', '').upper()
    results = [s for s in master_symbol_list if query in s['d'].upper()][:20]
    return jsonify(results)

@socketio.on('subscribe')
def on_sub(data):
    sym = data.get('symbol')
    if sym:
        subscribed_symbols[sym] = time.time()
        if sym in price_cache: emit('instant_price', price_cache[sym])

@app.route('/')
def health(): return {"status": "running"}

if __name__ == '__main__':
    download_master_symbols()
    socketio.start_background_task(engine)
    socketio.start_background_task(janitor)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
