import eventlet
eventlet.monkey_patch()

import os
import time
import requests
# threading ki jagah eventlet ka internal thread use karenge crash se bachne ke liye
import eventlet.greenpool 

from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

# --- 1. CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"

app = Flask(__name__)
# Flask-SocketIO ko manage karne ke liye
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

master_symbol_list = [] 
subscribed_symbols = {} 
price_cache = {}

# --- 2. ENGINE LOGIC (Updated for Stability) ---
def fetch_batch(batch):
    for sym in batch:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
            res = requests.get(url, timeout=2).json()
            if res.get('c'):
                price_cache[sym] = {"s": sym, "p": "{:.5f}".format(res['c'])}
        except: continue

def engine():
    pool = eventlet.greenpool.GreenPool(50) # Threading crash se bachne ke liye pool
    while True:
        active = list(subscribed_symbols.keys())
        if active:
            for i in range(0, len(active), 50):
                batch = active[i:i+50]
                pool.spawn_n(fetch_batch, batch)
            socketio.emit('live_ticks', price_cache)
        eventlet.sleep(1.5)

# --- Baki saara code (Search, Janitor, etc.) same rahega ---
def janitor():
    while True:
        now = time.time()
        expired = [s for s, t in subscribed_symbols.items() if now - t > 10]
        for s in expired:
            subscribed_symbols.pop(s, None)
            price_cache.pop(s, None)
        eventlet.sleep(5)

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

if __name__ == '__main__':
    # Initial load
    try:
        f_data = requests.get(f"https://finnhub.io/api/v1/forex/symbol?exchange=oanda&token={FINNHUB_KEY}").json()
        master_symbol_list = [{"s": i['symbol'], "d": i['displaySymbol']} for i in f_data]
    except: pass

    socketio.start_background_task(engine)
    socketio.start_background_task(janitor)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
