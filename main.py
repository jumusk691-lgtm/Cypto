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

# --- 2. THE ENGINE (Handles 1000+ Symbols & Errors) ---
def start_sync():
    print("🚀 Massive Engine Active: Optimizing for 1000+ Unique Symbols...")
    
    while True:
        try:
            # 1. Firebase Scan (Donon watchlists)
            updates = {}
            now = datetime.datetime.now().strftime("%H:%M:%S")
            unique_symbols = set()
            
            # Hum saara data ek saath fetch karte hain taaki speed mile
            db_root = db.reference('/').get()
            if not db_root:
                eventlet.sleep(5)
                continue

            # Nodes jahan symbols ho sakte hain
            target_nodes = ['forex_watchlist']
            
            # Sabhi unique symbols ki list banana
            for node in target_nodes:
                data = db_root.get(node, {})
                for key in data.keys():
                    sym = key.split('_')[0].upper()
                    unique_symbols.add(sym)

            if not unique_symbols:
                eventlet.sleep(5)
                continue

            # 2. Binance API - Har symbol ka price ek saath (Batch)
            try:
                res = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
                if res.status_code == 200:
                    prices = res.json()
                    # Check if prices is a list (Expected Binance format)
                    if isinstance(prices, list):
                        price_map = {item['symbol']: item['price'] for item in prices if item['symbol'] in unique_symbols}
                        
                        # 3. Update Map Taiyaar Karna
                        for node in target_nodes:
                            node_data = db_root.get(node, {})
                            for key in node_data.keys():
                                sym = key.split('_')[0].upper()
                                if sym in price_map:
                                    updates[f"{node}/{key}/price"] = float(price_map[sym])
                                    updates[f"{node}/{key}/utime"] = now
                        
                        # 4. Multi-Path Update (Single Shot for 1000 nodes)
                        if updates:
                            db.reference('/').update(updates)
                            print(f"⚡ {len(updates)} nodes updated at {now} (Unique: {len(unique_symbols)})")
                    else:
                        print("⚠️ Binance sent unexpected response format.")
                else:
                    print(f"⚠️ Binance API Down. Status: {res.status_code}")
            except Exception as api_e:
                print(f"❌ API Loop Error: {api_e}")

            eventlet.sleep(1) # 1 Second update frequency
            
        except Exception as e:
            print(f"⚠️ Global Engine Error: {e}")
            eventlet.sleep(5)

# --- 3. RENDER SERVER ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"Massive Sync Engine is RUNNING. Security & Scaling Active."]

if __name__ == '__main__':
    eventlet.spawn(start_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
