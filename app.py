import ccxt
import pandas as pd
import time
import schedule
import requests
import datetime
import os
import sys

# ==========================================
# KONFIGURASI TELEGRAM (DARI RAILWAY VARIABLES)
# ==========================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("ERROR: BOT_TOKEN atau CHAT_ID belum diatur di Environment Variables Railway!")
    sys.exit(1)

# ==========================================
# KONFIGURASI SCREENER
# ==========================================
TIMEFRAME = '1h'          # Timeframe 1 jam
LIMIT_GAINERS = 100       # Ambil 100 koin dengan persentase kenaikan 24h tertinggi
CANDLE_LIMIT = 50         # Jumlah candle yang diambil untuk hitung EMA

# Inisialisasi exchange Bitget menggunakan ccxt
exchange = ccxt.bitget({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap', 
    }
})

def get_top_100_gainers():
    """Mengambil Top 100 Gainers (24h) dari Bitget Futures."""
    tickers = exchange.fetch_tickers()
    usdt_tickers = []
    
    for symbol, ticker in tickers.items():
        if symbol.endswith(':USDT') and ticker.get('percentage') is not None:
            usdt_tickers.append(ticker)
            
    usdt_tickers.sort(key=lambda x: x['percentage'], reverse=True)
    top_coins = [t['symbol'] for t in usdt_tickers[:LIMIT_GAINERS]]
    return top_coins

def check_ema_crossover(symbol, timeframe):
    """Mengecek crossing EMA 5 & 10 ke atas EMA 30."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=CANDLE_LIMIT)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        if len(df) < 35:
            return False

        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()

        prev_ema5 = df['ema5'].iloc[-2]
        prev_ema10 = df['ema10'].iloc[-2]
        prev_ema30 = df['ema30'].iloc[-2]

        curr_ema5 = df['ema5'].iloc[-1]
        curr_ema10 = df['ema10'].iloc[-1]
        curr_ema30 = df['ema30'].iloc[-1]

        current_above = (curr_ema5 > curr_ema30) and (curr_ema10 > curr_ema30)
        previous_below = (prev_ema5 <= prev_ema30) or (prev_ema10 <= prev_ema30)

        if current_above and previous_below:
            return True
            
        return False
    except Exception as e:
        print(f"Error pada {symbol}: {e}")
        return False

def kirim_ke_telegram(pesan):
    """Fungsi untuk mengirim pesan ke Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": pesan, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Gagal kirim ke Telegram: {e}")

def jalankan_screener():
    """Fungsi utama yang akan dijalankan setiap jam."""
    waktu = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{waktu}] Memulai proses screening...")
    
    try:
        top_gainers = get_top_100_gainers()
        matched_coins = []
        
        for symbol in top_gainers:
            if check_ema_crossover(symbol, TIMEFRAME):
                matched_coins.append(symbol)
            time.sleep(0.1) # Jeda agar tidak kena limit API
            
        # Susun pesan untuk Telegram
        pesan = f"📊 <b>BITGET SCREENER (1H)</b>\n"
        pesan += f"⏰ Waktu: {waktu}\n"
        pesan += f"🔍 Kriteria: EMA 5 & 10 Cross EMA 30\n\n"
        
        if matched_coins:
            pesan += f"✅ <b>Ditemukan {len(matched_coins)} Koin Sinyal:</b>\n"
            for coin in matched_coins:
                # Menghapus ':USDT' agar nama koin lebih bersih saat dibaca (opsional)
                clean_name = coin.replace(':USDT', '') 
                pesan += f"🚀 <code>{clean_name}</code>\n"
        else:
            pesan += "<i>result not found</i>"
            
        kirim_ke_telegram(pesan)
        print(f"[{waktu}] Screening selesai. Hasil telah dikirim ke Telegram.")
        
    except Exception as e:
        pesan_error = f"⚠️ <b>ERROR SCREENER:</b>\n<code>{e}</code>"
        kirim_ke_telegram(pesan_error)
        print(f"Error saat screening: {e}")

# ==========================================
# PENGATURAN JADWAL
# ==========================================
# Jalankan tepat pada pergantian jam (menit ke-00)
schedule.every().hour.at(":00").do(jalankan_screener)

if __name__ == "__main__":
    print("🚀 Screener Bot menyala di Railway!")
    kirim_ke_telegram("✅ <b>Bot Screener Bitget</b> berhasil di-deploy dan menyala di Railway! Bersiap mengirim sinyal setiap jam...")
    
    # Langsung jalankan sekali saat baru dinyalakan tanpa menunggu jam berubah (Opsional)
    # Hapus tanda pagar di bawah ini jika Anda ingin bot langsung scan saat baru di-deploy
    # jalankan_screener()
    
    while True:
        schedule.run_pending()
        time.sleep(1)
