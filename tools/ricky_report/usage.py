"""Claude Code の会話記録から、モデルの呼び出し回数と読み込んだトークンを数える（費用の記録用）.

    python tools/ricky_report/usage.py ~/.claude/projects/<プロジェクト>/<セッションID>

<セッションID>.jsonl（本体の会話）と、<セッションID>/subagents/workflows/<runId>/agent-*.jsonl（ワークフローの
エージェント）を読み、本体・エージェントの種類（ラベルの「:」より前）ごとに数える。research/costs.md の数字は
これで数えた。利用料金の額はこの記録からは分からない。

- 呼び出し: assistant のメッセージ（message.id が同じものは1回）
- 読み込み: input_tokens＋cache_read_input_tokens＋cache_creation_input_tokens（大半はキャッシュの読み込み）
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def count(files: list[Path]) -> tuple[int, int]:
    seen, calls, tokens = set(), 0, 0
    for f in files:
        for line in open(f, encoding="utf-8"):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = d.get("message") if d.get("type") == "assistant" else None
            if not isinstance(m, dict) or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            u = m.get("usage") or {}
            calls += 1
            tokens += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return calls, tokens


def main() -> int:
    session = Path(sys.argv[1]).expanduser()
    main_file = session.with_suffix(".jsonl")
    if main_file.exists():
        c, t = count([main_file])
        print(f"本体: 呼び出し {c:,} 回・読み込み {t / 1e6:,.1f}M トークン")
    kinds: dict[str, list] = defaultdict(lambda: [0, 0, 0])
    for meta in sorted(session.glob("subagents/workflows/*/agent-*.meta.json")):
        label = json.loads(meta.read_text(encoding="utf-8")).get("description", "")
        kind = f"{meta.parent.name}  {re.sub(r':.*', '', label)}"
        c, t = count([meta.with_name(meta.name.replace(".meta.json", ".jsonl"))])
        k = kinds[kind]
        k[0] += 1
        k[1] += c
        k[2] += t
    for kind, (n, c, t) in kinds.items():
        print(f"{kind}: {n} 体・呼び出し {c:,} 回（1体あたり {c / n:.0f}）・読み込み {t / 1e6:,.1f}M トークン（1体あたり {t / n / 1e6:.1f}M）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
