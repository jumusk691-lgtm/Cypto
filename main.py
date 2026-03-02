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

# --- 2. IMPROVED MATCHING LOGIC ---
def update_firebase(incoming_symbol, price):
    global last_price_cache
    try:
        if not price or float(price) <= 0: return
        p_str = str(price)
        if last_price_cache.get(incoming_symbol) == p_str: return 
        
        last_price_cache[incoming_symbol] = p_str
        now = datetime.datetime.now().strftime("%H:%M:%S")
        ref = db.reference('forex_watchlist')
        all_nodes = ref.get()
        
        if all_nodes:
            updates = {}
            for node_key, data in all_nodes.items():
                # Extract clean symbol from Firebase (ETHUSDT_uid -> ETHUSDT)
                raw_name = node_key.split('_')[0].upper()
                
                # Multiplier Support
                multiplier = 1000.0 if raw_name.startswith("1000") else 1.0
                clean_name = raw_name.replace("1000", "")
                
                # MATCHING: ETH vs ETHUSDT or XAU vs XAUUSDT
                # Bybit sends: ETHUSDT. We check if ETH is in ETHUSDT.
                if clean_name == incoming_symbol or f"{clean_name}USDT" == incoming_symbol or incoming_symbol.startswith(clean_name):
                    final_p = float(price) * multiplier
                    updates[f"{node_key}/price"] = f"{final_p:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
            
            if updates:
                ref.update(updates)
                print(f"📡 Updated: {incoming_symbol} -> {price}")
    except Exception as e:
        print(f"⚠️ Logic Error: {e}")

# --- 3. STABLE WEBSOCKET HANDLERS ---
def on_message(ws, message):
    try:
        msg = json.loads(message)
        # Bybit V5 structure: msg['data'] contains 'symbol' and 'lastPrice'
        if 'data' in msg:
            data = msg['data']
            # Sometimes data is a list, sometimes a dict
            if isinstance(data, list):
                for item in data:
                    s, p = item.get('symbol'), item.get('lastPrice')
                    if s and p: update_firebase(s, p)
            else:
                s, p = data.get('symbol'), data.get('lastPrice')
                if s and p: update_firebase(s, p)
    except: pass

def run_ws_engine():
    global ws_app, already_subscribed
    while True:
        try:
            print("🚀 Engine Restarting...")
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

# --- 4. SYNC WATCHLIST ---
def sync_watchlist():
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get()
            if watchlist and ws_app and ws_app.sock and ws_app.sock.connected:
                symbols_to_sub = []
                for node_key in watchlist.keys():
                    s = node_key.split('_')[0].upper().replace("1000", "")
                    if not s.endswith("USDT") and s not in ["BTCUSDT", "ETHUSDT"]: 
                        s += "USDT"
                    if s not in already_subscribed:
                        symbols_to_sub.append(s)
                
                if symbols_to_sub:
                    # Subscribe to tickers topic
                    sub_msg = {"op": "subscribe", "args": [f"tickers.{sym}" for sym in symbols_to_sub]}
                    ws_app.send(json.dumps(sub_msg))
                    for sym in symbols_to_sub: already_subscribed.add(sym)
                    print(f"✅ Subscribed to: {symbols_to_sub}")
            eventlet.sleep(20)
        except: eventlet.sleep(10)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"STABLE"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(run_ws_engine)
    eventlet.spawn(sync_watchlist)
    wsgi.server(eventlet.listen(('0.0.0.0', int(os.environ.get("PORT", 10000)))), application)
