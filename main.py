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

# --- 2. ENGINE (Unique Subscriptions & 1s Updates) ---
def start_sync():
    print("🚀 Fast Engine Started (1-second updates)...")
    
    while True:
        try:
            # Poore database ka snapshot lena
            root_data = db.reference('/').get()
            if not root_data:
                eventlet.sleep(5)
                continue

            # Sabhi watchlist nodes ko check karna (Forex, Indian, etc.)
            watchlist_nodes = ['forex_watchlist', 'watchlist', 'indian_market'] # Apne nodes ke naam yahan add karein
            
            for node_name in watchlist_nodes:
                items = root_data.get(node_name, {})
                if not items:
                    continue

                # --- UNIQUE SUBSCRIPTION LOGIC ---
                # 'seen_symbols' set duplicate symbols ko rokega
                seen_symbols = set()
                
                for node_key, details in items.items():
                    # Symbol nikalna (e.g., BTCUSDT_abc -> BTCUSDT)
                    symbol = node_key.split('_')[0].upper()
                    
                    # Agar ye symbol is loop mein pehle hi update ho chuka hai, toh skip karo
                    if symbol in seen_symbols:
                        continue
                    
                    # Binance API for 1-second price
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                    res = requests.get(url, timeout=1).json()
                    
                    if 'price' in res:
                        price_val = float(res['price'])
                        p_str = "{:.2f}".format(price_val) if price_val > 1 else "{:.6f}".format(price_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")

                        # Database Update
                        db.reference(f'{node_name}/{node_key}').update({
                            "price": float(p_str),
                            "utime": ts
                        })
                        
                        # Is symbol ko 'seen' mark kar dena taaki dobara subscribe na ho
                        seen_symbols.add(symbol)
                        print(f"⚡ {node_name} | {symbol}: {p_str}")

            # 1-second delay for ultra-fast updates
            eventlet.sleep(1)
            
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(2)

# --- 3. WEB SERVER ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"1s Fast Engine is Running. Duplicate Filter Active."]

if __name__ == '__main__':
    eventlet.spawn(start_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
