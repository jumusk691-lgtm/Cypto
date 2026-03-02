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
        eventlet.sleep(3)
        last_price_cache.clear() 

# --- 3. UPDATED OVERWRITE ENGINE ---
def update_firebase(symbol, price):
    global watchlist_data, last_price_cache
    try:
        if not price or float(price) <= 0: return
        p_str = f"{float(price):.4f}"
        
        if last_price_cache.get(symbol) == p_str: return
        last_price_cache[symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        for node_key in list(watchlist_data.keys()):
            # Extract base name: "BTCUSDT_abc" -> "BTCUSDT"
            db_raw = node_key.split('_')[0].upper()
            incoming_sym = symbol.upper()
            
            # Match Logic: Agar DB mein 'BTC' hai aur Binance 'BTCUSDT' bhej raha hai
            if incoming_sym == db_raw or incoming_sym == f"{db_raw}USDT" or db_raw == f"{incoming_sym}USDT":
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            print(f"📡 [LIVE] {symbol} -> {p_str}")
    except: pass

# --- 4. FIXED BINANCE HANDLER ---
def run_binance():
    while True:
        try:
            # FIX: Symbols ko Binance format mein convert karein
            raw_symbols = [n.split('_')[0].lower() for n in watchlist_data.keys()]
            clean_symbols = []
            for s in raw_symbols:
                if s in ["xau", "xai", "eth", "btc", "chess"]: # Agar sirf coin name hai
                    clean_symbols.append(f"{s}usdt")
                else:
                    clean_symbols.append(s)
            
            if not clean_symbols: 
                eventlet.sleep(5); continue
            
            # Remove duplicates and limit to 50
            clean_symbols = list(set(clean_symbols))[:50]
            url = f"wss://stream.binance.com:9443/ws/{'@ticker/'.join(clean_symbols)}@ticker"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                if 's' in d and 'c' in d: update_firebase(d['s'], d['c'])
            
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"🔄 Binance Reconnect: {e}"); eventlet.sleep(5)

# --- 5. SYSTEM START ---
def start_listener():
    global watchlist_data
    db.reference('forex_watchlist').listen(lambda e: globals().update(watchlist_data=db.reference('forex_watchlist').get() or {}))

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
