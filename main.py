import eventlet
eventlet.monkey_patch()

import os
import time
import sqlite3
import requests
import json
import traceback
from flask import Flask, jsonify
from flask_socketio import SocketIO, join_room
from websocket import create_connection

app = Flask(__name__)

# --- 1. SOCKET CONFIG ---
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='eventlet',
    ping_timeout=60,
    max_http_buffer_size=100000000 # 100MB buffer for large watchlists
)

# --- CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2NDc0NDcsImV4cCI6MjA4ODIyMzQ0N30.cS3y68_X95q9sH4Ot2QqPnoGDc0HntqlzhAP8rDJSeE"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = set()
last_emit_time = 0

# --- 2. SYMBOL SMART FORMATTER ---
def format_symbol(sym):
    sym = str(sym).upper().replace("/", "")
    # Crypto: BTCUSDT -> BINANCE:BTCUSDT
    if any(x in sym for x in ["BTC", "ETH", "USDT", "SOL", "DOGE", "SHIB"]):
        return f"BINANCE:{sym}" if ":" not in sym else sym
    
    # Forex: EURUSD -> OANDA:EUR_USD
    # Finnhub requires underscore for Forex pairs
    if len(sym) == 6:
        return f"OANDA:{sym[:3]}_{sym[3:]}"
    
    return sym

# --- 3. OPTIMIZED PRICE ENGINE ---
def price_engine():
    global last_emit_time
    ws = None
    while True:
        try:
            if not ws:
                print("🔌 Connecting to Finnhub WebSocket...")
                ws = create_connection(f"wss://ws.finnhub.io?token={FINNHUB_KEY}")
            
            # Subscribe all symbols with a small delay to avoid 429 error
            current_list = list(subscribed_symbols)
            for sym in current_list:
                formatted = format_symbol(sym)
                ws.send(json.dumps({"type": "subscribe", "symbol": formatted}))
                eventlet.sleep(0.1) # 100ms gap
            
            while True:
                msg = json.loads(ws.recv())
                if msg.get('type') == 'data':
                    for data in msg['data']:
                        raw_sym = data['s']
                        # Map back to original: OANDA:EUR_USD -> EURUSD
                        clean_sym = raw_sym.split(':')[-1].replace('_', '') 
                        
                        new_price = float(data['p'])
                        old_price = float(price_cache.get(clean_sym, {}).get('p', 0))

                        # Blink logic
                        change = "up" if new_price > old_price else "down" if new_price < old_price else "none"

                        price_cache[clean_sym] = {
                            "s": clean_sym,
                            "p": "{:.5f}".format(new_price),
                            "c": change
                        }
                    
                    # Throttling: Emit only every 300ms to save mobile data/battery
                    current_time = time.time()
                    if current_time - last_emit_time > 0.3:
                        socketio.emit('live_ticks', price_cache)
                        last_emit_time = current_time
                
                eventlet.sleep(0.01)
        except Exception as e:
            print(f"⚠️ WS Error: {e}. Reconnecting in 10s...")
            ws = None
            eventlet.sleep(10)

# --- 4. API & SUBSCRIPTION ---
@app.route('/')
def home():
    return jsonify({"status": "Online", "version": "4.0.0", "assets": "Crypto/Forex"})

@socketio.on('subscribe')
def handle_subscription(data):
    watchlist = data.get('watchlist', [])
    if isinstance(watchlist, list):
        for item in watchlist:
            sym = item.get('symbol') or item.get('s')
            if sym:
                subscribed_symbols.add(str(sym))
                join_room(str(sym))
        print(f"✅ Sync: {len(watchlist)} symbols active")
    elif data.get('symbol'):
        sym = data.get('symbol')
        subscribed_symbols.add(str(sym))
        join_room(str(sym))

# --- 5. DB SYNC ---
def sync_db():
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f: f.write(r.content)
            print("✅ DB Synced")
    except: print("❌ DB Sync Failed")

if __name__ == '__main__':
    sync_db()
    socketio.start_background_task(price_engine)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
