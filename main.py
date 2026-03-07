import os, datetime, json, firebase_admin, time, threading, requests
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

# --- 2. MASTER ENGINE (1-SECOND POLLING) ---
def run_fast_engine():
    global node_map
    print("🚀 Fast Engine Started...")
    while True:
        try:
            # Watchlist fetch karein
            watchlist = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            for nid in watchlist.keys():
                sym = nid.split('_')[0].upper()
                if sym not in temp_map: temp_map[sym] = []
                temp_map[sym].append(nid)
            node_map = temp_map

            if node_map:
                # KuCoin API 1-second update ke liye sabse best hai
                resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=1)
                if resp.status_code == 200:
                    data = resp.json().get('data', {}).get('ticker', [])
                    # Sabhi symbols ko dictionary mein daalein (Fast lookup)
                    prices = {item['symbol'].replace("-", ""): item for item in data}
                    
                    updates = {}
                    for sym, nids in node_map.items():
                        # Binance formats ko match karne ke liye
                        target = sym if "USDT" in sym else f"{sym}USDT"
                        
                        if target in prices:
                            p_data = prices[target]
                            for nid in nids:
                                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(p_data['last']))
                                updates[f"forex_watchlist/{nid}/percent"] = "{:.2f}%".format(float(p_data.get('changeRate', 0)) * 100)
                                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")

                    if updates:
                        db.reference().update(updates)
            
            # EXACT 1 SECOND DELAY
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Engine Error: {e}")
            time.sleep(1)

@app.route('/')
def health():
    return "ENGINE_RUNNING_1SEC"

if __name__ == '__main__':
    # Engine ko separate thread mein chalayein
    t = threading.Thread(target=run_fast_engine, daemon=True)
    t.start()
    
    # Render port fix
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
