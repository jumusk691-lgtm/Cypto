import requests
import time
from supabase import create_client, Client

# Supabase Details (Jo aapne bhejii thin)
URL = "https://wgvilpsjgpqykbqhhxbc.supabase.co"
KEY = "EyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndndmlscHNqZ3BxeWticWhoeGJjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTcyNTgxNSwiZXhwIjoyMDg3MzAxODE1fQ.ALcIY1rCeK3oBny7PeHC3G2KMS1BKqmm1Hzxl16pDxM"

supabase: Client = create_client(URL, KEY)

def get_crypto_list():
    try:
        # Binance se saare USDT pairs uthana
        res = requests.get("https://api.binance.com/api/v3/exchangeInfo").json()
        return [s['symbol'] for s in res['symbols'] if s['symbol'].endswith('USDT') and s['status'] == 'TRADING']
    except:
        return []

def start_sync():
    all_tokens = get_crypto_list()
    print(f"Total {len(all_tokens)} pairs found. Syncing to Supabase...")

    while True:
        try:
            # Live Prices fetch karna
            prices = requests.get("https://api.binance.com/api/v3/ticker/price").json()
            
            for item in prices:
                tkn = item['symbol']
                if tkn in all_tokens:
                    # 'crypto_data' table mein data bharo
                    # APK Color Logic: exch_seg = 'CRYPTO'
                    supabase.table("crypto_data").upsert({
                        "symbol": tkn.replace("USDT", "/USDT"),
                        "token": tkn,
                        "price": float(item['price']),
                        "exch_seg": "CRYPTO",
                        "instrument_type": "SPOT",
                        "last_updated": "now()"
                    }).execute()
            
            print("Data Update Success.")
        except Exception as e:
            print(f"Error: {e}")
        
        # 1 Second Speed
        time.sleep(1)

if __name__ == "__main__":
    start_sync()
