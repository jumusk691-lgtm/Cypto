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
print("✅ Firebase Connected to forex_watchlist engine!")

already_subscribed = set()
last_price_cache = {}
ws_app = None

# --- 2. THE ULTIMATE MATCHING ENGINE ---
def update_firebase(incoming_symbol, price):
    global last_price_cache
    try:
        if not price or float(price) <= 0: return
        
        # Filtering: Agar price wahi hai jo cache mein hai, toh aage mat badho
        p_str = str(price)
        if last_price_cache.get(incoming_symbol) == p_str: 
            return 
        
        last_price_cache[incoming_symbol] = p_str
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Seedha 'forex_watchlist' node ko hit karo
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Node key parse (e.g., BTCUSDT_uid)
                raw_name = node_key.split('_')[0].upper()
                
                # Multiplier Logic
                multiplier = 1000.0 if raw_name.startswith("1000") else 1.0
                clean_name = raw_name.replace("1000", "")
                
                # Smart Match: Agar Bybit se ETHUSDT aaya aur Firebase mein ETH hai
                if clean_name == incoming_symbol or f"{clean_name}USDT" == incoming_symbol or incoming_symbol.startswith(clean_name):
                    final_p = float(price) * multiplier
                    
                    # Firebase Overwrite Logic (Sirf price aur utime badlega)
                    updates[f"{node_key}/price"] = f"{final_p:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates) # Sab kuch ek saath push
                print(f"📡 forex_watchlist updated: {incoming_symbol} -> {price}")
                del updates
    except Exception as e:
        print(f"⚠️ FB Update Error: {e}")

# --- 3. STABLE WEBSOCKET HANDLERS ---
def on_message(ws, message):
    try:
        msg = json.loads(message)
        if 'data' in msg:
            data = msg['data']
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
                on_close=lambda w, c, r: print("🔌 Connection Lost. Reconnecting...")
            )
            ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except: pass
        time.sleep(5)

# --- 4. SYNC LOOP (Watchlist Scanning) ---
def sync_watchlist():
    while True:
        try:
            # 1. Firebase se watchlist node scan karo
            watchlist_ref = db.reference('forex_watchlist')
            watchlist = watchlist_ref.get()
            
            if watchlist and ws_app and ws_app.sock and ws_app.sock.connected:
                to_sub = []
                for node_key in watchlist.keys():
                    # Symbol extraction
                    s = node_key.split('_')[0].upper().replace("1000", "")
                    if not s.endswith("USDT"): s += "USDT" 
                    
                    # 2. Duplicate Check: Dobara subscribe nahi karna
                    if s not in already_subscribed:
                        to_sub.append(s)
                
                if to_sub:
                    # 3. Batch Subscription (100 symbols per batch)
                    for i in range(0, len(to_sub), 100):
                        batch = to_sub[i:i+100]
                        ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{x}" for x in batch]}))
                        for x in batch: already_subscribed.add(x)
                        print(f"✅ Subscribed to new symbols in forex_watchlist: {batch}")
            
            eventlet.sleep(15) 
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(10)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"FOREX WATCHLIST ENGINE IS STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
