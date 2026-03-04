import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib, io
from firebase_admin import credentials, db
from flask import Flask, request, send_file

# --- 1. CONFIGURATION ---
API_KEY = "GGJkcBos5OVsqOgKVnyGq0eUMPLB1n"
API_SECRET = "yN23fyqfDj5MmjT9JQfn1MuMcmXkzaEjqwL2lW9At5BN7oADpcm8zoQN84Dp"
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

# थ्रॉटलिंग के लिए वेरिएबल्स
node_references = {}  
last_update_time = {}

# --- 2. LOGIC: LIVE PRICE UPDATE ---
def handle_price_update(symbol, price):
    try:
        now = time.time()
        # बड़े ब्रोकर्स वाला 2-सेकंड थ्रॉटल लॉजिक
        if symbol in last_update_time and (now - last_update_time[symbol] < 2):
            return 

        p_str = "%.2f" % float(price)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        updates = {}
        sym_upper = symbol.upper()
        
        # Batch Update Logic: एक साथ कई नोड्स अपडेट करना
        if sym_upper in node_references:
            for node_id in node_references[sym_upper]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[symbol] = now
            print(f"✅ UPDATED: {sym_upper} -> {p_str}")
    except Exception as e:
        print(f"❌ Error: {e}")

# --- 3. LOGIC: ON-THE-FLY MEMORY STREAMING ---
@app.route('/sync-symbols')
def sync_symbols():
    """
    बिना फाइल सेव किए नए Forex सिम्बल्स स्ट्रीम करना।
    User की ऐप यहाँ से चुपचाप नया डेटा 'खिंचेगी'।
    """
    last_id = int(request.args.get('last_id', 0))
    
    # यहाँ आप अपने नए 125+ Forex सिम्बल्स की लिस्ट रखेंगे
    all_new_symbols = [
        {"id": 1001, "symbol": "EURUSD", "name": "Euro / US Dollar", "token": "fx_101"},
        {"id": 1002, "symbol": "GBPUSD", "name": "British Pound", "token": "fx_102"},
        # ... बाकी सिम्बल्स यहाँ आएंगे
    ]
    
    # सिर्फ वो सिम्बल्स जो यूजर के पास नहीं हैं
    filtered_data = [s for s in all_new_symbols if s['id'] > last_id]
    
    # No-Storage Logic: RAM से सीधे डेटा भेजना
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(filtered_data).encode())
    mem_file.seek(0)
    
    return send_file(mem_file, mimetype='application/json')

# --- 4. LOGIC: DELTA WEBSOCKET ENGINE ---
def start_engine():
    global node_references
    while True:
        try:
            # Firebase से वाचलिस्ट सिंक करना
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
            
            # Delta Exchange WebSocket URL
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                # Delta API Ticker Subscription
                sub_msg = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [{"name": "v2/ticker", "symbols": symbols_to_subscribe}]
                    }
                }
                ws.send(json.dumps(sub_msg))

            def on_message(ws, msg):
                d = json.loads(msg)
                if d.get('type') == 'v2/ticker':
                    handle_price_update(d.get('symbol'), d.get('mark_price'))

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
            
        except Exception as e:
            print(f"⚠️ Reconnecting... {e}")
            eventlet.sleep(5)

# --- 5. RENDER SERVER CONFIG ---
@app.route('/')
def health(): return "FOREX_ENGINE_ACTIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
