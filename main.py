import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_references = {}  
current_subscriptions = set()

# --- 2. LIVE UPDATE LOGIC ---
def handle_price_update(symbol, price):
    try:
        p_str = "{:.2f}".format(float(price)) # Forex/Crypto ke liye 2 decimal kaafi hain
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if symbol in node_references:
            for node_id in node_references[symbol]:
                # Aapke exact Firebase paths ko update kar raha hai
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            print(f"✅ Price Sync: {symbol} -> {p_str}")
    except Exception as e:
        print(f"Update Error: {e}")

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
                # Step 1: Symbol uthao (e.g., "AMZNXUSDT_b02Oy...")
                raw_sym = fields.get('symbol', '').upper()
                if not raw_sym: continue
                
                # Step 2: Clean Symbol (Sirf "_" se pehle ka part)
                # Taaki "AMZNXUSDT_b02..." ban jaye "AMZNXUSDT"
                clean_sym = raw_sym.split('_')[0] 

                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    if clean_sym not in current_subscriptions:
                        new_symbols.append(clean_sym)
                
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            # Step 3: Delta Exchange ko subscribe message bhejna
            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [
                            {
                                "name": "v2/ticker", 
                                "symbols": new_symbols
                            }
                        ]
                    }
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 New Subscriptions: {new_symbols}")

            eventlet.sleep(10) # 10 second wait agle sync se pehle
        except Exception as e:
            print(f"Sync Watchlist Error: {e}")
            eventlet.sleep(5)

# --- 4. WEBSOCKET ENGINE ---
def start_engine():
    while True:
        try:
            # Public Ticker URL
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                print("🌐 Connected to Delta Exchange")
                current_subscriptions.clear()
                # Watchlist sync shuru karein
                eventlet.spawn(sync_watchlist, ws)

            def on_message(ws, msg):
                data = json.loads(msg)
                # Delta ticker data format check
                if data.get('type') == 'v2/ticker':
                    sym = data.get('symbol')
                    price = data.get('mark_price')
                    if sym and price:
                        handle_price_update(sym, price)

            def on_error(ws, error):
                print(f"WS Error: {error}")

            ws = websocket.WebSocketApp(
                url, 
                on_open=on_open, 
                on_message=on_message,
                on_error=on_error
            )
            ws.run_forever(ping_interval=30)
        except Exception as e:
            print(f"Engine Restarting: {e}")
            eventlet.sleep(5)

@app.route('/')
def health(): 
    return {"status": "running", "subscriptions": list(current_subscriptions)}

if __name__ == '__main__':
    # Engine ko background mein chalayein
    eventlet.spawn(start_engine)
    
    # Flask port setup for Render
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    print(f"🔥 Server starting on port {port}")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
