"""EDINET を使ったスクリーニング部分のユニットテスト（ネットワーク不要）."""

import io
import json
import os
import sys
import zipfile
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jpstock import screen
from jpstock.edinet import Company, EdinetClient, EdinetError, parse_code_list
from jpstock.history import merge_reports, nearest_split_ratio
from jpstock.prices import PriceInfo, load_prices_csv, parse_download_frame
from jpstock.ricky import evaluate_stage1, evaluate_stage2, evaluate_stage3
from jpstock.xbrl import (
    AnnualReport, FiscalPeriod, build_report, extract_instance, parse_instance, report_from_zip,
)

CRP = "http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2024-11-01/jpcrp_cor"
DEI = "http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/2013-08-31/jpdei_cor"


# ---- XBRL のテストデータ ---------------------------------------------------

def make_instance(periods, *, nonconsolidated_only=False, extra_facts="", policy=None):
    """periods は古い順（最大 5 期）。各要素は dict(end, start, eps, bps, dps, ni, ta, er, roe, shares)."""
    ctx, facts = [], []
    n = len(periods)
    for i, p in enumerate(periods):
        idx = n - 1 - i
        prefix = "CurrentYear" if idx == 0 else f"Prior{idx}Year"
        for suffix in ("", "_NonConsolidatedMember"):
            ctx.append(
                f'<xbrli:context id="{prefix}Duration{suffix}"><xbrli:entity><xbrli:identifier scheme="x">E0</xbrli:identifier></xbrli:entity>'
                f'<xbrli:period><xbrli:startDate>{p["start"]}</xbrli:startDate><xbrli:endDate>{p["end"]}</xbrli:endDate></xbrli:period></xbrli:context>'
            )
            ctx.append(
                f'<xbrli:context id="{prefix}Instant{suffix}"><xbrli:entity><xbrli:identifier scheme="x">E0</xbrli:identifier></xbrli:entity>'
                f'<xbrli:period><xbrli:instant>{p["end"]}</xbrli:instant></xbrli:period></xbrli:context>'
            )
        main = "_NonConsolidatedMember" if nonconsolidated_only else ""
        f = [
            ("BasicEarningsLossPerShareSummaryOfBusinessResults", f"{prefix}Duration{main}", p["eps"]),
            ("NetAssetsPerShareSummaryOfBusinessResults", f"{prefix}Instant{main}", p["bps"]),
            ("ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults", f"{prefix}Duration{main}", p["ni"]),
            ("TotalAssetsSummaryOfBusinessResults", f"{prefix}Instant{main}", p["ta"]),
            ("EquityToAssetRatioSummaryOfBusinessResults", f"{prefix}Instant{main}", p["er"]),
            ("RateOfReturnOnEquitySummaryOfBusinessResults", f"{prefix}Duration{main}", p["roe"]),
            ("DividendPaidPerShareSummaryOfBusinessResults", f"{prefix}Duration_NonConsolidatedMember", p["dps"]),
            ("TotalNumberOfIssuedSharesSummaryOfBusinessResults", f"{prefix}Instant_NonConsolidatedMember", p["shares"]),
        ]
        for name, ref, value in f:
            facts.append(f'<jpcrp_cor:{name} contextRef="{ref}" unitRef="u" decimals="2">{value}</jpcrp_cor:{name}>')
    ctx.append('<xbrli:context id="FilingDateInstant"><xbrli:entity><xbrli:identifier scheme="x">E0</xbrli:identifier></xbrli:entity>'
               '<xbrli:period><xbrli:instant>2026-06-20</xbrli:instant></xbrli:period></xbrli:context>')
    facts.append('<jpdei_cor:SecurityCodeDEI contextRef="FilingDateInstant">72030</jpdei_cor:SecurityCodeDEI>')
    facts.append('<jpdei_cor:FilerNameInJapaneseDEI contextRef="FilingDateInstant">テスト株式会社</jpdei_cor:FilerNameInJapaneseDEI>')
    if policy is not None:
        escaped = policy.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        facts.append(f'<jpcrp_cor:DividendPolicyTextBlock contextRef="FilingDateInstant">{escaped}</jpcrp_cor:DividendPolicyTextBlock>')
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        f'xmlns:jpcrp_cor="{CRP}" xmlns:jpdei_cor="{DEI}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + "".join(ctx) + "".join(facts) + extra_facts + "</xbrli:xbrl>"
    ).encode("utf-8")


def five_periods(first_year=2022):
    out = []
    for k in range(5):
        y = first_year + k
        out.append(dict(
            start=f"{y - 1}-04-01", end=f"{y}-03-31", eps=100 + 10 * k, bps=1000 + 100 * k,
            dps=30 + k, ni=1_000_000_000 + k, ta=25_000_000_000, er=0.452, roe=0.0964, shares=10_000_000,
        ))
    return out


def test_build_report_reads_summary_table():
    xbrl = make_instance(five_periods(), policy="<p>DOE（株主資本配当率）3.5%を目安に&amp;累進配当</p>")
    report = build_report(*parse_instance(xbrl), doc_id="S100TEST")
    assert [p.end for p in report.periods] == [date(y, 3, 31) for y in range(2022, 2027)]
    latest = report.latest
    assert latest.eps == 140 and latest.bps == 1400 and latest.dps == 34
    assert latest.equity_ratio == pytest.approx(45.2)
    assert latest.roe == pytest.approx(9.64)
    assert latest.roa == pytest.approx(1_000_000_004 / 25_000_000_000 * 100)
    assert latest.shares == 10_000_000 and latest.months == 12
    assert report.sec_code == "72030" and report.name == "テスト株式会社"
    assert report.consolidated is True
    assert "DOE（株主資本配当率）3.5%を目安に&累進配当" in report.dividend_policy


def test_build_report_nonconsolidated_only_company():
    report = build_report(*parse_instance(make_instance(five_periods(), nonconsolidated_only=True)), doc_id="X")
    assert report.consolidated is False
    assert report.latest.eps == 140 and report.latest.bps == 1400


def test_build_report_uses_parent_values_before_consolidation_started():
    # イチケン型: 連結決算は直近 2 期のみで、それより前の期は連結の欄が nil、個別の値だけがある
    periods = five_periods()
    xbrl = make_instance(periods)
    for idx in (2, 3, 4):
        for name, kind, value in (("BasicEarningsLossPerShareSummaryOfBusinessResults", "Duration", periods[4 - idx]["eps"]),
                                  ("NetAssetsPerShareSummaryOfBusinessResults", "Instant", periods[4 - idx]["bps"]),
                                  ("RateOfReturnOnEquitySummaryOfBusinessResults", "Duration", periods[4 - idx]["roe"])):
            ctx = f"Prior{idx}Year{kind}"
            xbrl = xbrl.replace(
                f'<jpcrp_cor:{name} contextRef="{ctx}" unitRef="u" decimals="2">{value}</jpcrp_cor:{name}>'.encode(),
                (f'<jpcrp_cor:{name} contextRef="{ctx}" unitRef="u" xsi:nil="true"/>'
                 f'<jpcrp_cor:{name} contextRef="{ctx}_NonConsolidatedMember" unitRef="u" decimals="2">{value - 1}</jpcrp_cor:{name}>').encode(),
            )
    report = build_report(*parse_instance(xbrl), doc_id="X")
    assert report.consolidated is True and report.filing_date == date(2026, 6, 20)
    assert [p.nonconsolidated for p in report.periods] == [True, True, True, False, False]
    assert [p.eps for p in report.periods] == [99, 109, 119, 130, 140]
    assert [p.bps for p in report.periods][:3] == [999, 1099, 1199]
    assert report.periods[0].roe == pytest.approx((0.0964 - 1) * 100)  # 個別の値（テスト用に 1 引いたもの）
    assert any("個別の値" in n for n in merge_reports([report]).notes)


def test_ifrs_values_take_priority():
    extra = ('<jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults contextRef="CurrentYearDuration" '
             'unitRef="u" decimals="2">155.5</jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults>')
    report = build_report(*parse_instance(make_instance(five_periods(), extra_facts=extra)), doc_id="X")
    assert report.latest.eps == 155.5
    assert report.periods[-2].eps == 130  # IFRS 値の無い期は日本基準の値
    assert [p.standard for p in report.periods][-2:] == ["JP", "IFRS"]
    # IFRS の BPS が無い移行期は、IFRS の持分から求められなければ日本基準の BPS を注記付きで使う
    assert report.latest.bps == 1400 and "別の会計基準（JP）" in report.latest.bps_source
    owners = ('<jpcrp_cor:EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults contextRef="CurrentYearInstant" '
              'unitRef="u" decimals="-6">16000000000</jpcrp_cor:EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults>')
    ifrs = build_report(*parse_instance(make_instance(five_periods(), extra_facts=extra + owners)), doc_id="X")
    # 持分 160 億円 ÷（純利益 1,000,000,004 円 ÷ EPS 155.5 円）≒ 2,488 円（同じ IFRS 基準の概算を優先）
    assert ifrs.latest.bps == pytest.approx(16_000_000_000 / (1_000_000_004 / 155.5)) and "概算" in ifrs.latest.bps_source
    assert any("JP→IFRS" in n for n in merge_reports([report]).notes)


def test_bps_from_mistagged_ratio_element_or_estimate():
    # IFRS の会社の多く（トヨタなど）: BPS の要素が無く、EquityToAssetRatioIFRS の要素に BPS が入っている
    periods = five_periods()
    xbrl = make_instance(periods)
    for i, p in enumerate(periods):
        idx = 4 - i
        prefix = "CurrentYear" if idx == 0 else f"Prior{idx}Year"
        xbrl = xbrl.replace(
            f'<jpcrp_cor:NetAssetsPerShareSummaryOfBusinessResults contextRef="{prefix}Instant" unitRef="u" decimals="2">{p["bps"]}</jpcrp_cor:NetAssetsPerShareSummaryOfBusinessResults>'.encode(),
            b"",
        )
    owners = lambda p: p["bps"] * p["ni"] / p["eps"]  # noqa: E731  純利益 / EPS の株数で BPS になる持分
    extra = "".join(
        f'<jpcrp_cor:EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults contextRef="{"CurrentYear" if 4 - i == 0 else f"Prior{4 - i}Year"}Instant" unitRef="u" decimals="-6">{owners(p)}</jpcrp_cor:EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults>'
        for i, p in enumerate(periods)
    )
    estimated = build_report(*parse_instance(xbrl.replace(b"</xbrli:xbrl>", extra.encode() + b"</xbrli:xbrl>")), doc_id="X")
    assert estimated.latest.bps == pytest.approx(1400) and "概算" in estimated.latest.bps_source

    mistag = ('<jpcrp_cor:EquityToAssetRatioIFRSSummaryOfBusinessResults contextRef="CurrentYearInstant" '
              'unitRef="u" decimals="2">1412.5</jpcrp_cor:EquityToAssetRatioIFRSSummaryOfBusinessResults>')
    report = build_report(*parse_instance(xbrl.replace(b"</xbrli:xbrl>", (extra + mistag).encode() + b"</xbrli:xbrl>")), doc_id="X")
    assert report.latest.bps == 1412.5 and "EquityToAssetRatioIFRS の要素" in report.latest.bps_source
    assert report.latest.equity_ratio == pytest.approx(45.2)  # 1.5 超の値は自己資本比率として使わない


def test_extract_instance_prefers_public_doc_asr():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/AuditDoc/jpaud-aar-cn-001_E0.xbrl", b"<x/>")
        zf.writestr("XBRL/PublicDoc/jpcrp030000-asr-001_E0-000_2026-03-31_01_2026-06-20.xbrl", make_instance(five_periods()))
    assert extract_instance(buf.getvalue()).startswith(b"<?xml")
    assert report_from_zip(buf.getvalue(), "S1").latest.eps == 140


# ---- 報告書の連結と分割調整 ------------------------------------------------

def fp(year, eps, bps, dps, shares, **kw):
    return FiscalPeriod(end=date(year, 3, 31), start=date(year - 1, 4, 1), eps=eps, bps=bps, dps=dps,
                        shares=shares, net_income=kw.get("ni", 1e9), total_assets=kw.get("ta", 2e10),
                        equity_ratio=kw.get("er", 50.0), roe=kw.get("roe", 10.0))


def test_nearest_split_ratio():
    assert nearest_split_ratio(2.01) == 2
    assert nearest_split_ratio(0.2) == 0.2
    assert nearest_split_ratio(1.2) is None


def test_merge_aligns_older_report_and_adjusts_dividends_for_split():
    # FY2023 に 1→2 の株式分割。新しい報告書は EPS/BPS を遡って修正済み、配当は未修正。
    newer = AnnualReport(doc_id="new", periods=[
        fp(2022, 50, 500, 40, 1_000_000), fp(2023, 55, 550, 22, 2_000_000), fp(2024, 60, 600, 24, 2_000_000),
        fp(2025, 65, 650, 26, 2_000_000), fp(2026, 70, 700, 28, 2_000_000),
    ])
    older = AnnualReport(doc_id="old", periods=[
        fp(2018, 80, 800, 30, 1_000_000), fp(2019, 84, 860, 32, 1_000_000), fp(2020, 88, 900, 34, 1_000_000),
        fp(2021, 92, 950, 36, 1_000_000), fp(2022, 100, 1000, 40, 1_000_000),
    ])
    h = merge_reports([newer, older])
    assert [p.end.year for p in h.periods] == list(range(2018, 2027))
    assert h.periods[0].eps == pytest.approx(40) and h.periods[0].bps == pytest.approx(400)
    assert h.splits == [(date(2023, 3, 31), 2)]
    dps = [p.dps for p in h.periods]
    assert dps[:5] == pytest.approx([15, 16, 17, 18, 20])  # 分割前の配当は 1/2
    assert all(b > a for a, b in zip(dps, dps[1:]))


def test_merge_fixes_unadjusted_eps_bps_inside_one_report():
    report = AnnualReport(doc_id="r", periods=[
        fp(2022, 100, 1000, 40, 1_000_000), fp(2023, 110, 1080, 44, 1_000_000),
        fp(2024, 60, 590, 24, 2_000_000), fp(2025, 65, 640, 26, 2_000_000), fp(2026, 70, 700, 28, 2_000_000),
    ])
    h = merge_reports([report])
    assert [p.bps for p in h.periods] == pytest.approx([500, 540, 590, 640, 700])
    assert [p.eps for p in h.periods][:2] == pytest.approx([50, 55])
    assert any("未修正" in n for n in h.notes)


def test_merge_fixes_eps_bps_restated_only_for_current_and_prior_year():
    # フィード・ワン型: 5→1 の併合（2021/3 期）。有報は当期と前期（2020/3 期）だけを併合後の基準に直し、
    # それより前の期は併合前のまま。株式数が変わる期の 1 期前の境目で BPS が 5 倍に飛ぶ
    report = AnnualReport(doc_id="r", periods=[
        fp(2017, 20, 155, 4.5, 197_000_000), fp(2018, 15, 167, 4.5, 197_000_000), fp(2019, 24, 183, 4.5, 197_000_000),
        fp(2020, 98, 978, 5.0, 197_000_000), fp(2021, 113, 1075, 15.0, 39_400_000),
    ])
    h = merge_reports([report], known_splits=[(date(2020, 9, 29), 0.2)])
    assert [p.bps for p in h.periods] == pytest.approx([775, 835, 915, 978, 1075])
    assert [p.eps for p in h.periods][:3] == pytest.approx([100, 75, 120])
    assert any("2020-03-31 期より前" in n for n in h.notes)


def test_merge_aligns_report_across_two_splits_and_retroactive_restatement():
    # 川田テクノロジーズ型: 古い報告書の後に 1→3 の分割が 2 回（係数 1/9）
    newer = AnnualReport(doc_id="new", periods=[fp(2022 + k, 100 + k, 1300 + 100 * k, 30, 17_000_000) for k in range(5)])
    older = AnnualReport(doc_id="old", periods=[fp(2018 + k, 900 + k, 9000 + 900 * k, 30, 1_900_000) for k in range(5)])
    older.periods[-1].bps, older.periods[-1].eps = 1300 * 9, 100 * 9
    h = merge_reports([newer, older])
    assert h.periods[0].bps == pytest.approx(1000) and any("係数 0.111111" in n for n in h.notes)
    # 三協フロンテア型: 重複期の BPS が遡及修正で 12% ずれる。EPS の比（0.5）で換算し、注記する
    newer2 = AnnualReport(doc_id="new", periods=[fp(2022 + k, 286 + k, 1738 + 100 * k, 80, 23_000_000) for k in range(5)])
    older2 = AnnualReport(doc_id="old", periods=[fp(2018 + k, 500 + k, 3000 + 200 * k, 160, 11_500_000) for k in range(5)])
    older2.periods[-1].bps, older2.periods[-1].eps = 3937.5, 572
    h2 = merge_reports([newer2, older2])
    assert h2.periods[0].bps == pytest.approx(1500)
    assert any("係数 0.5" in n for n in h2.notes) and any("遡って修正" in n for n in h2.notes)


def test_merge_keeps_dividends_already_restated_for_split():
    # 住友林業型: 新しい報告書は過去の 1 株配当も分割後（1→3）の基準に直して記載。古い報告書は分割前の基準。
    newer = AnnualReport(doc_id="new", periods=[
        fp(2022, 50, 500, 80 / 3, 1_000_000), fp(2023, 55, 550, 30, 1_000_000), fp(2024, 60, 600, 32, 1_000_000),
        fp(2025, 65, 650, 34, 1_000_000), fp(2026, 70, 700, 36, 3_000_000),
    ])
    older = AnnualReport(doc_id="old", periods=[
        fp(2018, 120, 1200, 60, 1_000_000), fp(2019, 126, 1260, 66, 1_000_000), fp(2020, 132, 1320, 70, 1_000_000),
        fp(2021, 138, 1380, 75, 1_000_000), fp(2022, 150, 1500, 80, 1_000_000),
    ])
    h = merge_reports([newer, older], known_splits=[(date(2025, 6, 27), 3.0)])
    dps = [p.dps for p in h.periods]
    assert dps == pytest.approx([20, 22, 70 / 3, 25, 80 / 3, 30, 32, 34, 36])
    assert evaluate_stage2(h).dividend_cuts == []
    assert any("修正済み" in n for n in h.notes)


def test_merge_uses_known_split_when_share_count_also_changed_by_buyback():
    # イエローハット型: 1→2 の分割と自己株式の消却が同じ期で、株式数は 1.79 倍
    report = AnnualReport(doc_id="r", periods=[
        fp(2022, 50, 500, 58, 50_000_000), fp(2023, 55, 550, 62, 50_000_000), fp(2024, 60, 600, 66, 50_000_000),
        fp(2025, 65, 650, 100, 48_000_000), fp(2026, 70, 700, 62, 86_000_000),
    ])
    without = merge_reports([report])
    assert any("分割以外の可能性" in n for n in without.notes)
    h = merge_reports([report], known_splits=[(date(2025, 3, 28), 2.0)])
    assert h.splits == [(date(2026, 3, 31), 2.0)]
    assert [p.dps for p in h.periods] == pytest.approx([29, 31, 33, 50, 62])
    assert any("1.79 倍" in n for n in h.notes)


def test_merge_adjusts_interim_dividend_for_mid_year_split():
    # トヨタ型: 期の途中（中間配当の基準日の後）に 1→5 の分割。当期の年間配当は「分割前の中間 120 円＋分割後の期末 28 円」
    periods = [fp(2020, 700, 7000, 220, 3_000_000), fp(2021, 800, 8000, 240, 3_000_000),
               fp(2022, 205, 1900, 148, 15_000_000), fp(2023, 180, 2090, 60, 15_000_000)]
    for p, interim in zip(periods, (100, 120, 120, 25)):
        p.interim_dps = interim
    # 古い期の EPS/BPS は分割未修正（報告書をまたいだ想定）だが、ここでは配当だけを見る
    h = merge_reports([AnnualReport(doc_id="r", periods=periods)], known_splits=[(date(2021, 9, 29), 5.0)])
    assert [p.dps for p in h.periods] == pytest.approx([44, 48, 52, 60])
    assert any("中間配当" in n for n in h.notes)
    # 分割日が分からなくても、配当のつながりから同じ判断になる
    periods2 = [replace(p) for p in periods]
    for p, d, i in zip(periods2, (220, 240, 148, 60), (100, 120, 120, 25)):
        p.dps, p.interim_dps = d, i
    assert [p.dps for p in merge_reports([AnnualReport(doc_id="r", periods=periods2)]).periods] == pytest.approx([44, 48, 52, 60])


# ---- 判定 -----------------------------------------------------------------

def test_stage1_pass_and_failures():
    latest = fp(2026, eps=200, bps=2000, dps=60, shares=10_000_000, ni=1e9, ta=2.5e10, er=45, roe=10)
    s = evaluate_stage1(latest, price=2000)
    assert s.passed is True
    assert s.per == pytest.approx(10) and s.pbr == pytest.approx(1.0)
    assert s.dividend_yield == pytest.approx(3.0) and s.market_cap == pytest.approx(2e10)
    assert s.roa == pytest.approx(4.0)

    bad = evaluate_stage1(latest, price=3000)  # PER 15, PBR 1.5, 利回り 2%
    assert bad.passed is False and {"PER", "PBR", "配当利回り"} <= set(bad.failures)


def test_stage1_financial_skips_roa_and_equity_ratio():
    bank = fp(2026, eps=200, bps=2000, dps=60, shares=10_000_000, ni=1e9, ta=1e12, er=5, roe=10)
    assert evaluate_stage1(bank, 2000, financial=False).passed is False
    assert evaluate_stage1(bank, 2000, financial=True).passed is True


def test_stage1_missing_price_and_loss():
    profitable = fp(2026, eps=200, bps=2000, dps=60, shares=10_000_000, ni=1e9, ta=2.5e10)
    s = evaluate_stage1(profitable, None)
    assert s.passed is None and s.missing == ["株価"]
    loss = fp(2026, eps=-10, bps=2000, dps=60, shares=10_000_000)
    for price in (None, 2000):  # 赤字なら株価に関係なく不合格
        r = evaluate_stage1(loss, price)
        assert r.passed is False and "PER（直近期赤字）" in r.failures and "PER" not in r.missing


def ten_years(eps=None, bps=None, dps=None):
    eps = eps or [100 + 15 * i for i in range(10)]
    bps = bps or [1000 + 120 * i for i in range(10)]
    dps = dps or [30 + 3 * i for i in range(10)]
    return merge_reports([AnnualReport(doc_id="x", periods=[
        fp(2017 + i, eps[i], bps[i], dps[i], 1_000_000) for i in range(10)
    ])])


def test_stage2_pass():
    s = evaluate_stage2(ten_years())
    assert s.passed is True
    assert s.eps_ratio == pytest.approx(235 / 100)
    assert s.bps_streak == 9 and s.bps_all_increase
    assert s.bps_growth == pytest.approx(2080 / 1000)


def test_stage2_failures():
    assert "EPS 2倍未達" in evaluate_stage2(ten_years(eps=[100 + i for i in range(10)])).failures
    bps = [1000 + 120 * i for i in range(10)]
    bps[5] = bps[4] - 1
    assert "BPS減少あり" in evaluate_stage2(ten_years(bps=bps)).failures
    eps = [100 + 15 * i for i in range(10)]
    eps[3] = -5
    assert "EPS赤字あり" in evaluate_stage2(ten_years(eps=eps)).failures


def test_stage2_dividend_cuts():
    one_cut = [30, 33, 36, 30, 40, 42, 44, 46, 48, 50]
    assert evaluate_stage2(ten_years(dps=one_cut)).passed is True
    two_cuts = [30, 33, 36, 30, 40, 35, 44, 46, 48, 50]
    assert "減配2回" in evaluate_stage2(ten_years(dps=two_cuts)).failures
    suspended = [30, 33, 36, 0, 40, 42, 44, 46, 48, 50]
    assert "無配転落あり" in evaluate_stage2(ten_years(dps=suspended)).failures


def test_stage2_short_history_is_undetermined():
    h = merge_reports([AnnualReport(doc_id="x", periods=[fp(2022 + i, 100 + i, 1000 + i, 30, 1) for i in range(5)])])
    s = evaluate_stage2(h)
    assert s.passed is None and any("10期分のデータなし" in m for m in s.missing)


def test_stage3_doe_and_marks():
    s = evaluate_stage3("累進配当を基本とし、連結株主資本配当率（DOE）3.75%以上を目途とします。", 1.06, True)
    assert s.progressive and s.doe and s.doe_values == [3.75] and s.mark == "★"
    s = evaluate_stage3("ＤＯＥ４％程度または配当性向40％程度", 1.25, True)
    assert s.doe_values == [4.0] and s.pbr_near_one is False and s.mark == "☆"
    assert evaluate_stage3("配当性向30%以上", 0.66, True).mark == ""


# ---- EDINET クライアント ----------------------------------------------------

def test_parse_code_list_keeps_listed_companies():
    text = (
        "ダウンロード実行日,2026年10月12日現在,件数,3件\n"
        "ＥＤＩＮＥＴコード,提出者種別,上場区分,連結の有無,資本金,決算日,提出者名,提出者名（英字）,提出者名（ヨミ）,所在地,提出者業種,証券コード,提出者法人番号\n"
        "E02144,内国法人・組合,上場,有,635401,3月31日,トヨタ自動車株式会社,TOYOTA,トヨタ,愛知県,輸送用機器,72030,1\n"
        "E99999,内国法人・組合,非上場,有,1,3月31日,非上場株式会社,X,ヒ,東京都,サービス業,,2\n"
        "E05426,内国法人・組合,上場,有,1,3月31日,みずほリース株式会社,M,ミ,東京都,その他金融業,84250,3\n"
    ).encode("cp932")
    companies = parse_code_list(text)
    assert [(c.sec_code, c.industry) for c in companies] == [("7203", "輸送用機器"), ("8425", "その他金融業")]


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content if payload is None else json.dumps(payload).encode()
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def test_client_filters_and_caches_document_lists(tmp_path):
    payload = {"metadata": {"status": "200"}, "results": [
        {"docID": "S1", "edinetCode": "E1", "secCode": "72030", "docTypeCode": "120", "withdrawalStatus": "0", "xbrlFlag": "1", "periodEnd": "2026-03-31"},
        {"docID": "S2", "edinetCode": "E2", "secCode": "13010", "docTypeCode": "140", "withdrawalStatus": "0", "xbrlFlag": "1"},
        {"docID": "S3", "edinetCode": "E3", "secCode": "13010", "docTypeCode": "120", "withdrawalStatus": "1", "xbrlFlag": "1"},
    ]}
    session = FakeSession([FakeResponse(payload=payload)])
    client = EdinetClient(api_key="SECRET", cache_dir=tmp_path, sleep=0, session=session)
    rows = client.annual_reports_on(date(2026, 6, 20))
    assert [r["docID"] for r in rows] == ["S1"]
    assert session.calls[0][1]["Subscription-Key"] == "SECRET"
    assert client.annual_reports_on(date(2026, 6, 20)) == rows  # 2 回目はキャッシュ
    assert len(session.calls) == 1


def test_client_caches_report_facts_and_rebuilds(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/jpcrp030000-asr-001_E0-000_2026-03-31_01_2026-06-20.xbrl",
                    make_instance(five_periods(), policy="累進配当"))
    session = FakeSession([FakeResponse(content=buf.getvalue())])
    client = EdinetClient(api_key="K", cache_dir=tmp_path, sleep=0, session=session)
    first = client.annual_report("S100TEST")
    second = client.annual_report("S100TEST")  # 2 回目はキャッシュした要素から組み立て直す
    assert len(session.calls) == 1
    assert second == first and second.latest.eps == 140 and second.filing_date == date(2026, 6, 20)
    assert (tmp_path / "reports" / "S100TEST.json.gz").exists()


def test_client_error_does_not_leak_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr("jpstock.edinet.time.sleep", lambda s: None)
    session = FakeSession([FakeResponse(status=401, content=b"unauthorized")])
    client = EdinetClient(api_key="SECRET", cache_dir=tmp_path, sleep=0, session=session)
    with pytest.raises(EdinetError) as err:
        client.annual_reports_on(date(2026, 6, 20))
    assert "SECRET" not in str(err.value) and "401" in str(err.value)


def test_client_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    client = EdinetClient(cache_dir=tmp_path, sleep=0, session=FakeSession([]))
    with pytest.raises(EdinetError):
        client.annual_reports_on(date(2026, 6, 20))


# ---- 株価 ---------------------------------------------------------------------

def test_parse_download_frame_reads_close_and_splits():
    idx = pd.to_datetime(["2026-03-30", "2026-04-01", "2026-10-09"])
    cols = pd.MultiIndex.from_product([["1847.T", "7203.T"], ["Close", "Stock Splits"]])
    df = pd.DataFrame([[3000, 0, 2900, 0], [1500, 2.0, 2950, 0], [1600, 0, 3000, 0]], index=idx, columns=cols)
    prices = parse_download_frame(df, ["1847.T", "7203.T", "9999.T"])
    assert prices["1847"].price == 1600 and prices["1847"].as_of == date(2026, 10, 9)
    assert prices["1847"].splits == [(date(2026, 4, 1), 2.0)]
    assert prices["1847"].split_factor_after(date(2026, 3, 31)) == 2.0
    assert prices["7203"].split_factor_after(date(2026, 3, 31)) == 1.0
    assert "9999" not in prices


class FakeYF:
    """yfinance の代わり。最初の呼び出しはアクセス制限で全滅し、2 回目から値を返す."""

    def __init__(self):
        self.calls = []
        self.shared = type("S", (), {"_ERRORS": {}})()

    def download(self, tickers, **kw):
        self.calls.append(list(tickers))
        if len(self.calls) == 1:
            self.shared._ERRORS = {t: "YFRateLimitError('Too Many Requests. Rate limited.')" for t in tickers}
            return pd.DataFrame()
        self.shared._ERRORS = {}
        idx = pd.to_datetime(["2026-10-08", "2026-10-09"])
        cols = pd.MultiIndex.from_product([tickers, ["Close", "Stock Splits"]])
        return pd.DataFrame([[1000, 0] * len(tickers), [1010, 0] * len(tickers)], index=idx, columns=cols)


def test_fetch_prices_retries_rate_limit_and_caches(tmp_path, monkeypatch):
    fake = FakeYF()
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    from jpstock.prices import fetch_prices
    waits = []
    prices = fetch_prices(["7203", "9882"], cache_dir=tmp_path, log=lambda m: None, sleep=waits.append)
    assert prices["7203"].price == 1010 and prices["9882"].as_of == date(2026, 10, 9)
    assert len(fake.calls) == 2 and 30 in waits
    again = fetch_prices(["7203", "9882"], cache_dir=tmp_path, log=lambda m: None, sleep=waits.append)
    assert len(fake.calls) == 2 and again["7203"].price == 1010  # 同じ日の 2 回目はキャッシュ


class LoggingFakeYF(FakeYF):
    """yfinance 1.x 型: エラーは shared に残らずログに出るだけ."""

    def download(self, tickers, **kw):
        import logging
        df = super().download(tickers, **kw)
        if self.shared._ERRORS:
            logging.getLogger("yfinance").error(f"{list(tickers)}: YFRateLimitError('Too Many Requests. Rate limited.')")
            self.shared._ERRORS = {}
        return df


def test_fetch_prices_detects_rate_limit_from_log(tmp_path, monkeypatch):
    fake = LoggingFakeYF()
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    from jpstock.prices import fetch_prices
    prices = fetch_prices(["7203"], log=lambda m: None, sleep=lambda s: None)
    assert prices["7203"].price == 1010 and len(fake.calls) == 2


class RegionalFakeYF(FakeYF):
    """東証（.T）では見つからず、札証（.S）にだけある銘柄."""

    def download(self, tickers, **kw):
        self.calls.append(list(tickers))
        self.shared._ERRORS = {}
        found = [t for t in tickers if t.endswith(".S")]
        if not found:
            return pd.DataFrame()
        idx = pd.to_datetime(["2026-10-09"])
        cols = pd.MultiIndex.from_product([found, ["Close", "Stock Splits"]])
        return pd.DataFrame([[1394, 0] * len(found)], index=idx, columns=cols)


def test_fetch_prices_falls_back_to_regional_exchanges(monkeypatch):
    fake = RegionalFakeYF()
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    from jpstock.prices import fetch_prices
    prices = fetch_prices(["1832"], log=lambda m: None, sleep=lambda s: None)
    assert prices["1832"].price == 1394 and prices["1832"].symbol == "1832.S"
    assert fake.calls == [["1832.T"], ["1832.S"]]


def test_load_prices_csv(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("code,price,date\n7203,\"3,061\",2026-10-09\n1911.T,1190,2026-10-08\nbad,x,2026-10-08\n", encoding="utf-8")
    prices = load_prices_csv(path)
    assert prices["7203"].price == 3061 and prices["1911"].as_of == date(2026, 10, 8)
    assert "BAD" not in prices


# ---- パイプライン全体 ------------------------------------------------------

def report_for(code, first_year, eps0, bps0, dps0, *, bps_dip=None, er=50.0):
    periods = []
    for i in range(5):
        y = first_year + i
        bps = bps0 + 120 * i
        if bps_dip == y:
            bps = bps0 + 120 * (i - 1) - 5
        periods.append(fp(y, eps0 + 15 * i, bps, dps0 + 3 * i, 10_000_000, ni=1e9, ta=2.5e10, er=er, roe=10))
    return AnnualReport(doc_id=f"{code}-{first_year}", sec_code=code, dividend_policy="DOE3%以上を目安", periods=periods)


class FakeClient:
    def __init__(self, companies, reports):
        self._companies = companies
        self.reports = reports  # {(edinet_code, 最新期の年): AnnualReport}

    def companies(self):
        return self._companies

    def latest_annual_reports(self, start, end):
        return {c.edinet_code: {"docID": f"{c.edinet_code}:2026"}
                for c in self._companies if (c.edinet_code, 2026) in self.reports}

    def annual_report(self, doc_id):
        code, year = doc_id.split(":")
        return self.reports[(code, int(year))]

    def find_annual_report(self, edinet_code, period_end):
        if (edinet_code, period_end.year) in self.reports:
            return {"docID": f"{edinet_code}:{period_end.year}"}
        return None


def make_company(edinet, sec, industry="建設業"):
    return Company(edinet_code=edinet, sec_code=sec, name=f"会社{sec}", industry=industry,
                   fiscal_year_end="3月31日", consolidated="有")


def full_set(code, edinet, **kw):
    # 2017〜2026 の 10 期: 最新(22〜26)、4年前(18〜22)、5年前(17〜21)
    eps = lambda y: 100 + 15 * (y - 2017)  # noqa: E731
    bps = lambda y: 1000 + 120 * (y - 2017)  # noqa: E731
    dps = lambda y: 30 + 3 * (y - 2017)  # noqa: E731
    out = {}
    for latest_year, first in ((2026, 2022), (2022, 2018), (2021, 2017)):
        out[(edinet, latest_year)] = report_for(code, first, eps(first), bps(first), dps(first), **kw)
    return out


def test_run_pipeline_end_to_end(tmp_path):
    companies = [make_company("E1", "1111"), make_company("E2", "2222"), make_company("E3", "3333"),
                 make_company("E4", "4444", industry="その他金融業"), make_company("E5", "5555")]
    reports = {}
    reports.update(full_set("1111", "E1"))
    reports.update(full_set("2222", "E2"))
    reports.update(full_set("3333", "E3", bps_dip=2019))
    reports.update(full_set("4444", "E4", er=8.0))
    client = FakeClient(companies, reports)  # E5 は有報なし

    # 2026/3 期は EPS 235・BPS 2080・配当 57。株価 1900 で PER 8.1・PBR 0.91・利回り 3.0%
    prices = {"1111": PriceInfo(1900, date(2026, 10, 9)), "2222": PriceInfo(4000, date(2026, 10, 9)),
              "3333": PriceInfo(1900, date(2026, 10, 9)), "4444": PriceInfo(1900, date(2026, 10, 9))}
    rows = screen.run_pipeline(client, lambda codes: {c: prices[c] for c in codes if c in prices},
                               as_of=date(2026, 10, 12), log=lambda m: None)
    status = {r.company.sec_code: r.status for r in rows}
    assert status == {"1111": "通過", "2222": "第1段階 不通過", "3333": "第2段階 不通過",
                      "4444": "通過", "5555": "有報なし"}
    passed = next(r for r in rows if r.company.sec_code == "1111")
    assert passed.stage2.eps_ratio == pytest.approx(235 / 100)
    assert passed.stage3.doe_values == [3.0]

    md = screen.render_markdown(rows, date(2026, 10, 12))
    assert "会社1111" in md and "### 金融（別枠）" in md and "会社3333" in md
    assert screen.display_name("株式会社\u3000極洋") == "極洋"
    out = tmp_path / "all.csv"
    screen.write_csv(rows, out)
    assert out.read_text(encoding="utf-8-sig").count("\n") == len(rows) + 1


def test_adjust_for_splits_after_filing():
    # 有報提出（6/20）より後の分割は EPS・BPS・配当・株式数のすべてに反映
    report = AnnualReport(doc_id="x", filing_date=date(2026, 6, 20),
                          periods=[fp(2026, 200, 2000, 60, 10_000_000, ni=2e9)])
    price = PriceInfo(1000, date(2026, 10, 9), splits=[(date(2026, 9, 29), 2.0)])
    adjusted, note = screen.adjust_for_later_splits(report, price)
    assert adjusted.latest.eps == 100 and adjusted.latest.bps == 1000
    assert adjusted.latest.dps == 30 and adjusted.latest.shares == 20_000_000
    assert "提出後" in note and report.latest.eps == 200  # 元の報告書は変えない


def test_adjust_for_split_between_period_end_and_filing():
    # イチケン型: 4/1 効力発生の分割（Yahoo の権利落ち日は 3/30）。有報の EPS・BPS は分割後の基準、
    # 期末発行済株式数と 1 株配当は分割前のまま（純利益 ÷ EPS が発行済株式数の 2 倍）
    report = AnnualReport(doc_id="x", filing_date=date(2026, 6, 18),
                          periods=[fp(2026, 200, 2000, 60, 10_000_000, ni=4e9)])
    price = PriceInfo(1500, date(2026, 10, 9), splits=[(date(2026, 3, 30), 2.0)])
    adjusted, note = screen.adjust_for_later_splits(report, price)
    assert adjusted.latest.eps == 200 and adjusted.latest.bps == 2000
    assert adjusted.latest.dps == 30 and adjusted.latest.shares == 20_000_000
    assert "決算期末〜提出日" in note and "要確認" not in note

    # Yahoo に分割履歴が無くても、比が 2 倍なら反映して要確認の注記を付ける
    adjusted, note = screen.adjust_for_later_splits(report, PriceInfo(1500, date(2026, 10, 9)))
    assert adjusted.latest.dps == 30 and "要確認" in note


def test_adjust_ignores_split_already_in_period_end_shares():
    # 権利落ちが期末の数日前でも、期末までに効力が生じていれば株式数は分割後（比は 1 倍前後）
    report = AnnualReport(doc_id="x", filing_date=date(2026, 6, 18),
                          periods=[fp(2026, 200, 2000, 60, 10_000_000, ni=1.9e9)])
    price = PriceInfo(1500, date(2026, 10, 9), splits=[(date(2026, 3, 26), 2.0)])
    assert screen.adjust_for_later_splits(report, price) == (report, None)
    # 比が 0.5 未満（期末直前の増資など）でも、Yahoo の裏付けが無ければ併合とはみなさない
    low = AnnualReport(doc_id="y", filing_date=date(2026, 6, 18),
                       periods=[fp(2026, 200, 2000, 60, 10_000_000, ni=0.8e9)])
    assert screen.adjust_for_later_splits(low, PriceInfo(1500, date(2026, 10, 9))) == (low, None)


def test_rebase_history_puts_series_on_current_share_basis():
    h = ten_years()
    rebased = screen.rebase_history(h, after_filing=1.0, before_filing=2.0)  # イチケン型: 期末後・提出前の 1→2 分割
    assert [p.dps for p in rebased.periods] == pytest.approx([p.dps / 2 for p in h.periods])
    assert [p.eps for p in rebased.periods] == [p.eps for p in h.periods]
    assert evaluate_stage2(rebased).dividend_cuts == evaluate_stage2(h).dividend_cuts
    assert screen.rebase_history(h, 1.0, 1.0) is h


def test_run_pipeline_skips_annual_report_without_summary_table():
    # クレディセゾン型: いちばん新しい有報（別の有報）に主要な経営指標が無い → 次の候補を使う
    companies = [make_company("E1", "1111")]
    reports = full_set("1111", "E1")
    reports[("E1", 9999)] = AnnualReport(doc_id="other", periods=[])

    class CandidateClient(FakeClient):
        def annual_report_candidates(self, start, end):
            return {"E1": [{"docID": "E1:9999"}, {"docID": "E1:2026"}]}

    prices = {"1111": PriceInfo(1900, date(2026, 10, 9))}
    rows = screen.run_pipeline(CandidateClient(companies, reports), lambda codes: prices, as_of=date(2026, 10, 12),
                               log=lambda m: None)
    assert rows[0].status == "通過" and any("主要な経営指標が無い" in n for n in rows[0].notes)


def test_small_split_is_not_matched_to_unchanged_share_count_or_normal_bps_growth():
    # 橋本総業型: Yahoo に 1.1 倍の分割があっても、株式数が変わらない期には当てはめない
    report = AnnualReport(doc_id="r", periods=[
        fp(2017, 50, 1000, 20, 10_000_000), fp(2018, 55, 1050, 22, 10_000_000), fp(2019, 60, 1100, 24, 10_000_000),
    ])
    h = merge_reports([report], known_splits=[(date(2018, 3, 28), 1.1)])
    assert h.splits == [] and [p.dps for p in h.periods] == [20, 22, 24]
    # タクミナ型: 1.2 倍の分割（株式数も 1.2 倍）で、前の期の BPS が普通に増えているだけなら割り戻さない
    report2 = AnnualReport(doc_id="r", periods=[
        fp(2017, 50, 1000, 20, 10_000_000), fp(2018, 46, 1040, 18, 12_000_000), fp(2019, 50, 1090, 19, 12_000_000),
    ])
    h2 = merge_reports([report2], known_splits=[(date(2017, 9, 27), 1.2)])
    assert h2.splits == [(date(2018, 3, 31), 1.2)]
    assert [p.bps for p in h2.periods] == [1000, 1040, 1090] and not any("未修正" in n for n in h2.notes)


def test_blank_dividend_is_treated_as_no_dividend_when_other_periods_have_one():
    # 石原産業型: 2 期は無配（欄が「－」）、その後に復配
    xbrl = make_instance(five_periods())
    for ctx in ("Prior4YearDuration_NonConsolidatedMember", "Prior3YearDuration_NonConsolidatedMember"):
        value = {"Prior4YearDuration_NonConsolidatedMember": 30, "Prior3YearDuration_NonConsolidatedMember": 31}[ctx]
        xbrl = xbrl.replace(
            f'<jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults contextRef="{ctx}" unitRef="u" decimals="2">{value}</jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults>'.encode(),
            f'<jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults contextRef="{ctx}" unitRef="u" xsi:nil="true"/>'.encode())
    report = build_report(*parse_instance(xbrl), doc_id="X")
    assert [p.dps for p in report.periods] == [0, 0, 32, 33, 34]
    h = merge_reports([report])
    assert any("無配とみなした" in n for n in h.notes)
    s2 = evaluate_stage2(h)
    assert s2.dividend_cuts == [] and s2.dividend_suspended == [] and "1株配当欠損" not in s2.missing
