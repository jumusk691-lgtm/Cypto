import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})

# ट्रैकिंग के लिए वेरिएबल्स
subscribed_symbols = set()   # Unique symbols for Binance
last_update_time = {}       # 2-sec delay logic
node_references = {}        # Symbol to Firebase Node mapping

# --- 2. LIVE PRICE OVERWRITE LOGIC ---
def handle_price_update(binance_symbol, price):
    try:
        current_time = time.time()
        
        # 2 सेकंड का थ्रॉटल (Throttle) ताकि रेंडर लॉग्स और फायरबेस साफ़ रहे
        if binance_symbol in last_update_time:
            if current_time - last_update_time[binance_symbol] < 2:
                return

        p_str = "%.2f" % float(price)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        incoming_sym = binance_symbol.upper()
        
        updates = {}
        # अब हम सीधा सिम्बल के आधार पर मैप किए गए नोड्स को अपडेट करेंगे
        if incoming_sym in node_references:
            for node_id in node_references[incoming_sym]:
                updates[f"forex_watchlist/{node_id}/price"] = p_str
                updates[f"forex_watchlist/{node_id}/utime"] = now_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[binance_symbol] = current_time
            # साफ़ लॉग्स
            print(f"✅ {incoming_sym} Overwritten: {p_str}")

    except Exception as e:
        pass # Errors hide for clean logs

# --- 3. SYNC ENGINE (Based on 'symbol' field) ---
def start_engine():
    global subscribed_symbols, node_references
    while True:
        try:
            # 1. Firebase से डेटा उठाना
            data = db.reference('forex_watchlist').get() or {}
            
            temp_node_map = {}
            new_streams = []

            for node_id, fields in data.items():
                # UUID चेक नहीं करना, सीधा 'symbol' फील्ड उठाना है
                sym_field = fields.get('symbol')
                if not sym_field: continue
                
                sym_upper = sym_field.upper()
                
                # मैपिंग बनाना: 'BTCUSDT' -> ['BTCUSDT_uid1', 'BTCUSDT_uid2']
                if sym_upper not in temp_node_map:
                    temp_node_map[sym_upper] = []
                temp_node_map[sym_upper].append(node_id)
                
                # Binance के लिए स्ट्रीम तैयार करना
                stream_name = sym_upper.lower()
                if not (stream_name.endswith("usdt") or stream_name.endswith("fdusd")):
                    stream_name += "usdt"
                
                full_stream = f"{stream_name}@ticker"
                if full_stream not in subscribed_symbols:
                    subscribed_symbols.add(full_stream)
                    new_streams.append(full_stream)

            node_references = temp_node_map

            # 2. अगर कोई नया सिम्बल मिला, तो सॉकेट रीस्टार्ट करें
            if new_streams or not subscribed_symbols:
                all_streams = list(subscribed_symbols)
                url = f"wss://stream.binance.com:9443/ws/{'/'.join(all_streams)}"
                
                def on_msg(ws, msg):
                    d = json.loads(msg)
                    if 's' in d and 'c' in d:
                        handle_price_update(d['s'], d['c'])

                print(f"🚀 Streaming started for symbols: {list(temp_node_map.keys())}")
                ws = websocket.WebSocketApp(url, on_message=on_msg)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            
            eventlet.sleep(10) # हर 10 सेकंड में नई एंट्री चेक करें
        except Exception as e:
            eventlet.sleep(5)

# --- 4. RENDER SERVER ---
if __name__ == '__main__':
    print("🔥 SYMBOL-BASED ENGINE ACTIVE...")
    eventlet.spawn(start_engine)
    
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"ACTIVE"]
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
