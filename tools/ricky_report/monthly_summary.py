"""月次の判定の要約（research/runs/<日付>.md）を書く。前回の通過銘柄と比べた変化を、そのまま読める形にする.

    python tools/ricky_report/monthly_summary.py --as-of YYYY-MM-DD --results results/full \
        --prev research/data/<前回>/passers.json \
        --verify research/data/*/verify.json --labels research/data/*/labels.json \
        --checked research/data/*/checked.json

出すもの: 件数、新しく通過・脱落（理由）・印が変わった銘柄、新しい有報が出た通過銘柄と配当政策の記載の変化、
条件の境界に近い通過銘柄、株価の日付が古い銘柄、調整漏れの洗い出しで新しく出た銘柄、まだ調べていない銘柄。
数値は判定結果の CSV の値。売買の推奨はしない。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tables as B  # noqa: E402
import scan_anomalies  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def borderline(r: dict) -> list[str]:
    """第1段階の境界に近い項目（株価や次の決算で外れうるもの）."""
    out = []
    checks = [("配当利回り", num(r["配当利回り(実績)"]), lambda x: x < 3.2, "%"),
              ("PER", num(r["PER(実績)"]), lambda x: x > 11.3, "倍"),
              ("PBR", num(r["PBR"]), lambda x: x > 1.2, "倍"),
              ("時価総額", num(r["時価総額(億円)"]), lambda x: x < 140, "億円")]
    if not r["金融"]:
        checks += [("ROA", num(r["ROA"]), lambda x: x < 3.4, "%"), ("自己資本比率", num(r["自己資本比率"]), lambda x: x < 37, "%")]
    checks.append(("ROE", num(r["ROE"]), lambda x: x < 7.8, "%"))
    for name, x, near, unit in checks:
        if x is not None and near(x):
            out.append(f"{name} {x:g}{unit}")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as-of", required=True)
    p.add_argument("--results", default="results/full")
    p.add_argument("--prev", required=True, help="前回の research/data/<日付>/passers.json")
    p.add_argument("--verify", nargs="*", default=[])
    p.add_argument("--labels", nargs="*", default=[])
    p.add_argument("--checked", nargs="*", default=[])
    p.add_argument("--out", help="既定: research/runs/<as-of>.md")
    a = p.parse_args()
    B.load(a.results, a.verify, a.labels)
    rows = B.rows
    prev_doc = json.loads(Path(a.prev).read_text(encoding="utf-8"))
    prev, prev_run = prev_doc["stocks"], prev_doc["run"]
    anomalies_checked = {}
    for f in a.checked:
        anomalies_checked.update(json.loads(Path(f).read_text(encoding="utf-8")).get("anomalies", {}))

    now = [c for c, r in rows.items() if r["判定"] == "通過"]
    order = B.passed_rows(False)[1] + B.passed_rows(True)[1]
    marks = {c: B.mark(c) for c in now}
    s1 = sum(1 for r in rows.values() if r["判定"] in ("通過", "第2段階 不通過", "第2段階 判定不能"))
    price_day = Counter(r["株価日付"] for r in rows.values() if r["株価日付"]).most_common(1)[0][0]
    new = [c for c in order if c not in prev]
    stay = [c for c in order if c in prev]
    gone = sorted(set(prev) - set(now))

    def why(c):
        r = rows.get(c)
        if r is None:
            return "今回の対象に無い（上場廃止など）"
        return f"{r['判定']}（{r['第1段階 不合格項目'] or r['第2段階 不合格項目'] or r['第1段階 未確認項目'] or r['第2段階 未確認項目']}）"

    def name(c):
        return rows[c]["銘柄名"] if c in rows else prev[c]["name"]

    L = ["---", f"title: 月次の判定 {a.as_of}", f"date: {a.as_of}", "tags: [ricky-screening, run, monthly]", "---", "",
         f"# 月次の判定 {a.as_of}", "",
         f"前回（{prev_run}）の通過銘柄と比べた変化。株価は主に {price_day} の終値。数値は判定結果の CSV の値で、"
         "売買の推奨ではない。銘柄ごとの数値は [銘柄ノートの一覧](../stocks/INDEX.md)。", "",
         "## 件数", "", "| 項目 | 今回 | 前回 |", "|---|---|---|",
         f"| 対象（上場会社） | {len(rows):,} | |",
         f"| 第1段階 通過 | {s1} | |",
         f"| 第3段階まで通過 | {len(now)}（事業 {sum(1 for c in now if not rows[c]['金融'])}・金融 {sum(1 for c in now if rows[c]['金融'])}） | {len(prev)} |",
         f"| ★ | {sum(1 for c in now if marks[c] == '★')} | {sum(1 for c in prev.values() if c.get('mark') == '★')} |",
         f"| ☆ | {sum(1 for c in now if marks[c] == '☆')} | {sum(1 for c in prev.values() if c.get('mark') == '☆')} |", ""]

    L += [f"## 新しく通過（{len(new)}）", ""]
    for c in new:
        r = rows[c]
        researched = c in B.research or c in B.MANUAL["theme"]
        L.append(f"- {marks[c] or '印なし'} **{c} {r['銘柄名']}**（{r['業種']}）: PER {B.f(r['PER(実績)'])}倍・PBR {B.f(r['PBR'])}倍・"
                 f"利回り {B.f(r['配当利回り(実績)'])}%・EPS {B.f(r['EPS倍率'])}倍・BPS {B.f(r['BPS伸び率'])}倍。"
                 + (f"配当方針 {B.policy_text(c)}、テーマ性 {B.theme_text(c)}" if researched
                    else "テーマ性・配当方針は未調査（印の DOE は有報の配当政策を機械的に見たもの）"))
    L += ([""] if new else ["- なし", ""])

    L += [f"## 脱落（{len(gone)}）", ""] + [f"- {c} {name(c)}: {why(c)}" for c in gone] + (["- なし"] if not gone else []) + [""]

    changed = [c for c in stay if (prev[c].get("mark") or "") != (marks[c] or "")]
    L += [f"## 印が変わった銘柄（{len(changed)}）", ""]
    L += [f"- {c} {rows[c]['銘柄名']}: {prev[c].get('mark') or '印なし'} → {marks[c] or '印なし'}（PBR {B.f(rows[c]['PBR'])}倍）"
          for c in changed] or ["- なし"]
    L.append("")

    updated = [c for c in stay if rows[c]["直近決算期末"] != prev[c]["latest_period_end"]]
    L += [f"## 新しい有報が出た通過銘柄（{len(updated)}）", "",
          "テーマ性・配当方針は前回の調査のまま。配当政策の記載（有報の文を機械的に見た累進・DOE）が変わったものは見直す。", ""]
    for c in updated:
        r, q = rows[c], prev[c]
        line = f"- {c} {r['銘柄名']}: 決算期 {q['latest_period_end']} → {r['直近決算期末']}"
        if "yuho_doe" in q:
            was = (q["yuho_progressive"], q["yuho_doe"], q["yuho_doe_value"])
            cur = (bool(r["累進"]), bool(r["DOE"]), r["DOE数値"])
            line += "、配当政策の記載 " + ("変化なし" if was == cur else f"**変化あり**（累進 {was[0]}→{cur[0]}、DOE {was[1]}→{cur[1]}、数値 {was[2] or '-'}→{cur[2] or '-'}）")
        L.append(line)
    if not updated:
        L.append("- なし")
    L.append("")

    edge = [(c, borderline(rows[c])) for c in order]
    edge = [(c, e) for c, e in edge if e]
    L += [f"## 条件の境界に近い通過銘柄（{len(edge)}）", "",
          "配当利回り 3.2% 未満、PER 11.3倍超、PBR 1.2倍超、時価総額 140億円未満、ROA 3.4% 未満、自己資本比率 37% 未満、ROE 7.8% 未満のもの。", ""]
    L += [f"- {c} {rows[c]['銘柄名']}: {'、'.join(e)}" for c, e in edge] or ["- なし"]
    L.append("")
    mark_edge = [c for c in order if num(rows[c]["PBR"]) is not None and (0.8 <= num(rows[c]["PBR"]) < 0.85 or 1.15 < num(rows[c]["PBR"]) <= 1.2)]
    if mark_edge:
        L += ["印の PBR 0.8〜1.2倍の境目に近い: " + "、".join(f"{rows[c]['銘柄名']}（{B.f(rows[c]['PBR'])}倍）" for c in mark_edge), ""]

    old = [c for c in order if rows[c]["株価日付"] != price_day]
    L += [f"## 株価の日付が {price_day} でない通過銘柄（{len(old)}）", ""]
    L += [f"- {c} {rows[c]['銘柄名']}: {rows[c]['株価日付']}" for c in old] or ["- なし"]
    L.append("")

    hits, _ = scan_anomalies.find(Path(a.results))
    fresh = [h for h in hits if not (h["code"] in anomalies_checked
                                     and anomalies_checked[h["code"]]["latest_period_end"] == h["latest_period_end"])]
    L += [f"## 調整漏れの洗い出しで新しく出た銘柄（{len(fresh)}／全 {len(hits)}）", "",
          "前回までに確かめた銘柄（checked.json、同じ決算期）は除いた。有報の原本で確かめる。", ""]
    L += [f"- {h['code']} {h['name']} [{h['status']}] BPS {h['bps_growth']}倍・EPS {h['eps_ratio'] or '-'}倍、"
          f"BPS の飛び: {', '.join(h['jumps']) or 'なし'}" for h in fresh] or ["- なし"]
    L.append("")

    todo = [c for c in new if c not in B.research and c not in B.MANUAL["theme"]]
    L += [f"## まだ調べていない通過銘柄（{len(todo)}）", ""]
    L += [f"- {c} {rows[c]['銘柄名']}" for c in todo] or ["- なし"]
    L += ["", "Related: [次回の進め方](../next-run.md) · [銘柄ノートの一覧](../stocks/INDEX.md) · [入口](../INDEX.md)", ""]

    out = Path(a.out) if a.out else ROOT / "research" / "runs" / f"{a.as_of}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"written {out}（新しく通過 {len(new)}・脱落 {len(gone)}・印の変化 {len(changed)}・未調査 {len(todo)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
