import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, hmac, hashlib, io
from firebase_admin import credentials, db
from flask import Flask, request, send_file

# --- 1. CONFIGURATION ---
# अपनी असली API Key और Secret यहाँ डालें
API_KEY = "GGJkcBos5OVsqOgKVnyGq0eUMPLB1n" 
API_SECRET = "yN23fyqfDj5MmjT9JQfn1MuMcmXkzaEjqwL2lW9At5BN7oADpcm8zoQN84Dp"
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/' #

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)

# ट्रैकिंग वेरिएबल्स
node_references = {}  
last_update_time = {}
open_prices = {} 

# --- 2. DATA CLEANING & LOGIC ---
def clean_symbol_name(name):
    """स्क्रीनशॉट में दिख रहे कचरा शब्दों को हटाता है"""
    if not name: return ""
    # 'AMXIDX' और '-1' जैसे शब्दों को हटाना
    return name.replace("AMXIDX", "").replace("-1", "").strip()

def calculate_pchange(current_price, open_price):
    try:
        if not open_price or float(open_price) == 0: return "0.00"
        change = ((float(current_price) - float(open_price)) / float(open_price)) * 100
        return "%.2f" % change
    except: return "0.00"

# --- 3. FIREBASE REALTIME UPDATE ---
def handle_price_update(symbol, price, open_p=None):
    try:
        now = time.time()
        # 2 सेकंड का थ्रॉटल (बड़े ब्रोकर्स वाला लॉजिक)
        if symbol in last_update_time and (now - last_update_time[symbol] < 2):
            return 

        p_str = "%.2f" % float(price)
        change_str = calculate_pchange(price, open_p)
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        updates = {}
        sym_upper = symbol.upper()
        if sym_upper in node_references:
            for node_id in node_references[sym_upper]:
                # Firebase स्ट्रक्चर के हिसाब से अपडेट
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/pChange"] = change_str
                updates[f"forex_watchlist/{node_id}/utime"] = time_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[symbol] = now
            print(f"⚡ {sym_upper}: {p_str} ({change_str}%)")
    except Exception as e:
        print(f"Error updating Firebase: {e}")

# --- 4. MEMORY STREAMING (FOR APP SYNC) ---
@app.route('/sync-symbols')
def sync_symbols():
    """बिना फाइल सेव किए नए सिम्बल्स स्ट्रीम करना"""
    last_id = request.args.get('last_id', 0)
    # यहाँ आप डेटाबेस से नए 125 टोकन्स फेच कर सकते हैं
    new_data = [
        {"id": 6001, "symbol": "BTCUSDT", "name": "Bitcoin", "token": "1"},
        {"id": 6002, "symbol": "ETHUSDT", "name": "Ethereum", "token": "2"}
    ]
    
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(new_data).encode())
    mem_file.seek(0)
    return send_file(mem_file, mimetype='application/json')

# --- 5. DELTA EXCHANGE WEBSOCKET ---
def start_engine():
    global node_references
    while True:
        try:
            # Firebase से वाचलिस्ट उठाना
            data = db.reference('forex_watchlist').get() or {}
            temp_map = {}
            symbols_to_subscribe = []

            for node_id, fields in data.items():
                raw_sym = fields.get('symbol', '').upper()
                if not raw_sym: continue
                
                # सिम्बल क्लीनिंग
                clean_sym = clean_symbol_name(raw_sym)
                
                if clean_sym not in temp_map:
                    temp_map[clean_sym] = []
                    symbols_to_subscribe.append(clean_sym)
                temp_map[clean_sym].append(node_id)
            
            node_references = temp_map

            # Delta Exchange WebSocket URL
            url = "wss://api.delta.exchange/v2/l2update" 
            
            def on_open(ws):
                # Delta API के हिसाब से सब्सक्राइब मैसेज
                subscribe_msg = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [{"name": "v2/ticker", "symbols": symbols_to_subscribe}]
                    }
                }
                ws.send(json.dumps(subscribe_msg))
                print(f"🚀 Subscribed to {len(symbols_to_subscribe)} symbols")

            def on_message(ws, msg):
                d = json.loads(msg)
                # Delta Ticker Message Parsing
                if d.get('type') == 'v2/ticker':
                    symbol = d.get('symbol')
                    price = d.get('mark_price') or d.get('last_price')
                    if symbol and price:
                        handle_price_update(symbol, price)

            ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=30)
            
        except Exception as e:
            print(f"WebSocket Error: {e}")
            eventlet.sleep(5)

# --- 6. RENDER SERVER ---
@app.route('/')
def health_check():
    return "BROKER_ENGINE_ACTIVE"

if __name__ == '__main__':
    print("🔥 Broker Logic Active with Data Cleaning...")
    eventlet.spawn(start_engine)
    port = int(os.environ.get("PORT", 10000))
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
