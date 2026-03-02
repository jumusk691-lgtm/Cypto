import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time
from firebase_admin import credentials, db

# --- 1. FIREBASE SETUP ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
KEY_PATH = os.path.join("/etc/secrets/", KEY_FILE) if os.path.exists("/etc/secrets/") else KEY_FILE

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})
print("✅ Firebase Connected!")

# Global States
watchlist_data = {}
last_price_cache = {}
update_counter = 0

# --- 2. UNIVERSAL UPDATE ENGINE (With Auto-Clear) ---
def update_firebase(symbol, price, source):
    global watchlist_data, last_price_cache, update_counter
    try:
        if not price: return
        p_str = str(price)
        
        # 1. Duplicate check (Stop unnecessary updates)
        if last_price_cache.get(symbol) == p_str: return
        
        # 2. Cache update (Memory overwrite)
        last_price_cache[symbol] = p_str
        update_counter += 1
        
        # 3. Memory Maintenance: Har 1000 updates par cache clear karein
        if update_counter > 1000:
            last_price_cache.clear()
            update_counter = 0
            print("🧹 Local Cache Cleared for Stability")

        now = datetime.datetime.now().strftime("%H:%M:%S")
        updates = {}
        
        # 4. Filter for specific Firebase nodes
        for node_key in list(watchlist_data.keys()):
            db_symbol = node_key.split('_')[0].upper()
            if symbol.upper() == db_symbol:
                updates[f"forex_watchlist/{node_key}/price"] = p_str
                updates[f"forex_watchlist/{node_key}/utime"] = now
        
        # 5. Push to Database & Clear local variables
        if updates:
            db.reference().update(updates)
            print(f"📡 [{source}] {symbol} -> {price}")
            updates.clear() # Clear temporary dict immediately
            
    except Exception as e:
        print(f"⚠️ Engine Error: {e}")

# --- 3. MULTI-API HANDLERS ---

# 1. BINANCE
def run_binance():
    def on_msg(ws, msg):
        d = json.loads(msg)
        if 's' in d and 'c' in d: update_firebase(d['s'], d['c'], "Binance")
    while True:
        try:
            symbols = [n.split('_')[0].lower() for n in watchlist_data.keys()]
            if not symbols: 
                time.sleep(5); continue
            url = f"wss://stream.binance.com:9443/ws/{'@ticker/'.join(symbols[:100])}@ticker"
            ws = websocket.WebSocketApp(url, on_message=on_msg)
            ws.run_forever(ping_interval=20)
        except: time.sleep(5)

# 2. BYBIT
def run_bybit():
    def on_msg(ws, msg):
        d = json.loads(msg).get("data", {})
        if isinstance(d, dict) and d.get("lastPrice"):
            update_firebase(d.get("symbol"), d.get("lastPrice"), "Bybit")
    while True:
        try:
            ws = websocket.WebSocketApp("wss://stream.bybit.com/v5/public/linear", on_message=on_msg)
            ws.on_open = lambda ws: ws.send(json.dumps({
                "op": "subscribe", 
                "args": [f"tickers.{n.split('_')[0]}" for n in watchlist_data.keys()]
            }))
            ws.run_forever(ping_interval=20)
        except: time.sleep(5)

# 3. OKX
def run_okx():
    def on_msg(ws, msg):
        res = json.loads(msg)
        if "data" in res:
            data = res["data"][0]
            sym = data['instId'].replace("-", "")
            update_firebase(sym, data['last'], "OKX")
    while True:
        try:
            ws = websocket.WebSocketApp("wss://ws.okx.com:8443/ws/v5/public", on_message=on_msg)
            def on_open(ws):
                args = [{"channel": "tickers", "instId": f"{n.split('_')[0][:3]}-{n.split('_')[0][3:]}"} for n in watchlist_data.keys() if len(n.split('_')[0]) > 4]
                if args: ws.send(json.dumps({"op": "subscribe", "args": args}))
            ws.on_open = on_open
            ws.run_forever()
        except: time.sleep(5)

# 4. GATE.IO
def run_gateio():
    def on_msg(ws, msg):
        d = json.loads(msg)
        if d.get("event") == "update":
            res = d.get("result", {})
            update_firebase(res.get("currency_pair", "").replace("_", ""), res.get("last"), "GateIO")
    while True:
        try:
            ws = websocket.WebSocketApp("wss://api.gateio.ws/ws/v4/", on_message=on_msg)
            def on_open(ws):
                payload = [n.split('_')[0] for n in watchlist_data.keys()]
                ws.send(json.dumps({"time": int(time.time()), "channel": "spot.tickers", "event": "subscribe", "payload": payload}))
            ws.on_open = on_open
            ws.run_forever()
        except: time.sleep(5)

# 5. MEXC
def run_mexc():
    def on_msg(ws, msg):
        res = json.loads(msg)
        if "d" in res:
            d = res["d"]
            update_firebase(d.get('s'), d.get('p'), "MEXC")
    while True:
        try:
            ws = websocket.WebSocketApp("wss://wbs.mexc.com/ws", on_message=on_msg)
            def on_open(ws):
                params = [f"spot@public.deals.v3.api@{n.split('_')[0]}" for n in watchlist_data.keys()]
                ws.send(json.dumps({"method": "SUBSCRIPTION", "params": params}))
            ws.on_open = on_open
            ws.run_forever()
        except: time.sleep(5)

# 6. KUCOIN (Using Ticker stream)
def run_kucoin():
    # Kucoin usually needs a token, but we can use their direct public feed if available
    # For now, we spawn this as a placeholder or use Binance as secondary.
    pass

# --- 4. SERVER SETUP ---
def start_listener():
    global watchlist_data
    def callback(event):
        global watchlist_data
        watchlist_data = db.reference('forex_watchlist').get() or {}
    db.reference('forex_watchlist').listen(callback)

def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b"6-API HYBRID ENGINE ONLINE"]

if __name__ == '__main__':
    from eventlet import wsgi
    # Start Real-time Data Sync
    eventlet.spawn(start_listener)
    
    # Start Multi-Source Engines
    eventlet.spawn(run_binance)
    eventlet.spawn(run_bybit)
    eventlet.spawn(run_okx)
    eventlet.spawn(run_gateio)
    eventlet.spawn(run_mexc)
    
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Master Engine started on port {port}")
    wsgi.server(eventlet.listen(('0.0.0.0', port)), application)
