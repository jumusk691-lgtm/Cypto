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

# --- 2. FAST ENGINE (1000+ Symbols Logic) ---
def start_sync():
    print("🚀 Massive Engine Active: Handling 1000+ Unique Symbols...")
    
    while True:
        try:
            # 1. Firebase se poora data ek baar mein fetch karna
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                print("⚠️ Waiting for user to add symbols from APK...")
                eventlet.sleep(5)
                continue

            # 2. Duplicate Token Filter (Unique Symbols Only)
            # Agar 1000 nodes mein same 'BTCUSDT' hai, toh set() usey 1 bana dega
            unique_symbols = set()
            for node_key in watchlist.keys():
                symbol = node_key.split('_')[0].upper()
                unique_symbols.add(symbol)

            # 3. Batch Price Fetching (Binance se sabka price ek saath)
            # Binance 1 call mein multiple prices de sakta hai
            price_map = {}
            try:
                # Sabhi unique symbols ka current price lena
                res = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5).json()
                for item in res:
                    if item['symbol'] in unique_symbols:
                        price_map[item['symbol']] = item['price']
            except Exception as api_err:
                print(f"❌ API Error: {api_err}")

            # 4. Database Update (Har node ko price dena)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            updates = {}
            
            for node_key in watchlist.keys():
                symbol = node_key.split('_')[0].upper()
                if symbol in price_map:
                    # Batch update ke liye dictionary taiyaar karna
                    updates[f"{node_key}/price"] = float(price_map[symbol])
                    updates[f"{node_key}/utime"] = now
            
            # Ek hi baar mein saare 1000 symbols update karna
            if updates:
                ref.update(updates)
                print(f"⚡ Batch Updated {len(updates)} nodes for {len(unique_symbols)} unique symbols at {now}")

            eventlet.sleep(1) # 1 Second Speed
            
        except Exception as e:
            print(f"⚠️ Global Engine Error: {e}")
            eventlet.sleep(2)

# --- 3. RENDER SERVER ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"Massive Sync Engine is LIVE. Handling 1000+ Symbols."]

if __name__ == '__main__':
    eventlet.spawn(start_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
