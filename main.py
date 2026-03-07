import eventlet
eventlet.monkey_patch()
import os, datetime, json, firebase_admin, websocket, time, threading, requests
from firebase_admin import credentials, db
from flask import Flask

# --- 1. CONFIG ---
KEY_FILE = "trade-f600a-firebase-adminsdk-fbsvc-269ab50c0c.json"
DB_URL = 'https://trade-f600a-default-rtdb.firebaseio.com/'
# Forex/Metals ke liye Finnhub Free API Key (finnhub.io se turant mil jayegi)
FINNHUB_KEY = "YOUR_FINNHUB_API_KEY" 

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

app = Flask(__name__)
node_map = {}

# --- 2. FAST UPDATE FUNCTION ---
def fast_update(symbol, price, change="0.00%"):
    updates = {}
    for nid in node_map.get(symbol.upper(), []):
        updates[f"forex_watchlist/{nid}/price"] = "{:.5f}".format(float(price))
        updates[f"forex_watchlist/{nid}/percent"] = change
        updates[f"forex_watchlist/{nid}/utime"] = datetime.datetime.now().strftime("%H:%M:%S")
    if updates:
        db.reference().update(updates)

# --- 3. CRYPTO WEBSOCKET (BINANCE US - No Block on Render) ---
def start_crypto_ws():
    def on_message(ws, msg):
        d = json.loads(msg)
        if 's' in d and 'c' in d:
            fast_update(d['s'], d['c'], f"{d['P']}%")

    def run():
        while True:
            try:
                # Binance US use kar rahe hain taaki 451 error na aaye
                active_list = [s.lower() for s in node_map.keys() if "USDT" in s]
                if active_list:
                    url = f"wss://stream.binance.us:9443/ws/{'/'.join([f'{s}@ticker' for s in active_list])}"
                    ws = websocket.WebSocketApp(url, on_message=on_message)
                    ws.run_forever()
            except: time.sleep(5)
    
    threading.Thread(target=run, daemon=True).start()

# --- 4. FOREX/GOLD WEBSOCKET (FINNHUB) ---
def start_forex_ws():
    def on_message(ws, msg):
        data = json.loads(msg)
        if data['type'] == 'trade':
            for trade in data['data']:
                fast_update(trade['s'], trade['p'])

    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(f"wss://ws.finnhub.io?token={FINNHUB_KEY}",
                                          on_message=on_message)
                def on_open(ws):
                    # Majors aur Gold ke liye subscribe
                    for s in ["OANDA:XAU_USD", "OANDA:EUR_USD", "OANDA:GBP_USD"]:
                        ws.send(json.dumps({"type":"subscribe", "symbol": s}))
                ws.on_open = on_open
                ws.run_forever()
            except: time.sleep(5)
            
    threading.Thread(target=run, daemon=True).start()

# --- 5. MONITOR WATCHLIST ---
def monitor_watchlist():
    global node_map
    while True:
        try:
            watchlist = db.reference('forex_watchlist').get() or {}
            new_map = {}
            for nid, data in watchlist.items():
                sym = nid.split('_')[0].upper()
                if sym not in new_map: new_map[sym] = []
                new_map[sym].append(nid)
            node_map = new_map
        except: pass
        time.sleep(30)

@app.route('/')
def health(): return "LIVE_1SEC_ENGINE_ACTIVE"

if __name__ == '__main__':
    threading.Thread(target=monitor_watchlist, daemon=True).start()
    start_crypto_ws()
    # start_forex_ws() # Finnhub key daalne ke baad ise uncomment karein
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
