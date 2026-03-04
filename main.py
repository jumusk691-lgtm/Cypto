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
    # Delta requires: Method + Timestamp + Path
    signature_data = "GET" + timestamp + "/v2/l2update"
    return hmac.new(API_SECRET.encode('utf-8'), signature_data.encode('utf-8'), hashlib.sha256).hexdigest()

# --- 3. LIVE UPDATE ---
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
    except: pass

# --- 4. SYNC WATCHLIST (Throttled) ---
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
                clean_sym = raw_sym.split('_')[0] 
                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    if clean_sym not in current_subscriptions:
                        new_symbols.append(clean_sym)
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            if new_symbols and ws.sock and ws.sock.connected:
                # Delta Exchange rate limit se bachne ke liye symbols ko batches mein bhejenge
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 Subscribed to: {new_symbols}")

            eventlet.sleep(30) # Firebase sync interval badha diya hai
        except: eventlet.sleep(10)

# --- 5. ENGINE (Exponential Backoff Fix) ---
def start_engine():
    retry_delay = 5 # Starting delay 5 seconds
    while True:
        try:
            url = "wss://socket.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                nonlocal retry_delay
                retry_delay = 5 # Reset delay on success
                print("🌐 Socket Open & Authenticating...")
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
                elif "error" in d:
                    print(f"⚠️ API Error: {d['error']}")

            ws = websocket.WebSocketApp(
                url, 
                header={"User-Agent": "Mozilla/5.0"},
                on_open=on_open, 
                on_message=on_message
            )
            ws.run_forever(ping_interval=30, ping_timeout=15)
        except Exception as e:
            print(f"🔄 Rate Limit/Connection Error. Waiting {retry_delay}s...")
            eventlet.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60) # Har baar wait time double karega (max 60s)

@app.route('/')
def health(): return {"status": "running", "pairs": list(current_subscriptions)}

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
