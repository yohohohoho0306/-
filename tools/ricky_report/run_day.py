"""今日（日本時間）が月次の実行日かを判定する。実行日なら「run」、違えば「skip」を出す.

    python tools/ricky_report/run_day.py            # 今日
    python tools/ricky_report/run_day.py 2027-03-12  # 日付を指定して確かめる

実行日は毎月14日。14日が土日・祝日（東証の休業日）なら、その前の営業日（多くは金曜日）。
定期実行は毎月10〜14日の朝に起動し、このスクリプトが「skip」なら何もせずに終える。
祝日は jpholiday（pip install jpholiday）で判定する。入っていなければ土日だけで判定し、その旨を出す。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

try:
    import jpholiday
except ImportError:  # pragma: no cover - 入っていない環境では土日だけで判定する
    jpholiday = None

DAY = 14
JST = timezone(timedelta(hours=9))


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


def main() -> int:
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(JST).date()
    target = run_date(today.year, today.month)
    if jpholiday is None:
        print("注意: jpholiday が無いので祝日を考えずに判定した（pip install jpholiday）", file=sys.stderr)
    print("run" if today == target else "skip", f"(今日 {today}、今月の実行日 {target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
