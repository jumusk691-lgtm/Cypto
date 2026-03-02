import eventlet
eventlet.monkey_patch()
import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH (The Final Fix) ---
firebase_config_env = os.environ.get("FIREBASE_CONFIG")

if firebase_config_env:
    try:
        # JSON load kar rahe hain
        service_account_info = json.loads(firebase_config_env)
        
        # Sabse important step: Private key ki formatting fix karna
        # Ye line 'invalid_grant' error ko khatam kar degi
        if "private_key" in service_account_info:
            original_key = service_account_info["private_key"]
            # Formatting fix for Render environment
            fixed_key = original_key.replace('\\n', '\n').strip()
            service_account_info["private_key"] = fixed_key
            
    except Exception as e:
        print(f"❌ JSON Parsing Error: {e}")
        exit(1)
else:
    print("⚠️ Error: Environment variable 'FIREBASE_CONFIG' nahi mila!")
    exit(1)

# Firebase Initialize
if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })
    print("✅ Firebase Connected Successfully!")

# --- 2. BATCH SYNC ENGINE ---
def sync_forex_batch():
    print("🚀 Binance Engine Running...")
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get()
            if watchlist:
                unique_symbols = {key.split('_')[0] for key in watchlist.keys()}
                for sym in unique_symbols:
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    if 'price' in res:
                        p_val = float(res['price'])
                        fmt_p = "{:.2f}".format(p_val) if p_val > 1 else "{:.6f}".format(p_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        updates = {}
                        for node_key in watchlist.keys():
                            if node_key.startswith(sym):
                                updates[f"{node_key}/price"] = float(fmt_p)
                                updates[f"{node_key}/utime"] = ts
                        if updates:
                            db.reference('forex_watchlist').update(updates)
                            print(f"✅ Synced {sym}: {fmt_p}")
            eventlet.sleep(1.5)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            eventlet.sleep(5)

if __name__ == '__main__':
    eventlet.spawn(sync_forex_batch)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    def app(e, r):
        r('200 OK', [('Content-Type', 'text/plain')])
        return [b"Sync Engine Live"]
    print(f"🌍 Live on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
