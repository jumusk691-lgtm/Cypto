import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading, sqlite3, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
# Aapki Supabase DB URL jahan se symbols ki list aayegi
SUPABASE_DB_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co/storage/v1/object/public/Myt/market_data.db"

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_map = {}
current_ws = None

# --- 2. AUTO-DOWNLOAD DATABASE ---
def download_latest_symbols():
    try:
        print("📥 Downloading latest symbol database from Supabase...")
        r = requests.get(SUPABASE_DB_URL)
        with open("market_data.db", "wb") as f:
            f.write(r.content)
        print("✅ Database updated successfully!")
    except Exception as e:
        print(f"❌ Download Error: {e}")

# --- 3. PRICE UPDATER ---
def update_firebase(binance_sym, price):
    global node_map
    try:
        incoming_sym = binance_sym.upper()
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Mapping for your app's specific names
        rev_map = {"PAXGUSDT": "XAU", "EURUSDT": "EURUSD", "GBPUSDT": "GBPUSD"}
        target_key = rev_map.get(incoming_sym, incoming_sym)

        if target_key in node_map:
            updates = {}
            for node_id in node_map[target_key]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
            if updates:
                db.reference().update(updates)
    except: pass

# --- 4. BINANCE ENGINE ---
def run_ws():
    global node_map, current_ws
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            subs = set()
            new_map = {}

            for node_id in data.keys():
                # Extracting symbol (e.g., BTCUSDT from BTCUSDT_user123)
                sym = node_id.split('_')[0].upper()
                if sym not in new_map: new_map[sym] = []
                new_map[sym].append(node_id)
                
                # Format for Binance subscription
                b_pair = sym.lower()
                if sym == "XAU": b_pair = "paxgusdt"
                elif "USD" in sym and len(sym) == 6: b_pair = sym.lower().replace("usd", "usdt")
                subs.add(b_pair)

            node_map = new_map
            if subs:
                streams = "/".join([f"{s}@ticker" for s in subs])
                url = f"wss://stream.binance.com:9443/ws/{streams}"

                def on_message(ws, msg):
                    d = json.loads(msg)
                    if 's' in d and 'c' in d: update_firebase(d['s'], d['c'])

                current_ws = websocket.WebSocketApp(url, on_message=on_message)
                print(f"⚡ Live Monitoring: {list(subs)}")
                current_ws.run_forever()
            time.sleep(5)
        except: time.sleep(5)

# --- 5. SYNC CHECKER ---
def sync_checker():
    global current_ws
    last_count = 0
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            if len(data) != last_count:
                if current_ws: current_ws.close()
                last_count = len(data)
        except: pass
        time.sleep(20)

@app.route('/')
def health(): return "AUTO_SYNC_DOWNLOAD_ACTIVE"

if __name__ == '__main__':
    download_latest_symbols() # Deploy hote hi naye symbols download karo
    threading.Thread(target=run_ws, daemon=True).start()
    threading.Thread(target=sync_checker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
