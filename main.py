import eventlet
eventlet.monkey_patch()
import os
import datetime
import requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
# Dhyaan rakhein ki serviceAccountKey.json aapke folder mein ho
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
})

# --- 2. BATCH SYNC ENGINE (CRYPTO/FOREX) ---
def sync_forex_batch():
    print("🚀 Binance Forex/Crypto Batch Engine Started...")
    print("✅ Mode: No Double Subscription | Multi-User Live")
    
    while True:
        try:
            # Step A: Firebase se puri watchlist ek baar mein uthao
            all_data = db.reference('forex_watchlist').get()
            
            if all_data:
                # Step B: Unique symbols nikalna (Taaki Binance ko ek hi request jaye)
                # Agar 100 users ne BTCUSDT dala hai, toh set() use sirf ek baar count karega
                unique_symbols = {key.split('_')[0] for key in all_data.keys()}
                
                for sym in unique_symbols:
                    # Step C: Binance Public API se price fetch karna
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        raw_price = float(res['price'])
                        # Price formatting (Badi price ke liye 2 decimal, choti ke liye 6)
                        formatted_price = "{:.2f}".format(raw_price) if raw_price > 1 else "{:.6f}".format(raw_price)
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Step D: Batch Update Dictionary taiyar karna
                        # Is ek price ko un sabhi users ke nodes mein map karo jinhone ye symbol add kiya hai
                        batch_updates = {}
                        for node_key in all_data.keys():
                            if node_key.startswith(sym):
                                batch_updates[f"{node_key}/price"] = float(formatted_price)
                                batch_updates[f"{node_key}/utime"] = timestamp
                        
                        # Step E: Ek single call mein Firebase update (Fastest Way)
                        if batch_updates:
                            db.reference('forex_watchlist').update(batch_updates)
            
            # Har 1.5 second mein loop chalega real-time feel ke liye
            eventlet.sleep(1.5)
            
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(5)

# --- 3. RENDER WEB SERVER BINDING ---
if __name__ == '__main__':
    # Engine ko background thread mein start karein
    eventlet.spawn(sync_forex_batch)
    
    # Render Dashboard par 'Live' status dikhane ke liye mini server
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    
    def render_health_check(env, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b"Forex/Crypto Engine is Live and Syncing!"]
    
    print(f"🌍 Server binding on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), render_health_check)
