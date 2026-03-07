import os, datetime, json, firebase_admin, time, threading, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

# Global state to keep track of symbols across threads
node_map = {}
last_data_cache = {}

# --- 2. DYNAMIC WATCHLIST LISTENER ---
def start_forex_listener():
    """Firebase mein badlav hote hi ye function node_map ko update kar deta hai"""
    global node_map
    def listener_callback(event):
        global node_map
        watchlist = db.reference('forex_watchlist').get() or {}
        temp_map = {}
        for nid in watchlist.keys():
            # Example: 'AED_b02Oy...' -> 'AED'
            sym = nid.split('_')[0].upper()
            if sym not in temp_map: 
                temp_map[sym] = []
            temp_map[sym].append(nid)
        node_map = temp_map
        print(f"📡 Forex Watchlist Updated: {list(node_map.keys())}")

    print("🚀 Monitoring 'forex_watchlist' for live changes...")
    db.reference('forex_watchlist').listen(listener_callback)

# --- 3. FAST UPDATE LOGIC ---
def fast_update(symbol, price, change="0.00"):
    global last_data_cache
    updates = {}
    
    # KuCoin format "BTC-USDT" ko aapke Firebase prefix "BTC" se match karna
    clean_sym = symbol.split('-')[0].upper()
    
    if clean_sym in node_map:
        current_price = float(price)
        
        # Performance check: Sirf tab update karein jab price badle
        if last_data_cache.get(clean_sym) == current_price:
            return

        now_time = datetime.datetime.now().strftime("%H:%M:%S")
        for nid in node_map[clean_sym]:
            path = f"forex_watchlist/{nid}"
            updates[f"{path}/price"] = "{:.5f}".format(current_price)
            updates[f"{path}/percent"] = f"{change}%"
            updates[f"{path}/utime"] = now_time
        
        if updates:
            try:
                db.reference().update(updates)
                last_data_cache[clean_sym] = current_price
            except Exception:
                pass

# --- 4. DATA FETCHING ENGINE ---
def run_forex_engine():
    print("💎 Forex/Crypto Engine Running...")
    while True:
        try:
            # KuCoin API call (Sabhi tickers ek saath fetch hote hain)
            resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=5)
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                tickers = data.get('ticker', [])
                
                for t in tickers:
                    # Sirf un symbols ko process karein jo node_map mein hain
                    sym = t['symbol'].split('-')[0].upper()
                    if sym in node_map:
                        fast_update(t['symbol'], t['last'], t.get('changeRate', '0.00'))
            
            # API rate limit aur battery saving ke liye 2 second ka gap
            time.sleep(2)
            
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            time.sleep(5)

# --- 5. FLASK WEB SERVER ---
@app.route('/')
def health():
    return f"FOREX_ENGINE_ACTIVE: {len(node_map)} symbols"

if __name__ == '__main__':
    # Step 1: Start Listener (Watchlist update karne ke liye)
    threading.Thread(target=start_forex_listener, daemon=True).start()
    
    # Step 2: Start Fetching Engine
    threading.Thread(target=run_forex_engine, daemon=True).start()
    
    # Step 3: Start Web Server (Render/Heroku ke liye)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
