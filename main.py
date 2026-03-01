import eventlet
eventlet.monkey_patch(all=True)
import os, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
cred = credentials.Certificate("serviceAccountKey.json") 
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
})

# --- 2. FOREX & CRYPTO LIVE ENGINE ---
def sync_forex_crypto_live():
    print("🌍 Binance Forex/Crypto Engine Started...")
    while True:
        try:
            # Firebase se saare added symbols uthao
            ref = db.reference('forex_watchlist').get()
            
            if ref:
                # Unique symbols nikalo taaki double subscription na ho
                unique_symbols = set()
                for key in ref.keys():
                    symbol = key.split('_')[0]
                    unique_symbols.add(symbol)
                
                for sym in unique_symbols:
                    # Binance Public API se price fetch karna
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        new_price = float(res['price'])
                        formatted_price = "{:.2f}".format(new_price) if new_price > 1 else "{:.6f}".format(new_price)
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Sabhi users ke liye ek saath update (Batch Update)
                        updates = {}
                        for key in ref.keys():
                            if key.startswith(sym):
                                updates[f"{key}/price"] = float(formatted_price)
                                updates[f"{key}/utime"] = timestamp
                        
                        if updates:
                            db.reference('forex_watchlist').update(updates)
                            
            eventlet.sleep(1.5) # Fast update speed
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(5)

# --- 3. RENDER SERVER BINDING ---
if __name__ == '__main__':
    # Background mein sync start karo
    eventlet.spawn(sync_forex_crypto_live)
    
    # Render ko zinda rakhne ke liye web server
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    def app(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b"Forex Engine Live"]
    
    print(f"🌍 Running on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
