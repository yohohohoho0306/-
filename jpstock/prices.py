"""株価（直近終値）と期間内の株式分割を取得する層.

yfinance でまとめて取得するか、手元の CSV（code,price,date）を読む。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable


@dataclass
class PriceInfo:
    price: float
    as_of: date
    splits: list[tuple[date, float]] = field(default_factory=list)  # (日付, 倍率) 例: 2.0 = 1→2 分割

    def split_factor_after(self, day: date) -> float:
        """day より後に行われた分割・併合の倍率の積."""
        factor = 1.0
        for d, ratio in self.splits:
            if d > day and ratio > 0:
                factor *= ratio
        return factor


def load_prices_csv(path: str | Path) -> dict[str, PriceInfo]:
    """code,price,date の CSV を読む（date は YYYY-MM-DD。見出し行必須）."""
    prices: dict[str, PriceInfo] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("code") or "").strip().upper().removesuffix(".T")
            try:
                price = float((row.get("price") or "").replace(",", ""))
                as_of = date.fromisoformat((row.get("date") or "").strip())
            except ValueError:
                continue
            if code:
                prices[code] = PriceInfo(price=price, as_of=as_of)
    return prices


def _frame_for(df, ticker: str):
    import pandas as pd

    if isinstance(df.columns, pd.MultiIndex):
        if ticker in df.columns.get_level_values(0):
            return df[ticker]
        if ticker in df.columns.get_level_values(1):
            return df.xs(ticker, axis=1, level=1)
        return None
    return df


def parse_download_frame(df, tickers: Iterable[str]) -> dict[str, PriceInfo]:
    """yfinance.download(group_by="ticker", actions=True) の結果を PriceInfo にする."""
    out: dict[str, PriceInfo] = {}
    if df is None or getattr(df, "empty", True):
        return out
    for ticker in tickers:
        frame = _frame_for(df, ticker)
        if frame is None or "Close" not in frame:
            continue
        close = frame["Close"].dropna()
        if close.empty:
            continue
        splits = []
        if "Stock Splits" in frame:
            s = frame["Stock Splits"].dropna()
            for idx, ratio in s[(s > 0) & (s != 1)].items():
                splits.append((idx.date(), float(ratio)))
        out[ticker.removesuffix(".T")] = PriceInfo(
            price=float(close.iloc[-1]), as_of=close.index[-1].date(), splits=splits
        )
    return out


def fetch_prices(
    codes: list[str],
    period: str = "2y",
    chunk: int = 100,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> dict[str, PriceInfo]:
    """Yahoo Finance から直近終値と分割履歴をまとめて取得する（要ネットワーク）."""
    import yfinance as yf

    prices: dict[str, PriceInfo] = {}
    for i in range(0, len(codes), chunk):
        tickers = [f"{c}.T" for c in codes[i:i + chunk]]
        log(f"  株価 {i + len(tickers)}/{len(codes)} 銘柄")
        df = yf.download(
            tickers, period=period, interval="1d", group_by="ticker",
            actions=True, auto_adjust=False, progress=False, threads=True,
        )
        prices.update(parse_download_frame(df, tickers))
    return prices



def fetch_split_history(
    codes: list[str],
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> dict[str, list[tuple[date, float]]]:
    """Yahoo Finance から全期間の分割・併合の履歴（権利落ち日, 倍率）を取得する（要ネットワーク）."""
    import yfinance as yf

    out: dict[str, list[tuple[date, float]]] = {}
    for n, code in enumerate(codes, 1):
        if n % 50 == 0:
            log(f"  分割履歴 {n}/{len(codes)} 銘柄")
        for _ in range(2):
            try:
                series = yf.Ticker(f"{code}.T").splits
            except Exception:  # noqa: BLE001 - 取れなければ株式数の変化だけで判定する
                continue
            out[code] = [(idx.date(), float(r)) for idx, r in series.items() if r > 0 and r != 1]
            break
    return out
