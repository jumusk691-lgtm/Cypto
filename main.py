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

already_subscribed = set()
last_price_cache = {}
ws_app = None

# --- 2. ADVANCED MATCHING LOGIC ---
def update_firebase(incoming_symbol, price):
    global last_price_cache
    try:
        if last_price_cache.get(incoming_symbol) == price:
            return 
        
        last_price_cache[incoming_symbol] = price
        now = datetime.datetime.now().strftime("%H:%M:%S")
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Node key se symbol nikalo (e.g., BTCUSDT_uid -> BTCUSDT)
                raw_name = node_key.split('_')[0].upper()
                
                # Multiplier handling
                multiplier = 1000.0 if raw_name.startswith("1000") else 1.0
                clean_name = raw_name.replace("1000", "") if multiplier > 1.0 else raw_name
                
                # KEY FIX: Agar "ETH" hai toh use "ETHUSDT" se match karo
                # Ya agar "ETHUSDT" hai toh use "ETHUSDT" se match karo
                if clean_name == incoming_symbol or f"{clean_name}USDT" == incoming_symbol or incoming_symbol.startswith(clean_name):
                    final_p = float(price) * multiplier
                    updates[f"{node_key}/price"] = f"{final_p:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates)
                print(f"📡 Match Found! Updated {incoming_symbol} -> {price}")
    except Exception as e:
        print(f"⚠️ Update Error: {e}")

# --- 3. STABLE WEBSOCKET ---
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
            already_subscribed.clear()
            ws_app = websocket.WebSocketApp(
                "wss://stream.bybit.com/v5/public/linear",
                on_message=on_message,
                on_error=lambda w, e: print(f"⚠️ WS Error: {e}"),
                on_close=lambda w, c, r: print("🔌 Connection Lost.")
            )
            ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except: pass
        time.sleep(5)

# --- 4. SYNC & SUBSCRIBE ---
def sync_watchlist():
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get()
            if watchlist:
                symbols_to_sub = []
                for node_key in watchlist.keys():
                    s = node_key.split('_')[0].upper().replace("1000", "")
                    # Bybit needs USDT suffix
                    if not s.endswith("USDT"): s += "USDT"
                    symbols_to_sub.append(s)
                
                # Subscribe in batches
                new_to_add = [s for s in symbols_to_sub if s not in already_subscribed]
                if new_to_add and ws_app and ws_app.sock and ws_app.sock.connected:
                    for i in range(0, len(new_to_add), 100):
                        batch = new_to_add[i:i+100]
                        ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{b}" for b in batch]}))
                        for b in batch: already_subscribed.add(b)
                        eventlet.sleep(0.3)
            eventlet.sleep(30)
        except: eventlet.sleep(10)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    wsgi.server(eventlet.listen(('0.0.0.0', int(os.environ.get("PORT", 10000)))), application)
