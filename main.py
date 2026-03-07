import os, datetime, json, firebase_admin, websocket, time, threading, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
FOREX_API_KEY = "8bc2800bcaaa268f50b12fa2" 

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
    # Clean symbol to match Firebase (BTC-USDT or BTC_USDT -> BTCUSDT)
    clean_sym = symbol.upper().replace("-", "").replace("_", "")
    
    # Try direct match and base match (e.g. BTCUSDT and BTC)
    targets = [clean_sym, clean_sym.replace("USDT", "")]
    
    for t in targets:
        if t in node_map:
            for nid in node_map[t]:
                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                updates[f"forex_watchlist/{nid}/percent"] = f"{change}%"
                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
    
    if updates:
        db.reference().update(updates)

# --- 3. BINANCE US WEBSOCKET (For Major Crypto) ---
def start_ws_engine():
    global current_ws, active_ws_list, node_map
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_map = {}
            new_ws_list = set()

            for nid in watchlist.keys():
                sym = nid.split('_')[0].upper()
                if sym not in new_map: new_map[sym] = []
                new_map[sym].append(nid)
                
                # Binance US supports these pairs
                if any(x in sym for x in ["BTC", "ETH", "BNB", "SOL", "USDT"]):
                    target = sym.lower() if "usdt" in sym.lower() else f"{sym.lower()}usdt"
                    new_ws_list.add(target)

            node_map = new_map

            if new_ws_list != active_ws_list:
                active_ws_list = new_ws_list
                if current_ws: current_ws.close()
                if active_ws_list:
                    url = f"wss://stream.binance.us:9443/ws/{'/'.join([f'{s}@ticker' for s in active_ws_list])}"
                    def on_msg(ws, msg):
                        d = json.loads(msg)
                        if 's' in d: fast_update(d['s'], d['c'], d['P'])
                    current_ws = websocket.WebSocketApp(url, on_message=on_msg)
                    threading.Thread(target=current_ws.run_forever, daemon=True).start()
                    print(f"✅ WS Live: {len(active_ws_list)} symbols")

            time.sleep(30)
        except Exception as e:
            print(f"❌ WS Master Error: {e}")
            time.sleep(10)

# --- 4. EXOTIC & FALLBACK ENGINE (For BETH, ETHBEAR, Forex) ---
def run_fallback_engine():
    print("🛰️ Fallback & Forex Engine Active...")
    while True:
        try:
            # A. Crypto Fallback (Gate.io for all exotic tokens)
            g_resp = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=5)
            if g_resp.status_code == 200:
                for item in g_resp.json():
                    fast_update(item['currency_pair'], item['last'], item.get('change_percentage', 0))

            # B. Forex Fallback (ExchangeRate-API)
            f_resp = requests.get(f"https://v6.exchangerate-api.com/v6/{FOREX_API_KEY}/latest/USD", timeout=5)
            if f_resp.status_code == 200:
                rates = f_resp.json().get('conversion_rates', {})
                for sym, rate in rates.items():
                    # Update if it's in our node_map (like AFA, AFN, etc.)
                    if sym in node_map:
                        price = 1 / rate
                        fast_update(sym, price)

            time.sleep(3) # Fast polling for non-WS symbols
        except Exception as e:
            print(f"❌ Fallback Error: {e}")
            time.sleep(5)

@app.route('/')
def health(): return "HYBRID_V8_MIXED_ACTIVE"

if __name__ == '__main__':
    # Start all engines
    threading.Thread(target=start_ws_engine, daemon=True).start()
    threading.Thread(target=run_fallback_engine, daemon=True).start()
    
    # Flask for Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
