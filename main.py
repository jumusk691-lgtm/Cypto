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

# --- 2. 3-SECOND STORAGE CLEANER ---
# Ye function local cache saaf rakhta hai taaki prices stagnant na ho
def storage_cleaner():
    global last_price_cache
    while True:
        eventlet.sleep(3)
        last_price_cache.clear() 

# --- 3. BINANCE-ONLY ENGINE ---
def update_firebase(symbol, price, source="Binance"):
    global watchlist_data, last_price_cache
    try:
        if not price or float(price) <= 0: return
        p_str = f"{float(price):.4f}" # Konsi bhi price ho, consistent format
        
        # Duplicate check to save Firebase bandwidth
        if last_price_cache.get(symbol) == p_str: return
        last_price_cache[symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Watchlist symbols ke saath match karke overwrite karein
        for node_key in list(watchlist_data.keys()):
            db_symbol = node_key.split('_')[0].upper()
            
            # Match BTCUSDT or XAUUSDT with partial matches
            if symbol.upper().startswith(db_symbol) or db_symbol.startswith(symbol.upper()):
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates) # Automatic Overwrite
            print(f"📡 [Binance] {symbol} -> {p_str}")
    except: pass

# --- 4. OPTIMIZED BINANCE HANDLER ---
def run_binance():
    def on_msg(ws, msg):
        d = json.loads(msg)
        # 's' is Symbol, 'c' is Last Price in Binance ticker stream
        if 's' in d and 'c' in d: 
            update_firebase(d['s'], d['c'])
            
    while True:
        try:
            # Firebase se symbols ki list lekar lowercase mein convert karein
            symbols = [n.split('_')[0].lower() for n in watchlist_data.keys()]
            if not symbols: 
                eventlet.sleep(5); continue
            
            # Binance Multi-stream URL (Max 50-100 symbols per connection)
            # Example: wss://stream.binance.com:9443/ws/btcusdt@ticker/ethusdt@ticker
            url = f"wss://stream.binance.com:9443/ws/{'@ticker/'.join(symbols[:100])}@ticker"
            
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            # ping_interval 20 ensures Render doesn't kill the connection
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except: 
            print("🔄 Binance Reconnecting..."); eventlet.sleep(5)

# --- 5. SYSTEM START ---
def start_listener():
    global watchlist_data
    # Real-time listener for your Firebase watchlist
    db.reference('forex_watchlist').listen(lambda e: globals().update(watchlist_data=db.reference('forex_watchlist').get() or {}))

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"BINANCE_ONLY_ENGINE_ACTIVE"]

if __name__ == '__main__':
    from eventlet import wsgi
    # Start all background tasks
    eventlet.spawn(start_listener)
    eventlet.spawn(storage_cleaner)
    eventlet.spawn(run_binance)
    
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Binance Engine running on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
