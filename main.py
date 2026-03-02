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

# --- 2. PURANA LOGIC: SMART PARSER (Format & Meme Token) ---
def parse_symbol(raw_key):
    full_sym = raw_key.split('_')[0].upper()
    clean = full_sym.replace("1000", "").replace("USDT", "")
    clean = re.sub(r'[^A-Z]', '', clean) # Sirf alphabets bacha raha hai (Pro Level)
    return clean, full_sym

# --- 3. MASTER ENGINE (Smart Memory + Storage Saver Mix) ---
def start_sync():
    print("🚀 Smart-Clean Engine Active: One-time Subscribe + Auto-Overwrite...")
    
    # NAYA LOGIC: Cache taaki baar-baar subscribe na ho
    subscribed_cache = {} 

    while True:
        try:
            # Step 1: Watchlist fetch karna
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                eventlet.sleep(5)
                continue

            # NAYA LOGIC: Check for New/Deleted symbols
            current_keys = set(watchlist.keys())
            cached_keys = set(subscribed_cache.keys())
            
            new_keys = current_keys - cached_keys
            deleted_keys = cached_keys - current_keys

            # Naya symbol aaya toh hi subscribe (parse) hoga
            if new_keys:
                print(f"🆕 Subscribing {len(new_keys)} New Symbols...")
                for k in new_keys:
                    clean, full = parse_symbol(k)
                    subscribed_cache[k] = {"clean": clean, "full": full}

            # Purana delete hua toh cache se saaf
            if deleted_keys:
                for k in deleted_keys:
                    subscribed_cache.pop(k, None)

            # Step 2: FAST API CALL (Tukdon mein taaki 1000+ handle ho ske)
            all_clean_names = list(set(info["clean"] for info in subscribed_cache.values()))
            all_prices = {}
            
            for i in range(0, len(all_clean_names), 80):
                chunk = ",".join(all_clean_names[i:i+80])
                url = f"https://min-api.cryptocompare.com/data/pricemulti?fsyms={chunk}&tsyms=USD"
                res = requests.get(url, timeout=5).json()
                if isinstance(res, dict) and "Response" not in res:
                    for c_sym, p_data in res.items():
                        all_prices[c_sym] = p_data['USD']

            # Step 3: PURANA LOGIC: OVERWRITE (Storage Saver)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            updates = {}
            
            for node_key, info in subscribed_cache.items():
                c_name = info["clean"]
                f_name = info["full"]
                
                if c_name in all_prices:
                    price_val = float(all_prices[c_name])
                    
                    # 1000x Multiplier (Meme Token Logic)
                    if "1000" in f_name:
                        price_val = price_val * 1000
                    
                    # DATABASE CLEANING: Pichla data mita kar naya overwrite
                    updates[f"{node_key}/price"] = price_val
                    updates[f"{node_key}/utime"] = now

            if updates:
                ref.update(updates)
                # RENDER CLEAN LOGS: Sirf ek line summary
                print(f"🔄 [{now}] DB Overwritten & Synced: {len(subscribed_cache)} symbols live.")

            eventlet.sleep(1) # Strict 1-Second Gap
            
        except Exception as e:
            print(f"⚠️ Status: {str(e)[:40]}")
            eventlet.sleep(2)

# --- 4. SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"SMART-CLEAN PRO ENGINE IS LIVE."]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_sync)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
