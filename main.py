import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, sqlite3, requests
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

# --- 2. DB SYNC (72h Cycle) ---
def sync_db_to_supabase():
    db_file = "market_data.db"
    if not os.path.exists(db_file): return
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS crypto_live")
        cursor.execute("CREATE TABLE crypto_live AS SELECT symbol, 'CRYPTO' as exch_seg FROM crypto")
        cursor.execute("DROP TABLE IF EXISTS forex_live")
        cursor.execute("CREATE TABLE forex_live AS SELECT AlphabeticCode as symbol, Currency as name, 'FOREX' as exch_seg FROM forex")
        conn.commit()
        conn.close()
        with open(db_file, "rb") as f:
            headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY, "Content-Type": "application/octet-stream", "x-upsert": "true"}
            requests.post(SUPABASE_DB_URL, headers=headers, data=f)
            print("🚀 DB Synced")
    except Exception as e: print(f"❌ DB Sync Error: {e}")

# --- 3. ZERO-DELAY UPDATER ---
def update_firebase(binance_sym, price):
    try:
        # Reverse Mapping: Binance sym ko wapas original sym mein badlo
        rev_map = {"PAXGUSDT": "XAU", "EURUSDT": "EURUSD", "GBPUSDT": "GBPUSD"}
        original_sym = rev_map.get(binance_sym.upper(), binance_sym.upper())
        
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if original_sym in node_references:
            for node_id in node_references[original_sym]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates: db.reference().update(updates)
    except: pass

# --- 4. FAST BINANCE ENGINE (All-In-One) ---
def start_engine():
    global node_references
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            current_subs = set()
            temp_refs = {}

            for node_id in data.keys():
                # Split symbol from Node ID
                raw_sym = node_id.split('_')[0].upper()
                
                # Mapping symbols to Binance pairs for <1s delay
                binance_pair = raw_sym
                if raw_sym == "XAU": binance_pair = "PAXGUSDT"
                elif raw_sym == "EURUSD": binance_pair = "EURUSDT"
                elif raw_sym == "GBPUSD": binance_pair = "GBPUSDT"
                
                if raw_sym not in temp_refs: temp_refs[raw_sym] = []
                temp_refs[raw_sym].append(node_id)
                current_subs.add(binance_pair.lower())

            node_references = temp_refs
            
            # WebSocket Connection for Real-time speed
            streams = "/".join([f"{s}@ticker" for s in current_subs])
            url = f"wss://stream.binance.com:9443/ws/{streams}"
            
            def on_message(ws, msg):
                d = json.loads(msg)
                update_firebase(d['s'], d['c'])

            ws = websocket.WebSocketApp(url, on_message=on_message)
            print(f"⚡ Fast Engine Subscribed: {list(current_subs)}")
            ws.run_forever()
        except: eventlet.sleep(2)

# --- START ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_db_to_supabase, trigger="interval", hours=72)
scheduler.start()

@app.route('/')
def health(): return "ULTRA_FAST_LIVE"

if __name__ == '__main__':
    sync_db_to_supabase()
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
