import requests
import time
import threading
import os
from flask import Flask
from supabase import create_client, Client

# 1. Flask Server for Render [cite: 2026-01-20]
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Data is Running Live!"

# 2. Supabase Connection
URL = "https://wgvilpsjgpqykbqhhxbc.supabase.co"
KEY = "EyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndndmlscHNqZ3BxeWticWhoeGJjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTcyNTgxNSwiZXhwIjoyMDg3MzAxODE1fQ.ALcIY1rCeK3oBny7PeHC3G2KMS1BKqmm1Hzxl16pDxM"
supabase: Client = create_client(URL, KEY)

def sync_data():
    while True:
        try:
            # Binance Live Data
            prices = requests.get("https://api.binance.com/api/v3/ticker/24hr").json()
            for item in prices:
                symbol = item['symbol']
                if symbol.endswith('USDT'):
                    # Data Insertion Logic
                    supabase.table("crypto_data").upsert({
                        "symbol": symbol.replace("USDT", "/USDT"),
                        "token": symbol,
                        "price": float(item['lastPrice']),
                        "change_24h": f"{item['priceChangePercent']}%",
                        "volume_24h": item['volume'],
                        "exch_seg": "CRYPTO",
                        "last_updated": "now()"
                    }).execute()
            print("Data Updated Successfully!")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(1) # 1 sec delay

if __name__ == "__main__":
    # Start Sync in Background [cite: 2026-01-20]
    threading.Thread(target=sync_data, daemon=True).start()
    
    # Run Flask on Render's Port
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
