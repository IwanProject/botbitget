import ccxt
import pandas as pd
import requests
import os
import time
from datetime import datetime

# Kredensial Telegram diambil dari GitHub Secrets untuk keamanan
TELEGRAM_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

def send_telegram_message(message):
    """Mengirim pesan notifikasi ke Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token atau Chat ID belum disetting!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Notifikasi Telegram berhasil dikirim.")
    except Exception as e:
        print(f"Gagal mengirim pesan Telegram: {e}")

def get_top_gainers_futures(exchange, limit=10):
    """Mengambil Top Gainers dari pasar Futures (Swap) USDT di Bitget."""
    try:
        print("Mengambil data seluruh ticker dari Bitget Futures...")
        tickers = exchange.fetch_tickers()
        
        # Filter hanya pair USDT-M Futures (biasanya berakhiran :USDT di CCXT Bitget)
        usdt_futures = []
        for symbol, ticker in tickers.items():
            if symbol.endswith(':USDT') and ticker.get('percentage') is not None:
                usdt_futures.append({
                    'symbol': symbol,
                    'last': ticker.get('last'),
                    'percentage': ticker.get('percentage')
                })
        
        # Urutkan berdasarkan persentase kenaikan 24h tertinggi
        sorted_tickers = sorted(usdt_futures, key=lambda x: x['percentage'], reverse=True)
        return sorted_tickers[:limit]
    except Exception as e:
        print(f"Error mengambil top gainers: {e}")
        return []

def calculate_stochastic(df, k_period=5, d_period=3, smooth_k=3):
    """
    Menghitung Stochastic Oscillator (5, 3, 3) secara manual menggunakan Pandas
    untuk menghindari dependensi library yang berat di GitHub Actions.
    """
    # 1. Hitung titik terendah (Lowest Low) dan tertinggi (Highest High) dalam periode K
    df['Low_5'] = df['low'].rolling(window=k_period).min()
    df['High_5'] = df['high'].rolling(window=k_period).max()
    
    # 2. Hitung Fast %K
    df['Fast_%K'] = 100 * ((df['close'] - df['Low_5']) / (df['High_5'] - df['Low_5']))
    
    # 3. Hitung Slow %K (Smooth K)
    df['%K'] = df['Fast_%K'].rolling(window=smooth_k).mean()
    
    # 4. Hitung Slow %D (Smooth D)
    df['%D'] = df['%K'].rolling(window=d_period).mean()
    
    return df

def run_screener():
    print(f"Menjalankan screener pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Inisialisasi CCXT untuk Bitget Futures
    exchange = ccxt.bitget({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })
    
    top_10 = get_top_gainers_futures(exchange, limit=10)
    
    if not top_10:
        print("Tidak ada data ticker ditemukan.")
        return

    print("\nTop 10 Gainers:")
    for t in top_10:
        print(f"{t['symbol']} - Naik: {t['percentage']}%")

    alerts = []
    
    print("\nMenganalisis Timeframe 1 Jam (Stochastic 5,3,3)...")
    for item in top_10:
        symbol = item['symbol']
        try:
            # Ambil OHLCV 1 jam, ambil 30 candle terakhir (cukup untuk perhitungan)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=30)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Hitung Stochastic
            df = calculate_stochastic(df, k_period=5, d_period=3, smooth_k=3)
            
            # AMBIL CANDLE YANG SUDAH CLOSE
            # df.iloc[-1] adalah candle yang sedang berjalan (belum close)
            # df.iloc[-2] adalah candle terakhir yang SUDAH close
            last_closed_candle = df.iloc[-2]
            
            k_value = last_closed_candle['%K']
            d_value = last_closed_candle['%D']
            close_price = last_closed_candle['close']
            
            # Cek kondisi: %K berada di area oversold (<= 25)
            if pd.notna(k_value) and k_value <= 25:
                alerts.append(
                    f"🔹 *{symbol.replace(':USDT', '')}*\n"
                    f"Harga Close (1H): `${close_price}`\n"
                    f"Kenaikan 24h: `+{item['percentage']}%`\n"
                    f"Stoch(5,3,3) %K: `{k_value:.2f}` *(Oversold)*\n"
                    f"Stoch(5,3,3) %D: `{d_value:.2f}`"
                )
                
            time.sleep(1) # Jeda agar tidak terkena rate limit API
            
        except Exception as e:
            print(f"Error menganalisis {symbol}: {e}")

    if alerts:
        message = "🚨 *SCREENER BITGET FUTURES* 🚨\n_Top Gainers di Area Oversold (TF 1H)_\n\n"
        message += "\n\n".join(alerts)
        send_telegram_message(message)
    else:
        print("Tidak ada koin Top Gainer yang sedang Oversold di TF 1 Jam saat ini.")

if __name__ == "__main__":
    run_screener()
