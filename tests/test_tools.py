"""tools/ricky_report の月次の実行まわり（実行日の判定・キャッシュの古いデータの削除）のテスト."""

import gzip
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "ricky_report")))

import cache_sync  # noqa: E402
import run_day  # noqa: E402


def test_run_day_is_the_14th_on_a_business_day():
    assert run_day.run_date(2026, 10) == date(2026, 10, 14)  # 水曜日


def test_run_day_moves_to_friday_when_the_14th_is_a_weekend():
    assert run_day.run_date(2026, 11) == date(2026, 11, 13)  # 14日は土曜日
    assert run_day.run_date(2027, 2) == date(2027, 2, 12)  # 14日は日曜日


def test_run_day_moves_to_friday_when_the_14th_is_a_monday_holiday():
    pytest.importorskip("jpholiday")
    assert run_day.run_date(2030, 1) == date(2030, 1, 11)  # 14日は成人の日（月曜日）
    assert run_day.run_date(2030, 10) == date(2030, 10, 11)  # 14日はスポーツの日（月曜日）


def test_prune_removes_lists_and_reports_older_than_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_sync, "CACHE", tmp_path)
    lists, reports = tmp_path / "edinet" / "lists", tmp_path / "edinet" / "reports"
    lists.mkdir(parents=True)
    reports.mkdir(parents=True)
    for day in ("2019-01-10", "2021-06-30", "2026-10-01"):
        (lists / f"{day}.json").write_text("[]")
    for doc, end in (("OLD", "2019-03-31"), ("NEW", "2021-03-31")):
        facts = {"facts": {"CurrentFiscalYearEndDateDEI": {"FilingDateInstant": end}}}
        (reports / f"{doc}.json.gz").write_bytes(gzip.compress(json.dumps(facts).encode()))
    assert cache_sync.prune(date(2026, 10, 15)) == (1, 1)  # 基準日の 5年＋600日前（2020-02-19）より前だけ消す
    assert sorted(p.stem for p in lists.glob("*.json")) == ["2021-06-30", "2026-10-01"]
    assert [p.name for p in reports.iterdir()] == ["NEW.json.gz"]
