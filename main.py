import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})
print("✅ Firebase Connected for Forex!")

# --- 2. MATCHING ENGINE (सिर्फ Forex के लिए) ---
def update_firebase(binance_symbol, price):
    try:
        p_val = float(price)
        # Forex के लिए 2 या 4 decimal places काफी हैं
        p_str = "%.2f" % p_val 
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        # 'forex_watchlist' से डेटा उठाना
        watchlist = db.reference('forex_watchlist').get()
        if not watchlist: return
        
        updates = {}
        incoming = binance_symbol.upper() # उदाहरण: "BTCUSDT"

        for node_key in watchlist.keys():
            # Check: क्या "BTCUSDT" हमारे Firebase की Key "BTCUSDT_uid" के अंदर है?
            if incoming in node_key.upper():
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            print(f"📡 [FOREX UPDATED] {binance_symbol} -> {p_str}")
    except Exception as e: 
        print(f"❌ Update Error: {e}")

# --- 3. BINANCE STREAM MANAGER ---
def run_binance():
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            raw_keys = list(watchlist.keys())
            
            if not raw_keys:
                print("⏳ Waiting for Forex symbols in Firebase...")
                eventlet.sleep(10); continue

            clean_symbols = []
            for k in raw_keys:
                # Key से सिम्बल निकालें (जैसे BTCUSDT_abc -> btcusdt)
                sym = k.split('_')[0].lower()
                
                # यहाँ हमने 'Double USDT' वाली गलती ठीक कर दी है:
                if not (sym.endswith("usdt") or sym.endswith("fdusd")):
                    sym += "usdt"
                
                clean_symbols.append(sym)

            # Unique symbols की लिस्ट बनाएँ
            streams = [f"{s}@ticker" for s in set(clean_symbols)]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                if 's' in d and 'c' in d:
                    update_firebase(d['s'], d['c'])
            
            print(f"🚀 Connecting to Binance Forex: {streams}")
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=20, ping_timeout=10)
            
        except Exception as e:
            print(f"🔄 Reconnecting: {e}"); eventlet.sleep(5)

if __name__ == '__main__':
    eventlet.spawn(run_binance)
    
    # Render.com के लिए Web Server
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"FOREX_ENGINE_RUNNING"]
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
