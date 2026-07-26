import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os
import time

def send_telegram_message(message):
    """Mengirim pesan ke Telegram"""
    token = os.getenv('TG_BOT_TOKEN')
    chat_id = os.getenv('TG_CHAT_ID')
    if not token or not chat_id:
        print("Error: TG_BOT_TOKEN atau TG_CHAT_ID belum diatur!")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

def get_bitget_exchange():
    return ccxt.bitget({'enableRateLimit': True})

def get_top_gainers(exchange):
    """Mengambil 10 koin dengan kenaikan tertinggi"""
    print("Mengambil data seluruh ticker dari Bitget Futures...")
    try:
        tickers = exchange.fetch_tickers()
        gainers = []
        for symbol, data in tickers.items():
            if symbol.endswith(':USDT') and data['percentage'] is not None:
                gainers.append({'symbol': symbol, 'change': data['percentage']})
        gainers.sort(key=lambda x: x['change'], reverse=True)
        return gainers[:10]
    except Exception as e:
        print(f"Gagal mengambil gainers: {e}")
        return []

def analyze_stochastic(exchange, symbol):
    """Mengambil data OHLCV dan menghitung Stoch 5,3,3"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        stoch = df.ta.stoch(fast_k=5, slow_k=3, slow_d=3)
        k = stoch.iloc[-1]['STOCHk_5_3_3']
        d = stoch.iloc[-1]['STOCHd_5_3_3']
        return k, d
    except Exception as e:
        print(f"Error menganalisis {symbol}: {e}")
        return None, None

def main():
    print("Memulai bot...")
    exchange = get_bitget_exchange()
    
    # Notifikasi Startup
    startup_msg = "✅ *Bot Screener Bitget Aktif!*\n\nProgram telah berhasil dijalankan dan siap memantau 10 Top Gainers."
    send_telegram_message(startup_msg)
    
    gainers = get_top_gainers(exchange)
    
    print(f"\nTop 10 Gainers Ditemukan:")
    for g in gainers:
        print(f"{g['symbol']}: {g['change']}%")
        
    print("\nMenganalisis Timeframe 1 Jam (Stochastic 5,3,3)...")
    
    for g in gainers:
        symbol = g['symbol']
        k, d = analyze_stochastic(exchange, symbol)
        
        if k is not None and d is not None:
            # Kondisi: K dan D di bawah 25
            if k < 25 and d < 25:
                msg = (f"🚨 *Sinyal Oversold!* 🚨\n\n"
                       f"Coin: {symbol}\n"
                       f"Change: {g['change']}%\n"
                       f"%K: {k:.2f}\n"
                       f"%D: {d:.2f}\n"
                       f"Status: Oversold (K & D < 25)")
                print(f"Mengirim sinyal untuk {symbol}!")
                send_telegram_message(msg)
            else:
                print(f"{symbol}: %K={k:.2f}, %D={d:.2f} (Belum Oversold)")
        
        # Jeda singkat agar tidak terkena rate limit API
        time.sleep(0.5)

if __name__ == "__main__":
    main()
