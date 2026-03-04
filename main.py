import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
# Keys from your Delta Dashboard
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
    # Delta Exchange requires method + timestamp + path + payload
    signature_data = "GET" + timestamp + "/v2/l2update"
    return hmac.new(
        API_SECRET.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

# --- 3. LIVE UPDATE LOGIC ---
def handle_price_update(symbol, price):
    try:
        if not price: return
        p_str = "{:.2f}".format(float(price)) 
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Checking against Firebase nodes
        if symbol in node_references:
            for node_id in node_references[symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            print(f"✅ Firebase Updated: {symbol} -> {p_str}")
    except Exception as e:
        print(f"⚠️ Update Error: {e}")

# --- 4. DYNAMIC WATCHLIST SYNC ---
def sync_watchlist(ws):
    global node_references, current_subscriptions
    while True:
        try:
            # Fetch symbols from your database
            ref = db.reference('forex_watchlist')
            data = ref.get() or {}
            temp_map = {}
            new_symbols = []

            for node_id, fields in data.items():
                raw_sym = fields.get('symbol', '').upper()
                if not raw_sym: continue
                
                # Cleanup: "AMZNXUSDT_b02..." -> "AMZNXUSDT"
                clean_sym = raw_sym.split('_')[0] 

                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    if clean_sym not in current_subscriptions:
                        new_symbols.append(clean_sym)
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            # Send Subscription Message
            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 New Subscription: {new_symbols}")

            eventlet.sleep(20) 
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(5)

# --- 5. SECURE ENGINE ---
def start_engine():
    while True:
        try:
            # Correct Delta Socket URL to avoid 404
            url = "wss://socket.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                print("🌐 Engine Connected to Socket")
                # Authenticate with API Key
                ts = str(int(time.time()))
                auth_payload = {
                    "type": "auth",
                    "payload": {
                        "api-key": API_KEY,
                        "signature": get_signature(ts),
                        "timestamp": ts
                    }
                }
                ws.send(json.dumps(auth_payload))
                current_subscriptions.clear()
                eventlet.spawn(sync_watchlist, ws)

            def on_message(ws, msg):
                d = json.loads(msg)
                # Filter specifically for ticker data
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            def on_error(ws, error):
                print(f"❌ Socket Error: {error}")

            # Added User-Agent to prevent 403 Forbidden
            ws = websocket.WebSocketApp(
                url, 
                header={"User-Agent": "Mozilla/5.0"},
                on_open=on_open, 
                on_message=on_message,
                on_error=on_error
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"🔄 Engine Restarting: {e}")
            eventlet.sleep(5)

@app.route('/')
def health(): 
    return {"status": "running", "active_pairs": list(current_subscriptions)}

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    print(f"🔥 Price Engine Live on Port {port}")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
