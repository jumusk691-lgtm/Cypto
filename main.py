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
watchlist_data = {} 
ws_app = None

# --- 2. FIREBASE LISTENER ---
def start_watchlist_listener():
    global watchlist_data
    def listener(event):
        global watchlist_data
        data = db.reference('forex_watchlist').get()
        if data:
            watchlist_data = data
            sync_now()
            
    db.reference('forex_watchlist').listen(listener)

# --- 3. IMPROVED MATCHING ENGINE ---
def update_firebase(incoming_symbol, price):
    global last_price_cache, watchlist_data
    try:
        if not price: return
        p_str = str(price)
        
        # Price Change Filter: Sirf naya price aane par update karein
        if last_price_cache.get(incoming_symbol) == p_str: return 
        last_price_cache[incoming_symbol] = p_str
        
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Screenshot ke format ke mutabik: BTCUSDT_uid
        for node_key in watchlist_data.keys():
            # Extract basic symbol from Firebase key (e.g., "BTCUSDT" from "BTCUSDT_id")
            db_symbol = node_key.split('_')[0].upper()
            
            # Match condition
            if incoming_symbol == db_symbol:
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            # Log for Render console
            print(f"🚀 LIVE: {incoming_symbol} updated to {p_str}")
            
    except Exception as e:
        print(f"⚠️ Match Error: {e}")

# --- 4. BYBIT V5 HANDLER ---
def on_message(ws, message):
    try:
        msg = json.loads(message)
        # Bybit V5 structure check
        if "topic" in msg and "tickers" in msg["topic"]:
            data = msg.get("data", {})
            # List check (kabhi kabhi Bybit list bhejta hai)
            ticks = data if isinstance(data, list) else [data]
            for tick in ticks:
                s = tick.get('symbol')
                p = tick.get('lastPrice')
                if s and p:
                    update_firebase(s, p)
    except Exception as e:
        pass # Handle parse errors silently

def run_ws_engine():
    global ws_app, already_subscribed
    while True:
        try:
            print("🔗 Connecting to Bybit Public Stream...")
            already_subscribed.clear()
            ws_app = websocket.WebSocketApp(
                "wss://stream.bybit.com/v5/public/linear",
                on_message=on_message,
                on_error=lambda w, e: print(f"❌ WS Error: {e}"),
                on_close=lambda w, c, r: print("🔌 Connection Lost.")
            )
            ws_app.run_forever(ping_interval=20, ping_timeout=10)
        except: pass
        time.sleep(5)

# --- 5. SYNC LOGIC ---
def sync_now():
    global already_subscribed, ws_app, watchlist_data
    if not ws_app or not ws_app.sock or not ws_app.sock.connected: return
    
    to_sub = []
    for node_key in watchlist_data.keys():
        s = node_key.split('_')[0].upper()
        # Bybit standard format check
        if s not in already_subscribed:
            to_sub.append(s)
    
    if to_sub:
        for i in range(0, len(to_sub), 10): # Small batches of 10
            batch = to_sub[i:i+10]
            ws_app.send(json.dumps({"op": "subscribe", "args": [f"tickers.{x}" for x in batch]}))
            for x in batch: already_subscribed.add(x)
            print(f"✅ Subscribed to: {batch}")

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"ENGINE_STATUS_RUNNING"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_watchlist_listener)
    eventlet.spawn(run_ws_engine)
    
    port = int(os.environ.get("PORT", 10000))
    print(f"💻 Server starting on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
