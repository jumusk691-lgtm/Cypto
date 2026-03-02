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
# Ye function har 3 second mein temporary cache saaf karega taaki 
# Firebase mein hamesha fresh overwrite ho aur storage clean rahe.
def storage_cleaner():
    global last_price_cache
    while True:
        eventlet.sleep(3)
        last_price_cache.clear() 
        # Note: Firebase RTDB mein .update() apne aap purane data ko overwrite karta hai.
        # Isliye extra storage kabhi nahi bharegi.

# --- 3. UNIVERSAL OVERWRITE ENGINE ---
def update_firebase(symbol, price, source):
    global watchlist_data, last_price_cache
    try:
        if not price or float(price) <= 0: return
        p_str = f"{float(price):.4f}" # 4 decimal places for consistency
        
        # Overwrite logic: Agar cache mein ye price hai toh skip (Firebase billing bachane ke liye)
        if last_price_cache.get(symbol) == p_str: return
        last_price_cache[symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Loop through watchlist to find matching symbol keys (e.g. BTCUSDT_uid)
        for node_key in list(watchlist_data.keys()):
            db_symbol = node_key.split('_')[0].upper()
            
            # Smart Matching: Agar incoming symbol 'XAUUSDT' hai aur DB mein 'XAU', toh match karega
            if symbol.upper().startswith(db_symbol) or db_symbol.startswith(symbol.upper()):
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates) # Automatic Overwrite in Firebase
            print(f"📡 [{source}] {symbol} -> {p_str}")
    except: pass

# --- 4. OPTIMIZED MULTI-API HANDLERS ---

def run_binance():
    def on_msg(ws, msg):
        d = json.loads(msg)
        if 's' in d and 'c' in d: update_firebase(d['s'], d['c'], "Binance")
    while True:
        try:
            # Sirf top 50 symbols ko Binance stream mein bhej rahe hain for stability
            symbols = [n.split('_')[0].lower() for n in watchlist_data.keys()][:50]
            if not symbols: eventlet.sleep(5); continue
            url = f"wss://stream.binance.com:9443/ws/{'@ticker/'.join(symbols)}@ticker"
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=20)
        except: eventlet.sleep(5)

def run_bybit():
    def on_msg(ws, msg):
        d = json.loads(msg).get("data", {})
        if isinstance(d, dict) and d.get("lastPrice"):
            update_firebase(d.get("symbol"), d.get("lastPrice"), "Bybit")
    while True:
        try:
            ws = websocket.WebSocketApp("wss://stream.bybit.com/v5/public/linear", on_message=on_msg)
            def on_open(ws):
                args = [f"tickers.{n.split('_')[0]}" for n in watchlist_data.keys()]
                ws.send(json.dumps({"op": "subscribe", "args": args}))
            ws.on_open = on_open
            ws.run_forever(ping_interval=20)
        except: eventlet.sleep(5)

# --- 5. SYSTEM START ---
def start_listener():
    global watchlist_data
    db.reference('forex_watchlist').listen(lambda e: globals().update(watchlist_data=db.reference('forex_watchlist').get() or {}))

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"MASTER_CLEANER_ENGINE_ACTIVE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_listener)
    eventlet.spawn(storage_cleaner) # Har 3 second mein saaf-safai
    eventlet.spawn(run_binance)
    eventlet.spawn(run_bybit)
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
