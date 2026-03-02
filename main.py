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

# --- 2. SMART PRICE FETCH (Binance Direct - No More Missing Symbols) ---
def get_binance_prices():
    try:
        # Binance ki ticker API saare prices ek saath deti hai
        url = "https://api.binance.com/api/3/ticker/price"
        response = requests.get(url, timeout=5).json()
        # Convert list to dict for fast lookup: {'BTCUSDT': '65000.00', ...}
        return {item['symbol']: float(item['price']) for item in response}
    except Exception as e:
        print(f"❌ Binance API Error: {e}")
        return {}

# --- 3. MASTER ENGINE (Updated for 100% Symbol Support) ---
def start_sync():
    print("🚀 Global Forex/Crypto Engine Started...")
    
    while True:
        try:
            # Step 1: Fetch Watchlist
            ref = db.reference('forex_watchlist')
            watchlist = ref.get()
            
            if not watchlist:
                print("⏳ Watchlist empty, waiting...")
                eventlet.sleep(5)
                continue

            # Step 2: Get All Market Prices
            market_prices = get_binance_prices()
            if not market_prices:
                eventlet.sleep(2)
                continue

            # Step 3: Prepare Updates
            now = datetime.datetime.now().strftime("%H:%M:%S")
            updates = {}
            
            for node_key, data in watchlist.items():
                # Node key se asli symbol nikalo (e.g., 'BTCUSDT_UID' -> 'BTCUSDT')
                full_symbol = node_key.split('_')[0].upper()
                
                # Agar symbol 1000LUNC jaisa hai toh Binance pe 'LUNCUSDT' dhoondo
                search_symbol = full_symbol
                multiplier = 1.0
                
                if full_symbol.startswith("1000"):
                    search_symbol = full_symbol.replace("1000", "")
                    multiplier = 1000.0
                
                # Agar Binance direct price de raha hai (e.g. BTCUSDT)
                if search_symbol in market_prices:
                    price = market_prices[search_symbol] * multiplier
                    updates[f"{node_key}/price"] = f"{price:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now
                
                # Back-up: Agar symbol ke aage USDT nahi laga (e.g. BTC)
                elif f"{search_symbol}USDT" in market_prices:
                    price = market_prices[f"{search_symbol}USDT"] * multiplier
                    updates[f"{node_key}/price"] = f"{price:.8f}".rstrip('0').rstrip('.')
                    updates[f"{node_key}/utime"] = now

            # Step 4: Firebase Push
            if updates:
                ref.update(updates)
                print(f"🔄 [{now}] Updated {len(updates)//2} Forex/Crypto symbols.")

            eventlet.sleep(1) # Har 1 second mein update
            
        except Exception as e:
            print(f"⚠️ Global Error: {str(e)}")
            eventlet.sleep(2)

# --- 4. SERVER SETUP ---
def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"FOREX ENGINE IS RUNNING"]

if __name__ == '__main__':
    from eventlet import wsgi
    eventlet.spawn(start_sync)
    port = int(os.environ.get("PORT", 10000))
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
