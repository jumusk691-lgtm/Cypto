import eventlet
eventlet.monkey_patch()
import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH ---
# Jo naam aapne bataya hai, wahi yahan likh raha hoon
# Render ke 'Secret Files' mein bhi EXACT yahi naam hona chahiye
KEY_FILE_NAME = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE_NAME)

def initialize_firebase():
    if os.path.exists(KEY_PATH):
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(KEY_PATH)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
                })
            print(f"✅ Firebase Connected via {KEY_FILE_NAME}!")
            return True
        except Exception as e:
            print(f"❌ Connection Error: {e}")
            return False
    else:
        print(f"❌ File Not Found! Check if filename is exactly: {KEY_FILE_NAME}")
        return False

# --- 2. SYNC ENGINE ---
def start_sync():
    if not initialize_firebase():
        return

    print("🚀 Binance Sync Engine is Running...")
    ref = db.reference('forex_watchlist')
    
    while True:
        try:
            watchlist = ref.get()
            if watchlist:
                # Unique symbols nikalna
                symbols = {k.split('_')[0] for k in watchlist.keys()}
                
                for s in symbols:
                    api_url = f"https://api.binance.com/api/v3/ticker/price?symbol={s}"
                    res = requests.get(api_url, timeout=5).json()
                    
                    if 'price' in res:
                        p_val = float(res['price'])
                        # Price formatting
                        p_str = "{:.2f}".format(p_val) if p_val > 1 else "{:.6f}".format(p_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Batch update
                        updates = {}
                        for node_key in watchlist.keys():
                            if node_key.startswith(s):
                                updates[f"{node_key}/price"] = float(p_str)
                                updates[f"{node_key}/utime"] = ts
                        
                        if updates:
                            ref.update(updates)
                            print(f"📈 Updated {s}: {p_str}")
            
            eventlet.sleep(2)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            eventlet.sleep(10)

if __name__ == '__main__':
    eventlet.spawn(start_sync)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), lambda e, r: [r('200 OK', []), b"Live"])
