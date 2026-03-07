import os, datetime, json, firebase_admin, websocket, time, threading, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_map = {}
active_ws_list = set()
current_ws = None

# --- 2. FAST UPDATE HELPER ---
def fast_update(symbol, price, change="0.00%"):
    updates = {}
    symbol_upper = symbol.upper().replace("-", "").replace("_", "")
    # Binance/KuCoin/Gate formats handle karne ke liye mapping logic
    for target_key in [symbol_upper, symbol_upper.replace("USDT", "")]:
        if target_key in node_map:
            for nid in node_map[target_key]:
                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                updates[f"forex_watchlist/{nid}/percent"] = str(change) + "%"
                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
    if updates:
        db.reference().update(updates)

# --- 3. BINANCE US WEBSOCKET (REAL-TIME 1S) ---
def start_ws_engine():
    global current_ws, active_ws_list
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_map = {}
            new_ws_list = set()

            for nid in watchlist.keys():
                sym = nid.split('_')[0].upper()
                if sym not in new_map: new_map[sym] = []
                new_map[sym].append(nid)
                # Only Binance US supported pairs
                if "USDT" in sym or any(x in sym for x in ["BTC", "ETH", "BNB"]):
                    new_ws_list.add(sym.lower())

            global node_map
            node_map = new_map

            if new_ws_list != active_ws_list:
                active_ws_list = new_ws_list
                if current_ws: current_ws.close()
                
                if active_ws_list:
                    # Binance US is NOT blocked on Render
                    url = f"wss://stream.binance.us:9443/ws/{'/'.join([f'{s}@ticker' for s in active_ws_list])}"
                    
                    def on_msg(ws, msg):
                        d = json.loads(msg)
                        if 's' in d: fast_update(d['s'], d['c'], d['P'])

                    current_ws = websocket.WebSocketApp(url, on_message=on_msg)
                    threading.Thread(target=current_ws.run_forever, daemon=True).start()
                    print(f"✅ WS Live: {len(active_ws_list)} symbols")

            time.sleep(20) # Watchlist check interval
        except Exception as e:
            print(f"❌ WS Error: {e}")
            time.sleep(5)

# --- 4. FALLBACK ENGINE (FOR BETH, ETHBEAR, ETC.) ---
def run_fallback_polling():
    while True:
        try:
            # Gate.io has almost every "exotic" crypto pair
            resp = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=2)
            if resp.status_code == 200:
                for item in resp.json():
                    pair = item['currency_pair'].replace("_", "")
                    fast_update(pair, item['last'], item.get('change_percentage', 0))
            time.sleep(2) # 2s polling for non-WS symbols
        except: time.sleep(5)

@app.route('/')
def health(): return "ULTRA_FAST_ENGINE_V7_ACTIVE"

if __name__ == '__main__':
    # Start Services
    threading.Thread(target=start_ws_engine, daemon=True).start()
    threading.Thread(target=run_fallback_polling, daemon=True).start()
    
    # Render Port Binding
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
