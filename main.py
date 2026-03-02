import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE) if os.path.exists("/etc/secrets/") else KEY_FILE

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
print("✅ Firebase Connected!")

# --- 2. GLOBAL CONTROLS ---
already_subscribed = set()
last_price_cache = {}
ws_app = None

# --- 3. SMART UPDATE LOGIC ---
def update_firebase(symbol, price):
    global last_price_cache
    try:
        if last_price_cache.get(symbol) == price:
            return 
        
        last_price_cache[symbol] = price
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Aapki key format (ETHUSDT_uid) ke liye logic
                clean_name = node_key.split('_')[0].upper()
                
                multiplier = 1000.0 if clean_name.startswith("1000") else 1.0
                search_target = clean_name.replace("1000", "") if multiplier > 1.0 else clean_name
                
                if search_target == symbol or f"{search_target}USDT" == symbol:
                    final_price = float(price) * multiplier
                    updates[f"{node_key}/price"] = f"{final_price:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates)
                print(f"📡 {symbol} Updated -> {price}")
                del updates
                
    except Exception as e:
        print(f"⚠️ Firebase Update Error: {e}")

# --- 4. BATCHED SUBSCRIPTION ---
def manage_subscriptions(current_list):
    global already_subscribed, ws_app
    new_to_add = [s for s in current_list if s not in already_subscribed]
    
    if not new_to_add or not ws_app or not ws_app.sock or not ws_app.sock.connected:
        return

    batch_size = 100
    for i in range(0, len(new_to_add), batch_size):
        batch = new_to_add[i:i + batch_size]
        ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{s}" for s in batch]}))
        for s in batch: already_subscribed.add(s)
        print(f"✅ Batch Subscribed: {len(batch)} symbols")
        eventlet.sleep(0.3)

# --- 5. WEBSOCKET ENGINE ---
def on_message(ws, message):
    data = json.loads(message)
    if 'data' in data:
        tick = data['data']
        s, p = tick.get('symbol'), tick.get('lastPrice')
        if s and p: update_firebase(s, p)

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
            ws_app.run_forever()
        except: pass
        time.sleep(5)

# --- 6. WATCHLIST SYNC ---
def sync_watchlist():
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get()
            if watchlist:
                symbols = []
                for node_key in watchlist.keys():
                    s = node_key.split('_')[0].upper()
                    if not s.endswith("USDT"): s += "USDT"
                    symbols.append(s)
                manage_subscriptions(symbols)
            eventlet.sleep(30)
        except Exception as e:
            print(f"⚠️ Sync Loop Error: {e}")
            eventlet.sleep(10)

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), lambda e, s: [s('200 OK', [('Content-Type', 'text/plain')]), b"STABLE"])
