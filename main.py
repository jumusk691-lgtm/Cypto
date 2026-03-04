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
current_subscriptions = set() # ट्रैक करने के लिए कि अभी क्या सब्सक्राइब है

# --- 2. LOGIC: PURE PRICE UPDATE (Per Second) ---
def handle_price_update(symbol, price):
    try:
        now = time.time()
        # थ्रॉटल को 0.8s किया है ताकि हर सेकंड डेटाबेस अपडेट हो सके
        if symbol in last_update_time and (now - last_update_time[symbol] < 0.8):
            return 

        p_str = "%.4f" % float(price)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        updates = {}
        sym_upper = symbol.upper()
        
        if sym_upper in node_references:
            for node_id in node_references[sym_upper]:
                # पाथ मैचिंग लॉजिक
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[symbol] = now
            print(f"⚡ SEC-SYNC: {sym_upper} -> {p_str}") 
    except: pass

# --- 3. LOGIC: DYNAMIC SYMBOL SCANNER (Runs every 2 seconds) ---
def sync_db_with_ws(ws):
    global node_references, current_subscriptions
    while True:
        try:
            # डेटाबेस से लाइव सिम्बल्स उठाना
            data = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            new_symbols = []

            for node_id, fields in data.items():
                sym = fields.get('symbol', '').upper()
                if not sym: continue
                
                if sym not in temp_map:
                    temp_map[sym] = []
                    # अगर नया सिम्बल आया है तो लिस्ट में जोड़ो
                    if sym not in current_subscriptions:
                        new_symbols.append(sym)
                temp_map[sym].append(node_id)
            
            node_references = temp_map

            # अगर नए सिम्बल्स मिले हैं, तो बिना कनेक्शन काटे सब्सक्राइब करो
            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🆕 NEW SYMBOLS ADDED: {new_symbols}")

            eventlet.sleep(2) # हर 2 सेकंड में DB चेक करेगा
        except Exception as e:
            print(f"Scanner Error: {e}")
            eventlet.sleep(5)

# --- 4. LOGIC: WEBSOCKET ENGINE ---
def start_engine():
    global current_subscriptions
    while True:
        try:
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                print("🌐 WebSocket Connected")
                current_subscriptions.clear()
                # स्कैनर को शुरू करो जो हर सेकंड DB चेक करेगा
                eventlet.spawn(sync_db_with_ws, ws)

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
            
        except:
            eventlet.sleep(5)

@app.route('/')
def health(): return "DYNAMIC_ENGINE_ACTIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
