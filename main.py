import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
# Render Secret Path handling
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE) if os.path.exists("/etc/secrets/") else KEY_FILE

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
print("✅ Firebase Connected!")

# --- 2. GLOBAL CONTROLS ---
already_subscribed = set()   # Duplicate check ke liye
last_price_cache = {}        # Price change detection ke liye
ws_app = None

# --- 3. SMART UPDATE LOGIC (With Overwrite & Cleanup) ---
def update_firebase(symbol, price):
    global last_price_cache
    try:
        # Check: Kya price badla hai? (Zero-Delay Filter)
        if last_price_cache.get(symbol) == price:
            return 
        
        last_price_cache[symbol] = price # Update local cache
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Firebase Reference
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Logic: node_key se symbol extract karna (e.g. BTCUSDT_uid)
                clean_name = node_key.split('_')[0].upper()
                
                # Multiplier Support (1000LUNC etc)
                multiplier = 1000.0 if clean_name.startswith("1000") else 1.0
                search_target = clean_name.replace("1000", "") if multiplier > 1.0 else clean_name
                
                # Symbol matching (Bybit names usually have USDT)
                if search_target == symbol or f"{search_target}USDT" == symbol:
                    final_price = float(price) * multiplier
                    # Overwrite existing fields
                    updates[f"{node_key}/price"] = f"{final_price:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates) # Firebase overwrite
                print(f"📡 [Update] {symbol}: {price}")
                del updates # Memory Cleanup
                
    except Exception as e:
        print(f"❌ Firebase Update Error: {e}")

# --- 4. BATCHED SUBSCRIPTION LOGIC ---
def manage_subscriptions(current_list):
    global already_subscribed, ws_app
    
    # Sirf wo symbols jo pehle se subscribe nahi hain
    new_to_add = [s for s in current_list if s not in already_subscribed]
    
    if not new_to_add or not ws_app or not ws_app.sock or not ws_app.sock.connected:
        return

    # Batching: 100 symbols per request (As per your logic)
    batch_size = 100
    for i in range(0, len(new_to_add), batch_size):
        batch = new_to_add[i:i + batch_size]
        subscribe_msg = {
            "op": "subscribe",
            "args": [f"tickers.{s}" for s in batch]
        }
        ws_app.send(json.dumps(subscribe_msg))
        
        for s in batch:
            already_subscribed.add(s) # Mark as subscribed
            
        print(f"✅ Batch Subscribed: {len(batch)} symbols")
        eventlet.sleep(0.3) # Rate limit safety

# --- 5. WEBSOCKET HANDLERS (With Auto-Reconnect) ---
def on_message(ws, message):
    data = json.loads(message)
    if 'data' in data:
        tick = data['data']
        s, p = tick.get('symbol'), tick.get('lastPrice')
        if s and p:
            update_firebase(s, p)
    del data # Local variable cleanup

def run_ws_engine():
    global ws_app, already_subscribed
    while True:
        try:
            print("🚀 Starting Bybit V5 Engine...")
            already_subscribed.clear() # Reset on new connection
            ws_app = websocket.WebSocketApp(
                "wss://stream.bybit.com/v5/public/linear",
                on_message=on_message,
                on_error=lambda w, e: print(f"⚠️ WS Error: {e}"),
                on_close=lambda w, c, r: print("🔌 Connection Lost. Reconnecting...")
            )
            ws_app.run_forever()
        except Exception as e:
            print(f"🔄 Engine Restarting: {e}")
        time.sleep(5) # Reconnect gap

# --- 6. SMART SYNC LOOP (Firebase to WS) ---
def sync_watchlist():
    while True:
        try:
            # Firebase se symbols read karein
            watchlist = db.reference('forex_watchlist').get()
            if watchlist:
                symbols_to_track = []
                for node_key in watchlist.keys():
                    s = node_key.split('_')[0].upper()
                    # Bybit v5 needs full name like BTCUSDT
                    if not s.endswith("USDT"): s += "USDT"
                    symbols_to_track.append(s)
                
                # Check for new symbols to add
                manage_subscriptions(symbols_to_track)
                
            eventlet.sleep(30) # Har 30 sec mein naye symbols check karein
        except Exception as e:
            print(f"⚠️ Sync Loop Error: {e}")
            eventlet.sleep(10)

# --- 7. RENDER SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"FOREX ENGINE IS RUNNING STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    # Threads ko start karna
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    
    # Render Port listen
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
