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
ws_app = None

# --- 2. THE ULTIMATE MATCHING ENGINE ---
def update_firebase(incoming_symbol, price):
    global last_price_cache
    try:
        if not price or float(price) <= 0: return
        
        # Price Change Filter: Sirf badla hua price hi bhejna hai
        p_str = str(price)
        if last_price_cache.get(incoming_symbol) == p_str: 
            return 
        
        last_price_cache[incoming_symbol] = p_str
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Extract clean name (e.g., ETH_uid -> ETH)
                raw_name = node_key.split('_')[0].upper()
                
                # Multiplier (1000LUNC etc)
                multiplier = 1000.0 if raw_name.startswith("1000") else 1.0
                clean_name = raw_name.replace("1000", "")
                
                # FLEXIBLE MATCHING LOGIC
                # Agar market bhej raha ETHUSDT aur Firebase mein hai ETH ya ETHUSDT
                is_match = (clean_name == incoming_symbol or 
                           f"{clean_name}USDT" == incoming_symbol or 
                           incoming_symbol.replace("USDT", "") == clean_name)
                
                if is_match:
                    final_p = float(price) * multiplier
                    # Overwrite fields
                    updates[f"{node_key}/price"] = f"{final_p:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates) # Firebase write
                print(f"📡 {incoming_symbol} -> {price} (Updated {len(updates)//2} Nodes)")
                del updates
    except Exception as e:
        print(f"⚠️ Logic Error: {e}")

# --- 3. STABLE WEBSOCKET HANDLERS ---
def on_message(ws, message):
    try:
        msg = json.loads(message)
        if 'data' in msg:
            data = msg['data']
            # Bybit data can be list or dict
            ticks = data if isinstance(data, list) else [data]
            for tick in ticks:
                s, p = tick.get('symbol'), tick.get('lastPrice')
                if s and p: 
                    update_firebase(s, p)
    except: pass

def run_ws_engine():
    global ws_app, already_subscribed
    while True:
        try:
            print("🚀 Starting Bybit V5 Engine...")
            already_subscribed.clear()
            ws_app = websocket.WebSocketApp(
                "wss://stream.bybit.com/v5/public/linear",
                on_message=on_message,
                on_error=lambda w, e: print(f"⚠️ WS Error: {e}"),
                on_close=lambda w, c, r: print("🔌 Connection Lost.")
            )
            # Keeping connection alive with Pings
            ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except: pass
        time.sleep(5)

# --- 4. SYNC LOOP ---
def sync_watchlist():
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get()
            if watchlist and ws_app and ws_app.sock and ws_app.sock.connected:
                to_sub = []
                for node_key in watchlist.keys():
                    s = node_key.split('_')[0].upper().replace("1000", "")
                    if not s.endswith("USDT"): s += "USDT" # Force Bybit Format
                    
                    if s not in already_subscribed:
                        to_sub.append(s)
                
                if to_sub:
                    # Bybit V5 Subscription
                    ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{x}" for x in to_sub]}))
                    for x in to_sub: already_subscribed.add(x)
                    print(f"✅ New Subscriptions: {to_sub}")
            
            eventlet.sleep(15) # Check for new symbols every 15s
        except: eventlet.sleep(10)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    wsgi.server(eventlet.listen(('0.0.0.0', int(os.environ.get("PORT", 10000)))), application)
