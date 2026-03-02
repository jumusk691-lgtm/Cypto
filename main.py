import eventlet
eventlet.monkey_patch()
import os, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE)

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
print(f"✅ Firebase Connected!")

# --- 2. ENGINE (Isme Price Update Dikhega) ---
def start_sync():
    print("🚀 Binance Price Engine Starting...")
    ref = db.reference('forex_watchlist')
    
    while True:
        try:
            watchlist = ref.get()
            if watchlist:
                for node_key in watchlist.keys():
                    # Symbol nikalna (e.g., BTCUSDT)
                    symbol = node_key.split('_')[0]
                    
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        p_float = float(res['price'])
                        p_str = "{:.2f}".format(p_float) if p_float > 1 else "{:.6f}".format(p_float)
                        now = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Database update
                        ref.child(node_key).update({
                            "price": float(p_str),
                            "utime": now
                        })
                        # YE LINE LOGS MEIN PRICE DIKHAYEGI
                        print(f"📈 UPDATED {symbol}: {p_str} at {now}")
            
            eventlet.sleep(2)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            eventlet.sleep(5)

# --- 3. FIXING THE WEB SERVER ERROR ---
def simple_app(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"Sync Engine is Running. Check Render Logs for Prices."]

if __name__ == '__main__':
    # Engine ko background mein chalana
    eventlet.spawn(start_sync)
    
    # Web server jo error de raha tha, uska fix
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), simple_app)
