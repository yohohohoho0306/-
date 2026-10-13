"""Ricky流の増配株スクリーニングを EDINET の上場会社全体に対して実行する CLI.

    python -m jpstock.screen --out-dir results

流れ:
  1. EDINET コードリストから上場会社を列挙
  2. 直近 15 か月ほどに提出された有価証券報告書を会社ごとに 1 通選び、指標を取り出す
  3. 株価を取得して第1段階を判定
  4. 第1段階の通過銘柄について 4〜5 年前の有価証券報告書も取り、10 期分で第2段階を判定
  5. 配当政策の文面から累進・DOE を拾い（第3段階の機械判定部分）、CSV と Markdown を出力

取得した書類一覧・指標はキャッシュするので、途中で止めても再実行で続きから進む。
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from .edinet import Company, EdinetClient, EdinetError
from .history import SPLIT_RATIOS, History, merge_reports
from .prices import Actions, PriceInfo, fetch_actions, fetch_prices, load_prices_csv
from .ricky import (
    Criteria, Stage1, Stage2, Stage3,
    evaluate_stage1, evaluate_stage2, evaluate_stage3, is_financial,
)
from .xbrl import AnnualReport


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class ScreenRow:
    company: Company
    report: Optional[AnnualReport] = None
    price: Optional[PriceInfo] = None
    stage1: Optional[Stage1] = None
    history: Optional[History] = None
    stage2: Optional[Stage2] = None
    stage3: Optional[Stage3] = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def financial(self) -> bool:
        return is_financial(self.company.industry)

    @property
    def status(self) -> str:
        if self.errors:
            return "取得エラー"
        if self.report is None:
            return "有報なし"
        if self.stage1 is None or self.stage1.passed is None:
            return "第1段階 判定不能"
        if not self.stage1.passed:
            return "第1段階 不通過"
        if self.stage2 is None or self.stage2.passed is None:
            return "第2段階 判定不能"
        if not self.stage2.passed:
            return "第2段階 不通過"
        return "通過"


def years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 2/29
        return day.replace(year=day.year - years, day=28)


def _split_between_end_and_filing(latest, yahoo_factor: float) -> tuple[float, bool]:
    """決算期末〜提出日の分割の倍率を、純利益 ÷ EPS（期中平均株式数）と期末発行済株式総数の比から推定する.

    有報の EPS・BPS は提出日までに効力が生じた分割を期首にさかのぼって反映するが、
    期末発行済株式総数と 1 株配当は分割前のまま。自己株式や期中の増減で比は 0.5〜1.3 程度に
    ばらつくので、その範囲なら分割なしとみなす。戻り値は (倍率, Yahoo の分割履歴と一致したか)。
    """
    if not (latest.net_income and latest.eps and latest.shares):
        return 1.0, True
    implied = latest.net_income / latest.eps
    if implied <= 0:
        return 1.0, True
    raw = implied / latest.shares
    if abs(yahoo_factor - 1) > 1e-9 and 0.5 < raw / yahoo_factor < 1.3:
        return yahoo_factor, True
    if raw < 1.3:
        # 0.5 未満は期末直前の大量の新株発行などでも起こるので、Yahoo の裏付けが無ければ併合とみなさない
        return 1.0, True
    candidates = [r for r in SPLIT_RATIOS if r > 1 and 0.5 < raw / r < 1.3]
    if not candidates:
        return 1.0, True
    return min(candidates, key=lambda r: abs(math.log(raw / r / 0.95))), False


def later_split_factors(report: AnnualReport, price: Optional[PriceInfo]) -> tuple[float, float, bool]:
    """有報の 1 株指標を現在の株数の基準にそろえる倍率.

    戻り値は (提出日より後の分割の倍率, 決算期末〜提出日の分割の倍率, Yahoo の分割履歴と一致したか)。
    - 提出日より後の分割: EPS・BPS・1 株配当・株式数のすべてに効く。
    - 決算期末〜提出日の分割: EPS・BPS は有報で反映済みなので、1 株配当と株式数だけに効く。
      Yahoo の分割日は権利落ち日で、効力発生日（決算期末の翌日など）より数日早いので、
      期末の 7 日前から提出日までを候補とし、純利益 ÷ EPS との比で確かめる。
    """
    latest = report.latest
    if latest is None:
        return 1.0, 1.0, True
    filed = report.filing_date
    after_filing = price.split_factor_after(filed) if price and filed else 1.0
    if price and filed:
        window = price.split_factor_after(latest.end - timedelta(days=7)) / after_filing
    elif price:  # 提出日が分からなければ期末以降の分割を候補にする
        window = price.split_factor_after(latest.end - timedelta(days=7))
    else:
        window = 1.0
    before_filing, confirmed = _split_between_end_and_filing(latest, window)
    return after_filing, before_filing, confirmed


def adjust_for_later_splits(report: AnnualReport, price: Optional[PriceInfo]) -> tuple[AnnualReport, Optional[str]]:
    """直近期の 1 株指標と株式数を、株価（現在の株数）の基準にそろえる（later_split_factors を参照）."""
    latest = report.latest
    if latest is None:
        return report, None
    after_filing, before_filing, confirmed = later_split_factors(report, price)
    if abs(after_filing - 1) < 1e-9 and abs(before_filing - 1) < 1e-9:
        return report, None
    adj = replace(latest)
    if adj.eps is not None:
        adj.eps /= after_filing
    if adj.bps is not None:
        adj.bps /= after_filing
    if adj.dps is not None:
        adj.dps /= after_filing * before_filing
    if adj.shares:
        adj.shares *= after_filing * before_filing
    notes = []
    if abs(before_filing - 1) >= 1e-9:
        notes.append(f"決算期末〜提出日の株式分割（{before_filing:g}倍）を直近期の1株配当・株式数に反映"
                     + ("" if confirmed else "（Yahooの分割履歴と一致せず、要確認）"))
    if abs(after_filing - 1) >= 1e-9:
        notes.append(f"有報提出後の株式分割（{after_filing:g}倍）を直近期の1株指標・株式数に反映")
    new_report = replace(report, periods=report.periods[:-1] + [adj])
    return new_report, " / ".join(notes)


def rebase_history(history: History, after_filing: float, before_filing: float) -> History:
    """10 期の系列を、直近期と同じく現在の株数の基準にそろえる（減配などの判定は変わらない）."""
    if abs(after_filing - 1) < 1e-9 and abs(before_filing - 1) < 1e-9:
        return history
    periods = []
    for p in history.periods:
        q = replace(p)
        for attr in ("eps", "bps"):
            if getattr(q, attr) is not None:
                setattr(q, attr, getattr(q, attr) / after_filing)
        for attr in ("dps", "interim_dps"):
            if getattr(q, attr) is not None:
                setattr(q, attr, getattr(q, attr) / (after_filing * before_filing))
        if q.shares:
            q.shares *= after_filing * before_filing
        periods.append(q)
    return replace(history, periods=periods)


def run_pipeline(
    client: EdinetClient,
    price_source: Callable[[list[str]], dict[str, PriceInfo]],
    as_of: date,
    codes: Optional[list[str]] = None,
    lookback_days: int = 460,
    stage2_all: bool = False,
    criteria: Criteria = Criteria(),
    log: Callable[[str], None] = _log,
    split_source: Optional[Callable[[list[str]], dict]] = None,
) -> list[ScreenRow]:
    companies = client.companies()
    if codes:
        wanted = {c.upper() for c in codes}
        companies = [c for c in companies if c.sec_code.upper() in wanted]
    log(f"対象: 上場 {len(companies)} 社")

    log("有価証券報告書を検索中…")
    start = as_of - timedelta(days=lookback_days)
    if hasattr(client, "annual_report_candidates"):
        candidates = client.annual_report_candidates(start, as_of)
    else:
        candidates = {k: [v] for k, v in client.latest_annual_reports(start, as_of).items()}

    rows: list[ScreenRow] = []
    for i, company in enumerate(companies, 1):
        if i % 100 == 0:
            log(f"  有報の指標 {i}/{len(companies)} 社")
        row = ScreenRow(company=company)
        rows.append(row)
        docs = candidates.get(company.edinet_code) or []
        try:
            for n, doc in enumerate(docs):
                report = client.annual_report(doc["docID"])
                if report.latest is not None or n == len(docs) - 1:
                    row.report = report
                    if n:
                        row.notes.append(f"最新の有報 {docs[0]['docID']} に主要な経営指標が無いため {doc['docID']} を使用")
                    break
        except (EdinetError, ValueError) as exc:
            row.errors.append(f"有報取得失敗: {exc}")

    targets = [r for r in rows if r.report is not None and r.report.latest is not None]
    log(f"株価を取得中…（{len(targets)} 銘柄）")
    prices = price_source([r.company.sec_code for r in targets])

    for row in targets:
        latest = row.report.latest
        if not latest.shares and latest.net_income and latest.eps and latest.net_income / latest.eps > 0:
            # 期末発行済株式総数が表に無い（アドヴァンの当期など）ときは、純利益 ÷ EPS の株数で時価総額を概算する
            latest.shares = latest.net_income / latest.eps
            row.notes.append("期末発行済株式総数が有報の表に無いため、時価総額は純利益÷EPSの株数（自己株式を除く期中平均）で概算")
        row.price = prices.get(row.company.sec_code)
        if row.price and row.price.symbol and not row.price.symbol.endswith(".T"):
            exchange = {"S": "札幌証券取引所", "F": "福岡証券取引所"}.get(row.price.symbol[-1], row.price.symbol)
            row.notes.append(f"株価は{exchange}の終値（{row.price.symbol}）")
        # 期の途中の分割で中間配当が分割前の基準のままなら、当期の 1 株配当を直してから判定する
        single = merge_reports([row.report], row.price.splits if row.price else [])
        report = replace(row.report, periods=single.periods)
        if report.latest.dps != row.report.latest.dps:
            row.notes.append(f"当期の1株配当を、分割前の中間配当を割り戻して {report.latest.dps:g} 円とした"
                             f"（有報の記載は {row.report.latest.dps:g} 円）")
        report, note = adjust_for_later_splits(report, row.price)
        if note:
            row.notes.append(note)
        months = report.latest.months
        if months is not None and months < 12:
            row.notes.append(f"直近期は {months} か月の変則決算（EPS・ROE・ROA・配当は通期に換算していない）")
        row.stage1 = evaluate_stage1(
            report.latest, row.price.price if row.price else None, row.financial, criteria
        )

    stage2_targets = [r for r in targets if stage2_all or (r.stage1 and r.stage1.passed)]
    log(f"第2段階: {len(stage2_targets)} 銘柄の過去の有報を取得中…")
    split_history = split_source([r.company.sec_code for r in stage2_targets]) if split_source else {}
    for i, row in enumerate(stage2_targets, 1):
        if i % 20 == 0:
            log(f"  第2段階 {i}/{len(stage2_targets)} 銘柄")
        reports = [row.report]
        latest_end = row.report.latest.end
        for years in (4, 5):
            try:
                doc = client.find_annual_report(row.company.edinet_code, years_before(latest_end, years))
                if doc is None:
                    row.notes.append(f"{years}年前の有報が見つからない")
                    continue
                reports.append(client.annual_report(doc["docID"]))
            except (EdinetError, ValueError) as exc:
                row.errors.append(f"{years}年前の有報取得失敗: {exc}")
        # split_source は {コード: Actions}（分割・配当の履歴）か {コード: 分割の一覧} を返す
        acts = split_history.get(row.company.sec_code)
        known, dividends = (acts.splits, acts.dividends) if isinstance(acts, Actions) else (acts or [], [])
        known = known or (row.price.splits if row.price else [])
        row.history = rebase_history(merge_reports(reports, known, dividends),
                                     *later_split_factors(row.report, row.price)[:2])
        row.stage2 = evaluate_stage2(row.history, criteria)
        row.stage3 = evaluate_stage3(
            row.report.dividend_policy,
            row.stage1.pbr if row.stage1 else None,
            row.stage2.bps_all_increase,
            criteria,
        )
    return rows


# ---- 出力 -------------------------------------------------------------------

def _f(value: Optional[float], digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def display_name(name: str) -> str:
    """表示用の会社名（「株式会社」と空白を除く）."""
    for word in ("株式会社", "（株）", "(株)"):
        name = name.replace(word, "")
    return name.replace("\u3000", "").strip()


def _oku(value: Optional[float]) -> str:
    return "" if value is None else f"{value / 1e8:,.0f}億円"


def _policy(s3: Optional[Stage3]) -> str:
    if s3 is None:
        return ""
    doe = "DOE" + ("/".join(f"{v:g}%" for v in s3.doe_values) if s3.doe_values else "（数値なし）") if s3.doe else "DOE記載なし"
    return f"{'累進あり' if s3.progressive else '累進記載なし'}・{doe}"


CSV_COLUMNS = [
    "コード", "銘柄名", "業種", "金融", "判定", "株価", "株価日付", "直近決算期末",
    "PER(実績)", "PBR", "ROE", "ROA", "配当利回り(実績)", "1株配当(実績)", "自己資本比率", "時価総額(億円)",
    "第1段階 不合格項目", "第1段階 未確認項目",
    "期数", "EPS 9期前", "EPS 直近", "EPS倍率", "赤字期", "BPS 9期前", "BPS 直近", "BPS伸び率",
    "BPS連続増加回数", "BPS減少期", "減配回数", "減配期", "無配転落期", "第2段階 不合格項目", "第2段階 未確認項目",
    "累進", "DOE", "DOE数値", "PBR1倍前後", "印", "注記", "エラー", "有報docID",
]


def to_csv_row(r: ScreenRow) -> dict:
    s1, s2, s3 = r.stage1, r.stage2, r.stage3
    latest = r.report.latest if r.report else None
    dates = lambda xs: " ".join(d.isoformat() for d in xs)  # noqa: E731
    return {
        "コード": r.company.sec_code,
        "銘柄名": display_name(r.company.name),
        "業種": r.company.industry,
        "金融": "○" if r.financial else "",
        "判定": r.status,
        "株価": _f(r.price.price if r.price else None, 1),
        "株価日付": r.price.as_of.isoformat() if r.price else "",
        "直近決算期末": latest.end.isoformat() if latest else "",
        "PER(実績)": _f(s1.per if s1 else None),
        "PBR": _f(s1.pbr if s1 else None),
        "ROE": _f(s1.roe if s1 else None),
        "ROA": _f(s1.roa if s1 else None),
        "配当利回り(実績)": _f(s1.dividend_yield if s1 else None),
        "1株配当(実績)": _f(s1.dps if s1 else None),
        "自己資本比率": _f(s1.equity_ratio if s1 else None, 1),
        "時価総額(億円)": _f(s1.market_cap / 1e8 if s1 and s1.market_cap else None, 0),
        "第1段階 不合格項目": " / ".join(s1.failures) if s1 else "",
        "第1段階 未確認項目": " / ".join(s1.missing) if s1 else "",
        "期数": s2.n_periods if s2 else "",
        "EPS 9期前": _f(s2.eps_first if s2 else None),
        "EPS 直近": _f(s2.eps_last if s2 else None),
        "EPS倍率": _f(s2.eps_ratio if s2 else None),
        "赤字期": dates(s2.loss_periods) if s2 else "",
        "BPS 9期前": _f(s2.bps_first if s2 else None),
        "BPS 直近": _f(s2.bps_last if s2 else None),
        "BPS伸び率": _f(s2.bps_growth if s2 else None),
        "BPS連続増加回数": s2.bps_streak if s2 else "",
        "BPS減少期": dates(s2.bps_decreases) if s2 else "",
        "減配回数": len(s2.dividend_cuts) + len(s2.dividend_suspended) if s2 else "",
        "減配期": dates(s2.dividend_cuts) if s2 else "",
        "無配転落期": dates(s2.dividend_suspended) if s2 else "",
        "第2段階 不合格項目": " / ".join(s2.failures) if s2 else "",
        "第2段階 未確認項目": " / ".join(s2.missing) if s2 else "",
        "累進": ("○" if s3.progressive else "") if s3 else "",
        "DOE": ("○" if s3.doe else "") if s3 else "",
        "DOE数値": " ".join(f"{v:g}%" for v in s3.doe_values) if s3 else "",
        "PBR1倍前後": ("○" if s3.pbr_near_one else "") if s3 else "",
        "印": s3.mark if s3 else "",
        "注記": " / ".join(r.notes + (r.history.notes if r.history else [])),
        "エラー": " / ".join(r.errors),
        "有報docID": r.report.doc_id if r.report else "",
    }


def write_csv(rows: list[ScreenRow], path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(to_csv_row(r))


def render_markdown(rows: list[ScreenRow], as_of: date, criteria: Criteria = Criteria()) -> str:
    c = criteria
    by_status: dict[str, list[ScreenRow]] = {}
    for r in rows:
        by_status.setdefault(r.status, []).append(r)
    passed = sorted(by_status.get("通過", []), key=lambda r: -(r.stage2.bps_growth or 0))
    out = [
        f"# Ricky流 増配株スクリーニング結果（{as_of.isoformat()} 実行）",
        "",
        "売買の推奨ではなく、条件に機械的に当てはめた結果です。",
        "",
        "## 前提",
        "",
        "- データ: EDINET の有価証券報告書（主要な経営指標等の推移）と Yahoo Finance の終値。",
        f"- 第1段階: PER≦{c.per_max:g}倍・PBR≦{c.pbr_max:g}倍・ROE≧{c.roe_min:g}%・ROA≧{c.roa_min:g}%・"
        f"配当利回り≧{c.yield_min:g}%・自己資本比率≧{c.equity_ratio_min:g}%・時価総額≧{c.market_cap_min / 1e8:,.0f}億円。"
        "金融（銀行・保険・証券・その他金融）は ROA と自己資本比率を判定しない。",
        "- **PER・配当利回りは実績ベース**（会社予想は EDINET に無いため）。ROA = 当期純利益 ÷ 期末総資産。"
        "時価総額 = 終値 × 期末発行済株式総数。",
        f"- 第2段階: 直近{c.periods}期で赤字なし・EPSが9期前の{c.eps_growth_min:g}倍以上、BPSが毎期増加、"
        f"減配{c.max_dividend_cuts}回まで・無配転落なし（1株配当は株式数の変化から分割を検出して割り戻し）。",
        f"- 第3段階（機械判定分のみ）: 有報「配当政策」に累進・DOEの記載があるか、PBRが{c.pbr_near_one[0]:g}〜{c.pbr_near_one[1]:g}倍か。"
        "テーマ性は対象外（手動で確認）。",
        "- 印: ★ = BPS毎期増加＋DOE記載＋PBR1倍前後のすべて、☆ = そのうち2つ。",
        "",
        "## 件数",
        "",
        "| 判定 | 件数 |",
        "|---|---|",
    ]
    for status in ["通過", "第2段階 不通過", "第2段階 判定不能", "第1段階 不通過", "第1段階 判定不能", "有報なし", "取得エラー"]:
        out.append(f"| {status} | {len(by_status.get(status, []))} |")

    def table(rs: list[ScreenRow], financial: bool) -> list[str]:
        head = ("| 印 | 銘柄名 | コード | 業種 | PER | PBR | ROE | ROA | 配当利回り | 自己資本比率 | 時価総額 | "
                "EPS 9期前→直近（倍率） | BPS伸び率 | BPS連続増加 | 減配回数 | 配当方針（有報） | テーマ性 | データ日付 |")
        lines = [head, "|" + "---|" * 18]
        for r in rs:
            s1, s2 = r.stage1, r.stage2
            lines.append(
                f"| {r.stage3.mark if r.stage3 else ''} | {display_name(r.company.name)} | {r.company.sec_code} | {r.company.industry} | "
                f"{_f(s1.per)} | {_f(s1.pbr)} | {_f(s1.roe, 1)}% | "
                f"{'—' if financial else _f(s1.roa, 1) + '%'} | {_f(s1.dividend_yield)}% | "
                f"{'—' if financial else _f(s1.equity_ratio, 1) + '%'} | {_oku(s1.market_cap)} | "
                f"{_f(s2.eps_first)}→{_f(s2.eps_last)}（{_f(s2.eps_ratio)}倍） | {_f(s2.bps_growth)}倍 | "
                f"{s2.bps_streak}回（{s2.n_periods}期中） | {len(s2.dividend_cuts)}回 | {_policy(r.stage3)} | 要手動確認 | "
                f"株価 {r.price.as_of if r.price else ''}／決算 {s2.first_end}〜{s2.last_end} |"
            )
        return lines

    out += ["", "## 第3段階まで通過（BPS伸び率順）", ""]
    non_fin = [r for r in passed if not r.financial]
    fin = [r for r in passed if r.financial]
    out += table(non_fin, False) if non_fin else ["該当なし"]
    out += ["", "### 金融（別枠）", ""]
    out += table(fin, True) if fin else ["該当なし"]

    out += ["", "## 第2段階で落ちた銘柄", "", "| 銘柄名 | コード | 業種 | 落ちた条件 | 詳細 |", "|---|---|---|---|---|"]
    for r in sorted(by_status.get("第2段階 不通過", []), key=lambda r: r.company.sec_code):
        s2 = r.stage2
        detail = []
        if s2.eps_ratio is not None:
            detail.append(f"EPS {_f(s2.eps_ratio)}倍")
        if s2.loss_periods:
            detail.append("赤字 " + ", ".join(d.isoformat() for d in s2.loss_periods))
        if s2.bps_decreases:
            detail.append("BPS減少 " + ", ".join(d.isoformat() for d in s2.bps_decreases))
        if s2.dividend_cuts:
            detail.append("減配 " + ", ".join(d.isoformat() for d in s2.dividend_cuts))
        out.append(f"| {display_name(r.company.name)} | {r.company.sec_code} | {r.company.industry} | "
                   f"{' / '.join(s2.failures)} | {'; '.join(detail)} |")

    out += ["", "## 第2段階 判定不能（データ不足）", "", "| 銘柄名 | コード | 理由 |", "|---|---|---|"]
    for r in sorted(by_status.get("第2段階 判定不能", []), key=lambda r: r.company.sec_code):
        out.append(f"| {display_name(r.company.name)} | {r.company.sec_code} | {' / '.join(r.stage2.missing) if r.stage2 else ''} |")

    out += ["", "## 通過銘柄の業種分布", ""]
    counts: dict[str, int] = {}
    for r in passed:
        counts[r.company.industry] = counts.get(r.company.industry, 0) + 1
    if counts:
        out += ["| 業種 | 件数 |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
        top, n = max(counts.items(), key=lambda kv: kv[1])
        if len(passed) >= 3 and n / len(passed) >= 0.4:
            out += ["", f"**偏りあり**: 通過 {len(passed)} 銘柄のうち {n} 銘柄（{n / len(passed):.0%}）が「{top}」。"]
    else:
        out.append("通過銘柄なし")
    out += ["", "注記（分割の検出・変則決算など）は CSV の「注記」列を参照。分割を検出した銘柄は IRBank 等で確認を推奨。", ""]
    return "\n".join(out)


# ---- CLI ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m jpstock.screen",
        description="EDINET の有価証券報告書で Ricky 流の増配株スクリーニングを行う（要 EDINET_API_KEY）",
    )
    p.add_argument("--codes", nargs="+", help="対象を絞る銘柄コード（例: 7203 1911）。未指定なら全上場会社")
    p.add_argument("--prices", help="株価 CSV（code,price,date）。未指定なら Yahoo Finance から取得")
    p.add_argument("--out-dir", default="results", help="出力先ディレクトリ（既定: results）")
    p.add_argument("--cache-dir", default=".cache/edinet", help="キャッシュ（既定: .cache/edinet）")
    p.add_argument("--sleep", type=float, default=0.5, help="EDINET API 呼び出し間隔の秒数（既定: 0.5）")
    p.add_argument("--lookback-days", type=int, default=460, help="直近の有報を探す日数（既定: 460）")
    p.add_argument("--stage2-all", action="store_true", help="第1段階の結果に関係なく全銘柄で第2段階を判定する")
    p.add_argument("--as-of", help="基準日 YYYY-MM-DD（既定: 今日）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    client = EdinetClient(cache_dir=args.cache_dir, sleep=args.sleep)
    if not client.api_key:
        print("エラー: 環境変数 EDINET_API_KEY が設定されていません", file=sys.stderr)
        return 1
    if args.prices:
        table = load_prices_csv(args.prices)
        price_source = lambda codes: {c: table[c] for c in codes if c in table}  # noqa: E731
        split_source = None
    else:
        price_cache = Path(args.cache_dir).parent / "prices"
        price_source = lambda codes: fetch_prices(codes, cache_dir=price_cache)  # noqa: E731
        split_source = lambda codes: fetch_actions(codes, cache_dir=price_cache)  # noqa: E731

    try:
        rows = run_pipeline(client, price_source, as_of, codes=args.codes,
                            lookback_days=args.lookback_days, stage2_all=args.stage2_all,
                            split_source=split_source)
    except EdinetError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = as_of.strftime("%Y%m%d")
    csv_path = out_dir / f"ricky_all_{stamp}.csv"
    md_path = out_dir / f"ricky_report_{stamp}.md"
    write_csv(rows, csv_path)
    md_path.write_text(render_markdown(rows, as_of), encoding="utf-8")
    passed = sum(1 for r in rows if r.status == "通過")
    print(f"完了: 通過 {passed} 銘柄 / 対象 {len(rows)} 社", file=sys.stderr)
    print(f"  {md_path}\n  {csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
