import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib, io
from firebase_admin import credentials, db
from flask import Flask, request, send_file

# --- 1. CONFIGURATION ---
API_KEY = "YOUR_DELTA_API_KEY"
API_SECRET = "YOUR_DELTA_API_SECRET"
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

# ट्रैकिंग वेरिएबल्स
node_references = {}  
last_update_time = {}
open_prices = {} # 24h Open price store karne ke liye

# --- 2. DELTA AUTH & PCHANGE LOGIC ---
def get_delta_signature(method, timestamp, path, query="", body=""):
    payload = method + timestamp + path + query + body
    return hmac.new(API_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()

def calculate_pchange(current_price, open_price):
    try:
        if not open_price or float(open_price) == 0: return "0.00"
        change = ((float(current_price) - float(open_price)) / float(open_price)) * 100
        return "%.2f" % change
    except: return "0.00"

# --- 3. LIVE PRICE & BATCH UPDATE ---
def handle_price_update(symbol, price, open_p=None):
    try:
        now = time.time()
        if symbol in last_update_time and (now - last_update_time[symbol] < 2):
            return # 2-sec throttle like big brokers

        p_str = "%.2f" % float(price)
        change_str = calculate_pchange(price, open_p)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        updates = {}
        sym_upper = symbol.upper()
        if sym_upper in node_references:
            for node_id in node_references[sym_upper]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/pChange"] = change_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[symbol] = now
    except: pass

# --- 4. MEMORY STREAMING (NO FILE ON RENDER) ---
@app.route('/sync-symbols')
def sync_symbols():
    """
    User ka phone yaha se naya data 'khinchega'. 
    Render par koi file save nahi hogi, sab RAM se stream hoga.
    """
    last_id = request.args.get('last_id', 0)
    # EXAMPLE DATA: Reality me aap ise database se fetch karenge
    new_data = [
        {"id": 5001, "symbol": "PEPEUSDT", "name": "Pepe", "token": "999"},
        {"id": 5002, "symbol": "FLOKIUSDT", "name": "Floki", "token": "888"}
    ]
    
    # Bytes me convert karke stream karna
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(new_data).encode())
    mem_file.seek(0)
    
    return send_file(mem_file, mimetype='application/json', download_name='update.json')

# --- 5. WEBSOCKET ENGINE ---
def start_engine():
    global node_references, open_prices
    while True:
        try:
            data = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            symbols_to_subscribe = []

            for node_id, fields in data.items():
                sym = fields.get('symbol', '').upper()
                if not sym: continue
                
                if sym not in temp_map:
                    temp_map[sym] = []
                    symbols_to_subscribe.append(sym.lower())
                temp_map[sym].append(node_id)
            
            node_references = temp_map

            # Delta Exchange WebSocket URL (Example)
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                # Delta API structure ke hisab se parse karein
                if 'symbol' in d and 'price' in d:
                    handle_price_update(d['symbol'], d['price'], open_prices.get(d['symbol']))

            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=30)
            
            eventlet.sleep(10)
        except:
            eventlet.sleep(5)

# --- 6. RENDER SERVER START ---
@app.route('/')
def health_check():
    return "BROKER_ENGINE_ACTIVE"

if __name__ == '__main__':
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    # Flask app as Render Server
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
