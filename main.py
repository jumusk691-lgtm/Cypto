import eventlet
eventlet.monkey_patch()
import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- 1. FIREBASE AUTH (Render Env se uthayega) ---
firebase_config_env = os.environ.get("FIREBASE_CONFIG")

if firebase_config_env:
    try:
        # Render variables se JSON load karega
        service_account_info = json.loads(firebase_config_env)
        
        # IMPORTANT: Private key ki formatting fix (JWT errors se bachne ke liye)
        if "private_key" in service_account_info:
            service_account_info["private_key"] = service_account_info["private_key"].replace('\\n', '\n')
            
    except Exception as e:
        print(f"❌ JSON Parsing Error: {e}")
        exit(1)
else:
    print("⚠️ Environment variable FIREBASE_CONFIG not found!")
    exit(1)

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'
    })

# --- 2. BATCH SYNC ENGINE ---
def sync_forex_batch():
    print("🚀 Binance Engine Running. Connecting to Firebase...")
    while True:
        try:
            # Step A: Watchlist fetch karna
            watchlist = db.reference('forex_watchlist').get()
            
            if watchlist:
                # Unique symbols nikalna (e.g., BTCUSDT_UID1 -> BTCUSDT)
                unique_symbols = {key.split('_')[0] for key in watchlist.keys()}
                
                for sym in unique_symbols:
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        p_val = float(res['price'])
                        # Formatting: Badi price ke liye 2 decimal, choti ke liye 6
                        fmt_p = "{:.2f}".format(p_val) if p_val > 1 else "{:.6f}".format(p_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Step B: Batch Updates taiyar karna
                        updates = {}
                        for node_key in watchlist.keys():
                            if node_key.startswith(sym):
                                updates[f"{node_key}/price"] = float(fmt_p)
                                updates[f"{node_key}/utime"] = ts
                        
                        # Step C: Firebase update
                        if updates:
                            db.reference('forex_watchlist').update(updates)
                            print(f"✅ Synced {sym}: {fmt_p}")
            
            eventlet.sleep(1.5) # API limits aur speed ka balance
            
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            eventlet.sleep(5)

# --- 3. RENDER HEALTH CHECK SERVER ---
if __name__ == '__main__':
    # Background engine start
    eventlet.spawn(sync_forex_batch)
    
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    
    def app(e, r):
        r('200 OK', [('Content-Type', 'text/plain')])
        return [b"Sync Engine is Live and Running!"]
    
    print(f"🌍 Health Check Server on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
