"""複数の有価証券報告書をつないで 10 期分の系列を作る層（ネットワーク不要）.

1 通の有価証券報告書には 5 期分しか載っていないため、新しい報告書と
4〜5 年前の報告書を重ねて 10 期分にする。

株式分割・併合の扱い:
- EPS / BPS は、重複する期の値の比から古い報告書の値を新しい基準に合わせる。
- 1 株配当は報告書上で遡って修正されないため、期末発行済株式総数の
  「きりのよい倍率」での増減を分割・併合とみなし、それより前の期を割り戻す。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from statistics import median
from typing import Optional

from .xbrl import AnnualReport, FiscalPeriod

_BASE_RATIOS = [1.5, 2, 3, 4, 5, 10, 20, 50, 100]
SPLIT_RATIOS = sorted(set(_BASE_RATIOS + [1 / r for r in _BASE_RATIOS]))


@dataclass
class History:
    """古い順の決算期（1 株指標は最新の株式数基準にそろえた値）."""

    periods: list[FiscalPeriod]
    splits: list[tuple[date, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def nearest_split_ratio(ratio: float, tol: float = 0.03) -> Optional[float]:
    """株式数の比が分割・併合の倍率（2倍, 1/5 など）に近ければその倍率を返す."""
    for candidate in SPLIT_RATIOS:
        if abs(ratio / candidate - 1) <= tol:
            return candidate
    return None


def _same_period(a: date, b: date, tol_days: int = 20) -> bool:
    return abs((a - b).days) <= tol_days


def _basis_factor(newer: list[FiscalPeriod], older: AnnualReport, notes: list[str]) -> float:
    """古い報告書の EPS/BPS を新しい基準に合わせる係数を、重複する期から求める."""
    pairs = [
        (n, o) for o in older.periods for n in newer if _same_period(n.end, o.end)
    ]
    if not pairs:
        notes.append(f"報告書 {older.doc_id} と重複する期がなく、1株指標の基準合わせができない（要確認）")
        return 1.0
    ratios = [n.bps / o.bps for n, o in pairs if n.bps and o.bps]
    if not ratios:
        ratios = [n.eps / o.eps for n, o in pairs if n.eps and o.eps and (n.eps > 0) == (o.eps > 0)]
    if not ratios:
        return 1.0
    factor = median(ratios)
    if abs(factor - 1) <= 0.03:
        return 1.0
    split = nearest_split_ratio(factor, tol=0.05)
    if split is not None:
        notes.append(f"報告書 {older.doc_id} の EPS・BPS を係数 {split:g} で新しい基準に換算（分割・併合）")
        return split
    notes.append(f"報告書 {older.doc_id} と重複期の BPS/EPS が一致しない（比 {factor:.3f}、要確認）")
    return 1.0


def _dividend_factor(newer: list[FiscalPeriod], older: AnnualReport, notes: list[str]) -> float:
    """古い報告書の 1 株配当を新しい報告書の基準に合わせる係数（重複する期の比）.

    1 株配当を分割後の基準に直して載せる会社（住友林業など）と直さない会社があるので、
    重複期の値が分割の倍率だけずれていれば古い報告書の配当にその倍率を掛ける。
    """
    ratios = [n.dps / o.dps for o in older.periods for n in newer
              if _same_period(n.end, o.end) and n.dps and o.dps]
    if not ratios:
        return 1.0
    factor = median(ratios)
    if abs(factor - 1) <= 0.03:
        return 1.0
    split = nearest_split_ratio(factor, tol=0.05)
    if split is not None:
        notes.append(f"報告書 {older.doc_id} の1株配当を係数 {split:g} で新しい基準に換算（新しい報告書が分割後の基準で記載）")
        return split
    notes.append(f"報告書 {older.doc_id} と重複期の1株配当が一致しない（比 {factor:.3f}、要確認）")
    return 1.0


def _add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    return date(day.year + y, m + 1, 1) if day.day == 1 else date(day.year + y, m + 1, min(day.day, 28))


# Yahoo の分割日は権利落ち日。効力発生日（株式数が増える日）はその数日後
_EFFECTIVE_LAG = timedelta(days=4)


def _match_known_split(ratio: Optional[float], known: list[tuple[date, float]], lo: date, hi: date,
                       used: set[int]) -> tuple[Optional[float], Optional[date]]:
    """株式数の変化（ratio）に合う Yahoo の分割を、権利落ち日が (lo, hi] のものから探す."""
    cands = [(k, d, r) for k, (d, r) in enumerate(known) if lo < d <= hi and k not in used and r > 0]
    if not cands:
        return None, None
    groups = [cands] + [[c] for c in cands] if len(cands) > 1 else [cands]
    for group in groups:
        r = 1.0
        for _, _, x in group:
            r *= x
        if ratio is None or 0.75 <= ratio / r <= 1.33:
            used.update(k for k, _, _ in group)
            return r, group[-1][1]
    return None, None


def _score(values: list[Optional[float]]) -> float:
    """配当の推移のなめらかさ（隣り合う期の変化率の対数の絶対値の和。小さいほど自然）."""
    total = 0.0
    for a, b in zip(values, values[1:]):
        if a and b and a > 0 and b > 0:
            total += abs(math.log(b / a))
    return total


def _choose_dividend_basis(merged: list[FiscalPeriod], i: int, split: float, ex_date: Optional[date]) -> str:
    """分割した期 i の前後で、1 株配当がどう記載されているかを判断する.

    - restated:       有報で分割後の基準に修正済み（何もしない）
    - before_interim: 未修正。期首〜中間配当の基準日までに分割（i より前の期を割り戻す）
    - after_interim:  未修正。中間配当の基準日より後に分割（さらに i 期の中間配当も割り戻す）
    分割の効力発生日が分かればそれで絞り、残りは前後の期との配当のつながりが自然なものを選ぶ。
    """
    prev, cur = merged[i - 1], merged[i]
    nxt = merged[i + 1].dps if i + 1 < len(merged) else None
    has_interim = cur.interim_dps is not None and cur.interim_dps > 0 and cur.dps is not None
    options = ["before_interim", "restated"]
    if has_interim:
        options.append("after_interim")
        if ex_date is not None and cur.start is not None:
            interim_record = _add_months(cur.start, 6) - timedelta(days=1)
            if ex_date + _EFFECTIVE_LAG > interim_record:
                options.remove("before_interim")
            else:
                options.remove("after_interim")

    def series(option: str) -> list[Optional[float]]:
        before = prev.dps / split if prev.dps is not None and option != "restated" else prev.dps
        now = cur.dps
        if option == "after_interim":
            now = cur.interim_dps / split + (cur.dps - cur.interim_dps)
        return [before, now, nxt]

    return min(options, key=lambda o: (_score(series(o)), o != "before_interim"))


def merge_reports(reports: list[AnnualReport], known_splits: Optional[list[tuple[date, float]]] = None) -> History:
    """報告書（新しい順）をつないで History を作る.

    known_splits は Yahoo Finance の分割履歴（権利落ち日, 倍率）。株式数の変化が分割の倍率から
    ずれる場合（分割と自己株式の消却が同じ期など）の確認と、分割の時期の判断に使う。
    """
    notes: list[str] = []
    if not reports:
        return History(periods=[], notes=["有価証券報告書がない"])
    known = sorted(known_splits or [])

    merged = [replace(p) for p in reports[0].periods]
    for older in reports[1:]:
        factor = _basis_factor(merged, older, notes)
        dps_factor = _dividend_factor(merged, older, notes)
        for p in older.periods:
            if any(_same_period(p.end, m.end) for m in merged):
                continue  # 新しい報告書の値を優先
            q = replace(p)
            if q.eps is not None:
                q.eps *= factor
            if q.bps is not None:
                q.bps *= factor
            if q.dps is not None:
                q.dps *= dps_factor
            if q.interim_dps is not None:
                q.interim_dps *= dps_factor
            merged.append(q)
    merged.sort(key=lambda p: p.end)

    # 株式数の変化から分割・併合を見つける（Yahoo の分割履歴があれば照合する）
    found: list[tuple[int, float, Optional[date], str]] = []
    used: set[int] = set()
    for i in range(1, len(merged)):
        prev, cur = merged[i - 1], merged[i]
        lo, hi = prev.end - timedelta(days=7), cur.end
        if not prev.shares or not cur.shares:
            split, ex_date = _match_known_split(None, known, prev.end, cur.end - timedelta(days=7), used)
            if split is not None and abs(split - 1) > 1e-9:
                found.append((i, split, ex_date, "株式数が無いため Yahoo の分割履歴で判定"))
            continue
        ratio = cur.shares / prev.shares
        split, ex_date = _match_known_split(ratio, known, lo, hi, used)
        if split is not None and abs(split - 1) > 1e-9:
            how = "Yahoo の分割履歴と一致"
            if nearest_split_ratio(ratio) is None:
                how += f"。株式数は {ratio:.2f} 倍（自己株式の消却や増資が同じ期に重なったとみられる）"
            found.append((i, split, ex_date, how))
            continue
        if 0.72 < ratio < 1.4:
            continue
        split = nearest_split_ratio(ratio)
        if split is None:
            notes.append(f"{cur.end} 期に発行済株式数が {ratio:.2f} 倍に変化（分割以外の可能性、要確認）")
            continue
        found.append((i, split, None, "株式数の変化から検出"))

    labels = {
        "restated": "1株配当は有報で分割後の基準に修正済みと判断",
        "before_interim": "以前の期の1株配当を割り戻した",
        "after_interim": "以前の期の1株配当と、当期の中間配当を割り戻した（期の途中の分割）",
    }
    splits: list[tuple[date, float]] = []
    for i, split, ex_date, how in sorted(found, reverse=True):  # 新しい分割から処理する
        prev, cur = merged[i - 1], merged[i]
        splits.append((cur.end, split))
        basis = _choose_dividend_basis(merged, i, split, ex_date)
        notes.append(f"{cur.end} 期に株式分割・併合（{split:g} 倍、{how}）を検出。{labels[basis]}")
        if basis != "restated":
            for j in range(i):
                if merged[j].dps is not None:
                    merged[j].dps /= split
                if merged[j].interim_dps is not None:
                    merged[j].interim_dps /= split
        if basis == "after_interim":
            cur.dps = cur.interim_dps / split + (cur.dps - cur.interim_dps)
            cur.interim_dps /= split
        # EPS/BPS も未修正（分割の前後で BPS が倍率どおりに飛ぶ）なら割り戻す
        if prev.bps and cur.bps:
            observed = prev.bps / cur.bps
            if split / 1.35 <= observed <= split * 1.35:
                notes.append(f"{cur.end} 期より前の EPS・BPS が分割未修正とみられるため割り戻した")
                for j in range(i):
                    if merged[j].eps is not None:
                        merged[j].eps /= split
                    if merged[j].bps is not None:
                        merged[j].bps /= split
    splits.sort()

    missing_shares = sum(1 for p in merged if not p.shares)
    if missing_shares:
        notes.append(f"発行済株式数が取れない期が {missing_shares} 期あり、分割の検出が不完全な可能性")
    for prev, cur in zip(merged, merged[1:]):
        if prev.standard and cur.standard and prev.standard != cur.standard:
            notes.append(f"{cur.end} 期から会計基準が {prev.standard}→{cur.standard} に変わる（前後の EPS・BPS は基準が異なる）")
    estimated = [p for p in merged if p.bps_source]
    if estimated:
        sources = "・".join(dict.fromkeys(p.bps_source for p in estimated))
        notes.append(f"BPS を表から直接取れない期が {len(estimated)} 期（{sources}）")
    parent_only = [p.end for p in merged if p.nonconsolidated]
    if parent_only:
        notes.append(f"{parent_only[0]}〜{parent_only[-1]} 期の {len(parent_only)} 期は連結の値が無く、個別の値を使用")
    for p in merged:
        if p.months is not None and p.months < 12:
            notes.append(f"{p.end} 期は {p.months} か月の変則決算")

    return History(periods=merged, splits=splits, notes=notes)
