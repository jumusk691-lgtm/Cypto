import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})

# ग्लोबल वेरिएबल्स: मेमोरी और परफॉरमेंस के लिए
subscribed_streams = set()   # Duplicate रोकने के लिए
last_update_time = {}       # 2-sec delay के लिए
local_watchlist_map = {}    # तेज़ मैचिंग के लिए

# --- 2. INSTANT OVERWRITE LOGIC (With 2-sec Throttle) ---
def handle_price_overwrite(binance_symbol, price):
    try:
        current_time = time.time()
        
        # LOGIC: अगर इस टोकन को अपडेट हुए 2 सेकंड नहीं हुए, तो छोड़ दो (Throttle)
        if binance_symbol in last_update_time:
            if current_time - last_update_time[binance_symbol] < 2:
                return

        p_str = "%.2f" % float(price)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        incoming_sym = binance_symbol.upper()
        
        updates = {}
        # Local map से पता चलेगा कि Firebase की किस Key को Overwrite करना है
        if incoming_sym in local_watchlist_map:
            for node_key in local_watchlist_map[incoming_sym]:
                # Overwrite Logic: 'price' और 'utime' को सीधा अपडेट करना
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now_str
        
        if updates:
            db.reference().update(updates)
            last_update_time[binance_symbol] = current_time
            # Render Logs को साफ़ (Clear) रखने के लिए सिर्फ एक ज़रूरी लाइन
            print(f"⚡ [OVERWRITE] {binance_symbol} -> {p_str} | Time: {now_str}")

    except Exception:
        pass # Logs साफ़ रखने के लिए एरर को इग्नोर करेंगे

# --- 3. SYNC & STREAM MANAGER ---
def run_forex_engine():
    global subscribed_streams, local_watchlist_map
    while True:
        try:
            # Firebase से वाचलिस्ट लाना (Screenshot के अनुसार)
            data = db.reference('forex_watchlist').get() or {}
            
            temp_map = {}
            new_tokens_found = False
            
            for k in data.keys():
                # "BTCUSDT_uid" में से सिम्बल अलग करना
                base_sym = k.split('_')[0].upper()
                
                if base_sym not in temp_map:
                    temp_map[base_sym] = []
                temp_map[base_sym].append(k)
                
                # Binance फॉर्मेट चेक (btcusdt@ticker)
                clean_name = base_sym.lower()
                if not (clean_name.endswith("usdt") or clean_name.endswith("fdusd")):
                    clean_name += "usdt"
                
                stream = f"{clean_name}@ticker"
                
                # LOGIC: एक टोकन एक ही बार सब्सक्राइब होगा
                if stream not in subscribed_streams:
                    subscribed_streams.add(stream)
                    new_tokens_found = True
            
            local_watchlist_map = temp_map

            # अगर नया सिम्बल मिला या इंजन पहली बार चला
            if new_tokens_found or not subscribed_streams:
                # Render Logs के अनुसार साफ़ कनेक्शन बनाना
                url = f"wss://stream.binance.com:9443/ws/{'/'.join(list(subscribed_streams))}"
                
                def on_msg(ws, msg):
                    d = json.loads(msg)
                    if 's' in d and 'c' in d:
                        handle_price_overwrite(d['s'], d['c'])
                
                print(f"🚀 Engine Connected: {len(subscribed_streams)} Unique Tokens Subscribed.")
                ws = websocket.WebSocketApp(url, on_message=on_msg)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            
            eventlet.sleep(10) # 10 सेकंड बाद फिर चेक करें
        except Exception:
            eventlet.sleep(5)

# --- 4. RENDER SERVER CONFIG ---
if __name__ == '__main__':
    # Render पर Logs साफ़ रखने के लिए शुरुआत में एक मैसेज
    print("🔥 Starting Forex Overwrite Engine... Logs will be cleared every 2s.")
    eventlet.spawn(run_forex_engine)
    
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"FOREX_ACTIVE"]
    
    # Render Port Binding
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
