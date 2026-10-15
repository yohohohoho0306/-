"""今日（日本時間）に月次の判定を始めるかを決める。始めるなら「run 基準日」、始めないなら「skip」を出す.

    python tools/ricky_report/run_day.py            # 今日
    python tools/ricky_report/run_day.py 2027-03-12  # 日付を指定して確かめる

実行日は毎月14日。14日が土日・祝日（東証の休業日）なら、その前の営業日（多くは金曜日）。
定期実行は毎月10〜16日の朝に起動し、このスクリプトが「skip」なら何もせずに終える。
実行日に失敗したときは、その月の実行が終わるまで、次の日以降の起動（16日まで）で取り直す。
「終わった」は、その月の実行日以降の日付で、次のどちらかがあること:
- research/runs/<日付>.md（月次の要約。既定のブランチにマージされたもの）
- キャッシュのブランチ claude/data-cache の保存（cache_sync.py save のコミットの文に基準日が入る）
「run」の後ろの日付（日本時間の今日）を、その回の基準日（--as-of・ファイル名）に使う。
祝日は jpholiday（pip install jpholiday）で判定する。入っていなければ判定を誤るので、終了コード 2 で止める。
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import jpholiday
except ImportError:  # pragma: no cover - 入っていない環境では main が止める
    jpholiday = None

DAY = 14
JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
BRANCH = "claude/data-cache"


def is_business_day(d: date) -> bool:
    """東証の営業日か（土日・祝日・年末年始 12/31〜1/3 を除く）."""
    if d.weekday() >= 5 or (d.month, d.day) in ((12, 31), (1, 1), (1, 2), (1, 3)):
        return False
    return not (jpholiday and jpholiday.is_holiday(d))


def run_date(year: int, month: int) -> date:
    """その月の実行日: 14日、休業日ならその前の営業日."""
    d = date(year, month, DAY)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def decide(today: date, finished: list[date]) -> tuple[bool, date]:
    """（始めるか, 今月の実行日）。実行日以降で、今月の実行日以降の実行がまだ終わっていなければ始める."""
    target = run_date(today.year, today.month)
    done = any(target <= d and (d.year, d.month) == (today.year, today.month) for d in finished)
    return today >= target and not done, target


def finished_runs() -> list[date]:
    """終わった月次の基準日: research/runs/<日付>.md と、キャッシュのブランチの保存の日付."""
    days = []
    for f in (ROOT / "research" / "runs").glob("*.md"):
        try:
            days.append(date.fromisoformat(f.stem))
        except ValueError:
            continue
    fetched = subprocess.run(["git", "-C", str(ROOT), "fetch", "--depth", "1", "origin", BRANCH], capture_output=True)
    if fetched.returncode == 0:
        msg = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", "FETCH_HEAD"],
                             capture_output=True, text=True).stdout
        m = re.search(r"\d{4}-\d{2}-\d{2}", msg)
        if m:
            days.append(date.fromisoformat(m.group()))
    return days


def main() -> int:
    if jpholiday is None:
        print("jpholiday が無いので祝日を判定できない。pip install -r requirements.txt をやり直す", file=sys.stderr)
        return 2
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(JST).date()
    target = run_date(today.year, today.month)
    start = today >= target and decide(today, finished_runs())[0]  # 実行日の前はブランチを見に行かない
    if start:
        print(f"run {today}", f"(今月の実行日 {target}" + ("" if today == target else "。実行日の分を取り直す") + ")")
    else:
        why = "まだ実行日の前" if today < target else "今月の分は終わっている"
        print("skip", f"(今日 {today}、今月の実行日 {target}、{why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
