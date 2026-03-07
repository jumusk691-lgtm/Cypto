import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, time, threading, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG & AUTH ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
FOREX_API_KEY = "8bc2800bcaaa268f50b12fa2" 

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
active_symbols = []
exotic_list = []
node_map = {}
is_forex_open = True

# --- 2. LOGIC: FOREX MARKET STATUS ---
def check_market_status():
    global is_forex_open
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        weekday = now.weekday() 
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
                    sym = nid.split('_')[0].upper().replace("USD", "")
                    if sym in rates:
                        price = 1 / rates[sym]
                        updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(price)
                        updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                if updates: 
                    db.reference().update(updates)
            except Exception as e:
                print(f"❌ Exotic Error: {e}")
        time.sleep(60)

# --- 4. LOGIC: MASTER ENGINE (NON-BLOCKING API) ---
def run_master_engine():
    global node_map, active_symbols, exotic_list
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_crypto = []
            new_exotic = []
            new_map = {}

            for node_id in watchlist.keys():
                raw = node_id.split('_')[0].upper()
                if "USDT" in raw or any(x in raw for x in ["EUR", "GBP", "JPY", "XAU", "XAG"]):
                    target = raw if "USDT" in raw else raw.replace("USD", "USDT")
                    new_crypto.append(target)
                    if target not in new_map: new_map[target] = []
                    new_map[target].append(node_id)
                else:
                    new_exotic.append(node_id)

            exotic_list = new_exotic
            node_map = new_map
            active_symbols = list(set(new_crypto))

            if active_symbols:
                # Using KuCoin API as it is generally NOT restricted on Render/Cloud IPs
                resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers")
                if resp.status_code == 200:
                    data = resp.json().get('data', {}).get('ticker', [])
                    # KuCoin uses hyphen format: BTC-USDT
                    price_dict = {item['symbol'].replace("-", ""): item for item in data}
                    
                    updates = {}
                    for sym in active_symbols:
                        if sym in price_dict:
                            item = price_dict[sym]
                            price = item['last']
                            # KuCoin change calculation
                            change = float(item.get('changeRate', 0)) * 100
                            
                            for nid in node_map.get(sym, []):
                                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                                updates[f"forex_watchlist/{nid}/percent"] = "{:.2f}%".format(change)
                                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                    
                    if updates:
                        db.reference().update(updates)
                        print(f"🚀 Updated {len(active_symbols)} symbols via KuCoin API")
                else:
                    print(f"⚠️ KuCoin API Error: {resp.status_code}")

            time.sleep(15)
        except Exception as e:
            print(f"❌ Master Engine Error: {e}")
            time.sleep(5)

@app.route('/')
def health(): return "HYBRID_ENGINE_V4_KUCOIN_ACTIVE"

if __name__ == '__main__':
    threading.Thread(target=check_market_status, daemon=True).start()
    threading.Thread(target=run_exotic_engine, daemon=True).start()
    threading.Thread(target=run_master_engine, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
