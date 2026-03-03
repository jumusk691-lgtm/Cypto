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
        eventlet.sleep(300) # 3 second bahut kam hai, 5 min (300s) thik hai cache clear karne ke liye
        last_price_cache.clear() 

# --- 3. OVERWRITE ENGINE ---
def update_firebase(binance_symbol, price):
    global watchlist_data, last_price_cache
    try:
        if not price or float(price) <= 0: return
        p_str = f"{float(price):.4f}"
        
        # Performance: Agar price change nahi hui toh update mat karo
        if last_price_cache.get(binance_symbol) == p_str: return
        last_price_cache[binance_symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        incoming_sym = binance_symbol.upper() # e.g., "BTCUSDT"

        for node_key in list(watchlist_data.keys()):
            # Node key format: "BTCUSDT_UID"
            db_raw = node_key.split('_')[0].upper()
            
            # Flexible Match: BTCUSDT == BTCUSDT or BTC == BTCUSDT (stripped)
            if incoming_sym == db_raw or incoming_sym.replace("USDT", "") == db_raw or db_raw.replace("USD", "") == incoming_sym.replace("USDT", ""):
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            print(f"📡 [LIVE] {binance_symbol} -> {p_str}")
    except Exception as e: 
        print(f"❌ Update Error: {e}")

# --- 4. BINANCE HANDLER ---
def run_binance():
    global watchlist_data
    while True:
        try:
            # Forex aur Crypto symbols filter karein
            raw_keys = list(watchlist_data.keys())
            if not raw_keys:
                print("⏳ Waiting for symbols in Firebase...")
                eventlet.sleep(5); continue

            clean_symbols = []
            for k in raw_keys:
                s = k.split('_')[0].lower()
                # Binance sirf USDT pairs support karta hai crypto ke liye
                # Aur gold ke liye XAUUSDT (Binance format)
                if any(x in s for x in ["btc", "eth", "bnb", "xau", "xag", "sol"]):
                    if not s.endswith("usdt"):
                        # Agar XAUUSD hai toh XAUUSDT banao, BTC hai toh BTCUSDT
                        s = s.replace("usd", "") + "usdt"
                clean_symbols.append(s)

            # Limit and remove duplicates
            streams = [f"{s}@ticker" for s in set(clean_symbols) if s]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                if 's' in d and 'c' in d: update_firebase(d['s'], d['c'])
            
            print(f"🚀 Connecting to Binance: {len(streams)} symbols")
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=25, ping_timeout=15)
        except Exception as e:
            print(f"🔄 Binance Reconnect: {e}"); eventlet.sleep(5)

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
