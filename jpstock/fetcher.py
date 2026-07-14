"""yfinance を使って日本株の情報を取得する層."""

from __future__ import annotations

import re
from typing import Optional

from .models import StockSummary

# 数字だけ（例: 7203）や 7203.JP 等を Yahoo Finance の日本株形式 7203.T に正規化する。
# 日本株コードは先頭が数字の 4 文字（従来の 4 桁数字 "7203" に加え、
# 2024 年以降の英数字コード "135A" 等にも対応）。
_CODE_RE = re.compile(r"^(?P<code>\d[0-9A-Z]{3})(?:\.(?:T|JP|TYO))?$", re.IGNORECASE)


def normalize_ticker(raw: str) -> str:
    """入力された銘柄コードを Yahoo Finance 形式（例: 7203.T）に正規化する.

    - "7203"       -> "7203.T"
    - "7203.T"     -> "7203.T"
    - "7203.JP"    -> "7203.T"
    - "^N225"      -> "^N225"（指数などはそのまま）
    - "AAPL"       -> "AAPL"（米国株などはそのまま）
    """
    s = raw.strip().upper()
    if not s:
        raise ValueError("空の銘柄コードが指定されました")
    m = _CODE_RE.match(s)
    if m:
        return f"{m.group('code')}.T"
    return s


def code_of(ticker: str) -> str:
    """正規化済みティッカーから表示用のコード部分を取り出す（7203.T -> 7203）."""
    return ticker.split(".")[0]


def _num(value) -> Optional[float]:
    """None / NaN / 非数値を安全に float | None へ変換する."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def build_summary_from_ticker(ticker_obj, ticker: str, period: str = "6mo") -> StockSummary:
    """yfinance.Ticker 互換オブジェクトから StockSummary を組み立てる.

    ticker_obj は `.info`（dict）と `.history(period=...)`（DataFrame）を
    持つオブジェクト。テスト時はモックを渡せる。
    """
    summary = StockSummary(ticker=ticker, code=code_of(ticker))

    try:
        info = ticker_obj.info or {}
    except Exception as exc:  # noqa: BLE001 - 取得失敗はエラーとして記録
        info = {}
        summary.error = f"info 取得失敗: {exc}"

    try:
        hist = ticker_obj.history(period=period)
    except Exception as exc:  # noqa: BLE001
        hist = None
        if summary.error is None:
            summary.error = f"history 取得失敗: {exc}"

    if hist is not None and not hist.empty:
        summary.history = hist
        last = hist.iloc[-1]
        summary.price = _num(last.get("Close"))
        summary.open = _num(last.get("Open"))
        summary.day_high = _num(last.get("High"))
        summary.day_low = _num(last.get("Low"))
        summary.volume = _num(last.get("Volume"))
        if len(hist) >= 2:
            summary.previous_close = _num(hist.iloc[-2].get("Close"))

    # info からの上書き・補完
    summary.name = info.get("shortName") or info.get("longName") or summary.name
    summary.sector = info.get("sector") or summary.sector
    summary.industry = info.get("industry") or summary.industry
    summary.currency = info.get("currency") or summary.currency
    summary.summary = info.get("longBusinessSummary") or summary.summary

    if summary.price is None:
        summary.price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    if summary.previous_close is None:
        summary.previous_close = _num(
            info.get("regularMarketPreviousClose") or info.get("previousClose")
        )

    summary.week52_high = _num(info.get("fiftyTwoWeekHigh"))
    summary.week52_low = _num(info.get("fiftyTwoWeekLow"))
    summary.market_cap = _num(info.get("marketCap"))
    summary.per = _num(info.get("trailingPE"))
    summary.pbr = _num(info.get("priceToBook"))
    summary.dividend_yield = _num(info.get("dividendYield"))
    summary.eps = _num(info.get("trailingEps"))

    # dividendYield は yfinance のバージョンにより「率(0.025)」か「%(2.5)」で
    # 返ってくることがあるため、明らかに % 表記のものは率へ寄せる。
    if summary.dividend_yield is not None and summary.dividend_yield > 1:
        summary.dividend_yield = summary.dividend_yield / 100.0

    if summary.name is None and summary.error is None and summary.price is None:
        summary.error = "データが見つかりませんでした（銘柄コードを確認してください）"

    return summary


def fetch(ticker_raw: str, period: str = "6mo") -> StockSummary:
    """1 銘柄を Yahoo Finance から取得する（要ネットワーク）."""
    import yfinance as yf  # 遅延 import: ネットワーク不要のテストで読み込ませない

    ticker = normalize_ticker(ticker_raw)
    try:
        t = yf.Ticker(ticker)
    except Exception as exc:  # noqa: BLE001
        s = StockSummary(ticker=ticker, code=code_of(ticker))
        s.error = f"取得失敗: {exc}"
        return s
    return build_summary_from_ticker(t, ticker, period=period)


def fetch_many(tickers: list[str], period: str = "6mo") -> list[StockSummary]:
    """複数銘柄をまとめて取得する."""
    return [fetch(t, period=period) for t in tickers]
