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

# --- 2. LIVE UPDATE LOGIC (Updates back to forex_watchlist) ---
def handle_price_update(symbol, price):
    try:
        p_str = "%.4f" % float(price)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        if symbol in node_references:
            for node_id in node_references[symbol]:
                # सिर्फ forex_watchlist के अंदर अपडेट
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            print(f"✅ UPDATED: {symbol} -> {p_str}")
    except: pass

# --- 3. DYNAMIC SYMBOL PICKER (From forex_watchlist) ---
def sync_watchlist(ws):
    global node_references, current_subscriptions
    while True:
        try:
            # स्टेप: सिर्फ forex_watchlist नोड को पढ़ना
            ref = db.reference('forex_watchlist')
            data = ref.get() or {}
            
            temp_map = {}
            new_symbols = []

            for node_id, fields in data.items():
                # डेटाबेस से 'symbol' फील्ड उठाना
                sym = fields.get('symbol', '').upper()
                if not sym: continue
                
                # 'GOLDM' या 'MCX' जैसे सिम्बल्स को इग्नोर करना (Delta उन्हें सपोर्ट नहीं करता)
                if "FUT" in sym or "MCX" in fields.get('exch_seg', ''):
                    continue

                if sym not in temp_map:
                    temp_map[sym] = []
                    if sym not in current_subscriptions:
                        new_symbols.append(sym)
                temp_map[sym].append(node_id)
            
            node_references = temp_map

            # नए सिम्बल्स को लाइव सब्सक्राइब करना
            if new_symbols and ws.sock and ws.sock.connected:
                sub_msg = {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": "v2/ticker", "symbols": new_symbols}]}
                }
                ws.send(json.dumps(sub_msg))
                current_subscriptions.update(new_symbols)
                print(f"🚀 Subscribed to New Forex: {new_symbols}")

            eventlet.sleep(2) # हर 2 सेकंड में चेक करेगा कि कोई नया सिम्बल तो नहीं आया
        except Exception as e:
            print(f"Sync Error: {e}")
            eventlet.sleep(5)

# --- 4. WEBSOCKET ENGINE ---
def start_engine():
    while True:
        try:
            url = "wss://api.delta.exchange/v2/l2update" 
            def on_open(ws):
                print("🌐 Engine Connected to Delta")
                current_subscriptions.clear()
                eventlet.spawn(sync_watchlist, ws)

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
        except: eventlet.sleep(5)

@app.route('/')
def health(): return "FOREX_LIVE_ENGINE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
