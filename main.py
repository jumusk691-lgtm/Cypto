import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})

# ट्रैकिंग के लिए ग्लोबल वेरिएबल्स
subscribed_streams = set()
last_update_time = {}
local_watchlist_map = {}

# --- 2. MATCHING & OVERWRITE LOGIC (2 SEC DELAY) ---
def handle_instant_update(binance_symbol, price):
    try:
        current_time = time.time()
        
        # 2 सेकंड का गैप चेक करें (Duplicate avoid and throttle)
        if binance_symbol in last_update_time:
            if current_time - last_update_time[binance_symbol] < 2:
                return

        p_str = "%.2f" % float(price)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        incoming_sym = binance_symbol.upper()
        
        updates = {}
        # केवल तभी अपडेट करें जब सिम्बल हमारे लोकल मैप में हो
        if incoming_sym in local_watchlist_map:
            for node_key in local_watchlist_map[incoming_sym]:
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now_str
        
        if updates:
            db.reference().update(updates) # Firebase Overwrite
            last_update_time[binance_symbol] = current_time
            # साफ़ सुथरे लॉग्स
            print(f"⚡ [UPDATE] {binance_symbol} -> {p_str} | Logs Cleared")

    except Exception:
        pass # लॉग्स साफ़ रखने के लिए

# --- 3. BINANCE SYNC & STREAM MANAGER ---
def run_forex_engine():
    global subscribed_streams, local_watchlist_map
    while True:
        try:
            # Firebase से watchlist लाना
            data = db.reference('forex_watchlist').get() or {}
            
            temp_map = {}
            new_streams_found = False
            
            for k in data.keys():
                # "BTCUSDT_b02Oy..." -> "BTCUSDT"
                base_sym = k.split('_')[0].upper()
                
                if base_sym not in temp_map:
                    temp_map[base_sym] = []
                temp_map[base_sym].append(k)
                
                # Binance फॉर्मेट चेक (btcusdt@ticker)
                clean_name = base_sym.lower()
                if not (clean_name.endswith("usdt") or clean_name.endswith("fdusd")):
                    clean_name += "usdt"
                
                stream = f"{clean_name}@ticker"
                if stream not in subscribed_streams:
                    subscribed_streams.add(stream)
                    new_streams_found = True
            
            local_watchlist_map = temp_map

            # अगर नया टोकन है या कनेक्शन नहीं है तो नया Socket खोलें
            if new_streams_found or not subscribed_streams:
                url = f"wss://stream.binance.com:9443/ws/{'/'.join(list(subscribed_streams))}"
                
                def on_msg(ws, msg):
                    d = json.loads(msg)
                    if 's' in d and 'c' in d:
                        handle_instant_update(d['s'], d['c'])
                
                print(f"🚀 Engine Connected for {len(subscribed_streams)} tokens.")
                ws = websocket.WebSocketApp(url, on_message=on_msg)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            
            eventlet.sleep(10) # हर 10 सेकंड में नई वाचलिस्ट चेक करें
        except Exception as e:
            eventlet.sleep(5)

# --- 4. RENDER SERVER ---
if __name__ == '__main__':
    print("🔥 Starting Forex Overwrite Engine...")
    eventlet.spawn(run_forex_engine)
    
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"FOREX_ACTIVE"]
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
