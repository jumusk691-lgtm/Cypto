import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})
print("✅ Firebase Connected!")

# --- 2. IMPROVED MATCHING ENGINE ---
def update_firebase(binance_symbol, price):
    try:
        p_val = float(price)
        # Stable Precision
        p_str = "%.4f" % p_val
        now = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Fresh fetch to ensure we have latest keys from Android app
        watchlist = db.reference('forex_watchlist').get()
        if not watchlist: return
        
        updates = {}
        incoming = binance_symbol.upper() # "BTCUSDT"

        for node_key in watchlist.keys():
            # Match Logic: Agar node_key (BTCUSDT_uid) mein "BTCUSDT" hai
            if incoming in node_key.upper():
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            # Sirf logs check karne ke liye:
            print(f"📡 [MATCHED] {binance_symbol} -> {p_str}")
    except Exception as e: 
        print(f"❌ Update Error: {e}")

# --- 3. STREAM MANAGER ---
def run_binance():
    while True:
        try:
            # Refresh watchlist for streams
            watchlist = db.reference('forex_watchlist').get() or {}
            raw_keys = list(watchlist.keys())
            
            if not raw_keys:
                print("⏳ Waiting for symbols in Firebase...")
                eventlet.sleep(10); continue

            # Clean symbols for Binance URL
            clean_symbols = []
            for k in raw_keys:
                # Key se "BTCUSDT" nikalna (e.g., BTCUSDT_uid -> btcusdt)
                sym = k.split('_')[0].lower()
                if not sym.endswith("usdt") and not sym.endswith("fdusd"):
                    sym += "usdt"
                clean_symbols.append(sym)

            streams = [f"{s}@ticker" for s in set(clean_symbols)]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                # 's' is Symbol, 'c' is Close Price
                if 's' in d and 'c' in d:
                    update_firebase(d['s'], d['c'])
            
            print(f"🚀 Connecting to Binance: {streams}")
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"🔄 Reconnecting Binance: {e}"); eventlet.sleep(5)

if __name__ == '__main__':
    eventlet.spawn(run_binance)
    
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"FOREX_ENGINE_ACTIVE"]
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
