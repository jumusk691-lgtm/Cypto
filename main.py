import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, sqlite3, requests
from firebase_admin import credentials, db
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- 1. CONFIGURATION ---
# Note: Tiingo key nahi hai toh bhi Crypto aur Gold (Binance se) chalega
TIINGO_API_KEY = "YOUR_TIINGO_FREE_API_KEY"
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

SUPABASE_DB_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co/storage/v1/object/public/Myt/market_data.db"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRucmhsdmliYWVpd2hscnhkeG5tIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjY0NzQ0NywiZXhwIjoyMDg4MjIzNDQ3fQ.epYmt7sxhZRhEQWoj0doCHAbfOTHOjSurBbLss5a4Pk"

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_references = {}  

# --- 2. SUPABASE DB AUTO-UPDATE (72 HOURS) ---
def sync_db_to_supabase():
    db_file = "market_data.db"
    if not os.path.exists(db_file): return
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        # Clean tables for Android Search
        cursor.execute("DROP TABLE IF EXISTS crypto_live")
        cursor.execute("CREATE TABLE crypto_live AS SELECT symbol, 'CRYPTO' as exch_seg FROM crypto")
        cursor.execute("DROP TABLE IF EXISTS forex_live")
        cursor.execute("CREATE TABLE forex_live AS SELECT AlphabeticCode as symbol, Currency as name, 'FOREX' as exch_seg FROM forex")
        conn.commit()
        conn.close()

        with open(db_file, "rb") as f:
            headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY, "Content-Type": "application/octet-stream", "x-upsert": "true"}
            requests.post(SUPABASE_DB_URL, headers=headers, data=f)
            print("🚀 Supabase Upload Success")
    except Exception as e: print(f"❌ DB Sync Error: {e}")

# --- 3. PRICE UPDATE LOGIC (Firebase Writes) ---
def update_firebase(symbol, price):
    try:
        # Gold fix: Agar Binance se PAXG aa raha hai toh use XAU dikhao
        display_symbol = "XAU" if "PAXG" in symbol.upper() else symbol.upper()
        
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if display_symbol in node_references:
            for node_id in node_references[display_symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
    except: pass

# --- 4. BINANCE ENGINE (FREE CRYPTO & GOLD) ---
def start_binance():
    global node_references
    while True:
        try:
            # Step 1: Firebase se list fetch karo
            data = db.reference('forex_watchlist').get() or {}
            current_symbols = set()
            temp_refs = {}

            for node_id, fields in data.items():
                # Symbol clean karo (e.g., "BTCUSDT_userid" -> "BTCUSDT")
                raw_sym = node_id.split('_')[0].upper()
                
                # Agar XAU (Gold) hai toh Binance ka PAXGUSDT use karo (Free Key)
                fetch_sym = "PAXGUSDT" if raw_sym == "XAU" else raw_sym
                
                if fetch_sym not in temp_refs: temp_refs[fetch_sym] = []
                temp_refs[fetch_sym].append(node_id)
                current_symbols.add(fetch_sym.lower())

            node_references = temp_refs
            
            if not current_symbols:
                eventlet.sleep(10); continue

            # Step 2: WebSocket Connection
            streams = "/".join([f"{s}@ticker" for s in current_symbols])
            url = f"wss://stream.binance.com:9443/ws/{streams}"
            
            def on_message(ws, msg):
                d = json.loads(msg)
                update_firebase(d['s'], d['c'])

            ws = websocket.WebSocketApp(url, on_message=on_message)
            print(f"📡 Binance Subscribed: {list(current_symbols)}")
            ws.run_forever()
        except: 
            eventlet.sleep(5)

# --- 5. SCHEDULER & FLASK ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_db_to_supabase, trigger="interval", hours=72)
scheduler.start()

@app.route('/')
def health(): return "SYSTEM_LIVE_FIREBASE_CONNECTED"

if __name__ == '__main__':
    sync_db_to_supabase()
    eventlet.spawn(start_binance)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
