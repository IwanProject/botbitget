import ccxt
import pandas as pd
import requests
import time
import json
import os
import html

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel


# ============================================================
# 1. CONFIGURATION
# ============================================================

console = Console()

TIMEFRAME = "4h"

EMA_FAST = 11
EMA_SLOW = 50

PIVOT_LEFT = 2
PIVOT_RIGHT = 2

CANDLE_LIMIT = 200

MAX_EMA_DISTANCE = 0.005
APPROACH_CANDLES = 3

REQUEST_DELAY = 0.15

CLOSE_BUFFER_SECONDS = 10
SCHEDULER_CHECK_SECONDS = 15

# Railway Volume mount: /app/data
# Local testing default: ./data
DATA_DIR = os.getenv("DATA_DIR", "./data")

os.makedirs(DATA_DIR, exist_ok=True)

SENT_SIGNALS_FILE = os.path.join(
    DATA_DIR,
    "sent_signals.json"
)


# ============================================================
# 2. TELEGRAM CONFIGURATION
# ============================================================

TELEGRAM_ENABLED = True

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# 3. EXCHANGE CONNECTION
# ============================================================

def create_exchange():

    return ccxt.bitget({
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap"
        },
        "timeout": 30000
    })


# ============================================================
# 4. TIME FUNCTIONS
# ============================================================

def get_exchange_time(exchange):

    try:

        server_time = exchange.fetch_time()

        if server_time:
            return server_time

    except Exception as e:

        console.print(
            f"[yellow]Server time fallback: {e}[/yellow]"
        )

    return int(time.time() * 1000)


def format_timestamp(timestamp_ms):

    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_latest_closed_candle(exchange, now_ms=None):

    if now_ms is None:
        now_ms = get_exchange_time(exchange)

    timeframe_ms = (
        exchange.parse_timeframe(TIMEFRAME) * 1000
    )

    return (
        (now_ms // timeframe_ms) * timeframe_ms
        - timeframe_ms
    )


# ============================================================
# 5. AUTO TIMEFRAME SCHEDULER
# ============================================================

def wait_for_next_candle(exchange, last_processed=None):

    timeframe_ms = (
        exchange.parse_timeframe(TIMEFRAME) * 1000
    )

    # Jika baru pertama dijalankan,
    # tunggu candle yang sedang berjalan selesai.
    if last_processed is None:

        initial_time = get_exchange_time(exchange)

        target_open = (
            initial_time // timeframe_ms
        ) * timeframe_ms

    else:

        target_open = (
            last_processed + timeframe_ms
        )

    target_close = target_open + timeframe_ms

    console.print(
        Panel(
            f"Timeframe       : {TIMEFRAME}\n"
            f"Target Candle   : {format_timestamp(target_open)}\n"
            f"Expected Close  : {format_timestamp(target_close)}",
            title="RAILWAY AUTO SCHEDULER",
            border_style="cyan"
        )
    )

    while True:

        now_ms = get_exchange_time(exchange)

        latest_closed = get_latest_closed_candle(
            exchange,
            now_ms
        )

        # Pastikan candle sudah close dan buffer terpenuhi.
        if (
            latest_closed >= target_open
            and now_ms >= (
                latest_closed
                + timeframe_ms
                + CLOSE_BUFFER_SECONDS * 1000
            )
        ):

            console.print(
                "\n[bold green]CANDLE CLOSED - START SCANNING[/bold green]"
            )

            console.print(
                f"[green]Candle: {format_timestamp(latest_closed)}[/green]"
            )

            return latest_closed

        remaining = max(
            0,
            (
                target_close
                + CLOSE_BUFFER_SECONDS * 1000
                - now_ms
            ) / 1000
        )

        console.print(
            f"[dim]Waiting: {remaining / 60:.1f} minutes...[/dim]",
            end="\r"
        )

        time.sleep(SCHEDULER_CHECK_SECONDS)


# ============================================================
# 6. TELEGRAM SENDER
# ============================================================

def send_telegram(message):

    if not TELEGRAM_ENABLED:
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        console.print(
            "[bold red]Telegram credentials belum diisi.[/bold red]"
        )

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    # Membagi pesan jika terlalu panjang.
    chunks = []
    current_chunk = ""

    for line in message.split("\n"):

        if len(current_chunk) + len(line) + 1 > 3500:

            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = line

        else:

            if current_chunk:
                current_chunk += "\n"

            current_chunk += line

    if current_chunk:
        chunks.append(current_chunk)

    all_success = True

    for chunk in chunks:

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML"
        }

        try:

            response = requests.post(
                url,
                data=payload,
                timeout=20
            )

            response.raise_for_status()

            result = response.json()

            if result.get("ok"):

                console.print(
                    "[green]Telegram: pesan berhasil dikirim.[/green]"
                )

            else:

                all_success = False

                console.print(
                    f"[red]Telegram API error: {result}[/red]"
                )

        except Exception as e:

            all_success = False

            console.print(
                f"[bold red]Telegram gagal: {e}[/bold red]"
            )

    return all_success


# ============================================================
# 7. TELEGRAM STARTUP CONNECTION TEST
# ============================================================

def telegram_startup_test(exchange):

    if not TELEGRAM_ENABLED:
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID "
            "wajib diisi melalui Railway Variables."
        )

    now_ms = get_exchange_time(exchange)

    timeframe_ms = (
        exchange.parse_timeframe(TIMEFRAME) * 1000
    )

    next_close = (
        (now_ms // timeframe_ms) + 1
    ) * timeframe_ms

    message = (
        "🟢 <b>TELEGRAM CONNECTED</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "BITGET AUTO SCANNER\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "✅ Telegram API: Connected\n"
        "✅ Startup Test: Successful\n"
        "✅ Scanner: Initialized\n"
        "✅ Scheduler: Active\n"
        "\n"
        f"🏦 Exchange: Bitget\n"
        f"📊 Market: USDT Perpetual\n"
        f"⏱ Timeframe: {TIMEFRAME.upper()}\n"
        f"📈 EMA: {EMA_FAST}/{EMA_SLOW}\n"
        f"🔎 Pivot: {PIVOT_LEFT}/{PIVOT_RIGHT}\n"
        "\n"
        "🕒 Next candle close:\n"
        f"{format_timestamp(next_close)}\n"
        "\n"
        "📡 Scanner siap menunggu candle close."
    )

    console.print(
        "\n[cyan]Testing Telegram connection...[/cyan]"
    )

    # Maksimal 3 percobaan.
    for attempt in range(1, 4):

        console.print(
            f"[dim]Telegram test attempt {attempt}/3[/dim]"
        )

        if send_telegram(message):

            console.print(
                Panel(
                    "TELEGRAM CONNECTION SUCCESS\n"
                    "Startup notification berhasil dikirim.",
                    title="TELEGRAM STATUS",
                    border_style="green"
                )
            )

            return True

        time.sleep(10)

    raise RuntimeError(
        "Telegram startup test gagal setelah 3 percobaan. "
        "Periksa token, Chat ID, dan koneksi internet."
    )


# ============================================================
# 8. LOAD SENT SIGNALS
# ============================================================

def load_sent_signals():

    if not os.path.exists(SENT_SIGNALS_FILE):
        return set()

    try:

        with open(
            SENT_SIGNALS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return set(data)

    except Exception as e:

        console.print(
            f"[yellow]Riwayat sinyal gagal dibaca: {e}[/yellow]"
        )

        return set()


# ============================================================
# 9. SAVE SENT SIGNALS
# ============================================================

def save_sent_signals(signals):

    temp_file = SENT_SIGNALS_FILE + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                sorted(signals),
                file,
                indent=4
            )

        os.replace(
            temp_file,
            SENT_SIGNALS_FILE
        )

        return True

    except Exception as e:

        console.print(
            f"[red]Gagal menyimpan riwayat: {e}[/red]"
        )

        return False


# ============================================================
# 10. SIGNAL UNIQUE KEY
# ============================================================

def get_signal_key(item):

    return (
        f"{item['symbol']}|"
        f"{TIMEFRAME}|"
        f"{item['candle_timestamp']}"
    )


# ============================================================
# 11. GET ALL ACTIVE USDT PERPETUAL COINS
# ============================================================

def get_all_coins(exchange):

    console.print(
        "\n[cyan]Mengambil seluruh market USDT perpetual...[/cyan]"
    )

    markets = exchange.load_markets()

    tickers = exchange.fetch_tickers()

    coins = []

    for symbol, market in markets.items():

        if not market.get("active"):
            continue

        if not market.get("swap"):
            continue

        if not market.get("linear"):
            continue

        if market.get("quote") != "USDT":
            continue

        ticker = tickers.get(symbol, {})

        coins.append({
            "symbol": symbol,
            "percentage": ticker.get("percentage")
        })

    return coins


# ============================================================
# 12. FETCH CLOSED CANDLES
# ============================================================

def fetch_ohlcv(
    exchange,
    symbol,
    candle_timestamp
):

    try:

        data = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=CANDLE_LIMIT
        )

        if not data:
            return None

        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        df = (
            df.sort_values("timestamp")
            .drop_duplicates("timestamp")
            .reset_index(drop=True)
        )

        timeframe_ms = (
            exchange.parse_timeframe(TIMEFRAME) * 1000
        )

        # Gunakan candle yang sudah benar-benar close.
        candle_close_time = (
            candle_timestamp + timeframe_ms
        )

        df = df[
            (df["timestamp"] + timeframe_ms)
            <= candle_close_time
        ].copy()

        df.reset_index(drop=True, inplace=True)

        # Pastikan semua koin dianalisis pada candle yang sama.
        if df.empty:
            return None

        if int(df["timestamp"].iloc[-1]) != candle_timestamp:
            return None

        if len(df) < 60:
            return None

        return df

    except Exception as e:

        console.print(
            f"\n[red]Error {symbol}: {e}[/red]"
        )

        return None


# ============================================================
# 13. CALCULATE EMA
# ============================================================

def calculate_ema(df):

    df = df.copy()

    df["ema11"] = df["close"].ewm(
        span=EMA_FAST,
        adjust=False
    ).mean()

    df["ema50"] = df["close"].ewm(
        span=EMA_SLOW,
        adjust=False
    ).mean()

    return df


# ============================================================
# 14. DETECT PIVOTS 2/2
# ============================================================

def detect_pivots(df):

    highs = []
    lows = []

    last_closed = len(df) - 1

    for i in range(
        PIVOT_LEFT,
        last_closed - PIVOT_RIGHT + 1
    ):

        high = df["high"].iloc[i]
        low = df["low"].iloc[i]

        left_highs = df["high"].iloc[
            i - PIVOT_LEFT:i
        ]

        right_highs = df["high"].iloc[
            i + 1:i + PIVOT_RIGHT + 1
        ]

        left_lows = df["low"].iloc[
            i - PIVOT_LEFT:i
        ]

        right_lows = df["low"].iloc[
            i + 1:i + PIVOT_RIGHT + 1
        ]

        if (
            high > left_highs.max()
            and high > right_highs.max()
        ):

            highs.append({
                "index": i,
                "price": high
            })

        if (
            low < left_lows.min()
            and low < right_lows.min()
        ):

            lows.append({
                "index": i,
                "price": low
            })

    return highs, lows


# ============================================================
# 15. CHECK DOWNTREND AND LOWER HIGH
# ============================================================

def check_market_structure(df):

    highs, lows = detect_pivots(df)

    if len(highs) < 2 or len(lows) < 2:
        return None

    previous_high = highs[-2]
    latest_high = highs[-1]

    previous_low = lows[-2]
    latest_low = lows[-1]

    lower_high = (
        latest_high["price"] < previous_high["price"]
    )

    lower_low = (
        latest_low["price"] < previous_low["price"]
    )

    lh_after_ll = (
        latest_high["index"] > latest_low["index"]
    )

    if not (
        lower_high
        and lower_low
        and lh_after_ll
    ):
        return None

    lh_confirmed_index = (
        latest_high["index"] + PIVOT_RIGHT
    )

    return {
        "lh_index": latest_high["index"],
        "lh_confirmed_index": lh_confirmed_index
    }


# ============================================================
# 16. DETECT EMA APPROACH OR FRESH CROSS
# ============================================================

def detect_ema_signal(df, lh_confirmed_index):

    last_closed = len(df) - 1

    if lh_confirmed_index >= last_closed:
        return None

    current = df.iloc[last_closed]
    previous = df.iloc[last_closed - 1]

    ema11 = current["ema11"]
    ema50 = current["ema50"]

    previous_ema11 = previous["ema11"]
    previous_ema50 = previous["ema50"]

    # BARU CROSS
    fresh_cross = (
        previous_ema11 >= previous_ema50
        and ema11 < ema50
    )

    if fresh_cross:
        return "BARU CROSS"

    # MENDEKATI CROSS
    if ema11 <= ema50:
        return None

    distance_now = (
        (ema11 - ema50) / abs(ema50)
    )

    if distance_now > MAX_EMA_DISTANCE:
        return None

    distances = []

    start = (
        last_closed - APPROACH_CANDLES + 1
    )

    if start < 0:
        return None

    for i in range(start, last_closed + 1):

        fast = df["ema11"].iloc[i]
        slow = df["ema50"].iloc[i]

        if fast <= slow:
            return None

        distance = (
            (fast - slow) / abs(slow)
        )

        distances.append(distance)

    getting_closer = all(
        distances[i] < distances[i - 1]
        for i in range(1, len(distances))
    )

    if getting_closer:
        return "MENDEKATI CROSS"

    return None


# ============================================================
# 17. ANALYZE COIN
# ============================================================

def analyze_coin(df):

    if df is None or len(df) < 60:
        return None

    df = calculate_ema(df)

    structure = check_market_structure(df)

    if structure is None:
        return None

    signal = detect_ema_signal(
        df,
        structure["lh_confirmed_index"]
    )

    if signal is None:
        return None

    return {
        "status": signal,
        "candle_timestamp": int(
            df["timestamp"].iloc[-1]
        )
    }


# ============================================================
# 18. DISPLAY RESULTS
# ============================================================

def display_results(results):

    table = Table(
        title="BITGET BEARISH EMA SCANNER",
        box=box.ROUNDED,
        show_lines=True
    )

    table.add_column("COIN", style="cyan")
    table.add_column("24H GAIN", justify="right")
    table.add_column("STATUS", justify="center")

    priority = {
        "BARU CROSS": 1,
        "MENDEKATI CROSS": 2
    }

    sorted_results = sorted(
        results,
        key=lambda x: priority.get(x["status"], 99)
    )

    for item in sorted_results:

        status = item["status"]

        color = (
            "bold red"
            if status == "BARU CROSS"
            else "yellow"
        )

        percentage = item["percentage"]

        gain = (
            f"{percentage:+.2f}%"
            if percentage is not None
            else "N/A"
        )

        table.add_row(
            item["symbol"],
            gain,
            f"[{color}]{status}[/{color}]"
        )

    console.print(table)

    console.print(
        f"\n[green]Total kandidat: {len(results)}[/green]"
    )


# ============================================================
# 19. BUILD TELEGRAM REPORT
# ============================================================

def build_telegram_report(
    results,
    new_results,
    total_coins,
    analyzed_coins,
    unavailable_coins,
    candle_timestamp
):

    now = datetime.now(
        timezone.utc
    ).strftime("%d-%m-%Y %H:%M:%S UTC")

    baru_cross = [
        x for x in new_results
        if x["status"] == "BARU CROSS"
    ]

    mendekati = [
        x for x in new_results
        if x["status"] == "MENDEKATI CROSS"
    ]

    message = [
        "📊 <b>BITGET BEARISH EMA SCANNER</b>",
        "",
        "🟢 <b>SCAN SELESAI</b>",
        "",
        f"🕒 Scan Time: {now}",
        f"🕯 Candle: {format_timestamp(candle_timestamp)}",
        f"⏱ Timeframe: {TIMEFRAME.upper()}",
        f"📈 EMA: {EMA_FAST}/{EMA_SLOW}",
        f"🔎 Pivot: {PIVOT_LEFT}/{PIVOT_RIGHT}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "<b>SCAN STATISTICS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"Total Market: {total_coins}",
        f"Data Berhasil: {analyzed_coins}",
        f"Data Tidak Tersedia: {unavailable_coins}",
        f"Total Kandidat: {len(results)}",
        f"Sinyal Baru: {len(new_results)}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"🔴 <b>BARU CROSS ({len(baru_cross)})</b>",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if baru_cross:

        for item in baru_cross:

            percentage = item["percentage"]

            gain = (
                f"{percentage:+.2f}%"
                if percentage is not None
                else "N/A"
            )

            symbol = html.escape(item["symbol"])

            message.append(
                f"• <b>{symbol}</b> | 24H: {gain}"
            )

    else:

        message.append("Tidak ada sinyal baru.")

    message.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"🟡 <b>MENDEKATI CROSS ({len(mendekati)})</b>",
        "━━━━━━━━━━━━━━━━━━"
    ])

    if mendekati:

        for item in mendekati:

            percentage = item["percentage"]

            gain = (
                f"{percentage:+.2f}%"
                if percentage is not None
                else "N/A"
            )

            symbol = html.escape(item["symbol"])

            message.append(
                f"• <b>{symbol}</b> | 24H: {gain}"
            )

    else:

        message.append("Tidak ada sinyal baru.")

    if not new_results and results:

        message.extend([
            "",
            "ℹ️ Kandidat sudah pernah dikirim "
            "untuk candle yang sama."
        ])

    if not results:

        message.extend([
            "",
            "ℹ️ Belum ada koin yang memenuhi kondisi."
        ])

    message.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 Auto Scanner: RUNNING",
        "📡 Telegram: Connected",
        "🏦 Exchange: Bitget",
        "",
        "<i>BITGET AUTO SCANNER</i>"
    ])

    return "\n".join(message)


# ============================================================
# 20. RUN SCANNER
# ============================================================

def run_scanner(exchange, candle_timestamp):

    coins = get_all_coins(exchange)

    console.print(
        Panel(
            f"Exchange       : Bitget\n"
            f"Market         : USDT-M Perpetual\n"
            f"Total Coins    : {len(coins)}\n"
            f"Timeframe      : {TIMEFRAME}\n"
            f"Closed Candle  : {format_timestamp(candle_timestamp)}\n"
            f"Pivot          : {PIVOT_LEFT} Left / {PIVOT_RIGHT} Right\n"
            f"EMA            : {EMA_FAST}/{EMA_SLOW}\n"
            f"Near Cross     : {MAX_EMA_DISTANCE * 100:.2f}%\n"
            f"Structure      : Downtrend + Lower High",
            title="RAILWAY SCANNER SETTINGS",
            border_style="cyan"
        )
    )

    results = []

    analyzed_coins = 0
    unavailable_coins = 0

    for index, coin in enumerate(coins, start=1):

        symbol = coin["symbol"]

        console.print(
            f"[dim][{index}/{len(coins)}] Scanning {symbol}...[/dim]",
            end="\r"
        )

        df = fetch_ohlcv(
            exchange,
            symbol,
            candle_timestamp
        )

        if df is None:

            unavailable_coins += 1

        else:

            analyzed_coins += 1

            analysis = analyze_coin(df)

            if analysis:

                results.append({
                    "symbol": symbol,
                    "percentage": coin["percentage"],
                    "status": analysis["status"],
                    "candle_timestamp": analysis["candle_timestamp"]
                })

        time.sleep(REQUEST_DELAY)

    console.print("\n")

    if results:

        display_results(results)

    else:

        console.print(
            "[yellow]Belum ada koin yang memenuhi kondisi.[/yellow]"
        )

    # ========================================================
    # ANTI DUPLICATE
    # ========================================================

    sent_signals = load_sent_signals()

    new_results = []

    for item in results:

        signal_key = get_signal_key(item)

        if signal_key not in sent_signals:
            new_results.append(item)

    # ========================================================
    # BUILD TELEGRAM REPORT
    # ========================================================

    telegram_message = build_telegram_report(
        results=results,
        new_results=new_results,
        total_coins=len(coins),
        analyzed_coins=analyzed_coins,
        unavailable_coins=unavailable_coins,
        candle_timestamp=candle_timestamp
    )

    # ========================================================
    # SEND TELEGRAM
    # ========================================================

    success = send_telegram(telegram_message)

    # Simpan riwayat hanya jika seluruh laporan terkirim.
    if success:

        for item in new_results:

            sent_signals.add(
                get_signal_key(item)
            )

        if not save_sent_signals(sent_signals):

            console.print(
                "[bold red]Peringatan: riwayat sinyal belum tersimpan.[/bold red]"
            )

            return False

        return True

    return False


# ============================================================
# 21. MAIN - RAILWAY BACKGROUND WORKER
# ============================================================

def main():

    exchange = create_exchange()

    last_processed = None

    # Menyimpan candle yang sedang menunggu pengiriman.
    pending_candle = None

    try:

        console.print(
            Panel(
                f"Platform       : Railway\n"
                f"Service        : Background Worker\n"
                f"Exchange       : Bitget\n"
                f"Market         : USDT-M Perpetual\n"
                f"Timeframe      : {TIMEFRAME}\n"
                f"EMA            : {EMA_FAST}/{EMA_SLOW}\n"
                f"Pivot          : {PIVOT_LEFT}/{PIVOT_RIGHT}\n"
                f"Telegram       : ON\n"
                f"Auto Scanner   : ON\n"
                f"Anti Duplicate : ON\n"
                f"Data Directory : {DATA_DIR}",
                title="BITGET RAILWAY AUTO SCANNER",
                border_style="green"
            )
        )

        # ====================================================
        # TELEGRAM STARTUP TEST
        # ====================================================

        telegram_startup_test(exchange)

        # ====================================================
        # MAIN LOOP
        # ====================================================

        while True:

            try:

                # Jika belum ada candle yang menunggu,
                # tunggu candle timeframe berikutnya.
                if pending_candle is None:

                    pending_candle = wait_for_next_candle(
                        exchange,
                        last_processed
                    )

                console.print(
                    "\n[bold green]START SCANNING[/bold green]"
                )

                console.print(
                    f"[cyan]Candle: {format_timestamp(pending_candle)}[/cyan]"
                )

                success = run_scanner(
                    exchange,
                    pending_candle
                )

                if success:

                    last_processed = pending_candle

                    pending_candle = None

                    console.print(
                        Panel(
                            f"Scanner Status : RUNNING\n"
                            f"Telegram       : CONNECTED\n"
                            f"Timeframe      : {TIMEFRAME}\n"
                            f"Last Scan      : {format_timestamp(last_processed)}\n"
                            f"Next Action    : Wait for next candle",
                            title="RAILWAY SCANNER HEALTH",
                            border_style="green"
                        )
                    )

                else:

                    console.print(
                        "[bold red]Telegram/report gagal. "
                        "Candle akan dicoba kembali.[/bold red]"
                    )

                    time.sleep(30)

            except KeyboardInterrupt:

                raise

            except Exception as e:

                console.print(
                    f"\n[bold red]Scanner error: {e}[/bold red]"
                )

                console.print(
                    "[yellow]Retry dalam 30 detik...[/yellow]"
                )

                time.sleep(30)

    finally:

        exchange.close()


# ============================================================
# 22. PROGRAM ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        console.print(
            "\n[bold red]Scanner dihentikan.[/bold red]"
        )

    except Exception as e:

        console.print(
            f"\n[bold red]FATAL ERROR: {e}[/bold red]"
        )

        raise
