import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE) if os.path.exists("/etc/secrets/") else KEY_FILE

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})
print("✅ Firebase Connected!")

watchlist_data = {}
last_price_cache = {}

# --- 2. STORAGE CLEANER ---
def storage_cleaner():
    global last_price_cache
    while True:
        eventlet.sleep(300) 
        last_price_cache.clear() 

# --- 3. FLEXIBLE OVERWRITE ENGINE ---
def update_firebase(binance_symbol, price):
    global watchlist_data, last_price_cache
    try:
        p_val = float(price)
        if p_val <= 0: return
        
        # Smart Precision: Crypto ke liye 4 decimal, baki 2
        p_str = f"{p_val:.4f}" if p_val < 100 else f"{p_val:.22f}".split('.')[0] + f".{str(round(p_val,2)).split('.')[1]}"
        p_str = "%.4f" % p_val # Stable approach
        
        if last_price_cache.get(binance_symbol) == p_str: return
        last_price_cache[binance_symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Normalize incoming (e.g., "BTCUSDT" -> "BTC")
        incoming_raw = binance_symbol.upper()
        base_incoming = incoming_raw.replace("USDT", "").replace("USD", "").replace("USDS", "")

        for node_key in list(watchlist_data.keys()):
            # db_raw split logic: "BTC_UID" -> "BTC"
            db_sym_full = node_key.split('_')[0].upper()
            base_db = db_sym_full.replace("USDT", "").replace("USD", "").replace("USDS", "")
            
            # Agar base match ho gaya (BTC == BTC) toh update karo
            if base_incoming == base_db:
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            print(f"📡 [MATCHED] {binance_symbol} -> {p_str}")
    except Exception as e: 
        print(f"❌ Update Error: {e}")

# --- 4. BINANCE HANDLER ---
def run_binance():
    global watchlist_data
    while True:
        try:
            raw_keys = list(watchlist_data.keys())
            if not raw_keys:
                print("⏳ Waiting for symbols in Firebase...")
                eventlet.sleep(5); continue

            clean_symbols = []
            for k in raw_keys:
                s = k.split('_')[0].lower()
                # Mapping symbols to Binance pairs
                if any(x in s for x in ["btc", "eth", "bnb", "xau", "xag", "sol", "weth", "fdusd"]):
                    if "xau" in s: s = "xauusdt"
                    elif "xag" in s: s = "xagusdt"
                    elif not s.endswith("usdt") and not s.endswith("fdusd"):
                        s = s.replace("usd", "").replace("usds", "") + "usdt"
                clean_symbols.append(s)

            streams = [f"{s}@ticker" for s in set(clean_symbols) if s]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                if 's' in d and 'c' in d: update_firebase(d['s'], d['c'])
            
            print(f"🚀 Connecting: {len(streams)} streams")
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=25, ping_timeout=15)
        except Exception as e:
            print(f"🔄 Reconnect: {e}"); eventlet.sleep(5)

# --- 5. SYSTEM START ---
def start_listener():
    def sync_data(event):
        global watchlist_data
        watchlist_data = db.reference('forex_watchlist').get() or {}
        print(f"🔄 Watchlist Synced: {len(watchlist_data)} items")

    db.reference('forex_watchlist').listen(sync_data)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"BINANCE_ENGINE_FIXED_ACTIVE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_listener)
    eventlet.spawn(storage_cleaner)
    eventlet.spawn(run_binance)
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
