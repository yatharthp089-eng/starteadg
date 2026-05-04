import os
import time
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd
import requests
import feedparser
from textblob import TextBlob
from telegram import Bot
import ta

# ===== CONFIG =====
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SCAN_INTERVAL_SECONDS = 3600

bot = Bot(token="starteadgebot")

# ===== NIFTY 50 (SHORT LIST FOR TEST) =====
stocks = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    "ITC.NS","SBIN.NS","LT.NS","AXISBANK.NS","KOTAKBANK.NS"
]

# ===== FAST SCAN =====
def fast_scan():
    results = []

    for stock in stocks:
        try:
            print(f"Scanning {stock}...")

            df = yf.download(stock, period="5d", interval="1d", progress=False)

            # ❌ ERROR LINE FIX #1
            if df.empty or len(df) < 3:
                continue

            # ❌ ERROR LINE FIX #2 (convert to values)
            close = df["Close"].values
            volume = df["Volume"].values

            momentum = (close[-1] - close[-2]) / close[-2]

            avg_vol = volume.mean()
            vol_spike = (volume[-1] - avg_vol) / avg_vol

            score = momentum + vol_spike

            results.append({"stock": stock, "score": score})

            time.sleep(0.5)

        except Exception as e:
            print(f"Error in {stock}: {e}")

    # ❌ ERROR LINE FIX #3 (empty DataFrame protection)
    if not results:
        print("⚠️ No data fetched")
        return pd.DataFrame(columns=["stock","score"])

    df = pd.DataFrame(results)
    return df.sort_values(by="score", ascending=False).head(5)


# ===== NEWS =====
def get_news(stock):
    news = []

    try:
        url = f"https://newsapi.org/v2/everything?q={stock}&apiKey={NEWS_API_KEY}"
        data = requests.get(url).json()
        news += [a['title'] for a in data.get('articles', [])[:3]]
    except:
        pass

    try:
        url = f"https://news.google.com/rss/search?q={stock}"
        feed = feedparser.parse(url)
        news += [entry.title for entry in feed.entries[:3]]
    except:
        pass

    return news


# ===== SENTIMENT =====
def get_sentiment(news):
    if not news:
        return 0
    return sum(TextBlob(n).sentiment.polarity for n in news) / len(news)


# ===== MARKET HOURS =====
INDIA_TZ = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)


def is_india_market_open():
    now = datetime.now(tz=ZoneInfo("UTC")).astimezone(INDIA_TZ)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def next_market_open_seconds():
    now = datetime.now(tz=ZoneInfo("UTC")).astimezone(INDIA_TZ)
    today = now.date()

    if now.weekday() >= 5:
        days_ahead = 7 - now.weekday()
        next_open_date = today + timedelta(days=days_ahead)
        next_open_dt = datetime.combine(next_open_date, MARKET_OPEN, tzinfo=INDIA_TZ)
        return max(0, (next_open_dt - now).total_seconds())

    if now.time() < MARKET_OPEN:
        next_open_dt = datetime.combine(today, MARKET_OPEN, tzinfo=INDIA_TZ)
        return max(0, (next_open_dt - now).total_seconds())

    if now.time() > MARKET_CLOSE:
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        next_open_dt = datetime.combine(next_day, MARKET_OPEN, tzinfo=INDIA_TZ)
        return max(0, (next_open_dt - now).total_seconds())

    return 0


# ===== DEEP SCAN =====
def deep_scan(filtered_df):
    results = []

    if filtered_df.empty:
        return pd.DataFrame()

    for _, row in filtered_df.iterrows():
        stock = row["stock"]

        try:
            df = yf.download(stock, period="10d", interval="1d", progress=False)

            # ❌ ERROR LINE FIX #4
            if df.empty or len(df) < 5:
                continue

            # ❌ ERROR LINE FIX #5 (important fix for your error)
            close = df["Close"].values
            volume = df["Volume"].values

            momentum = (close[-1] - close[-3]) / close[-3]

            avg_vol = volume.mean()
            vol_strength = (volume[-1] - avg_vol) / avg_vol

            # ❌ ERROR LINE FIX #6 (force float)
            rsi_series = ta.momentum.RSIIndicator(df["Close"]).rsi()
            rsi = float(rsi_series.iloc[-1])

            news = get_news(stock)
            sentiment = get_sentiment(news)

            # RSI logic
            rsi_score = 0
            if rsi < 30:
                rsi_score = 0.3
            elif rsi > 70:
                rsi_score = -0.3

            final_score = (
                sentiment * 0.4 +
                momentum * 0.3 +
                vol_strength * 0.2 +
                rsi_score
            )

            results.append({
                "stock": stock,
                "score": round(float(final_score),3),
                "rsi": round(rsi,1),
                "sentiment": round(sentiment,2)
            })

        except Exception as e:
            print(f"Deep scan error in {stock}: {e}")

    # ❌ ERROR LINE FIX #7
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    return df.sort_values(by="score", ascending=False).head(3)


# ===== TELEGRAM =====
def send_signal(df):
    if df.empty:
        print("⚠️ No signals")
        return

    message = "🚀 AI STOCK SCANNER\n\n"

    for _, row in df.iterrows():

        if row["score"] > 0.4:
            signal = "🟢 STRONG BUY"
        elif row["score"] > 0.2:
            signal = "🟢 BUY"
        elif row["score"] < -0.4:
            signal = "🔴 STRONG SELL"
        elif row["score"] < -0.2:
            signal = "🔴 SELL"
        else:
            signal = "⚪ HOLD"

        message += (
            f"{row['stock']}\n"
            f"Signal: {signal}\n"
            f"Score: {row['score']}\n"
            f"RSI: {row['rsi']}\n"
            f"Sentiment: {row['sentiment']}\n"
            f"-----------------\n"
        )

    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"Telegram error: {e}")


# ===== MAIN LOOP =====
while True:
    print("\n🔄 Running Scanner...")

    try:
        top = fast_scan()

        if top.empty:
            print("Retrying...")
            time.sleep(60)
            continue

        final = deep_scan(top)
        send_signal(final)

    except Exception as e:
        print(f"Main loop error: {e}")

    if not is_india_market_open():
        wait_sec = next_market_open_seconds()
        hours = int(wait_sec // 3600)
        minutes = int((wait_sec % 3600) // 60)
        print(f"Indian market closed. Sleeping until next open: {hours}h {minutes}m")
        time.sleep(wait_sec if wait_sec > 0 else SCAN_INTERVAL_SECONDS)
        continue

    print(f"Waiting {SCAN_INTERVAL_SECONDS // 60} minutes until next hourly scan...")
    time.sleep(SCAN_INTERVAL_SECONDS)