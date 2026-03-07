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

# --- 2. FAST UPDATE FUNCTION ---
def fast_update(symbol, price, change="0.00"):
    updates = {}
    # Symbol cleaning for Firebase mapping
    clean_sym = symbol.upper().replace("-", "").replace("_", "")
    
    # Check both BTCUSDT and BTC formats in your map
    targets = [clean_sym, clean_sym.replace("USDT", "")]
    
    for t in targets:
        if t in node_map:
            for nid in node_map[t]:
                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                updates[f"forex_watchlist/{nid}/percent"] = f"{change}%"
                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
    
    if updates:
        db.reference().update(updates)

# --- 3. THE "NO-BLOCK" ENGINE (KuCoin + Gate.io) ---
def run_ultra_engine():
    global node_map
    print("🚀 Ultra Engine Started (Bye Bye Binance)...")
    while True:
        try:
            # Refresh watchlist mapping
            watchlist = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            for nid in watchlist.keys():
                sym = nid.split('_')[0].upper()
                if sym not in temp_map: temp_map[sym] = []
                temp_map[sym].append(nid)
            node_map = temp_map

            # Fetch from KuCoin (Not blocked on Render)
            # update interval: 1 second
            resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=2)
            if resp.status_code == 200:
                tickers = resp.json().get('data', {}).get('ticker', [])
                for t in tickers:
                    # KuCoin format is BTC-USDT
                    fast_update(t['symbol'], t['last'], t.get('changeRate', '0.00'))
            
            time.sleep(1) # Strict 1-second delay
            
        except Exception as e:
            print(f"⚠️ Engine Log: {e}")
            time.sleep(2)

@app.route('/')
def health(): return "ENGINE_V9_STABLE_NO_BINANCE"

if __name__ == '__main__':
    # Start Engine
    threading.Thread(target=run_ultra_engine, daemon=True).start()
    # Flask Port Binding
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
