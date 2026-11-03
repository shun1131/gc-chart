"""GCチャート用データを作る。

- 母集団: Binance現物のUSDTペアから、出来高上位 UNIVERSE_SIZE 銘柄(ステーブル等は除外)
- rate USD: 各銘柄のUSDT建て終値で「短期SMA > 長期SMA」の銘柄の割合
- rate BTC: 各銘柄の終値をBTCUSDTで割ったBTC建て価格で同じ判定をした割合
- 併せて BTCUSD / ETHUSD / Fear & Greed / Russell2000 / S&P600 を出力する

外部ライブラリなし(標準ライブラリのみ)。出力: site/data.json
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BINANCE = "https://data-api.binance.vision/api/v3"
DAYS = 1500  # 取得日数(表示の最大期間 + 長期SMAの助走)
UNIVERSE_SIZE = 100
PERIOD_PAIRS = [(7, 25), (5, 20), (10, 30), (25, 75)]  # (短期, 長期)

# 価格がほぼ動かない・指数連動などGC判定に意味のない銘柄
EXCLUDE = {
    "BTC", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "AEUR", "EURI",
    "USDE", "XUSD", "USD1", "RLUSD", "PYUSD", "BFUSD", "UST", "USTC", "PAXG",
    "XAUT", "WBTC", "WBETH", "BNSOL", "SUSD", "GBP", "TRY", "BRL",
}

OUT = Path(__file__).resolve().parent.parent / "site" / "data.json"


def get_json(url: str, retries: int = 3):
    req = urllib.request.Request(url, headers={"User-Agent": "gc-chart/1.0"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - 失敗は再試行して最後に投げる
            if i == retries - 1:
                raise
            print(f"  retry {url[:80]}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))


def day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def klines(symbol: str, days: int = DAYS) -> dict[str, float]:
    """日足終値を {日付: 終値} で返す。未確定の当日足は除く。"""
    out: dict[str, float] = {}
    end = None
    remaining = days
    while remaining > 0:
        limit = min(1000, remaining)
        url = f"{BINANCE}/klines?symbol={symbol}&interval=1d&limit={limit}"
        if end is not None:
            url += f"&endTime={end}"
        rows = get_json(url)
        if not rows:
            break
        for r in rows:
            out[day_key(r[0])] = float(r[4])
        remaining -= len(rows)
        if len(rows) < limit:
            break
        end = rows[0][0] - 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out.pop(today, None)
    return out


def pick_universe() -> list[str]:
    info = get_json(f"{BINANCE}/exchangeInfo?permissions=SPOT")
    bases = {
        s["baseAsset"]
        for s in info["symbols"]
        if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"
    }
    bases -= EXCLUDE
    # 漢字名のミームコイン等はURLに乗らないので英数字の銘柄だけにする
    bases = {b for b in bases if b.isascii() and b.isalnum()}
    tickers = get_json(f"{BINANCE}/ticker/24hr?type=MINI")
    vol = {t["symbol"]: float(t["quoteVolume"]) for t in tickers}
    ranked = sorted(bases, key=lambda b: vol.get(b + "USDT", 0), reverse=True)
    return ranked[:UNIVERSE_SIZE]


def sma_above(series: list[float | None], short: int, long: int) -> list[bool | None]:
    """各日について 短期SMA > 長期SMA なら True。データ不足なら None。"""
    res: list[bool | None] = []
    for i in range(len(series)):
        if i + 1 < long:
            res.append(None)
            continue
        window = series[i + 1 - long : i + 1]
        if any(v is None for v in window):
            res.append(None)
            continue
        s = sum(window[-short:]) / short
        lg = sum(window) / long
        res.append(s > lg)
    return res


def ratio(flags_by_coin: list[list[bool | None]], n_days: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(n_days):
        vals = [f[i] for f in flags_by_coin if f[i] is not None]
        out.append(round(sum(vals) / len(vals), 4) if len(vals) >= 10 else None)
    return out


def fear_greed() -> dict[str, float]:
    d = get_json(f"https://api.alternative.me/fng/?limit={DAYS}")
    return {day_key(int(x["timestamp"]) * 1000): int(x["value"]) / 100 for x in d["data"]}


def yahoo(symbol: str) -> dict[str, float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    return {
        day_key(ts * 1000): round(c, 2)
        for ts, c in zip(res["timestamp"], closes)
        if c is not None
    }


def ffill(src: dict[str, float], dates: list[str]) -> list[float | None]:
    """休場日(土日祝)は直前の値で埋める。線が途切れないようにするため。"""
    out, last = [], None
    for d in dates:
        last = src.get(d, last)
        out.append(last)
    return out


def safe(fn, *args) -> dict:
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - 補助系列は欠けても全体を止めない
        print(f"WARN {fn.__name__}{args}: {e}", file=sys.stderr)
        return {}


def main() -> None:
    universe = pick_universe()
    print(f"universe: {len(universe)} coins", file=sys.stderr)

    btc = klines("BTCUSDT")
    eth = klines("ETHUSDT")
    dates = sorted(btc)[-DAYS:]

    with ThreadPoolExecutor(max_workers=8) as ex:
        coin_prices = list(ex.map(lambda b: klines(b + "USDT"), universe))

    usd_series = [[p.get(d) for d in dates] for p in coin_prices]
    btc_series = [
        [(p[d] / btc[d]) if d in p and d in btc else None for d in dates]
        for p in coin_prices
    ]

    rates = {}
    for short, long in PERIOD_PAIRS:
        key = f"{short}-{long}"
        rates[key] = {
            "usd": ratio([sma_above(s, short, long) for s in usd_series], len(dates)),
            "btc": ratio([sma_above(s, short, long) for s in btc_series], len(dates)),
        }

    fng = safe(fear_greed)
    rut = safe(yahoo, "%5ERUT")
    sp600 = safe(yahoo, "%5ESP600")

    data = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "universe": universe,
        "dates": dates,
        "rates": rates,
        "btcusd": [btc.get(d) for d in dates],
        "ethusd": [eth.get(d) for d in dates],
        "fng": [fng.get(d) for d in dates],
        "rut2000": ffill(rut, dates),
        "sp600": ffill(sp600, dates),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote {OUT} ({len(dates)} days, {dates[0]}..{dates[-1]})", file=sys.stderr)


if __name__ == "__main__":
    main()
