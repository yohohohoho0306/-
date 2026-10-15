"""tools/ricky_report の月次の実行まわり（実行日の判定・キャッシュ・表記の引き継ぎ・前回の選び方）のテスト."""

import csv
import gzip
import io
import json
import os
import sys
import tarfile
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "ricky_report")))

import build_tables  # noqa: E402
import cache_sync  # noqa: E402
import prev_passers  # noqa: E402
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


def test_run_day_starts_on_or_after_the_run_date_until_the_month_is_done():
    nov = date(2026, 11, 13)  # 2026-11 の実行日（14日は土曜日）
    assert run_day.decide(date(2026, 11, 12), []) == (False, nov)
    assert run_day.decide(nov, [date(2026, 10, 14)]) == (True, nov)
    assert run_day.decide(date(2026, 11, 16), [date(2026, 11, 12)]) == (True, nov)  # 実行日より前の実行は数えない
    assert run_day.decide(date(2026, 11, 16), [nov]) == (False, nov)


def test_prune_keeps_old_reports_only_for_stage1_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_sync, "CACHE", tmp_path)
    reports = tmp_path / "edinet" / "reports"
    reports.mkdir(parents=True)
    (tmp_path / "edinet" / "lists").mkdir()
    for doc, end, sec in (("KEEP", "2022-03-31", "13010"), ("DROP", "2022-03-31", "99990"), ("NEW", "2026-03-31", "99990")):
        facts = {"facts": {"CurrentFiscalYearEndDateDEI": {"FilingDateInstant": end},
                           "SecurityCodeDEI": {"FilingDateInstant": sec}}}
        (reports / f"{doc}.json.gz").write_bytes(gzip.compress(json.dumps(facts).encode()))
    assert cache_sync.prune(date(2026, 10, 15), {"1301"}) == (0, 1)
    assert sorted(p.name for p in reports.iterdir()) == ["KEEP.json.gz", "NEW.json.gz"]


def test_restore_takes_only_plain_files_under_edinet():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("edinet/lists/2026-10-01.json", "edinet/../prices/x.json", "/edinet/abs.json", "other/y.json"):
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"[]"))
        link = tarfile.TarInfo("edinet/link")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        assert [m.name for m in cache_sync.safe_members(tar)] == ["edinet/lists/2026-10-01.json"]


def _results(tmp_path, codes):
    res = tmp_path / "results"
    res.mkdir()
    with open(res / "ricky_all_20261113.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["コード", "DOE", "累進", "DOE数値"])
        w.writeheader()
        for c in codes:
            w.writerow({"コード": c, "DOE": "", "累進": "", "DOE数値": ""})
    (res / "series.json").write_text("{}", encoding="utf-8")
    return res


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def fresh_tables(monkeypatch):
    for name in ("rows", "series", "research", "review", "fragile", "checked_on"):
        monkeypatch.setattr(build_tables, name, {})
    monkeypatch.setattr(build_tables, "MANUAL", {k: {} for k in build_tables.MANUAL})
    monkeypatch.setattr(build_tables, "LABEL_DAY", {k: {} for k in build_tables.MANUAL})


def test_labels_carry_over_can_be_removed_and_lose_tied_notes_after_new_research(tmp_path, fresh_tables):
    res = _results(tmp_path, ["1111", "2222", "3333", "4444"])
    data = tmp_path / "data"
    old = _write(data / "2026-10-13" / "labels.json", {
        "doe": {"1111": "DOE 3%以上（下限）", "2222": "DOE 2%以上", "4444": "DOE 2%以上"},
        "evidence": {"1111": {"text": "前の調査の文"}, "3333": {"text": "調べ直していない銘柄の文"}},
        "caution": {"2222": "前回の注意"}})
    new = _write(data / "2026-11-13" / "labels.json", {"doe": {"2222": "DOEの採用なし"}, "caution": {"2222": None}})
    policy = {"progressive": "累進の明記なし", "doe": "DOE 4%を下限（中計）"}
    verify = _write(data / "2026-11-13" / "verify.json", {"passers": [{"research": {"stocks": [
        {"code": "1111", "policy": policy}, {"code": "2222", "policy": policy},
        {"code": "4444", "policy": {"progressive": "累進の明記なし", "doe": "DOEの採用なし（有報に記載なし）"}}]}}]})
    build_tables.load(res, [verify], [old, new])
    assert build_tables.doe_adopted("1111") and build_tables.policy_text("1111") == "累進：記載なし／DOE 3%以上（下限）"
    assert not build_tables.doe_adopted("2222")  # 後の labels.json で「DOEの採用なし」
    assert build_tables.policy_text("2222") == "累進：記載なし／DOE：なし"
    assert "2222" not in build_tables.MANUAL["caution"]  # null で消えた
    assert "1111" not in build_tables.MANUAL["evidence"]  # 2026-11-13 に調べ直したので前の文は使わない
    assert build_tables.MANUAL["evidence"]["3333"]["text"] == "調べ直していない銘柄の文"
    # 2026-10-13 の表記のまま、2026-11-13 の調査では DOE が見つからなかった（2222 は 11-13 に書き直し済み）
    assert [(c, k) for c, k, *_ in build_tables.stale_labels()] == [("4444", "DOE")]


def test_doe_found_by_research_counts_without_a_label(tmp_path, fresh_tables):
    res = _results(tmp_path, ["1111", "2222"])
    verify = _write(tmp_path / "data" / "2026-11-13" / "verify.json", {"passers": [{"research": {"stocks": [
        {"code": "1111", "policy": {"progressive": "累進配当を明記", "doe": "DOE 1.5%を下限"}},
        {"code": "2222", "policy": {"progressive": "未確認", "doe": "未確認（有報にDOEの記載なし）"}}]}}]})
    build_tables.load(res, [verify], [])
    assert build_tables.doe_adopted("1111") and build_tables.policy_text("1111") == "累進：あり／DOE 1.5%を下限"
    assert not build_tables.doe_adopted("2222")
    assert build_tables.policy_text("2222") == "累進：有報に記載なし（IR資料は未確認）／DOE：有報に記載なし（IR資料は未確認）"


def test_prev_passers_picks_the_latest_usable_file_before_the_as_of(tmp_path, monkeypatch):
    monkeypatch.setattr(prev_passers, "DATA", tmp_path)
    _write(tmp_path / "2026-10-12" / "passers.json", {"run": "2026-10-12", "stocks": {"1111": {"name": "A", "method": "手作業"}}})
    _write(tmp_path / "2026-10-13" / "passers.json", {"run": "2026-10-13", "stocks": {"1111": {"latest_period_end": "2026-03-31"}}})
    _write(tmp_path / "2026-11-13" / "passers.json", {"run": "2026-11-13", "stocks": {"1111": {"latest_period_end": "2026-03-31"}}})
    assert prev_passers.find("2026-11-13") == tmp_path / "2026-10-13" / "passers.json"
    assert prev_passers.find("2026-10-13") is None
    with pytest.raises(SystemExit):
        prev_passers.load(str(tmp_path / "2026-10-12" / "passers.json"), "2026-11-13")
