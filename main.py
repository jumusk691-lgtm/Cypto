import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db
from flask import Flask

# --- CONFIGURATION ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

node_references = {}  
current_subscriptions = set()

# --- PRICE UPDATE LOGIC ---
def handle_price_update(symbol, price):
    try:
        p_str = "%.4f" % float(price)
        updates = {}
        if symbol in node_references:
            for node_id in node_references[symbol]:
                # Sirf Price aur Time update
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
        
        if updates:
            db.reference().update(updates)
            print(f"⚡ LIVE: {symbol} -> {p_str}")
    except: pass

# --- DYNAMIC SCANNER (Every 2 Sec) ---
def sync_db_with_ws(ws):
    global node_references, current_subscriptions
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            new_to_subscribe = []

            for node_id, fields in data.items():
                # Logic: Database se 'symbol' field uthana
                raw_sym = fields.get('symbol', '').upper()
                if not raw_sym: continue
                
                if raw_sym not in temp_map:
                    temp_map[raw_sym] = []
                    if raw_sym not in current_subscriptions:
                        new_to_subscribe.append(raw_sym)
                temp_map[raw_sym].append(node_id)
            
            node_references = temp_map

            # Naye symbols subscribe karna
            if new_to_subscribe and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_to_subscribe}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_to_subscribe)
                print(f"🆕 Subscribed New: {new_to_subscribe}")

            eventlet.sleep(2)
        except Exception as e:
            print(f"Scanner Error: {e}")
            eventlet.sleep(5)

# --- WEBSOCKET ENGINE ---
def start_engine():
    while True:
        try:
            url = "wss://api.delta.exchange/v2/l2update" 
            def on_open(ws):
                print("🌐 WebSocket Connected")
                current_subscriptions.clear()
                eventlet.spawn(sync_db_with_ws, ws)

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
        except: eventlet.sleep(5)

@app.route('/')
def health(): return "RUNNING"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
