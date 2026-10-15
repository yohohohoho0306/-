"""前回の通過銘柄（research/data/<日付>/passers.json）を探して読む（diff_passers・prepare_verify・monthly_summary 用）.

「前回」は、基準日より前の日付で、銘柄ごとの直近の決算期（latest_period_end）が入っている、いちばん新しい
passers.json。2026-10-12 の passers.json（手作業の調査の通過銘柄）には決算期が無いので、前回には使えない。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "research" / "data"


def _usable(doc: dict) -> bool:
    return any("latest_period_end" in s for s in doc.get("stocks", {}).values())


def find(as_of: str) -> Path | None:
    """基準日（YYYY-MM-DD）より前で、決算期の入ったいちばん新しい passers.json."""
    found = []
    for f in DATA.glob("*/passers.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        run = str(doc.get("run") or f.parent.name)
        if run < as_of and _usable(doc):
            found.append((run, f))
    return max(found)[1] if found else None


def load(path: str | None, as_of: str) -> tuple[dict, Path]:
    """（passers.json の中身, そのパス）。path を省くと find(as_of) で選ぶ。使えないときは理由を出して終える."""
    p = Path(path) if path else find(as_of)
    if p is None:
        sys.exit(f"前回の passers.json が見つからない（{DATA}/*/passers.json のうち {as_of} より前で決算期の入ったもの）")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not _usable(doc):
        sys.exit(f"{p} には銘柄ごとの決算期（latest_period_end）が無いので前回に使えない。"
                 f"代わりに {find(as_of) or '（使えるものが無い）'} を使う")
    return doc, p


def as_of_of(results: Path) -> str:
    """判定結果のフォルダの CSV の名前（ricky_all_YYYYMMDD.csv）から基準日を出す."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})", max(results.glob("ricky_all_*.csv")).stem)
    return f"{m[1]}-{m[2]}-{m[3]}"
