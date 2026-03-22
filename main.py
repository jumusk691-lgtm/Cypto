import eventlet
eventlet.monkey_patch()

import os
import time
import sqlite3
import requests
import json
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit
from websocket import create_connection # pip install websocket-client

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2NDc0NDcsImV4cCI6MjA4ODIyMzQ0N30.cS3y68_X95q9sH4Ot2QqPnoGDc0HntqlzhAP8rDJSeE"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = set()

# --- 1. SYNC LOGIC ---
def sync_db_from_supabase():
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f:
                f.write(r.content)
            print("✅ DB Synced")
            return True
    except: pass
    return False

# --- 2. SYMBOL FORMATTER (Fix for Crypto/Forex) ---
def format_symbol(sym):
    """Finnhub ke liye symbol format fix karein"""
    sym = sym.upper()
    # Crypto Fix
    if "USDT" in sym or "BTC" in sym or "ETH" in sym:
        if ":" not in sym:
            return f"BINANCE:{sym}"
    # Forex Fix (Example: EURUSD -> OANDA:EUR_USD)
    # Note: Agar aapka DB 'AED' de raha hai toh wo base currency hai. 
    # Finnhub ko pair chahiye hota hai jaise 'FX_IDC:USD_AED'
    return sym

# --- 3. REAL-TIME ENGINE (WebSocket Mode) ---
def price_engine():
    """Finnhub WebSocket se high-speed data fetcher"""
    ws = None
    while True:
        try:
            if not ws:
                ws = create_connection(f"wss://ws.finnhub.io?token={FINNHUB_KEY}")
            
            # Jo bhi naye symbols aaye hain unhe subscribe karo
            for sym in list(subscribed_symbols):
                formatted = format_symbol(sym)
                ws.send(json.dumps({"type": "subscribe", "symbol": formatted}))
            
            while True:
                msg = json.loads(ws.recv())
                if msg['type'] == 'data':
                    for data in msg['data']:
                        raw_sym = data['s']
                        # Map back to original symbol for App
                        original_sym = raw_sym.split(':')[-1].replace('_', '') 
                        # Actual Logic for Blink
                        new_price = float(data['p'])
                        old_data = price_cache.get(original_sym, {"p": 0})
                        old_price = float(old_data['p'])

                        change = "none"
                        if new_price > old_price: change = "up"
                        elif new_price < old_price: change = "down"

                        price_cache[original_sym] = {
                            "s": original_sym,
                            "p": "{:.5f}".format(new_price),
                            "c": change
                        }
                    
                    socketio.emit('live_ticks', price_cache)
                eventlet.sleep(0.01)
        except Exception as e:
            print(f"WS Error: {e}, reconnecting...")
            ws = None
            eventlet.sleep(5)

# --- 4. API ROUTES ---
@app.route('/')
def home():
    return "✅ Titan Forex/Crypto Engine Live"

@app.route('/api/forex')
def get_forex():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, name FROM forex")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"s": r[0], "d": r[1], "type": "forex"} for r in rows])

@app.route('/api/crypto')
def get_crypto():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, name FROM crypto")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"s": r[0], "d": r[1], "type": "crypto"} for r in rows])

@socketio.on('subscribe')
def on_subscribe(data):
    sym = data.get('symbol')
    if sym:
        subscribed_symbols.add(sym)
        print(f"📺 Subscribed to: {sym}")

if __name__ == '__main__':
    sync_db_from_supabase()
    socketio.start_background_task(price_engine)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
