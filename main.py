import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
# Aapki provide ki hui Keys
API_KEY = "GGJkcBos5OVsqOgKVnyGq0eUMPLB1n"
API_SECRET = "yN23fyqfDj5MmjT9JQfn1MuMcmXkzaEjqwL2lW9At5BN7oADpcm8zoQN84Dp"

KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(KEY_FILE)
        firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})
    except Exception as e:
        print(f"❌ Firebase Init Error: {e}")

app = Flask(__name__)
node_references = {}  
current_subscriptions = set()

# --- 2. AUTHENTICATION HELPER ---
def get_auth_headers():
    # Delta Exchange Auth Signature Logic
    method = 'GET'
    timestamp = str(int(time.time()))
    path = '/link/v1/ticker' # WebSocket auth path
    payload = ""
    signature_data = method + timestamp + path + payload
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return {
        "api-key": API_KEY,
        "api-signature": signature,
        "api-timestamp": timestamp,
        "User-Agent": "Mozilla/5.0"
    }

# --- 3. LIVE UPDATE LOGIC ---
def handle_price_update(symbol, price):
    try:
        p_str = "{:.2f}".format(float(price)) 
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if symbol in node_references:
            for node_id in node_references[symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            print(f"✅ Updated {symbol}: {p_str}")
    except:
        pass

# --- 4. DYNAMIC SYMBOL PICKER ---
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
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 Subscribed to: {new_symbols}")

            eventlet.sleep(15) 
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(5)

# --- 5. WEBSOCKET ENGINE ---
def start_engine():
    while True:
        try:
            # Authenticated URL
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                print("🌐 Engine Connected with API Key")
                current_subscriptions.clear()
                eventlet.spawn(sync_watchlist, ws)

            def on_message(ws, msg):
                data = json.loads(msg)
                if data.get('type') == 'v2/ticker':
                    sym = data.get('symbol')
                    price = data.get('mark_price')
                    if sym and price:
                        handle_price_update(sym, price)

            def on_error(ws, error):
                print(f"❌ WS Error: {error}")

            ws = websocket.WebSocketApp(
                url, 
                header=get_auth_headers(), # Yahan key use ho rahi hai
                on_open=on_open, 
                on_message=on_message,
                on_error=on_error
            )
            ws.run_forever(ping_interval=20)
        except Exception as e:
            print(f"🔄 Restarting: {e}")
            eventlet.sleep(5)

@app.route('/')
def health(): 
    return {"status": "active", "pairs": list(current_subscriptions)}

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
