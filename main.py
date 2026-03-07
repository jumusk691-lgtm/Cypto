import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading, sqlite3, requests, gc
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIGURATION & AUTH ---
# Firebase and Database configuration
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
SUPABASE_URL = "https://tnrhlvibaeiwhlrxdxnm.supabase.co/storage/v1/object/public/Myt/market_data.db"

# Your validated API Key for Exotic Forex pairs
FOREX_API_KEY = "8bc2800bcaaa268f50b12fa2" 

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
active_binance = set()
exotic_list = []
node_map = {}
current_ws = None
is_market_open = True

# --- 2. LOGIC: MARKET STATUS (Auto-Sleep Logic) ---
def check_market_status():
    """Checks if the market is open (Monday to Friday)"""
    global is_market_open
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        weekday = now.weekday() # 5=Sat, 6=Sun
        if weekday >= 5:
            if is_market_open:
                print("🌙 Weekend: Market Closed. Entering Sleep Mode.")
                is_market_open = False
                if current_ws: current_ws.close()
        else:
            is_market_open = True
        time.sleep(600)

# --- 3. LOGIC: AUTO-SYNC (Daily 05:00 AM) ---
def auto_sync_scheduler():
    """Daily sync of symbols from Supabase"""
    while True:
        now = datetime.datetime.now()
        if now.hour == 5 and now.minute == 0:
            try:
                r = requests.get(SUPABASE_URL, timeout=60)
                with open("market_data.db", "wb") as f: f.write(r.content)
                gc.collect() # Memory cleanup
                print("✅ Daily Sync Complete.")
            except: pass
            time.sleep(70)
        time.sleep(30)

# --- 4. LOGIC: EXOTIC UPDATER (Afghani Solution) ---
def run_exotic_engine():
    """Fetches rates for pairs not on Binance (e.g., Afghani)"""
    global exotic_list, is_market_open
    while True:
        if is_market_open and exotic_list:
            try:
                resp = requests.get(f"https://v6.exchangerate-api.com/v6/{FOREX_API_KEY}/latest/USD")
                rates = resp.json().get('conversion_rates', {})
                updates = {}
                for nid in exotic_list:
                    sym = nid.split('_')[0].upper().replace("USD", "")
                    if sym in rates:
                        # Converting USD base to Pair price
                        price = 1 / rates[sym]
                        updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(price)
                        updates[f"forex_watchlist/{nid}/percent"] = "0.00%" # Default for exotic
                        updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                db.reference().update(updates)
            except Exception as e:
                print(f"Exotic Engine Error: {e}")
        time.sleep(60)

# --- 5. LOGIC: LIVE BINANCE ENGINE (Real-time Mix) ---
def run_master_engine():
    """Streaming live prices and percentages for Majors and Crypto"""
    global node_map, current_ws, active_binance, exotic_list, is_market_open
    while True:
        if not is_market_open:
            time.sleep(10); continue
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_binance = set()
            new_exotic = []
            new_map = {}

            for node_id in watchlist.keys():
                raw = node_id.split('_')[0].upper()
                # Route to Binance if Major or Crypto
                if any(x in raw for x in ["BTC", "ETH", "EUR", "GBP", "JPY", "XAU"]):
                    target = raw.lower().replace("usd", "usdt")
                    new_binance.add(target)
                    if target.upper() not in new_map: new_map[target.upper()] = []
                    new_map[target.upper()].append(node_id)
                else:
                    new_exotic.append(node_id)

            exotic_list = new_exotic
            
            # Restart WebSocket only if watchlist changes
            if new_binance != active_binance:
                active_binance = new_binance
                node_map = new_map
                if current_ws: current_ws.close()
                if active_binance:
                    url = f"wss://stream.binance.com:9443/ws/{'/'.join([f'{s}@ticker' for s in active_binance])}"
                    
                    def on_message(ws, msg):
                        d = json.loads(msg)
                        if 's' in d and 'c' in d:
                            s_id, price, p_change = d['s'].upper(), d['c'], d['P']
                            updates = {}
                            for nid in node_map.get(s_id, []):
                                updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
                                updates[f"forex_watchlist/{nid}/percent"] = f"{p_change}%" # Live Percent
                                updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
                            db.reference().update(updates)
                    
                    current_ws = websocket.WebSocketApp(url, on_message=on_message)
                    threading.Thread(target=current_ws.run_forever).start()
            time.sleep(15)
        except: time.sleep(5)

@app.route('/')
def health(): return "ULTIMATE_HYBRID_ENGINE_V2_LIVE"

if __name__ == '__main__':
    # Start all background logic threads
    threading.Thread(target=check_market_status, daemon=True).start()
    threading.Thread(target=auto_sync_scheduler, daemon=True).start()
    threading.Thread(target=run_exotic_engine, daemon=True).start()
    threading.Thread(target=run_master_engine, daemon=True).start()
    
    # Render Optimized Production Server
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
