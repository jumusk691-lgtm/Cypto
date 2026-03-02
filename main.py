import eventlet
eventlet.monkey_patch()
import os, datetime, requests, firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE)

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
print("✅ Firebase Connected!")

# --- 2. FAST ENGINE (1-Second No-Block Route) ---
def start_sync():
    print("🚀 1-Second Live Engine Active (Global Route)...")
    
    while True:
        try:
            # Firebase se symbols uthana
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                eventlet.sleep(5)
                continue

            # Unique Symbols Filter
            unique_symbols = set()
            for key in watchlist.keys():
                sym = key.split('_')[0].upper().replace("USDT", "")
                unique_symbols.add(sym)

            # CryptoCompare API (Fast & No-Block)
            sym_list = ",".join(unique_symbols)
            url = f"https://min-api.cryptocompare.com/data/pricemulti?fsyms={sym_list}&tsyms=USD"
            
            res = requests.get(url, timeout=2).json()
            now = datetime.datetime.now().strftime("%H:%M:%S")

            updates = {}
            for node_key in watchlist.keys():
                raw_sym = node_key.split('_')[0].upper().replace("USDT", "")
                
                if raw_sym in res:
                    price_val = res[raw_sym]['USD']
                    updates[f"{node_key}/price"] = float(price_val)
                    updates[f"{node_key}/utime"] = now
                    print(f"⚡ LIVE: {raw_sym} -> {price_val}")

            if updates:
                ref.update(updates)

            eventlet.sleep(1) # 1-Second Gap
            
        except Exception as e:
            print(f"⚠️ API Route Error: {e}")
            eventlet.sleep(2)

# --- 3. SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"High-Speed Engine is Live. No Proxy Key Required."]

if __name__ == '__main__':
    eventlet.spawn(start_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
