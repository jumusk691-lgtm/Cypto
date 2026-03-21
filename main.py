import eventlet
eventlet.monkey_patch() # Crash se bachne ke liye sabse upar

import os
import time
import sqlite3
import requests
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# SocketIO setup with eventlet mode
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
# Aapki updated key
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2NDc0NDcsImV4cCI6MjA4ODIyMzQ0N30.cS3y68_X95q9sH4Ot2QqPnoGDc0HntqlzhAP8rDJSeE"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = {}

# --- 1. SUPABASE SYNC LOGIC ---
def sync_db_from_supabase():
    """Supabase Storage se market_data.db download karna"""
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f:
                f.write(r.content)
            print("✅ DB Synced from Supabase")
            return True
    except Exception as e:
        print(f"❌ Sync Error: {e}")
    return False

# --- 2. DATABASE READ LOGIC ---
def get_symbols_from_db(table_name):
    """SQLite se Forex ya Crypto ki list uthana"""
    if not os.path.exists(DB_FILE):
        sync_db_from_supabase()
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT symbol, name FROM {table_name}")
        rows = cursor.fetchall()
        conn.close()
        return [{"s": r[0], "d": r[1], "type": table_name} for r in rows]
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return []

# --- 3. LIVE PRICE ENGINE ---
def price_engine():
    """Live price fetcher aur blink logic"""
    while True:
        active = list(subscribed_symbols.keys())
        if active:
            for sym in active:
                try:
                    url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
                    res = requests.get(url, timeout=2).json()
                    
                    if res.get('c') and res['c'] != 0:
                        new_price = "{:.5f}".format(res['c'])
                        # Purani price comparison for blink
                        old_price = price_cache.get(sym, {}).get('p', "0")
                        
                        change = "none"
                        if float(new_price) > float(old_price): change = "up"
                        elif float(new_price) < float(old_price): change = "down"
                        
                        price_cache[sym] = {"s": sym, "p": new_price, "c": change}
                except:
                    continue
                eventlet.sleep(0.1) # Rate limiting
            
            socketio.emit('live_ticks', price_cache)
        eventlet.sleep(1.0)

# --- 4. API ROUTES ---
@app.route('/')
def home():
    return "✅ Render Server is Running"

@app.route('/api/forex')
def get_forex():
    return jsonify(get_symbols_from_db('forex'))

@app.route('/api/crypto')
def get_crypto():
    return jsonify(get_symbols_from_db('crypto'))

@socketio.on('subscribe')
def on_subscribe(data):
    sym = data.get('symbol')
    if sym:
        subscribed_symbols[sym] = time.time()

if __name__ == '__main__':
    sync_db_from_supabase()
    socketio.start_background_task(price_engine)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
