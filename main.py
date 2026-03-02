import eventlet
eventlet.monkey_patch()
import os, datetime, requests, firebase_admin, re
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

# --- 2. SMART PARSER (Format & Meme Token Logic) ---
def parse_symbol(raw_key):
    # Har symbol ko unique aur clean rakhta hai
    full_sym = raw_key.split('_')[0].upper()
    clean = full_sym.replace("1000", "").replace("USDT", "")
    clean = re.sub(r'\d+', '', clean)
    return clean, full_sym

# --- 3. HIGH-SPEED CLEAN ENGINE (Storage Saver) ---
def start_sync():
    print("🚀 Clean-Storage Engine Active: Overwriting history every second...")
    
    while True:
        try:
            # Step 1: Current data snapshot (Fastest way)
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                eventlet.sleep(5)
                continue

            # Step 2: Unique Symbol Mapping
            clean_to_full = {parse_symbol(k)[0]: None for k in watchlist.keys()}

            # Step 3: Fast API Call (1-Second Data)
            sym_list = ",".join(clean_to_full.keys())
            url = f"https://min-api.cryptocompare.com/data/pricemulti?fsyms={sym_list}&tsyms=USD"
            res = requests.get(url, timeout=3).json()
            
            now = datetime.datetime.now().strftime("%H:%M:%S")
            updates = {}
            count = 0

            # Step 4: OVERWRITE LOGIC (Storage & Log Saving)
            for node_key in watchlist.keys():
                clean_name, full_name = parse_symbol(node_key)
                
                if clean_name in res:
                    price_val = float(res[clean_name]['USD'])
                    
                    # 1000x Meme Token Multiplier
                    if "1000" in full_name:
                        price_val = price_val * 1000
                    
                    # Yahan pichla data automatically clean (overwrite) ho raha hai
                    updates[f"{node_key}/price"] = price_val
                    updates[f"{node_key}/utime"] = now
                    count += 1

            if updates:
                # 'update' command purani values ko mita kar naya likhti hai (Zero storage growth)
                ref.update(updates)
                # Render Logs Cleaning: Sirf ek line summary taaki storage bache
                print(f"🔄 [{now}] DB Cleaned & Synced: {count} symbols live.")

            eventlet.sleep(1) # Strict 1-Second Gap
            
        except Exception as e:
            # Error log ko chhota rakho taaki Render memory na bhare
            print(f"⚠️ Status: {str(e)[:40]}")
            eventlet.sleep(2)

# --- 4. SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"STORAGE-SAVER ENGINE IS LIVE. DATABASE CLEANED EVERY SECOND."]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_sync)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
