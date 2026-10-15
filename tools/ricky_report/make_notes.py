"""判定結果と確認結果から、Obsidian 用の銘柄ノート（research/stocks/）と通過銘柄の記録（passers.json）を書く.

    python tools/ricky_report/make_notes.py --as-of 2026-10-13 --results results/full \
        --verify research/data/*/verify.json --labels research/data/*/labels.json \
        --report research/ricky_screening_full_2026-10-13.md

- research/data/<日付>/passers.json: 今回の通過銘柄の数値・表記（次回 diff_passers.py が前回分として読む）。
- research/stocks/<コード>-<銘柄名>.md: 銘柄ごとのノート。書き換えるのは <!-- auto:start --> 〜 <!-- auto:end -->
  の間と、frontmatter のうちこのスクリプトが持つ項目（title・date・status・mark・first_passed・last_run・code、
  tags・aliases の自動の分）だけ。手で足したプロパティ・タグ・別名、H1 の下の文、「メモ」の欄は残す。
  今回は通過していない銘柄も、ノートがあれば今回の判定に更新する。
- research/stocks/INDEX.md: 銘柄ノートの一覧（毎回作り直す。手で書き足さない）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tables as B  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STOCKS = ROOT / "research" / "stocks"
DATA = ROOT / "research" / "data"
AUTO_MARK = "<!-- auto:start"
AUTO_START = (AUTO_MARK + "（tools/ricky_report/make_notes.py が書き換える。手で書くのはこの外に。"
              "frontmatter は自動の項目だけ書き換え、手で足したプロパティ・タグは残す） -->")
AUTO_END = "<!-- auto:end -->"
REPORT_LABEL = ""  # main() で決める
MEMO = "\n## メモ\n\n（自由に書いてよい。make_notes.py はこの欄を書き換えない）\n"
MANAGED_KEYS = ("title", "date", "tags", "aliases", "code", "status", "mark", "first_passed", "last_run")
AUTO_TAGS = {"ricky-screening", "通過", "脱落"}
# エージェントの文に残る、確認用 JSON の項目名を読める言葉に直す
FIELD_WORDS = {
    "label": "表記", "profit_already": "利益化の判断", "script_notes": "スクリプトの注記", "notes_check": "注記の確認",
    "numbers": "数値の確認", "verdict": "判定", "detail": "詳細", "source_url": "出典", "evidence": "根拠",
    "dividend_cuts_external": "外部の減配回数", "eps_first_external": "外部の9期前EPS",
    "eps_last_external": "外部の直近EPS", "bps_all_increase_external": "外部のBPS毎期増加",
    "series_10_periods": "10期の系列", "stage2_failures": "第2段階の不合格項目",
}


def plain_name(name: str) -> str:
    """全角英数を半角にし、ファイル名に使えない文字・括弧と空白を除く."""
    s = unicodedata.normalize("NFKC", name)
    return re.sub(r'[\s/\\:*?"<>|#^\[\]()]', "", s)


def note_path(code: str, name: str) -> Path:
    existing = sorted(STOCKS.glob(f"{code}-*.md"))
    return existing[0] if existing else STOCKS / f"{code}-{plain_name(name)}.md"


def encode(path: str) -> str:
    """リンク先の書き方: 日本語はそのまま（読みやすさのため）、空白や記号だけ % で符号化する."""
    return "".join(ch if ord(ch) > 127 else quote(ch, safe="/-._~") for ch in path)


def link(path: Path, base: Path) -> str:
    rel = path.relative_to(base) if path.is_relative_to(base) else Path("..") / path.relative_to(base.parent)
    return encode(rel.as_posix())


def readable(text: str) -> str:
    """JSON の項目名を言葉に直し、2行目以降を字下げして箇条書きの中に収める."""
    for key, word in FIELD_WORDS.items():
        text = re.sub(rf"(?<![A-Za-z_]){key}(?![A-Za-z_])", word, text)
    return "\n  ".join(line for line in text.strip().splitlines() if line.strip())


def history(code: str) -> list[tuple[str, dict]]:
    out = []
    for f in sorted(DATA.glob("*/passers.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if code in d["stocks"]:
            out.append((d["run"], {**d["stocks"][code], "method": d.get("method", "")}))
    return out


def text_block(title: str, body: str) -> list[str]:
    return [f"### {title}", "", body.strip() or "未確認", ""]


def auto_block(code: str, as_of: str, report: Path) -> list[str]:
    r = B.rows[code]
    s = B.series.get(code, {"periods": [], "notes": []})
    res = B.research.get(code) or {}
    rv = B.review.get(code) or {}
    day = B.checked_on.get(code, "")
    passed = r["判定"] == "通過"
    reason = r["第1段階 不合格項目"] or r["第2段階 不合格項目"] or r["第1段階 未確認項目"] or r["第2段階 未確認項目"]
    lines = [AUTO_START, "", f"## {as_of} の判定: {r['判定']}" + ("" if passed else f"（{reason}）"), ""]
    if B.MANUAL["caution"].get(code):
        lines += [f"> [!WARNING] {B.MANUAL['caution'][code]}", ""]
    lines += ["| 項目 | 値 |", "|---|---|"]
    cuts = r["減配期"].split()
    items = [
        ("印（第3段階）", B.mark(code) or "なし") if passed else None,
        ("業種", r["業種"] + ("（金融: ROA・自己資本比率は判定対象外）" if r["金融"] else "")),
        ("株価", f"{B.f(r['株価'], 1)}円（{r['株価日付']}）"),
        ("PER（実績）・PBR", f"{B.f(r['PER(実績)'])}倍・{B.f(r['PBR'])}倍"),
        ("ROE（有報）・ROA", f"{B.f(r['ROE'], 1)}%・{B.f(r['ROA'])}%"),
        ("配当利回り（実績）・1株配当", f"{B.f(r['配当利回り(実績)'])}%・{B.f(r['1株配当(実績)'])}円"),
        ("自己資本比率・時価総額", f"{B.f(r['自己資本比率'], 1)}%・{B.f(r['時価総額(億円)'], 0)}億円"),
        ("EPS 9期前→直近", f"{B.f(r['EPS 9期前'])}→{B.f(r['EPS 直近'])}円（{B.f(r['EPS倍率'])}倍）"),
        ("BPS 10年伸び率・連続増加", f"{B.f(r['BPS伸び率'])}倍・{r['BPS連続増加回数'] or '未確認'}期連続"),
        ("減配", f"{len(cuts)}回" + (f"（{', '.join(B.ym(d) for d in cuts)}）" if cuts else "")),
        ("配当方針", B.policy_text(code) if passed else "（通過時のみ調べる）"),
        ("テーマ性", B.theme_text(code) if passed else "（通過時のみ調べる）"),
        ("直近の決算期・有報", f"{r['直近決算期末']}・{r['有報docID']}"),
    ]
    lines += [f"| {k} | {v} |" for k, v in (x for x in items if x)]
    lines.append("")
    if s["periods"]:
        lines += ["### 10期の推移（現在の株数の基準）", "", "| 決算期 | EPS | BPS | 1株配当 | 備考 |", "|---|---|---|---|---|"]
        for p in s["periods"][-10:]:
            memo = "・".join(x for x in (
                f"{p['months']}か月決算" if p.get("months") and p["months"] < 12 else "",
                "個別の値" if p.get("nc") else "", p.get("standard") or "") if x)
            lines.append(f"| {p['end'][:7]} | {B.f(p['eps'])} | {B.f(p['bps'])} | {B.f(p['dps'])} | {memo} |")
        lines.append("")

    theme = res.get("theme") or {}
    manual = B.MANUAL["evidence"].get(code) or {}
    ev = manual.get("text") or theme.get("evidence", "")
    when = f"{day} の調査" if day else "調査日は未記録"
    if passed or ev:
        head = []
        verdict = rv.get("theme_verdict", "")
        if theme.get("label") and verdict in ("未確認に変更", "表現を修正") and not manual.get("text"):
            head.append(f"調査担当の表記「{theme['label']}」を、反証役が「{verdict}」とした（理由は下の点検）。"
                        "下の文は調査担当が抜き出したもので、評価は表のテーマ性の欄。")
        if B.MANUAL["theme_note"].get(code):
            head.append(f"表のテーマ性の表記は本体の判断: {B.MANUAL['theme_note'][code]}")
        src = manual.get("source") or B._sources(code)
        body = "\n\n".join(head + [ev + (f"\n\n出典: {src}" if ev else "")])
        title = "テーマ性の根拠（人が書き直した文）" if manual.get("text") else f"テーマ性の根拠（調査担当の抜き出し・{when}）"
        lines += text_block(title, body)
        if manual.get("numbers"):
            lines += text_block("数値の確認", f"{manual.get('verdict', '')}。\n\n{manual['numbers']}")
        if rv:
            lines += text_block(f"反証役の点検（{when}。テーマ: {rv.get('theme_verdict', '')}・配当方針: {rv.get('policy_verdict', '')}）",
                                f"- テーマ: {readable(rv.get('theme_reason', ''))}\n- 配当方針: {readable(rv.get('policy_reason', ''))}")
        pol = res.get("policy") or {}
        if pol or B.MANUAL["policy_note"].get(code):
            body = ""
            if B.MANUAL["policy_note"].get(code):
                body += f"本体の補足: {B.MANUAL['policy_note'][code]}\n\n"
            if pol:
                body += f"{pol.get('other', '')}\n\n出典: {pol.get('source_url', '')}（{pol.get('source_date', '')}）"
            lines += text_block(f"配当方針の詳細（{when}）", body)
        nums = res.get("numbers") or {}
        concern = rv.get("numbers_concern", "")
        if nums or concern:
            body = ""
            if B.MANUAL["numbers_note"].get(code):
                body += f"> [!NOTE] {B.MANUAL['numbers_note'][code]}\n\n"
            body += f"- 照合: {nums.get('verdict', '未確認')}。{readable(nums.get('detail', ''))}"
            if res.get("notes_check"):
                body += f"\n- 注記の確認: {readable(res['notes_check'])}"
            if concern and not concern.startswith("なし"):
                body += f"\n- 反証役の指摘: {readable(concern)}"
            lines += text_block(f"数値の確認（{when}）", body)
    if s.get("notes"):
        lines += ["### スクリプトの注記（今回の実行）", ""] + [f"- {n}" for n in s["notes"]] + [""]
    lines += ["### 判定の履歴", "", "| 実行日 | 判定 | 印 | テーマ性 |", "|---|---|---|---|"]
    for run, st in history(code):
        how = f"通過（{st['method']}）" if st.get("method") else "通過"
        lines.append(f"| {run} | {how} | {st.get('mark') or 'なし'} | {st.get('theme', '')} |")
    if not passed:
        lines.append(f"| {as_of} | {r['判定']} | | |")
    lines += ["", f"Related: [{REPORT_LABEL}]({link(report, STOCKS)}) · [銘柄ノートの一覧](INDEX.md) · "
              f"[次回の進め方](../next-run.md)", "", AUTO_END]
    return lines


def split_front(text: str) -> tuple[list[tuple[str, list[str]]], str]:
    """先頭の frontmatter を (キー, そのキーの行) の並びと残りの本文に分ける（簡単な YAML だけ扱う）."""
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    if not m:
        return [], text
    blocks: list[tuple[str, list[str]]] = []
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):", line)
        if km:
            blocks.append((km.group(1), [line]))
        elif blocks:
            blocks[-1][1].append(line)  # 字下げしたリストの続きなど
    return blocks, text[m.end():]


def list_values(lines: list[str]) -> list[str]:
    """`key: [a, "b"]` と、字下げした `- a` の両方からリストの値を読む."""
    first = lines[0].split(":", 1)[1].strip()
    vals = [v.strip().strip('"\'') for v in first.strip("[]").split(",")] if first.startswith("[") else []
    vals += [ln.strip()[1:].strip().strip('"\'') for ln in lines[1:] if ln.strip().startswith("-")]
    return [v for v in vals if v]


def yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


def write_note(code: str, as_of: str, report: Path) -> Path:
    r = B.rows[code]
    path = note_path(code, r["銘柄名"])
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks, rest = split_front(old)
    old_keys = dict(blocks)
    hist = history(code)
    first = hist[0][0] if hist else (as_of if r["判定"] == "通過" else "")
    # Obsidian のタグに使えない記号（「・」など）は _ にする
    industry = re.sub(r"[^\w/-]", "_", r["業種"])
    auto_tags = ["ricky-screening", "通過" if r["判定"] == "通過" else "脱落", industry]
    user_tags = [t for t in list_values(old_keys["tags"]) if t not in AUTO_TAGS | {industry}] if "tags" in old_keys else []
    names = list(dict.fromkeys([r["銘柄名"], plain_name(r["銘柄名"])]))
    user_aliases = [a for a in list_values(old_keys["aliases"]) if a not in names] if "aliases" in old_keys else []
    front = ["---", f'title: "{code} {plain_name(r["銘柄名"])}"', f"date: {as_of}",
             "tags: " + yaml_list(auto_tags + user_tags), "aliases: " + yaml_list(names + user_aliases),
             f'code: "{code}"', f"status: {r['判定']}", f"mark: \"{B.mark(code) if r['判定'] == '通過' else ''}\"",
             f"first_passed: {first}", f"last_run: {as_of}"]
    front += [ln for key, lines in blocks if key not in MANAGED_KEYS for ln in lines]  # 手で足したプロパティ
    front.append("---")
    auto = auto_block(code, as_of, report)
    if AUTO_MARK in rest and AUTO_END in rest:
        before = rest[:rest.index(AUTO_MARK)]
        after = rest[rest.index(AUTO_END) + len(AUTO_END):]
        text = "\n".join(front) + "\n" + before + "\n".join(auto) + after
    else:
        text = "\n".join(front) + f"\n\n# {code} {plain_name(r['銘柄名'])}\n\n" + "\n".join(auto) + "\n" + MEMO
    path.write_text(text, encoding="utf-8")
    return path


def write_index(as_of: str, report: Path) -> None:
    passed_nonfin = B.passed_rows(False)[1]
    passed_fin = B.passed_rows(True)[1]
    lines = ["---", "title: 銘柄ノートの一覧", f"date: {as_of}", "tags: [ricky-screening, index]", "---", "",
             "# 銘柄ノートの一覧", "",
             "> [!NOTE] このファイルは tools/ricky_report/make_notes.py が毎回作り直す。手で書き足すと次回消えるので、"
             "メモは各銘柄ノートの「メモ」の欄に書く。", "",
             f"Ricky流スクリーニングで第3段階まで通過した銘柄のノート（{as_of} の判定）。"
             "各ノートは判定の数値・10期の推移・配当方針・テーマ性の根拠・確認で分かった注意点・判定の履歴を持つ。"
             "印は ★＝BPS毎期増加＋DOE採用＋PBR 0.8〜1.2倍、☆＝3つのうち2つ。", ""]

    def entry(c):
        r = B.rows[c]
        path = note_path(c, r["銘柄名"])
        warn = " ⚠" if B.MANUAL["caution"].get(c) else ""
        return (f"- [{c} {plain_name(r['銘柄名'])}]({encode(path.name)}){warn}: {B.mark(c) or '印なし'}・{r['業種']}・"
                f"BPS {B.f(r['BPS伸び率'])}倍・EPS {B.f(r['EPS倍率'])}倍・テーマ {B.theme_text(c)}")

    lines += [f"## 事業会社（{len(passed_nonfin)}、BPS 10年伸び率の高い順）", ""] + [entry(c) for c in passed_nonfin]
    lines += ["", f"## 金融（{len(passed_fin)}）", ""] + [entry(c) for c in passed_fin]
    dropped = [p for p in sorted(STOCKS.glob("*-*.md")) if p.name.split("-")[0] not in set(passed_nonfin + passed_fin)]
    if dropped:
        lines += ["", "## 以前は通過、今回は不通過", ""]
        for p in dropped:
            c = p.name.split("-")[0]
            r = B.rows.get(c)
            lines.append(f"- [{p.stem}]({encode(p.name)}): {r['判定'] if r else '今回の対象外'}")
    lines += ["", "⚠ はノートの先頭に注意書き（判定の読み方に関わる点）があるもの。", "",
              f"Related: [{REPORT_LABEL}]({link(report, STOCKS)}) · [調査ノートの入口](../INDEX.md)", ""]
    (STOCKS / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as-of", required=True)
    p.add_argument("--results", default="results/full")
    p.add_argument("--verify", nargs="*", default=[], help="research/data/*/verify.json を古い順にすべて")
    p.add_argument("--labels", nargs="*", default=[], help="research/data/*/labels.json を古い順にすべて")
    p.add_argument("--report", required=True, help="今回のレポート（ノートからリンクする）。月次は research/runs/<日付>.md")
    p.add_argument("--report-label", help="リンクの文字（既定: 「<as-of> の全社版レポート」。月次は「<as-of> の月次の判定」など）")
    a = p.parse_args()
    B.load(a.results, a.verify, a.labels)
    report = Path(a.report).resolve()
    global REPORT_LABEL
    REPORT_LABEL = a.report_label or f"{a.as_of} の全社版レポート"
    STOCKS.mkdir(parents=True, exist_ok=True)

    passers = [c for c, r in B.rows.items() if r["判定"] == "通過"]
    record = {"run": a.as_of, "stocks": {}}
    for c in passers:
        r = B.rows[c]
        record["stocks"][c] = {
            "name": r["銘柄名"], "industry": r["業種"], "financial": bool(r["金融"]),
            "latest_period_end": r["直近決算期末"], "doc_id": r["有報docID"], "mark": B.mark(c),
            "PER": r["PER(実績)"], "PBR": r["PBR"], "ROE": r["ROE"], "ROA": r["ROA"],
            "yield": r["配当利回り(実績)"], "equity_ratio": r["自己資本比率"], "market_cap_oku": r["時価総額(億円)"],
            "EPS_first": r["EPS 9期前"], "EPS_last": r["EPS 直近"], "EPS_ratio": r["EPS倍率"],
            "BPS_growth": r["BPS伸び率"], "dividend_cuts": r["減配期"].split(),
            # 有報の配当政策を機械的に見た記載（次回、新しい有報で変わったかを diff_passers.py が比べる）
            "yuho_progressive": bool(r["累進"]), "yuho_doe": bool(r["DOE"]), "yuho_doe_value": r["DOE数値"],
            "policy": B.policy_text(c), "theme": B.theme_text(c), "checked_on": B.checked_on.get(c, ""),
        }
    out = DATA / a.as_of / "passers.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    targets = set(passers) | {p.name.split("-")[0] for p in STOCKS.glob("*-*.md")}
    for c in sorted(targets):
        if c in B.rows:
            write_note(c, a.as_of, report)
    write_index(a.as_of, report)
    print(f"passers.json {len(passers)} 銘柄、ノート {len(targets)} 件（{STOCKS}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
