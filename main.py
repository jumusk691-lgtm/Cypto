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

# --- 2. FOREX ONLY ENGINE ---
def start_forex_sync():
    print("🚀 Forex Engine Live (Unique & Fast)...")
    
    while True:
        try:
            # Sirf forex_watchlist ko target karna
            ref = db.reference('forex_watchlist')
            data = ref.get()
            
            if not data:
                print("⚠️ No Forex symbols found. Waiting...")
                eventlet.sleep(5)
                continue

            unique_symbols = set()
            for k in data.keys():
                sym = k.split('_')[0].upper()
                unique_symbols.add(sym)

            # Alternate Route for Global Prices (Avoiding 451 Error)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            for symbol in unique_symbols:
                # Using a more stable global endpoint
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                try:
                    res = requests.get(url, timeout=3).json()
                    if 'price' in res:
                        price_val = res['price']
                        
                        # Sirf unhi nodes ko update karna jo is symbol ke hain
                        updates = {}
                        for k in data.keys():
                            if k.startswith(symbol):
                                updates[f"{k}/price"] = float(price_val)
                                updates[f"{k}/utime"] = now
                        
                        if updates:
                            ref.update(updates)
                            print(f"📈 {symbol} -> {price_val}")
                    else:
                        print(f"❌ Error for {symbol}: {res.get('msg', 'Unknown')}")
                except:
                    continue

            eventlet.sleep(1) # 1 Second Speed
            
        except Exception as e:
            print(f"⚠️ Engine Pause: {e}")
            eventlet.sleep(5)

# --- 3. WEB INTERFACE ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"FOREX ENGINE IS RUNNING."]

if __name__ == '__main__':
    eventlet.spawn(start_forex_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
