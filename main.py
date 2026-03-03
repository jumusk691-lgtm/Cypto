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

watchlist_data = {}

# --- 2. UPDATED MATCHING ENGINE ---
def update_firebase(binance_symbol, price):
    global watchlist_data
    try:
        p_val = float(price)
        p_str = "%.4f" % p_val # Crypto precision
        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # Binance symbol: "BTCUSDT"
        incoming = binance_symbol.upper()

        for node_key in list(watchlist_data.keys()):
            # Firebase key example: "BTCUSDT_bO2O..."
            # Hum check karenge ki kya "BTCUSDT" is key ke andar maujood hai
            if incoming in node_key.upper() or node_key.upper().startswith(incoming.replace("USDT", "")):
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        if updates:
            db.reference().update(updates)
            print(f"📡 [LIVE] {binance_symbol} -> {p_str}")
    except Exception as e: 
        print(f"❌ Update Error: {e}")

# --- 3. STREAM MANAGER ---
def run_binance():
    global watchlist_data
    while True:
        try:
            # Sync data from Firebase first
            watchlist_data = db.reference('forex_watchlist').get() or {}
            raw_keys = list(watchlist_data.keys())
            
            if not raw_keys:
                print("⏳ Waiting for symbols in forex_watchlist...")
                eventlet.sleep(10); continue

            # Create stream list: "btcusdt@ticker", "ethusdt@ticker"
            clean_symbols = []
            for k in raw_keys:
                # Key se "BTCUSDT" nikalna
                sym = k.split('_')[0].lower()
                if not sym.endswith("usdt") and not sym.endswith("fdusd"):
                    sym += "usdt"
                clean_symbols.append(sym)

            streams = [f"{s}@ticker" for s in set(clean_symbols)]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            def on_msg(ws, msg):
                d = json.loads(msg)
                if 's' in d and 'c' in d: update_firebase(d['s'], d['c'])
            
            print(f"🚀 Connecting to Binance: {len(streams)} pairs")
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=25, ping_timeout=15)
        except Exception as e:
            print(f"🔄 Reconnecting Binance: {e}"); eventlet.sleep(5)

if __name__ == '__main__':
    # Background thread for Binance
    eventlet.spawn(run_binance)
    
    # Web server for Render
    from eventlet import wsgi
    def app(env, start_res):
        start_res('200 OK', [('Content-Type', 'text/plain')])
        return [b"FOREX_ENGINE_RUNNING"]
    
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
