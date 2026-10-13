"""株価（直近終値）と期間内の株式分割を取得する層.

yfinance でまとめて取得するか、手元の CSV（code,price,date）を読む。
"""

from __future__ import annotations

import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional


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


_LIMIT_WORDS = ("rate limit", "too many requests")


class _LogCollector(logging.Handler):
    """yfinance がログにだけ出す取得エラー（アクセス制限など）を拾う."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _rate_limited(yf, missing: list[str], messages: list[str]) -> list[str]:
    """取得できなかった銘柄のうち、「アクセスが多すぎる」と断られたもの."""
    shared = getattr(yf, "shared", None) or sys.modules.get("yfinance.shared")
    errors = getattr(shared, "_ERRORS", None) or {}
    hit = [t for t in missing if any(w in str(errors.get(t, "")).lower() for w in _LIMIT_WORDS)]
    if hit:
        return hit
    # yfinance 1.x はエラーをログに出すだけなので、ログに制限のメッセージがあれば取れなかった銘柄すべてを対象にする
    if any(w in m.lower() for m in messages for w in _LIMIT_WORDS):
        return list(missing)
    return []


def _load_json(path: Optional[Path]) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save_json(path: Optional[Path], data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def fetch_prices(
    codes: list[str],
    period: str = "2y",
    chunk: int = 50,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    cache_dir: Optional[Path] = None,
    pause: float = 2.0,
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    threads: int = 4,
) -> dict[str, PriceInfo]:
    """Yahoo Finance から直近終値と分割履歴をまとめて取得する（要ネットワーク）.

    「アクセスが多すぎる」と断られた銘柄は、待ち時間を延ばしながら取り直す。
    cache_dir を渡すと、その日に取得した分を保存し、再実行では取り直さない。
    """
    import yfinance as yf

    path = Path(cache_dir) / f"prices_{date.today().isoformat()}.json" if cache_dir else None
    cached = _load_json(path)
    prices: dict[str, PriceInfo] = {
        c: PriceInfo(price=v[0], as_of=date.fromisoformat(v[1]), splits=[(date.fromisoformat(d), r) for d, r in v[2]])
        for c, v in cached.items()
    }
    todo = [c for c in codes if c not in prices]
    if cached:
        log(f"  株価 {len(codes) - len(todo)} 銘柄はキャッシュを使用")
    for i in range(0, len(todo), chunk):
        tickers = [f"{c}.T" for c in todo[i:i + chunk]]
        log(f"  株価 {i + len(tickers)}/{len(todo)} 銘柄")
        for attempt in range(retries + 1):
            collector = _LogCollector()
            yf_logger = logging.getLogger("yfinance")
            yf_logger.addHandler(collector)
            try:
                df = yf.download(
                    tickers, period=period, interval="1d", group_by="ticker",
                    actions=True, auto_adjust=False, progress=False, threads=threads,
                )
            finally:
                yf_logger.removeHandler(collector)
            got = parse_download_frame(df, tickers)
            prices.update(got)
            for code, info in got.items():
                cached[code] = [info.price, info.as_of.isoformat(), [[d.isoformat(), r] for d, r in info.splits]]
            limited = _rate_limited(yf, [t for t in tickers if t.removesuffix(".T") not in got], collector.messages)
            if not limited or attempt == retries:
                if limited:
                    log(f"  株価: {len(limited)} 銘柄はアクセス制限で取得できず")
                break
            wait = 30 * 2 ** attempt
            log(f"  株価: アクセス制限のため {wait} 秒待って {len(limited)} 銘柄を取り直す")
            sleep(wait)
            tickers = limited
        _save_json(path, cached)
        sleep(pause)
    return prices


def fetch_split_history(
    codes: list[str],
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    cache_dir: Optional[Path] = None,
    pause: float = 0.3,
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[tuple[date, float]]]:
    """Yahoo Finance から全期間の分割・併合の履歴（権利落ち日, 倍率）を取得する（要ネットワーク）."""
    import yfinance as yf

    path = Path(cache_dir) / f"splits_{date.today().isoformat()}.json" if cache_dir else None
    cached = _load_json(path)
    out: dict[str, list[tuple[date, float]]] = {
        c: [(date.fromisoformat(d), r) for d, r in v] for c, v in cached.items()
    }
    todo = [c for c in codes if c not in out]
    for n, code in enumerate(todo, 1):
        if n % 50 == 0:
            log(f"  分割履歴 {n}/{len(todo)} 銘柄")
        for attempt in range(retries + 1):
            try:
                series = yf.Ticker(f"{code}.T").splits
            except Exception as exc:  # noqa: BLE001 - 取れなければ株式数の変化だけで判定する
                text = f"{type(exc).__name__} {exc}".lower()
                if ("ratelimit" in text or "too many requests" in text) and attempt < retries:
                    sleep(30 * 2 ** attempt)
                    continue
                break
            out[code] = [(idx.date(), float(r)) for idx, r in series.items() if r > 0 and r != 1]
            cached[code] = [[d.isoformat(), r] for d, r in out[code]]
            break
        if n % 20 == 0:
            _save_json(path, cached)
        sleep(pause)
    _save_json(path, cached)
    return out
