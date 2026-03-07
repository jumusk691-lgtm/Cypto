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

# Global state
node_map = {}
last_data_cache = {}

# --- 2. DYNAMIC WATCHLIST LISTENER ---
def start_forex_listener():
    """Firebase se live symbols load karta hai"""
    global node_map
    def listener_callback(event):
        global node_map
        watchlist = db.reference('forex_watchlist').get() or {}
        temp_map = {}
        for nid in watchlist.keys():
            # 'AED_b02Oy...' se 'AED' nikalna
            sym = nid.split('_')[0].upper()
            if sym not in temp_map: 
                temp_map[sym] = []
            temp_map[sym].append(nid)
        node_map = temp_map
        print(f"📡 Forex Watchlist Updated: {list(node_map.keys())}")

    # Initial load + Listen for changes
    db.reference('forex_watchlist').listen(listener_callback)

# --- 3. IMPROVED UPDATE LOGIC ---
def fast_update(raw_symbol, price, change="0.00"):
    global last_data_cache
    updates = {}
    
    # FIX: KuCoin 'BTC-USDT' ya 'AED-USDT' ko 'BTC' ya 'AED' banata hai
    clean_sym = raw_symbol.split('-')[0].upper()
    
    if clean_sym in node_map:
        try:
            current_price = float(price)
            
            # Optimization: Price badle tabhi update karein
            if last_data_cache.get(clean_sym) == current_price:
                return

            now_time = datetime.datetime.now().strftime("%H:%M:%S")
            
            for nid in node_map[clean_sym]:
                path = f"forex_watchlist/{nid}"
                # 5 decimal places tak update (Forex ke liye zaroori)
                updates[f"{path}/price"] = "{:.5f}".format(current_price)
                updates[f"{path}/percent"] = f"{change}%"
                updates[f"{path}/utime"] = now_time
                
            if updates:
                db.reference().update(updates)
                last_data_cache[clean_sym] = current_price
                # Debugging ke liye log (Check karein Render logs mein)
                print(f"✅ Live Update: {clean_sym} -> {current_price}")
                
        except Exception as e:
            print(f"❌ Update Error for {clean_sym}: {e}")

# --- 4. OPTIMIZED ENGINE ---
def run_forex_engine():
    print("💎 Forex/Crypto Engine Running...")
    while True:
        try:
            # KuCoin API - Best for Render (No Block)
            resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=10)
            if resp.status_code == 200:
                tickers = resp.json().get('data', {}).get('ticker', [])
                
                for t in tickers:
                    s = t.get('symbol') # e.g., 'AED-USDT'
                    p = t.get('last')   # Price
                    c = t.get('changeRate', '0.00')
                    
                    if s and p:
                        fast_update(s, p, c)
            
            # 1-2 second ka gap zaroori hai
            time.sleep(1.5)
            
        except Exception as e:
            print(f"⚠️ Network/API Error: {e}")
            time.sleep(5)

# --- 5. HEALTH CHECK ---
@app.route('/')
def health():
    # Render ko batata hai ki engine active hai
    return {
        "status": "stable",
        "tracked_symbols": list(node_map.keys()),
        "last_sync": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

if __name__ == '__main__':
    # Listener start karein
    threading.Thread(target=start_forex_listener, daemon=True).start()
    
    # Engine start karein
    threading.Thread(target=run_forex_engine, daemon=True).start()
    
    # Port binding for Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
