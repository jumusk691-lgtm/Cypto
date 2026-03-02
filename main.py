import eventlet
eventlet.monkey_patch()
import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH (Direct File Method) ---
# Hum Render ki Secret File read kar rahe hain
KEY_PATH = "/etc/secrets/serviceAccountKey.json"

if os.path.exists(KEY_PATH):
    if not firebase_admin._apps:
        cred = credentials.Certificate(KEY_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
        })
    print("✅ Firebase Connected via Secret File!")
else:
    print("❌ Error: Secret File not found at /etc/secrets/serviceAccountKey.json")
    exit(1)

# --- 2. BATCH SYNC ENGINE ---
def sync_forex_batch():
    print("🚀 Binance Engine Running...")
    ref = db.reference('forex_watchlist')
    while True:
        try:
            watchlist = ref.get()
            if watchlist:
                # Unique symbols nikalna
                unique_symbols = {key.split('_')[0] for key in watchlist.keys()}
                
                for sym in unique_symbols:
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        p_val = float(res['price'])
                        fmt_p = "{:.2f}".format(p_val) if p_val > 1 else "{:.6f}".format(p_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Batch update har user ke liye
                        updates = {}
                        for node_key in watchlist.keys():
                            if node_key.startswith(sym):
                                updates[f"{node_key}/price"] = float(fmt_p)
                                updates[f"{node_key}/utime"] = ts
                        
                        if updates:
                            ref.update(updates)
                            print(f"📈 {sym} Updated: {fmt_p}")
            
            eventlet.sleep(2)
        except Exception as e:
            print(f"⚠️ Sync Error: {e}")
            eventlet.sleep(10)

if __name__ == '__main__':
    eventlet.spawn(sync_forex_batch)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), lambda e, r: [r('200 OK', []), b"Engine Live"])
