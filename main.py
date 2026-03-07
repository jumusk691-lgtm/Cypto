import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading, sqlite3, requests, gc
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG & AUTH ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co/storage/v1/object/public/Myt/market_data.db"
# Aapki verified Exotic API Key
FOREX_API_KEY = "8bc2800bcaaa268f50b12fa2" 

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
active_binance = set()
exotic_list = []
node_map = {}
current_ws = None
is_forex_open = True

# --- 2. LOGIC: FOREX MARKET STATUS ---
def check_market_status():
    global is_forex_open
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        weekday = now.weekday() 
        # Forex logic: Closed from Fri 22:00 UTC to Sun 22:00 UTC
        if weekday == 5 or (weekday == 4 and now.hour >= 22) or (weekday == 6 and now.hour < 22):
            is_forex_open = False
        else:
            is_forex_open = True
        time.sleep(300)

# --- 3. LOGIC: EXOTIC UPDATER (AFGHANI ETC) ---
def run_exotic_engine():
    global exotic_list, is_forex_open
    while True:
        if is_forex_open and exotic_list:
            try:
                # API Key use karke exotic rates fetch
                resp = requests.get(f"https://v6.exchangerate-api.com/v6/{FOREX_API_KEY}/latest/USD")
                rates = resp.json().get('conversion_rates', {})
                updates = {}
                for nid in exotic_list:
                    sym = nid.split('_')[0].upper().replace("USD", "")
                    if sym in rates:
                        price = 1 / rates[sym]
                        updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(price)
                        updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                if updates: db.reference().update(updates)
            except: pass
        time.sleep(60)

# --- 4. LOGIC: BINANCE ENGINE (CRYPTO 24/7) ---
def run_master_engine():
    global node_map, current_ws, active_binance, exotic_list
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_binance = set()
            new_exotic = []
            new_map = {}

            for node_id in watchlist.keys():
                raw = node_id.split('_')[0].upper()
                # Binance Routing for Majors and Crypto
                if any(x in raw for x in ["BTC", "ETH", "EUR", "GBP", "JPY", "XAU"]):
                    target = raw.lower().replace("usd", "usdt")
                    new_binance.add(target)
                    if target.upper() not in new_map: new_map[target.upper()] = []
                    new_map[target.upper()].append(node_id)
                else:
                    new_exotic.append(node_id)

            exotic_list = new_exotic
            
            if new_binance != active_binance:
                active_binance = new_binance
                node_map = new_map
                if current_ws: current_ws.close()
                if active_binance:
                    url = f"wss://stream.binance.com:9443/ws/{'/'.join([f'{s}@ticker' for s in active_binance])}"
                    def on_message(ws, msg):
                        d = json.loads(msg)
                        if 's' in d and 'c' in d:
                            s_id, price, p_change = d['s'].upper(), d['c'], d['P']
                            updates = {}
                            for nid in node_map.get(s_id, []):
                                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                                updates[f"forex_watchlist/{nid}/percent"] = f"{p_change}%"
                                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                            db.reference().update(updates)
                    current_ws = websocket.WebSocketApp(url, on_message=on_message)
                    threading.Thread(target=current_ws.run_forever).start()
            time.sleep(15)
        except: time.sleep(5)

@app.route('/')
def health(): return "HYBRID_ENGINE_V3_READY"

if __name__ == '__main__':
    # Start Background Threads
    threading.Thread(target=check_market_status, daemon=True).start()
    threading.Thread(target=run_exotic_engine, daemon=True).start()
    threading.Thread(target=run_master_engine, daemon=True).start()
    
    # Render Production Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
