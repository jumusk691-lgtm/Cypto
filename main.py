import eventlet
eventlet.monkey_patch()

import os
import time
import sqlite3
import requests
import json
import schedule
from flask import Flask, jsonify
from flask_socketio import SocketIO
from websocket import create_connection

app = Flask(__name__)
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='eventlet',
    ping_timeout=60
)

# --- CONFIGURATION ---
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co"
BUCKET_NAME = "Myt"
DB_FILE = "market_data.db"

price_cache = {}
subscribed_symbols = set()

# --- 1. DATABASE LOGIC (Sync & Clean) ---

def sync_from_supabase():
    """Har Monday ko Supabase se fresh DB download karega"""
    print("🔄 Syncing: Downloading DB from Supabase...")
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{DB_FILE}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(DB_FILE, "wb") as f: f.write(r.content)
            print("✅ DB Successfully Synced from Supabase")
    except Exception as e:
        print(f"❌ DB Sync Failed: {e}")

def daily_db_clean():
    """Roj subah tables clear karega naye data ke liye"""
    print("🧹 Cleaning Tables for the day...")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM forex")
        cursor.execute("DELETE FROM crypto")
        conn.commit()
        conn.close()
        print("✅ Database tables cleared.")
    except Exception as e:
        print(f"❌ Cleaning Failed: {e}")

def run_scheduler():
    # Monday subah 00:00 Sync
    schedule.every().monday.at("00:00").do(sync_from_supabase)
    # Roj subah 06:00 Clean
    schedule.every().day.at("06:00").do(daily_db_clean)
    while True:
        schedule.run_pending()
        eventlet.sleep(30)

# --- 2. CRYPTO ENGINE (Binance WebSocket - High Speed) ---
def crypto_engine():
    ws = None
    while True:
        try:
            print("🚀 Connecting to Binance WebSocket...")
            ws = create_connection("wss://stream.binance.com:9443/ws/!ticker@arr")
            while True:
                data = json.loads(ws.recv())
                for ticker in data:
                    sym = ticker['s']
                    if sym.endswith("USDT"):
                        clean_sym = sym.replace("USDT", "")
                        price_cache[clean_sym] = {
                            "s": clean_sym,
                            "p": "{:.2f}".format(float(ticker['c'])),
                            "c": "up" if float(ticker['p']) > 0 else "down"
                        }
                socketio.emit('live_ticks', price_cache)
                eventlet.sleep(0.1) # Smooth streaming
        except Exception as e:
            print(f"⚠️ Crypto WS Error: {e}. Reconnecting...")
            ws = None
            eventlet.sleep(5)

# --- 3. FOREX ENGINE (Real-Time Tick Engine) ---
def forex_engine():
    # Twelve Data API use kar rahe hain (Har second tick ke liye best hai)
    # API Key yahan daalein: https://twelvedata.com/ (Free Tier)
    FOREX_KEY = "YOUR_TWELVE_DATA_API_KEY"
    
    while True:
        try:
            forex_list = [s for s in list(subscribed_symbols) if len(s) == 6]
            if forex_list:
                symbols_str = ",".join([f"{s[:3]}/{s[3:]}" for s in forex_list])
                url = f"https://api.twelvedata.com/price?symbol={symbols_str}&apikey={FOREX_KEY}"
                
                res = requests.get(url).json()
                
                # Agar multiple symbols hain toh res ek dictionary hogi
                for sym in forex_list:
                    formatted_sym = f"{sym[:3]}/{sym[3:]}"
                    if formatted_sym in res:
                        price = res[formatted_sym]['price']
                        price_cache[sym] = {
                            "s": sym,
                            "p": "{:.5f}".format(float(price)),
                            "t": "fx"
                        }
                socketio.emit('live_ticks', price_cache)
            
            eventlet.sleep(1) # Har 1 second mein update
        except Exception as e:
            print(f"⚠️ Forex Engine Error: {e}")
            eventlet.sleep(2)

# --- 4. SOCKET & ROUTES ---
@app.route('/')
def status():
    return jsonify({"status": "Super-Fast Engine Live", "version": "5.0.0"})

@socketio.on('subscribe')
def handle_sub(data):
    watchlist = data.get('watchlist', [])
    for item in watchlist:
        s = item.get('symbol') or item.get('s')
        if s: subscribed_symbols.add(str(s).upper())
    print(f"📡 New Subscriptions: {len(subscribed_symbols)} symbols active")

# --- 5. START SERVER ---
if __name__ == '__main__':
    # Initial setup
    sync_from_supabase()
    
    # Background Tasks run
    socketio.start_background_task(crypto_engine)
    socketio.start_background_task(forex_engine)
    socketio.start_background_task(run_scheduler)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
