import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, sqlite3, requests
from firebase_admin import credentials, db
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- 1. CONFIGURATION ---
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
active_crypto_subs = set()

# --- 2. SUPABASE DB AUTO-UPDATE (72 HOURS) ---
def sync_db_to_supabase():
    db_file = "market_data.db"
    if not os.path.exists(db_file): return
    try:
        print(f"🔄 Processing DB Clean: {datetime.datetime.now()}")
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        # Clean tables based on your database structure
        cursor.execute("DROP TABLE IF EXISTS crypto_live")
        cursor.execute("CREATE TABLE crypto_live AS SELECT symbol, 'CRYPTO' as exch_seg FROM crypto")
        cursor.execute("DROP TABLE IF EXISTS forex_live")
        cursor.execute("CREATE TABLE forex_live AS SELECT AlphabeticCode as symbol, Currency as name, 'FOREX' as exch_seg FROM forex")
        conn.commit()
        conn.close()

        with open(db_file, "rb") as f:
            headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY, "Content-Type": "application/octet-stream", "x-upsert": "true"}
            requests.post(SUPABASE_DB_URL, headers=headers, data=f)
            print("🚀 Supabase Upload Success (72h Cycle)")
    except Exception as e: print(f"❌ DB Sync Error: {e}")

# --- 3. PRICE UPDATE LOGIC ---
def update_firebase(symbol, price):
    try:
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        if symbol in node_references:
            for node_id in node_references[symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        if updates: db.reference().update(updates)
    except: pass

# --- 4. BINANCE ENGINE (BATCHING & DOUBLE-SUB PREVENTION) ---
def start_binance():
    global node_references, active_crypto_subs
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            current_symbols = set()
            temp_refs = {}

            for k, v in data.items():
                sym = v.get('symbol', '').upper().replace('_', '')
                if 'USD' in sym: # Crypto Filter
                    clean_sym = sym.lower()
                    current_symbols.add(clean_sym)
                    if clean_sym not in temp_refs: temp_refs[clean_sym] = []
                    temp_refs[clean_sym].append(k)
            
            node_references.update(temp_refs)
            
            # Batching logic: 100 symbols per stream (Binance limit)
            symbol_list = list(current_symbols)
            for i in range(0, len(symbol_list), 100):
                batch = symbol_list[i:i+100]
                streams = "/".join([f"{s}@ticker" for s in batch])
                stream_url = f"wss://stream.binance.com:9443/ws/{streams}"
                
                def on_message(ws, msg):
                    d = json.loads(msg)
                    update_firebase(d['s'].lower(), d['c'])

                ws = websocket.WebSocketApp(stream_url, on_message=on_message)
                eventlet.spawn(ws.run_forever)
                print(f"📡 Subscribed to Crypto Batch: {len(batch)} tokens")
            
            eventlet.sleep(300) # Re-check watchlist every 5 mins
        except Exception as e:
            print(f"Binance Error: {e}")
            eventlet.sleep(10)

# --- 5. TIINGO ENGINE (FOREX) ---
def start_tiingo():
    while True:
        try:
            ws_url = "wss://api.tiingo.com/fx"
            def on_open(ws):
                ws.send(json.dumps({
                    "eventName": "subscribe",
                    "authorization": TIINGO_API_KEY,
                    "eventData": {"thresholdLevel": 5}
                }))
            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('messageType') == 'A':
                    update_firebase(d['data'][0].upper(), d['data'][4])

            ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
            ws.run_forever()
        except: eventlet.sleep(5)

# --- 6. SCHEDULER & FLASK ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_db_to_supabase, trigger="interval", hours=72)
scheduler.start()

@app.route('/')
def health(): return "LIVE_TRADING_SERVER_ACTIVE"

if __name__ == '__main__':
    sync_db_to_supabase() # Immediate sync on start
    eventlet.spawn(start_binance)
    eventlet.spawn(start_tiingo)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
