import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading, sqlite3, requests, gc
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG & AUTH ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
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
                resp = requests.get(f"https://v6.exchangerate-api.com/v6/{FOREX_API_KEY}/latest/USD")
                rates = resp.json().get('conversion_rates', {})
                updates = {}
                for nid in exotic_list:
                    # Example: "AFNUSD_uid" -> "AFN"
                    sym = nid.split('_')[0].upper().replace("USD", "")
                    if sym in rates:
                        price = 1 / rates[sym]
                        updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(price)
                        updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                if updates: 
                    db.reference().update(updates)
                    print(f"✅ {len(updates)} Exotic Pairs Updated.")
            except Exception as e:
                print(f"❌ Exotic Error: {e}")
        time.sleep(60)

# --- 4. LOGIC: MASTER ENGINE (BINANCE + AUTO-DETECTION) ---
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
                
                # --- AUTO ROUTING LOGIC ---
                # 1. Any symbol with "USDT" (e.g., BTSUSDT, BTTCUSDT)
                # 2. Majors and Gold/Silver
                if "USDT" in raw or any(x in raw for x in ["EUR", "GBP", "JPY", "XAU", "XAG"]):
                    # Binance mapping (ensure usdt format)
                    target = raw.lower()
                    if "usd" in target and "usdt" not in target:
                        target = target.replace("usd", "usdt")
                    
                    new_binance.add(target)
                    if target.upper() not in new_map: new_map[target.upper()] = []
                    new_map[target.upper()].append(node_id)
                else:
                    new_exotic.append(node_id)

            exotic_list = new_exotic
            
            # Restart WS only if targets changed
            if new_binance != active_binance:
                print(f"🔄 Watchlist Change Detected. Updating Stream: {new_binance}")
                active_binance = new_binance
                node_map = new_map
                if current_ws: 
                    current_ws.close()
                
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

                    def on_error(ws, error): print(f"❌ WS Error: {error}")
                    def on_close(ws, c, m): print("🔌 WebSocket Connection Closed")
                    
                    current_ws = websocket.WebSocketApp(url, 
                                                       on_message=on_message, 
                                                       on_error=on_error, 
                                                       on_close=on_close)
                    threading.Thread(target=current_ws.run_forever, daemon=True).start()
            
            time.sleep(15)
        except Exception as e:
            print(f"❌ Master Engine Error: {e}")
            time.sleep(5)

@app.route('/')
def health(): return "HYBRID_ENGINE_V3_ACTIVE"

if __name__ == '__main__':
    # Start Services
    threading.Thread(target=check_market_status, daemon=True).start()
    threading.Thread(target=run_exotic_engine, daemon=True).start()
    threading.Thread(target=run_master_engine, daemon=True).start()
    
    # Run Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
