import eventlet
eventlet.monkey_patch() # Sabse upar hona chahiye crash se bachne ke liye

import os
import time
import sqlite3
import requests
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# SocketIO setup with eventlet
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- CONFIGURATION ---
FINNHUB_KEY = "d6vag8hr01qiiutb3j9gd6vag8hr01qiiutb3ja0"
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2NDc0NDcsImV4cCI6MjA4ODIyMzQ0N30.cS3y68_X95q9sH4Ot2QqPnoGDc0HntqlzhAP8rDJSeE"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = {}
forex_list = []
crypto_list = []

# --- DATABASE LOGIC (Supabase Cloud) ---

def sync_db_from_supabase():
    """Supabase Storage se DB file download karta hai"""
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f:
                f.write(r.content)
            print("✅ DB Synced from Cloud")
    except:
        print("❌ Sync Failed")

def get_symbols_from_db(table_name):
    """Local SQLite se symbols read karta hai"""
    if not os.path.exists(DB_FILE):
        sync_db_from_supabase()
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT symbol, name FROM {table_name}")
        rows = cursor.fetchall()
        conn.close()
        return [{"s": r[0], "d": r[1], "type": table_name} for r in rows]
    except:
        return []

# --- ENGINE LOGIC (Live Prices) ---

def price_engine():
    """Live price fetcher loop"""
    while True:
        active = list(subscribed_symbols.keys())
        if active:
            for sym in active:
                try:
                    url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
                    res = requests.get(url, timeout=2).json()
                    if res.get('c') and res['c'] != 0:
                        price_cache[sym] = {
                            "s": sym, 
                            "p": "{:.5f}".format(res['c']),
                            "t": time.time()
                        }
                except:
                    continue
            socketio.emit('live_ticks', price_cache)
        eventlet.sleep(1.0)

# --- API ROUTES ---

@app.route('/api/forex')
def get_forex():
    """Sirf Forex ki list return karega"""
    return jsonify(get_symbols_from_db('forex'))

@app.route('/api/crypto')
def get_crypto():
    """Sirf Crypto ki list return karega"""
    return jsonify(get_symbols_from_db('crypto'))

@app.route('/api/search', methods=['POST'])
def search():
    """Symbol search karne ke liye"""
    query = request.json.get('query', '').upper()
    all_symbols = get_symbols_from_db('forex') + get_symbols_from_db('crypto')
    results = [s for s in all_symbols if query in s['s'].upper()][:20]
    return jsonify(results)

@socketio.on('subscribe')
def on_subscribe(data):
    """Android app se subscription handle karta hai"""
    sym = data.get('symbol')
    if sym:
        subscribed_symbols[sym] = time.time()

if __name__ == '__main__':
    # Background tasks start karein
    socketio.start_background_task(price_engine)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
