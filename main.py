import eventlet
eventlet.monkey_patch()
import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, db

# --- FIREBASE SETUP ---
service_account_info = {
  "type": "service_account",
  "project_id": "trade-f600a",
  "private_key_id": "d3414fc3a948f93409e6f4038f683341f82a9c2a",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDHLXAZg4YsBJXI\ndSYFnEgKPWUPSv7trW6CXUDS4R6PolwebzqSJZ3FGr1mk4IgOM0Vkku3djnkMjqM\nDxUgJFjgH2N44HmSpMDbuEfBhd/fYZ7sNI6uNXsHEhK1hBwZJyXy7D1KGaIxqlaI\n9I/kzl+3wtbTcLH0xsLSGz+w5plsZpI134u+y/ZhcDOuZywAhZgQ6NlxjRZpdLwn\nUx+vIoTFUTWjIoCmd3DNE6JoTPN7CBstP9YpcNoy87MBjKoNpX+lTBrmlwku1zlO\n1O7kip7trnMy4b/hNu9PvLeEyeMIWqBLCiSVkv9FGgPsMxHmpnpAnQO+VcAyczJM\ncJOXITBXAgMBAAECggEAD5uMZrtrNqTPVet0JMlnzcGc2zNtwZMvDzEehMfWPLwk\nys+9f7lJ4SmkwNZ7QmohC/kwTLqLc8nJ07LU3XVrr3hWM6EndanKYQ1SNiR29Aqy\nyOCfc6BGOTod1DJ7fy8VprEDZnyWvJyT9lxvsCbJ0l0Gt3/jugIfPxaaiZKwYBGQ\nK1Vy+2kFq8UjK9C7Izr8+B85qYyuDG4JovT8lu8gd6OCTz2UzUvGZfao+koUSibY\nyTd9OC4uxKQDn9Ylpgn50sns6GSkzsKb9UGtIgt/P3WlnDjwcQlNy3VDqrP61aNG\n7z14hzbq8rzgFdGWo5Yar7O5A1tW3K76v6My8jjAzQKBgQDl7s1mgaPW0+WoGQDC\nTrQTBSLctulyApUWajH9oXV0QuqpBWZ4PE8UzYV7PEEB9akG3WUoAq0IpjAMaJYR\nRgSy3M6KZ6Njo/i75LzerxUl0hLKWC0otkgBIc583cV8HrvWweHwvGPjBfxQK+Ka\ngD/OoqY6UkndAj3HzbsffWlSSwKBgQDdwgrtMMtAFvwUWNA4S8vG8OUg9KWBs4/p\nFc4IQq4EO7c7jJEit1hatxjC5zPE2D0cPBmq89+2MQciGyfS0d2sKy3lUrun9wVW\nHXggxcpZ+rAegTLswoMdf4FzwZRW4Vb53RUr9oXdVEknin5axyVhIJK6nOfpEcI+\nOR9BCLWypQKBgBd6fvbMnhI9qOG1S+KLbs/SYnDvLH87zEVxqpEff4LTomqH5qK4\nZcrWAZ9H08uDbjMJQF8JhumvLpDVzR0ObURmT6DKXGC8SZXGEZMbhalK/igzQMk7\nc7bJ4O/XJWc7LCsNuSh/1CNGZTE6ifUEy38qFJc399rdc7mHRGg+whZpAoGBALKo\n4qS16wp3eh/qbdbtOf/NlMw4Th9wy0C+kH+XORuwAK+5UDToAgcT/J8KJmswzAsz\nYHqagGIInfacajkvW6iaIR/gx89K9MGsfFvq/lv/3GS3MpANJhVd5K2eCCT251vn\nAmeo9bCbd1Sj/6ijSTo3Q/+U6kKcTCJVYxjCK6EBAoGBAJdM1ZMN19uQpZ7tP6cO\nvc+FDoA1xLAgFlB7X/xfUxtkwHxUCEcaCax6LfZgNSXDqyFa3/2Wx4edCfLQU7ol\n4MrEOfmmbI20WIjZyxyG5pAfByyNX2fGWzLIAV0xhVNhxOmgHZOeVxeXCCOBhvB5\nu2i5Xdu5JRZ/AEBH+C6bJC2d\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@trade-f600a.iam.gserviceaccount.com",
  "client_id": "105189844130830324690",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40trade-f600a.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://trade-f600a-default-rtdb.firebaseio.com/'})

# --- BATCH SYNC ENGINE ---
def sync_forex_batch():
    print("🚀 Binance Engine Running: Broad Update Mode")
    while True:
        try:
            # Puri watchlist fetch karo
            watchlist = db.reference('forex_watchlist').get()
            if watchlist:
                # Unique symbols (e.g. BTCUSDT)
                unique_symbols = {key.split('_')[0] for key in watchlist.keys()}
                
                for sym in unique_symbols:
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                    res = requests.get(url, timeout=5).json()
                    
                    if 'price' in res:
                        price_val = float(res['price'])
                        fmt_price = "{:.2f}".format(price_val) if price_val > 1 else "{:.6f}".format(price_val)
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        
                        # Loop through all keys to update every user who has this symbol
                        updates = {}
                        for node_key in watchlist.keys():
                            if node_key.startswith(sym):
                                updates[f"{node_key}/price"] = float(fmt_price)
                                updates[f"{node_key}/utime"] = ts
                        
                        if updates:
                            db.reference('forex_watchlist').update(updates)
                            print(f"✅ Updated {sym}: {fmt_price}")
            
            eventlet.sleep(1) # Har 1 sec mein update
        except Exception as e:
            print(f"⚠️ Error: {e}")
            eventlet.sleep(5)

if __name__ == '__main__':
    eventlet.spawn(sync_forex_batch)
    from eventlet import wsgi
    port = int(os.environ.get("PORT", 10000))
    def app(env, res):
        res('200 OK', [('Content-Type', 'text/plain')])
        return [b"Sync Active"]
    wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
