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

# --- 2. IMPROVED SMART PARSER (Universal Compatibility) ---
def parse_symbol(raw_key):
    # e.g., '1000CATUSDT_8Jtbg...' -> Full: '1000CATUSDT'
    full_sym = raw_key.split('_')[0].upper()
    
    # Cleaning Logic: '1000' aur 'USDT' ko hatao
    clean = full_sym.replace("1000", "").replace("USDT", "")
    
    # [IMPORTANT] Sirf asli symbol letters nikalo (e.g., 1000CHEEMSUSDT -> CHEEMS)
    # Ye Regex kisi bhi format ke kachre ko saaf kar dega
    clean = re.sub(r'[^A-Z]', '', clean)
    
    return clean, full_sym

# --- 3. MASTER ENGINE (Mixed Memory + Storage Saver) ---
def start_sync():
    print("🚀 Universal Smart-Clean Engine Active...")
    print("🧹 Cleaning Logic: Overwriting DB every second to save storage.")
    
    # Memory Cache: Sirf naye symbols ko subscribe karne ke liye
    subscribed_cache = {} 

    while True:
        try:
            # Step 1: Watchlist fetch
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                eventlet.sleep(5)
                continue

            # Check for New/Deleted keys (Subscription Logic)
            current_keys = set(watchlist.keys())
            cached_keys = set(subscribed_cache.keys())
            
            new_keys = current_keys - cached_keys
            deleted_keys = cached_keys - current_keys

            if new_keys:
                print(f"🆕 Subscribing {len(new_keys)} New Nodes...")
                for k in new_keys:
                    clean_name, full_name = parse_symbol(k)
                    subscribed_cache[k] = {"clean": clean_name, "full": full_name}

            if deleted_keys:
                for k in deleted_keys:
                    subscribed_cache.pop(k, None)

            # Step 2: FETCH PRICES (Batching for Scale)
            # Saare unique symbols (BTC, ETH, CHEEMS, CAT, etc.)
            unique_clean = list(set(info["clean"] for info in subscribed_cache.values()))
            all_prices = {}
            
            # API Chunking (Max 80 symbols per call to prevent blocking)
            for i in range(0, len(unique_clean), 80):
                chunk = ",".join(unique_clean[i:i+80])
                url = f"https://min-api.cryptocompare.com/data/pricemulti?fsyms={chunk}&tsyms=USD"
                res = requests.get(url, timeout=5).json()
                
                if isinstance(res, dict) and "Response" not in res:
                    for c_sym, p_data in res.items():
                        all_prices[c_sym] = p_data['USD']

            # Step 3: UPDATE & OVERWRITE (Storage Saving Logic)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            updates = {}
            
            for node_key, info in subscribed_cache.items():
                c_name = info["clean"]
                f_name = info["full"]
                
                if c_name in all_prices:
                    raw_p = float(all_prices[c_name])
                    
                    # 1000x Multiplier (Agar ID mein 1000 hai toh rate fix karo)
                    final_p = raw_p * 1000 if "1000" in f_name else raw_p
                    
                    # Atomic Update: Purana price/time mita kar naya likho
                    updates[f"{node_key}/price"] = final_p
                    updates[f"{node_key}/utime"] = now

            if updates:
                ref.update(updates)
                # Render Clean Logs: Summary only
                print(f"🔄 [{now}] Global Update: {len(subscribed_cache)} symbols live. DB Clean.")

            eventlet.sleep(1) # Strict 1-Second Gap
            
        except Exception as e:
            print(f"⚠️ Status: {str(e)[:50]}...")
            eventlet.sleep(2)

# --- 4. SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"UNIVERSAL SMART-CLEAN ENGINE LIVE."]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_sync)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
