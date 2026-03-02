import eventlet
eventlet.monkey_patch()
import os, datetime, requests, firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE)

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
print("✅ Firebase Connected!")

# --- 2. THE ENGINE (With Proxy Logic) ---
def start_forex_sync():
    print("🚀 Forex Engine Live with Proxy Support...")
    
    # Binance Global Proxies taaki restricted location bypass ho sake
    proxied_urls = [
        "https://api.binance.com/api/v3/ticker/price",
        "https://api1.binance.com/api/v3/ticker/price",
        "https://api-gcp.binance.com/api/v3/ticker/price" # Google Cloud Route
    ]

    while True:
        try:
            ref = db.reference('forex_watchlist')
            data = ref.get()
            
            if not data:
                eventlet.sleep(5)
                continue

            # Unique symbols ki list
            unique_symbols = {k.split('_')[0].upper() for k in data.keys()}
            now = datetime.datetime.now().strftime("%H:%M:%S")

            for symbol in unique_symbols:
                success = False
                # Har symbol ke liye proxy routes try karna
                for url in proxied_urls:
                    try:
                        # Hum Binance ko bol rahe hain hum global route se aa rahe hain
                        res = requests.get(f"{url}?symbol={symbol}", timeout=3).json()
                        
                        if 'price' in res:
                            price_val = float(res['price'])
                            
                            # Batch updates for this symbol
                            updates = {}
                            for k, v in data.items():
                                if k.startswith(symbol):
                                    updates[f"{k}/price"] = price_val
                                    updates[f"{k}/utime"] = now
                            
                            if updates:
                                ref.update(updates)
                                print(f"📈 PROXY SUCCESS: {symbol} -> {price_val}")
                            
                            success = True
                            break
                    except:
                        continue
                
                if not success:
                    print(f"❌ Still Blocked for {symbol}. Try later.")

            eventlet.sleep(1) # Fast sync
            
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            eventlet.sleep(5)

# --- 3. SERVER ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"Forex Engine Running with Proxy Tunnel."]

if __name__ == '__main__':
    eventlet.spawn(start_forex_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
