"""レポートを組み立てる: テンプレートのプレースホルダ（<<NAME>>）を、表と文章のパーツで置き換える.

    python tools/ricky_report/assemble.py --results results/full \
        --verify research/data/2026-10-13/verify.json --labels research/data/2026-10-13/labels.json \
        --template tools/ricky_report/report_template.tmpl --parts work/parts \
        --out research/ricky_screening_full_YYYY-MM-DD.md

表（通過銘柄・金融・印・不通過・業種・件数・テーマ性の根拠）は判定結果と確認結果から作る。
文章のパーツ（SUMMARY・RECONCILE・PASSED_INTRO・PASSED_CAUTIONS・FRAGILE・INDUSTRY・SPLITS・FIXES・LIMITS・
SOURCES・EVIDENCE_INTRO）は --parts のフォルダに <NAME>.md（または .txt）として、実行ごとに書く（無ければ「未作成」と入る）。
前回の文章は前回のレポートの各章にあるので、それを写して今回の事実に合わせて直すとよい。
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tables as B  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="レポートを組み立てる")
    p.add_argument("--results", default="results/full")
    p.add_argument("--verify", nargs="*", default=[])
    p.add_argument("--labels", nargs="*", default=[])
    p.add_argument("--template", default=str(Path(__file__).resolve().parent / "report_template.tmpl"))
    p.add_argument("--parts", required=True, help="文章のパーツ（<NAME>.md）のフォルダ")
    p.add_argument("--as-of", required=True, help="基準日 YYYY-MM-DD（見出しに入る）")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    B.load(a.results, a.verify, a.labels)
    rows = B.rows
    tpl = Path(a.template).read_text(encoding="utf-8")
    parts = Path(a.parts)

    def part(name):
        for ext in (".md", ".txt"):
            f = parts / f"{name}{ext}"
            if f.exists():
                return f.read_text(encoding="utf-8").strip()
        return f"（{name} は未作成）"

    cnt = Counter(r["判定"] for r in rows.values())
    passed = [c for c, r in rows.items() if r["判定"] == "通過"]
    nonfin = [c for c in passed if not rows[c]["金融"]]
    fin = [c for c in passed if rows[c]["金融"]]
    s1 = [c for c, r in rows.items() if r["判定"] in ("通過", "第2段階 不通過", "第2段階 判定不能")]

    passed_table, order = B.passed_rows(False)
    fin_table, fin_order = B.passed_rows(True)

    # 件数表
    counts = ["| 判定 | 件数 | 内訳・備考 |", "|---|---|---|",
              f"| 対象（上場会社） | {len(rows):,} | |",
              f"| 第1段階 通過 | {len(s1)} | うち金融 {sum(1 for c in s1 if rows[c]['金融'])} |",
              f"| **第3段階まで通過** | **{len(passed)}** | 事業会社 {len(nonfin)}・金融 {len(fin)} |",
              f"| 第2段階 不通過 | {cnt['第2段階 不通過']} | 4章 |",
              f"| 第2段階 判定不能 | {cnt['第2段階 判定不能']} | 10期分の有報がそろわない等（4-2） |",
              f"| 第1段階 不通過 | {cnt['第1段階 不通過']:,} | |",
              f"| 第1段階 判定不能 | {cnt['第1段階 判定不能']} | 株価が取れない（名証のみ上場など）等 |",
              f"| 有報なし | {cnt['有報なし']} | 期間内に有報の提出が無い（新規上場直後など） |"]

    # 第1段階の不合格理由
    s1fail = Counter(f for r in rows.values() if r["判定"] == "第1段階 不通過" for f in r["第1段階 不合格項目"].split(" / ") if f)

    # 印
    marks = {c: B.mark(c) for c in passed}
    star = [c for c in order + fin_order if marks[c] == "★"]
    half = [c for c in order + fin_order if marks[c] == "☆"]
    def label(c):
        r = rows[c]
        return f"{r['銘柄名']}（{c}、PBR {B.f(r['PBR'])}倍、{B.policy_text(c).split('／')[1] if '／' in B.policy_text(c) else B.policy_text(c)}）"
    marks_md = [f"- **★（BPS毎期増加＋DOE採用＋PBR 0.8〜1.2倍）: {len(star)}銘柄**"]
    marks_md += [f"  - {label(c)}" for c in star] or ["  - 該当なし"]
    marks_md += [f"- **☆（3条件のうち2つ）: {len(half)}銘柄** — " + "、".join(f"{rows[c]['銘柄名']}（{'DOE' if B.doe_adopted(c) else 'PBR ' + B.f(rows[c]['PBR']) + '倍'}）" for c in half)]
    marks_md += ["", "DOE 採用の有無は、有報の「配当政策」と会社の資料（確認できた範囲）による。PBR は 2026-10-13 終値ベース。",
                 "", "DOE の書き方は会社によって違う。下限（例：日本信号 2.0%以上）、目安（西部電機 4.0%）、将来の目標（ツムラ 2031年度 5%、ヤマタネ 2028/3期 3.0%）、配当性向と比べて高い方（木村化工機・第一実業）があり、"
                 "ヤマダコーポレーション（★）と日本新薬（☆）は DOE を指標に使うと書いているが、水準の数値は示していない。DOE の数値は 3-1 の表の「配当方針」の欄。"]

    # 第2段階の不合格理由の集計
    fails = [r for r in rows.values() if r["判定"] == "第2段階 不通過"]
    reason_cnt = Counter()
    for r in fails:
        for fl in r["第2段階 不合格項目"].split(" / "):
            key = "減配2回以上" if fl.startswith("減配") else fl
            reason_cnt[key] += 1
    only = Counter()
    for r in fails:
        fl = r["第2段階 不合格項目"].split(" / ")
        if len(fl) == 1:
            only["減配2回以上" if fl[0].startswith("減配") else fl[0]] += 1
    fails_intro = (f"第1段階を通過した {len(s1)} 銘柄のうち {len(fails)} 銘柄が第2段階で落ちた。"
                   "落ちた条件の内訳（重複あり）: " + "、".join(f"{k} {v}" for k, v in reason_cnt.most_common()) +
                   "。条件1つだけで落ちたのは " + "、".join(f"{k} {v}" for k, v in only.most_common()) + "。"
                   "表は業種・コード順。一言の欄の年月は決算期（例: 21/3 = 2021年3月期）。")

    # 判定不能
    und2 = [r for r in rows.values() if r["判定"] == "第2段階 判定不能"]
    und2_md = ["| 銘柄名 | コード | 理由 |", "|---|---|---|"] + [
        f"| {r['銘柄名']} | {r['コード']} | {r['第2段階 未確認項目']}（{r['注記'][:80]}） |" for r in und2]

    # 業種
    uni = Counter(r["業種"] for r in rows.values() if r["判定"] != "有報なし")
    s1c = Counter(rows[c]["業種"] for c in s1)
    pc = Counter(rows[c]["業種"] for c in passed)
    ind_md = ["| 業種 | 通過 | 通過に占める割合 | 第1段階通過 | 全上場会社に占める割合 |", "|---|---|---|---|---|"]
    for ind, n in pc.most_common():
        ind_md.append(f"| {ind} | {n} | {n / len(passed):.0%} | {s1c[ind]} | {uni[ind] / sum(uni.values()):.1%} |")

    filled = {
        "SUMMARY": part("SUMMARY"),
        "RECONCILE": part("RECONCILE"),
        "PASSED_INTRO": part("PASSED_INTRO"),
        "N_NONFIN": str(len(nonfin)),
        "PASSED_TABLE": "\n".join(passed_table),
        "FIN_TABLE": "\n".join(fin_table),
        "MARKS": "\n".join(marks_md),
        "PASSED_CAUTIONS": part("PASSED_CAUTIONS"),
        "N_FAIL": str(len(fails)),
        "FAILS_INTRO": fails_intro,
        "FAILS_TABLE": "\n".join(B.fails_table()),
        "FRAGILE": part("FRAGILE"),
        "UNDET2": "\n".join(und2_md),
        "INDUSTRY": "\n".join(ind_md) + "\n\n" + part("INDUSTRY"),
        "SPLITS": part("SPLITS"),
        "FIXES": part("FIXES"),
        "LIMITS": part("LIMITS"),
        "SOURCES": part("SOURCES"),
        "EVIDENCE_INTRO": part("EVIDENCE_INTRO"),
        "EVIDENCE_TABLE": "\n".join(B.evidence_rows()),
        "COUNTS": "\n".join(counts),
        "N_ALL": f"{len(rows):,}",
        "N_S1": str(len(s1)),
        "N_PASS": str(len(passed)),
        "N_FIN": str(len(fin)),
        "N_STAR": str(len(star)),
        "N_HALF": str(len(half)),
        "N_THEME": str(sum(1 for c in passed if not B.theme_text(c).startswith(("未確認", "該当なし")))),
        "S1FAIL": "、".join(f"{k} {v:,}" for k, v in s1fail.most_common()),
    }
    filled["AS_OF"] = a.as_of
    out = tpl
    for k, v in filled.items():
        out = out.replace(f"<<{k}>>", v)
    left = re.findall(r"<<[A-Z_0-9]+>>", out)
    if left:
        print("埋まっていないプレースホルダ:", left, file=sys.stderr)
    Path(a.out).write_text(out + "\n", encoding="utf-8")
    print("written", a.out, len(out))


if __name__ == "__main__":
    main()
