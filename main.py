import eventlet
eventlet.monkey_patch() # Sabse upar hona chahiye crash se bachne ke liye

import os
import time
import sqlite3
import requests
import json
import traceback
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room
from websocket import create_connection # pip install websocket-client

app = Flask(__name__)

# ==============================================================================
# --- 1. SOCKET CONFIGURATION (BUFFER FIX) ---
# ==============================================================================
# max_http_buffer_size ko 50MB rakha hai taaki "Too many packets" error na aaye
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='eventlet',
    ping_timeout=120,
    ping_interval=40,
    max_http_buffer_size=50000000 
)

# --- CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2NDc0NDcsImV4cCI6MjA4ODIyMzQ0N30.cS3y68_X95q9sH4Ot2QqPnoGDc0HntqlzhAP8rDJSeE"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = set()

# --- 2. SYNC LOGIC ---
def sync_db_from_supabase():
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f:
                f.write(r.content)
            print("✅ Database Synced from Cloud")
            return True
    except Exception as e:
        print(f"❌ Sync Error: {e}")
    return False

# --- 3. SYMBOL FORMATTER (Fix for Crypto/Forex) ---
def format_symbol(sym):
    sym = str(sym).upper()
    # Crypto: BTCUSDT -> BINANCE:BTCUSDT
    if any(x in sym for x in ["BTC", "ETH", "USDT", "SOL", "DOGE"]):
        if ":" not in sym:
            return f"BINANCE:{sym}"
    # Forex: EURUSD -> OANDA:EUR_USD (Depends on your DB naming)
    return sym

# --- 4. REAL-TIME ENGINE (WebSocket Mode) ---
def price_engine():
    """Finnhub WebSocket Engine for 24/7 Live Price"""
    ws = None
    while True:
        try:
            if not ws:
                print("🔌 Connecting to Finnhub WebSocket...")
                ws = create_connection(f"wss://ws.finnhub.io?token={FINNHUB_KEY}")
            
            # Subscribe current set of symbols
            current_subs = list(subscribed_symbols)
            for sym in current_subs:
                formatted = format_symbol(sym)
                ws.send(json.dumps({"type": "subscribe", "symbol": formatted}))
            
            while True:
                msg = json.loads(ws.recv())
                if msg['type'] == 'data':
                    for data in msg['data']:
                        raw_sym = data['s']
                        # Map back: 'BINANCE:BTCUSDT' -> 'BTCUSDT'
                        clean_sym = raw_sym.split(':')[-1].replace('_', '') 
                        
                        new_price = float(data['p'])
                        old_val = price_cache.get(clean_sym, {}).get('p', "0")
                        old_price = float(old_val)

                        # Blink Logic
                        change = "none"
                        if new_price > old_price: change = "up"
                        elif new_price < old_price: change = "down"

                        price_cache[clean_sym] = {
                            "s": clean_sym,
                            "p": "{:.5f}".format(new_price),
                            "c": change
                        }
                    
                    # Live update broadcast
                    socketio.emit('live_ticks', price_cache)
                
                eventlet.sleep(0.01)
        except Exception as e:
            print(f"⚠️ WS Connection Lost: {e}. Reconnecting in 5s...")
            ws = None
            eventlet.sleep(5)

# --- 5. API ROUTES ---
@app.route('/')
def home():
    return jsonify({"status": "Online", "engine": "Titan Forex/Crypto V3"})

@app.route('/api/forex')
def get_forex():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name FROM forex")
        rows = cursor.fetchall()
        conn.close()
        return jsonify([{"s": r[0], "d": r[1], "type": "forex"} for r in rows])
    except: return jsonify([])

@app.route('/api/crypto')
def get_crypto():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name FROM crypto")
        rows = cursor.fetchall()
        conn.close()
        return jsonify([{"s": r[0], "d": r[1], "type": "crypto"} for r in rows])
    except: return jsonify([])

# ==============================================================================
# --- 6. UPDATED SUBSCRIPTION LOGIC (BULK SYNC) ---
# ==============================================================================
@socketio.on('subscribe')
def handle_subscription(data):
    """Purana data aur naya data dono ko ek sath subscribe karega"""
    watchlist = data.get('watchlist', [])
    
    # 1. Agar list aa rahi hai (Firebase/Initial load)
    if isinstance(watchlist, list) and len(watchlist) > 0:
        for item in watchlist:
            sym = item.get('symbol') or item.get('s')
            if sym:
                subscribed_symbols.add(sym)
                join_room(str(sym))
        print(f"✅ Bulk Sync: {len(watchlist)} symbols added")

    # 2. Agar single symbol aa raha hai (Manual add)
    elif data.get('symbol'):
        sym = data.get('symbol')
        subscribed_symbols.add(sym)
        join_room(str(sym))
        print(f"✅ Single Add: {sym}")

# ==============================================================================
# --- 7. BOOTSTRAP ---
# ==============================================================================
if __name__ == '__main__':
    # Initial DB sync
    sync_db_from_supabase()
    
    # Background thread for prices
    socketio.start_background_task(price_engine)
    
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Server running on port {port}")
    socketio.run(app, host='0.0.0.0', port=port)
