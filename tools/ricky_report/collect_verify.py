"""ワークフロー（workflows/verify.js）の journal.jsonl から確認結果を集め、verify.json にまとめる.

    python tools/ricky_report/collect_verify.py research/data/<日付>/verify.json <journal.jsonl> [...] \
        [--selected <作業フォルダ>/selected.json]

journal は ~/.claude/projects/<プロジェクト>/<セッションID>/subagents/workflows/<runId>/journal.jsonl
（runId は Workflow ツールの結果に出る wf_… ）。同じ銘柄が複数あれば、後に渡した journal の結果を優先する。
出力が既にあれば、その内容に上書きで足す。--selected を付けると、確かめた不通過銘柄と直近の決算期末を
同じフォルダの checked.json に書く（次回 prepare_verify.py --skip-checked で使う）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    argv = sys.argv[1:]
    selected = None
    if "--selected" in argv:
        i = argv.index("--selected")
        selected = json.loads(Path(argv[i + 1]).read_text(encoding="utf-8"))
        argv = argv[:i] + argv[i + 2:]
    out, journals = Path(argv[0]), argv[1:]
    research, review, fragile = {}, {}, {}
    if out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        for b in old.get("passers", []):
            research.update({s["code"]: s for s in (b.get("research") or {}).get("stocks", [])})
            review.update({s["code"]: s for s in (b.get("review") or {}).get("reviews", [])})
        for b in old.get("fragile", []):
            fragile.update({s["code"]: s for s in (b.get("result") or {}).get("stocks", [])})
    for jp in journals:
        for line in open(jp, encoding="utf-8"):
            d = json.loads(line)
            if d.get("type") != "result":
                continue
            r = d.get("result") or d.get("value") or {}
            if not isinstance(r, dict):
                continue
            # 1 エージェント分の結果（stocks / reviews）と、ワークフロー全体の戻り値（passers / fragile）の両方を読む
            for st in r.get("stocks", []):
                (fragile if "overall" in st else research)[st["code"]] = st
            for rv in r.get("reviews", []):
                review[rv["code"]] = rv
            for b in r.get("passers", []):
                research.update({s["code"]: s for s in (b.get("research") or {}).get("stocks", [])})
                review.update({s["code"]: s for s in (b.get("review") or {}).get("reviews", [])})
            for b in r.get("fragile", []):
                fragile.update({s["code"]: s for s in (b.get("result") or {}).get("stocks", [])})
    result = {"passers": [{"batch": 0, "research": {"stocks": list(research.values())},
                           "review": {"reviews": list(review.values())}}],
              "fragile": [{"batch": 0, "result": {"stocks": list(fragile.values())}}]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"research {len(research)}・review {len(review)}・fragile {len(fragile)} → {out}")
    if selected is not None:
        path = out.parent / "checked.json"
        checked = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"run": out.parent.name, "fragile": {}}
        for code, st in fragile.items():
            if code in selected.get("fragile", {}):
                checked["fragile"][code] = {"latest_period_end": selected["fragile"][code], "overall": st.get("overall", "")}
        path.write_text(json.dumps(checked, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"checked.json: 不通過の確認 {len(checked['fragile'])} 銘柄 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
