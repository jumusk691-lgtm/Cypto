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

# Global States
already_subscribed = set()
last_price_cache = {}
watchlist_data = {} # Local copy taaki baar-baar fetch na karna pade
ws_app = None

# --- 2. FIREBASE LISTENER (Zaruri Badlav) ---
def start_watchlist_listener():
    """Ye function Firebase mein badlav hote hi apne aap local data update kar dega"""
    global watchlist_data
    def listener(event):
        global watchlist_data
        data = db.reference('forex_watchlist').get()
        if data:
            watchlist_data = data
            # Naye symbols ko turant subscribe karne ki koshish karein
            sync_now()
            
    db.reference('forex_watchlist').listen(listener)

# --- 3. THE UPDATED MATCHING ENGINE ---
def update_firebase(incoming_symbol, price):
    global last_price_cache, watchlist_data
    try:
        if not price or float(price) <= 0: return
        p_str = str(price)
        
        # 1. Price Change Filter
        if last_price_cache.get(incoming_symbol) == p_str: return 
        last_price_cache[incoming_symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # 2. Local watchlist data se match karo (Fast Performance)
        for node_key, data in watchlist_data.items():
            raw_name = node_key.split('_')[0].upper()
            multiplier = 1000.0 if raw_name.startswith("1000") else 1.0
            clean_name = raw_name.replace("1000", "")
            
            if clean_name == incoming_symbol or f"{clean_name}USDT" == incoming_symbol or incoming_symbol.startswith(clean_name):
                final_p = float(price) * multiplier
                updates[f"forex_watchlist/{node_key}/price"] = f"{final_p:.8f}".rstrip('0').rstrip('.')
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates) # Multi-path update
            print(f"📡 {incoming_symbol} -> {price}")
            
    except Exception as e:
        print(f"⚠️ Update Error: {e}")

# --- 4. WEBSOCKET HANDLERS ---
def on_message(ws, message):
    try:
        msg = json.loads(message)
        if 'data' in msg:
            data = msg['data']
            ticks = data if isinstance(data, list) else [data]
            for tick in ticks:
                s, p = tick.get('symbol'), tick.get('lastPrice')
                if s and p: update_firebase(s, p)
    except: pass

def run_ws_engine():
    global ws_app, already_subscribed
    while True:
        try:
            print("🚀 Connecting to Bybit V5...")
            already_subscribed.clear()
            ws_app = websocket.WebSocketApp(
                "wss://stream.bybit.com/v5/public/linear",
                on_message=on_message,
                on_error=lambda w, e: print(f"⚠️ WS Error: {e}"),
                on_close=lambda w, c, r: print("🔌 Connection Lost. Reconnecting...")
            )
            # 20s Ping interval connection ko stable rakhega
            ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except: pass
        time.sleep(5)

# --- 5. SYNC LOGIC ---
def sync_now():
    global already_subscribed, ws_app, watchlist_data
    if not ws_app or not ws_app.sock or not ws_app.sock.connected: return
    
    to_sub = []
    for node_key in watchlist_data.keys():
        s = node_key.split('_')[0].upper().replace("1000", "")
        if not s.endswith("USDT"): s += "USDT"
        if s not in already_subscribed:
            to_sub.append(s)
    
    if to_sub:
        for i in range(0, len(to_sub), 100):
            batch = to_sub[i:i+100]
            ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{x}" for x in batch]}))
            for x in batch: already_subscribed.add(x)
            print(f"✅ Subscribed: {batch}")

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"ENGINE IS STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    # Start Listener and Engines
    eventlet.spawn(start_watchlist_listener)
    eventlet.spawn(run_ws_engine)
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
