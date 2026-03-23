import eventlet
eventlet.monkey_patch()

import os
import time
import sqlite3
import requests
import json
from flask import Flask, jsonify
from flask_socketio import SocketIO
from websocket import create_connection

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- CONFIGURATION ---
DB_FILE = "market_data.db"
price_cache = {}
subscribed_symbols = set()

# --- 1. CRYPTO ENGINE (Binance WebSocket - Real Second Ticks) ---
def crypto_engine():
    ws = None
    while True:
        try:
            # Binance ka stream sabse fast hai aur free hai
            ws = create_connection("wss://stream.binance.com:9443/ws/!ticker@arr")
            print("🚀 Crypto Engine Live (Binance)")
            while True:
                data = json.loads(ws.recv())
                for ticker in data:
                    sym = ticker['s'] # e.g., BTCUSDT
                    if "USDT" in sym:
                        clean_sym = sym.replace("USDT", "")
                        price_cache[clean_sym] = {
                            "s": clean_sym,
                            "p": "{:.2f}".format(float(ticker['c'])),
                            "c": "up" if float(ticker['p']) > 0 else "down"
                        }
                # Har second emit karega
                socketio.emit('live_ticks', price_cache)
                eventlet.sleep(0.5) 
        except Exception as e:
            print(f"Crypto WS Error: {e}")
            eventlet.sleep(5)

# --- 2. FOREX ENGINE (High-Speed Polling) ---
# Note: Forex ke liye free mein real WebSocket milna mushkil hai, 
# isliye hum Alpha Vantage ya naye Fast API ko fast loop mein chalayenge.
def forex_engine():
    # Aapka Alpha Vantage ya koi aur Premium Key yahan kaam aayegi
    AV_KEY = "YOUR_KEY_HERE" 
    while True:
        try:
            for sym in list(subscribed_symbols):
                if len(sym) == 6: # Only Forex pairs like EURUSD
                    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={sym[:3]}&to_currency={sym[3:]}&apikey={AV_KEY}"
                    r = requests.get(url).json()
                    if "Realtime Currency Exchange Rate" in r:
                        rate = r["Realtime Currency Exchange Rate"]["5. Exchange Rate"]
                        price_cache[sym] = {
                            "s": sym,
                            "p": "{:.5f}".format(float(rate)),
                            "t": "forex"
                        }
            socketio.emit('live_ticks', price_cache)
            eventlet.sleep(1) # 1 Second Delay
        except:
            eventlet.sleep(2)

# --- 3. DATABASE SYNC & CLEAN ---
def sync_and_clean():
    # Har Monday ko Supabase se download aur daily clean logic
    # (Puraani script wala logic yahan add kar sakte hain)
    pass

# --- 4. ROUTES ---
@socketio.on('subscribe')
def handle_sub(data):
    watchlist = data.get('watchlist', [])
    for item in watchlist:
        s = item.get('symbol') or item.get('s')
        if s: subscribed_symbols.add(str(s).upper())

@app.route('/')
def status():
    return jsonify({"status": "Super-Fast Engine Live", "ticks": "1-sec"})

# --- 5. RUN ---
if __name__ == '__main__':
    # Start Background Engines
    socketio.start_background_task(crypto_engine)
    socketio.start_background_task(forex_engine)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
