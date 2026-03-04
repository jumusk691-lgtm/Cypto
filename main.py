import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, io
from firebase_admin import credentials, db
from flask import Flask, request, send_file

# --- 1. CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

node_references = {}  
last_update_time = {}

# --- 2. LOGIC: FIREBASE REALTIME PRICE UPDATE ---
def handle_price_update(symbol, price):
    try:
        now = time.time()
        # 2-sec throttle (Broker Logic)
        if symbol in last_update_time and (now - last_update_time[symbol] < 2):
            return 

        p_str = "%.2f" % float(price)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        updates = {}
        sym_upper = symbol.upper()
        
        if sym_upper in node_references:
            for node_id in node_references[sym_upper]:
                # As per your Firebase structure
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[symbol] = now
            print(f"🔥 LIVE: {sym_upper} -> {p_str}") # Logs mein ye dikhna chahiye
    except Exception as e:
        print(f"Update Error: {e}")

# --- 3. LOGIC: ON-THE-FLY SYNC (Memory Streaming) ---
@app.route('/sync-symbols')
def sync_symbols():
    last_id = int(request.args.get('last_id', 0))
    # Add your Forex symbols here
    all_new_symbols = [{"id": 1001, "symbol": "AAPLXUSDT", "name": "Apple Crypto"}]
    filtered_data = [s for s in all_new_symbols if s['id'] > last_id]
    
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(filtered_data).encode())
    mem_file.seek(0)
    return send_file(mem_file, mimetype='application/json')

# --- 4. LOGIC: DELTA WEBSOCKET ENGINE (Subscription Fix) ---
def start_engine():
    global node_references
    while True:
        try:
            # Firebase se watchlist fetch karna
            data = db.reference('forex_watchlist').get() or {} 
            temp_map = {}
            symbols_to_subscribe = []

            for node_id, fields in data.items():
                sym = fields.get('symbol', '').upper()
                if not sym: continue
                
                if sym not in temp_map:
                    temp_map[sym] = []
                    symbols_to_subscribe.append(sym)
                temp_map[sym].append(node_id)
            
            node_references = temp_map
            
            if not symbols_to_subscribe:
                print("⚠️ No symbols found in Firebase. Waiting...")
                eventlet.sleep(10)
                continue

            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                # Correct Delta Subscription Message
                sub_msg = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [{"name": "v2/ticker", "symbols": symbols_to_subscribe}]
                    }
                }
                ws.send(json.dumps(sub_msg))
                print(f"🚀 Subscribed to: {symbols_to_subscribe}")

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
            
        except Exception as e:
            print(f"⚠️ Socket Restarting: {e}")
            eventlet.sleep(5)

# --- 5. RENDER SETUP ---
@app.route('/')
def health(): return "ACTIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
