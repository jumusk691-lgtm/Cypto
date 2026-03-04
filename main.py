import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
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

# --- 2. LIVE UPDATE LOGIC ---
def handle_price_update(symbol, price):
    try:
        # Forex ke liye 4 ya 2 decimal (as per need)
        p_str = "{:.2f}".format(float(price)) 
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if symbol in node_references:
            for node_id in node_references[symbol]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            # Bahut saare logs se bachne ke liye sirf print karein jab price update ho
    except:
        pass

# --- 3. DYNAMIC SYMBOL PICKER ---
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
                
                # Clean Symbol Logic: "AMZNXUSDT_UID" -> "AMZNXUSDT"
                clean_sym = raw_sym.split('_')[0] 

                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    if clean_sym not in current_subscriptions:
                        new_symbols.append(clean_sym)
                
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            # Delta Exchange Subscribe
            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [{"name": "v2/ticker", "symbols": new_symbols}]
                    }
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 Subscribed to: {new_symbols}")

            eventlet.sleep(15) 
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(5)

# --- 4. WEBSOCKET ENGINE (Fixes 403 Forbidden) ---
def start_engine():
    while True:
        try:
            url = "wss://api.delta.exchange/v2/l2update" 
            
            # Browser jaisa behavior dikhane ke liye headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            def on_open(ws):
                print("🌐 Engine Connected (403 Bypass Active)")
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
                print(f"❌ WebSocket Error: {error}")

            # 'header' parameter yahan add kiya gaya hai
            ws = websocket.WebSocketApp(
                url, 
                header=headers,
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
    return {"status": "active", "active_pairs": list(current_subscriptions)}

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    print(f"🔥 Live Price Engine running on port {port}")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
