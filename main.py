import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
API_KEY = "GGJkcBos5OVsqOgKVnyGq0eUMPLB1n"
API_SECRET = "yN23fyqfDj5MmjT9JQfn1MuMcmXkzaEjqwL2lW9At5BN7oADpcm8zoQN84Dp"
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_references = {}  
current_subscriptions = set()

# --- 2. AUTH SIGNATURE ---
def get_signature(timestamp):
    signature_data = "GET" + timestamp + "/v2/l2update"
    return hmac.new(API_SECRET.encode('utf-8'), signature_data.encode('utf-8'), hashlib.sha256).hexdigest()

# --- 3. LIVE UPDATE (Firebase write optimized) ---
def handle_price_update(symbol, price):
    try:
        if not price: return
        p_str = "{:.2f}".format(float(price)) 
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if symbol in node_references:
            for node_id in node_references[symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            # Sirf important updates print honge taaki logs overflow na ho
            if time.time() % 5 < 1: 
                print(f"📊 Live Sync: {symbol} @ {p_str}")
    except: pass

# --- 4. SYNC WATCHLIST (Symbol Mapping) ---
def sync_watchlist(ws):
    global node_references, current_subscriptions
    while True:
        try:
            ref = db.reference('forex_watchlist')
            data = ref.get() or {}
            temp_map = {}
            new_symbols = []

            for node_id, fields in data.items():
                raw_sym = fields.get('symbol', '').upper()
                if not raw_sym: continue
                
                # Delta Exchange ke liye symbol clean karein (e.g. BTC_USDT -> BTCUSDT)
                clean_sym = raw_sym.replace('_', '') 

                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    if clean_sym not in current_subscriptions:
                        new_symbols.append(clean_sym)
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 Subscribed to New Pairs: {new_symbols}")

            eventlet.sleep(45) 
        except: eventlet.sleep(10)

# --- 5. ENGINE (Wait for 429 Recovery) ---
def start_engine():
    # Pehla wait 5 min ka kyunki aapka API block hai
    print("⏳ Waiting for API cooldown (60s)...")
    eventlet.sleep(60) 
    
    wait_time = 15
    while True:
        try:
            url = "wss://socket.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                print("🌐 Socket Connected!")
                ts = str(int(time.time()))
                auth_payload = {
                    "type": "auth",
                    "payload": {"api-key": API_KEY, "signature": get_signature(ts), "timestamp": ts}
                }
                ws.send(json.dumps(auth_payload))
                current_subscriptions.clear()
                eventlet.spawn(sync_watchlist, ws)

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))
                elif d.get('type') == 'error':
                    print(f"❌ Delta Error: {d.get('payload')}")

            ws = websocket.WebSocketApp(
                url, 
                header={"User-Agent": "Mozilla/5.0"},
                on_open=on_open, 
                on_message=on_message
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"🔄 Reconnect Loop. Waiting {wait_time}s...")
            eventlet.sleep(wait_time)
            wait_time = min(wait_time * 2, 300)

@app.route('/')
def health(): return "LIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
