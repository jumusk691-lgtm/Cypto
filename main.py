import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, sqlite3, requests, yfinance as yf
from firebase_admin import credentials, db
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
SUPABASE_DB_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co/storage/v1/object/public/Myt/market_data.db"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjY0NzQ0NywiZXhwIjoyMDg4MjIzNDQ3fQ.epYmt7sxhZRhEQWoj0doCHAbfOTHOjSurBbLss5a4Pk"

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_references = {}  

# --- 2. DB AUTO-UPDATE (Har Deploy aur har 72h par) ---
def sync_db_to_supabase():
    db_file = "market_data.db"
    if not os.path.exists(db_file): return
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        # Crypto Live Table
        cursor.execute("DROP TABLE IF EXISTS crypto_live")
        cursor.execute("CREATE TABLE crypto_live AS SELECT symbol, 'CRYPTO' as exch_seg FROM crypto")
        # Global Forex Live Table
        cursor.execute("DROP TABLE IF EXISTS forex_live")
        cursor.execute("CREATE TABLE forex_live AS SELECT AlphabeticCode as symbol, Currency as name, 'FOREX' as exch_seg FROM forex")
        conn.commit()
        conn.close()

        with open(db_file, "rb") as f:
            headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY, "Content-Type": "application/octet-stream", "x-upsert": "true"}
            requests.post(SUPABASE_DB_URL, headers=headers, data=f)
            print("🚀 Supabase File Updated Successfully")
    except Exception as e: print(f"❌ DB Error: {e}")

# --- 3. PRICE UPDATER ---
def update_firebase(symbol, price):
    try:
        # Global Mapping
        mapping = {"GC=F": "GOLD", "SI=F": "SILVER", "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD"}
        display_symbol = mapping.get(symbol.upper(), symbol.upper())
        
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if display_symbol in node_references:
            for node_id in node_references[display_symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        if updates: db.reference().update(updates)
    except: pass

# --- 4. GLOBAL FOREX ENGINE (Yahoo - No Key) ---
def start_global_forex():
    while True:
        try:
            # Sirf Global Symbols
            forex_list = {"GOLD": "GC=F", "SILVER": "SI=F", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X"}
            for name, y_sym in forex_list.items():
                ticker = yf.Ticker(y_sym)
                price = ticker.fast_info['last_price']
                update_firebase(name, price)
            eventlet.sleep(2)
        except: eventlet.sleep(5)

# --- 5. BINANCE ENGINE (Crypto) ---
def start_binance():
    global node_references
    while True:
        try:
            # Watchlist Sync
            data = db.reference('forex_watchlist').get() or {}
            current_crypto = set()
            temp_refs = {}

            for node_id in data.keys():
                raw_sym = node_id.split('_')[0].upper()
                if raw_sym not in temp_refs: temp_refs[raw_sym] = []
                temp_refs[raw_sym].append(node_id)
                
                # Check if it's a crypto symbol
                if any(x in raw_sym for x in ['BTC', 'ETH', 'USDT', 'DOGE', 'SOL']):
                    current_crypto.add(raw_sym.lower())

            node_references = temp_refs
            if not current_crypto: 
                eventlet.sleep(10); continue

            streams = "/".join([f"{s}@ticker" for s in current_crypto])
            url = f"wss://stream.binance.com:9443/ws/{streams}"
            def on_message(ws, msg):
                d = json.loads(msg)
                update_firebase(d['s'], d['c'])
            ws = websocket.WebSocketApp(url, on_message=on_message)
            ws.run_forever()
        except: eventlet.sleep(5)

# --- 6. SCHEDULER & FLASK ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_db_to_supabase, trigger="interval", hours=72)
scheduler.start()

@app.route('/')
def health(): return "GLOBAL_MARKET_LIVE"

if __name__ == '__main__':
    sync_db_to_supabase() 
    eventlet.spawn(start_binance)
    eventlet.spawn(start_global_forex)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
