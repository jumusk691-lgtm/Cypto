import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_map = {}
current_ws = None

# --- 2. LIVE PRICE UPDATER ---
def update_firebase(binance_sym, price):
    global node_map
    try:
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Mapping for special cases
        rev_map = {"paxgusdt": "XAU", "eurusdt": "EURUSD", "gbpusdt": "GBPUSD"}
        search_key = rev_map.get(binance_sym.lower(), binance_sym.upper())

        if search_key in node_map:
            for node_id in node_map[search_key]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
            
            if updates:
                db.reference().update(updates)
    except: pass

# --- 3. BINANCE WS ENGINE ---
def run_ws():
    global node_map, current_ws
    while True:
        try:
            # Get latest watchlist for subscription
            data = db.reference('forex_watchlist').get() or {}
            subs = set()
            new_map = {}

            for node_id in data.keys():
                sym = node_id.split('_')[0].upper()
                if sym not in new_map: new_map[sym] = []
                new_map[sym].append(node_id)
                
                # Format for Binance
                b_pair = sym.lower()
                if sym == "XAU": b_pair = "paxgusdt"
                elif "USD" in sym and len(sym) == 6: b_pair = sym.lower().replace("usd", "usdt")
                subs.add(b_pair)

            node_map = new_map
            if not subs: 
                time.sleep(5); continue

            streams = "/".join([f"{s}@ticker" for s in subs])
            url = f"wss://stream.binance.com:9443/ws/{streams}"

            def on_message(ws, msg):
                d = json.loads(msg)
                update_firebase(d['s'], d['c'])

            current_ws = websocket.WebSocketApp(url, on_message=on_message)
            print(f"⚡ Connected to Binance: {list(subs)}")
            current_ws.run_forever()
        except: time.sleep(5)

# --- 4. WATCHLIST AUTO-RELOADER ---
def sync_checker():
    # Ye function har 30 sec mein check karega ki koi naya symbol toh nahi aaya
    global current_ws
    last_count = 0
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            if len(data) != last_count:
                print("🔄 New symbols detected, restarting WebSocket...")
                if current_ws: current_ws.close()
                last_count = len(data)
        except: pass
        time.sleep(30)

@app.route('/')
def health(): return "FAST_PRICE_SYNC_v2_ACTIVE"

if __name__ == '__main__':
    threading.Thread(target=run_ws, daemon=True).start()
    threading.Thread(target=sync_checker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
