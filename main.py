import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, sqlite3, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
# Sabhi nodes ko store karne ke liye dictionary
node_map = {} 

# --- 2. PRICE UPDATER (Fixed Logic) ---
def update_firebase(binance_sym, price):
    global node_map
    try:
        p_str = "{:.2f}".format(float(price))
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Binance symbol ko wapas normal mein badlo (e.g., paxgusdt -> XAU)
        rev_map = {"paxgusdt": "XAU", "eurusdt": "EURUSD", "gbpusdt": "GBPUSD"}
        search_key = rev_map.get(binance_sym.lower(), binance_sym.upper())

        # Firebase ke sabhi nodes check karo jo is symbol se shuru hote hain
        for node_id in node_map.get(search_key, []):
            updates[f"forex_watchlist/{node_id}/price"] = p_str
            updates[f"forex_watchlist/{node_id}/utime"] = time_str
            
        if updates:
            db.reference().update(updates)
    except Exception as e:
        print(f"Update Error: {e}")

# --- 3. BINANCE WebSocket ENGINE ---
def start_engine():
    global node_map
    while True:
        try:
            # 1. Firebase se watchlist fetch karke mapping banao
            data = db.reference('forex_watchlist').get() or {}
            current_subs = set()
            new_node_map = {}

            for node_id in data.keys():
                # Symbol nikaalo (e.g., BTCUSDT_abc -> BTCUSDT)
                symbol = node_id.split('_')[0].upper()
                
                if symbol not in new_node_map: new_node_map[symbol] = []
                new_node_map[symbol].append(node_id)
                
                # Binance pair mapping
                b_pair = symbol.lower()
                if symbol == "XAU": b_pair = "paxgusdt"
                elif "USD" in symbol and len(symbol) == 6:
                    b_pair = symbol.lower().replace("usd", "usdt")
                
                current_subs.add(b_pair)

            node_map = new_node_map
            
            # 2. WebSocket Connect
            if current_subs:
                streams = "/".join([f"{s}@ticker" for s in current_subs])
                url = f"wss://stream.binance.com:9443/ws/{streams}"
                
                def on_message(ws, msg):
                    d = json.loads(msg)
                    # d['s'] is symbol (BTCUSDT), d['c'] is close price
                    update_firebase(d['s'], d['c'])

                ws = websocket.WebSocketApp(url, on_message=on_message)
                print(f"⚡ Subscribed to: {list(current_subs)}")
                ws.run_forever()
            
            time.sleep(10)
        except Exception as e:
            print(f"Engine Error: {e}")
            time.sleep(5)

@app.route('/')
def health(): return "FAST_PRICE_SYNC_ACTIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
