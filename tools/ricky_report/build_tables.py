"""通過銘柄・金融・第2段階の不通過・テーマ性の根拠の表を作る（判定結果の CSV・系列・確認結果から）.

    python tools/ricky_report/build_tables.py passed --results results/full \
        --verify research/data/2026-10-13/verify.json --labels research/data/2026-10-13/labels.json

表の種類: passed（事業会社の通過銘柄）・financial（金融）・fails（第2段階の不通過）・evidence（テーマ性の根拠）。
assemble.py から import して使う（load() で読み込んでから各関数を呼ぶ）。

- verify.json: workflows/verify.js の結果（collect_verify.py でまとめたもの）。複数渡すと後のものを優先。
- labels.json: 人が確かめて決めた表記。theme（テーマ性の表記）・doe（DOE の表記）・evidence（根拠を直接書く銘柄）、
  ノート用の補足 theme_note・policy_note・numbers_note・caution。複数渡すと後のものを優先
  （research/data/*/labels.json を古い順にすべて渡せば、前回までの表記を引き継いで今回の分で上書きできる）。
"""
import argparse
import csv
import json
import re
from pathlib import Path

rows, series = {}, {}
research, review, fragile = {}, {}, {}
checked_on = {}  # 銘柄コード → 調査・点検した日（verify.json の親フォルダ名 research/data/<日付>/）
MANUAL = {"theme": {}, "doe": {}, "evidence": {}, "theme_note": {}, "policy_note": {}, "numbers_note": {},
          "caution": {}}


def load(results, verify_paths=(), label_paths=()):
    """判定結果（results/full など）・確認結果・表記を読み込む。モジュールの変数に入れる."""
    res = Path(results)
    rows.clear()
    rows.update({r["コード"]: r for r in csv.DictReader(open(max(res.glob("ricky_all_*.csv")), encoding="utf-8-sig"))})
    series.clear()
    series.update(json.loads((res / "series.json").read_text(encoding="utf-8")))
    for p in verify_paths:
        verify = json.loads(Path(p).read_text(encoding="utf-8"))
        day = Path(p).resolve().parent.name
        for b in verify.get("passers", []):
            for st in (b.get("research") or {}).get("stocks", []):
                research[st["code"]] = st
                checked_on[st["code"]] = day
            for rv in (b.get("review") or {}).get("reviews", []):
                review[rv["code"]] = rv
        for b in verify.get("fragile", []):
            for st in (b.get("result") or {}).get("stocks", []):
                fragile[st["code"]] = st
    for p in label_paths:
        labels = json.loads(Path(p).read_text(encoding="utf-8"))
        for key in MANUAL:
            MANUAL[key].update(labels.get(key, {}))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def f(v, d=2):
    x = num(v)
    return "未確認" if x is None else f"{x:,.{d}f}"


def ym(d):  # 2021-03-31 -> 21/3
    return f"{d[2:4]}/{int(d[5:7])}" if d else ""


def _policy_raw(code):
    """調査担当が調べた配当方針（dict）。無ければ反証役の修正文（str）、どちらも無ければ None."""
    p = (research.get(code) or {}).get("policy")
    if isinstance(p, dict):
        return p
    rv = review.get(code) or {}
    if rv.get("policy_verdict") == "修正" and rv.get("revised_policy"):
        return rv["revised_policy"]
    return None




def doe_adopted(code):
    """DOE を配当の指標に使っているか（会社資料・有報で確認した表記 MANUAL["doe"] に載っているもの）."""
    if code in MANUAL["doe"]:
        return True
    p = _policy_raw(code)
    if isinstance(p, dict):
        return False  # 調査済みで DOE の記載なし
    return bool(rows[code]["DOE"])


def policy_text(code):
    r = rows[code]
    p = _policy_raw(code)
    if isinstance(p, dict):
        prog = {"累進配当を明記": "累進：あり", "累進の明記なし": "累進：記載なし",
                "未確認": "累進：有報に記載なし（IR資料は未確認）"}.get(p["progressive"], p["progressive"])
        if code in MANUAL["doe"]:
            doe = MANUAL["doe"][code]
        elif p["doe"].startswith("未確認"):
            doe = "DOE：有報に記載なし（IR資料は未確認）"
        else:
            doe = "DOE：なし"
        return f"{prog}／{doe}"
    if isinstance(p, str):
        return p
    prog = "累進：有報に記載あり" if r["累進"] else "累進：有報に記載なし"
    doe = f"DOE：有報に記載あり（{r['DOE数値'] or '数値なし'}）" if r["DOE"] else "DOE：有報に記載なし"
    return f"{prog}／{doe}"


def theme_full(code):
    """（ラベル, 根拠, 出典）。反証役の判断を反映する."""
    t = (research.get(code) or {}).get("theme")
    rv = review.get(code) or {}
    if not t:
        return "未確認", "", ""
    if rv.get("theme_verdict") == "未確認に変更":
        return "未確認", rv.get("theme_reason", ""), t.get("source_url", "")
    label = rv.get("revised_theme_label") if rv.get("theme_verdict") == "表現を修正" and rv.get("revised_theme_label") else t["label"]
    if not t.get("profit_already") and not label.startswith(("未確認", "該当なし")):
        label = "未確認"
    return label, t.get("evidence", ""), t.get("source_url", "")


def theme_text(code):
    if code in MANUAL["theme"]:
        return MANUAL["theme"][code]
    label = theme_full(code)[0]
    if label.startswith("未確認"):
        return "未確認"
    if label.startswith("該当なし"):
        return "該当なし（確認範囲）"
    return re.split(r"[（(]", label)[0].strip()


def mark(code):
    pbr = num(rows[code]["PBR"])
    near = pbr is not None and 0.8 <= pbr <= 1.2
    hits = 1 + int(doe_adopted(code)) + int(near)  # 通過銘柄は BPS が毎期増加
    return "★" if hits == 3 else ("☆" if hits == 2 else "")


def passed_rows(financial):
    out = [
        "| 順位 | 印 | 銘柄名 | コード | 業種 | PER（実績） | PBR | ROE | ROA | 配当利回り（実績） | 自己資本比率 | 時価総額 | "
        "EPS 9期前→直近（倍率） | BPS 10年伸び率 | BPS連続増加期数 | 減配回数 | 配当方針（累進・DOE） | テーマ性 | データ取得日 |",
        "|" + "---|" * 19,
    ]
    codes = [c for c, r in rows.items() if r["判定"] == "通過" and bool(r["金融"]) == financial]
    codes.sort(key=lambda c: -num(rows[c]["BPS伸び率"]))
    for i, c in enumerate(codes, 1):
        r = rows[c]
        s = series[c]["periods"][-10:]
        roa = f"{f(r['ROA'])}%" + ("（参考）" if financial else "")
        er = f"{f(r['自己資本比率'], 1)}%" + ("（参考）" if financial else "")
        cuts = r["減配期"].split()
        cut_txt = f"{len(cuts)}回" + (f"（{', '.join(ym(d) for d in cuts)}）" if cuts else "")
        out.append(
            f"| {i} | {mark(c)} | {r['銘柄名']} | {c} | {r['業種']} | {f(r['PER(実績)'])}倍 | {f(r['PBR'])}倍 | {f(r['ROE'], 1)}% | {roa} | "
            f"{f(r['配当利回り(実績)'])}% | {er} | {f(r['時価総額(億円)'], 0)}億円 | "
            f"{f(r['EPS 9期前'])}円({ym(s[0]['end'])})→{f(r['EPS 直近'])}円({ym(s[-1]['end'])}) **{f(r['EPS倍率'])}倍** | "
            f"{f(r['BPS伸び率'])}倍 | {r['BPS連続増加回数']}期連続 | {cut_txt} | {policy_text(c)} | {theme_text(c)} | "
            f"株価 {r['株価日付'][2:].replace('-', '/')}／決算 {ym(r['直近決算期末'])}期 |")
    return out, codes


def fail_reason(r):
    parts = []
    for fl in r["第2段階 不合格項目"].split(" / "):
        if fl == "EPS赤字あり":
            ds = r["赤字期"].split()
            parts.append("赤字（" + ", ".join(ym(d) for d in ds[:3]) + ("…" if len(ds) > 3 else "") + "）")
        elif fl == "EPS 2倍未達":
            parts.append(f"EPS {f(r['EPS倍率'])}倍")
        elif fl == "BPS減少あり":
            ds = r["BPS減少期"].split()
            parts.append("BPS減少（" + ", ".join(ym(d) for d in ds[:3]) + ("…" if len(ds) > 3 else "") + "）")
        elif fl.startswith("減配"):
            ds = r["減配期"].split()
            parts.append(f"{fl}（" + ", ".join(ym(d) for d in ds[:4]) + ("…" if len(ds) > 4 else "") + "）")
        elif fl == "無配転落あり":
            parts.append("無配転落（" + ", ".join(ym(d) for d in r["無配転落期"].split()) + "）")
    return "・".join(parts)


def fails_table():
    out = ["| 銘柄名 | コード | 業種 | 落ちた条件（一言） | EPS 9期前→直近 | BPS 10年伸び率 |", "|---|---|---|---|---|---|"]
    for c in sorted([c for c, r in rows.items() if r["判定"] == "第2段階 不通過"], key=lambda c: (rows[c]["業種"], c)):
        r = rows[c]
        fin = "（金融）" if r["金融"] else ""
        out.append(f"| {r['銘柄名']}{fin} | {c} | {r['業種']} | {fail_reason(r)} | {f(r['EPS 9期前'])}→{f(r['EPS 直近'])} | {f(r['BPS伸び率'])}倍 |")
    return out


def _short(text, limit=200):
    """根拠の文を、確認手段の前置き（「有報（…）で確認した。」など）を除いて先頭の数文に縮める."""
    sents = [x + "。" for x in re.split(r"。", text or "") if x.strip()]
    sents = [x for x in sents if not re.match(r"^(有報|会社資料|EDINET|原本)[^。]{0,40}(確認した|で確認|を確認)。$", x)]
    out = ""
    for x in sents:
        if out and len(out) + len(x) > limit:
            break
        out += x
    return out


def _sources(code):
    ids = []
    t = (research.get(code) or {}).get("theme") or {}
    rv = review.get(code) or {}
    for u in [t.get("source_url", "")] + list(rv.get("sources") or []):
        for d in re.findall(r"S100[0-9A-Z]{4}", u or ""):
            if d not in ids:
                ids.append(d)
    return "有報 " + "・".join(ids[:2]) if ids else "未確認"


def evidence_rows():
    out = ["| 順位 | 銘柄名（コード） | テーマ性（表の表記） | 会社資料の記載の要点 | 点検 | 出典（EDINET 書類番号） |",
           "|---|---|---|---|---|---|"]
    order = passed_rows(False)[1] + passed_rows(True)[1]
    for i, c in enumerate(order, 1):
        t = (research.get(c) or {}).get("theme") or {}
        rv = review.get(c) or {}
        e = MANUAL["evidence"].get(c) or {}
        if e.get("text"):
            ev = e["text"]  # 人が確かめて書き直した根拠
        else:
            ev = re.sub(r"^(有報|2\d{3}/\d+期の有報)[^。]{0,20}(による|より)。", "", t.get("evidence", ""))
            ev = _short(ev, 180).replace("|", "／") or "未確認"
        verdict = e.get("verdict") or rv.get("theme_verdict", "未点検")
        if c in MANUAL["theme_note"]:
            verdict += f"（表記は本体の判断: {MANUAL['theme_note'][c]}）"
        out.append(f"| {i} | {rows[c]['銘柄名']}（{c}） | {theme_text(c)} | {ev} | {verdict} | {e.get('source') or _sources(c)} |")
    return out


def main():
    p = argparse.ArgumentParser(description="表を Markdown で出す")
    p.add_argument("table", choices=["passed", "financial", "fails", "evidence"])
    p.add_argument("--results", default="results/full")
    p.add_argument("--verify", nargs="*", default=[])
    p.add_argument("--labels", nargs="*", default=[])
    a = p.parse_args()
    load(a.results, a.verify, a.labels)
    table = {"passed": lambda: passed_rows(False)[0], "financial": lambda: passed_rows(True)[0],
             "fails": fails_table, "evidence": evidence_rows}[a.table]()
    print("\n".join(table))


if __name__ == "__main__":
    main()
