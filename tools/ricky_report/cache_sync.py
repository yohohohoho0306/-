"""有報のキャッシュ（.cache/edinet）を、リポジトリのデータ用ブランチに圧縮して保存・復元する.

    python tools/ricky_report/cache_sync.py restore              # 実行の最初に（ブランチが無ければ何もしない）
    python tools/ricky_report/cache_sync.py save --as-of YYYY-MM-DD   # 実行の最後に

- 保存先はブランチ claude/data-cache の edinet-cache.tar.gz（1ファイル・1コミットだけ）。保存のたびにブランチを
  新しい1コミットで置き換えるので、前回までの圧縮ファイルはブランチの履歴に残らない。
- 保存の前に、もう使わない古いデータを消す: 基準日の 5 年＋600 日より前の書類一覧と、それより前に終わった
  決算期の有報（10期の系列は最新・4年前・5年前の有報で作るので、それより古いものは使わない）。
- 株価のキャッシュ（.cache/prices）は日ごとのファイルで次回は使わないので保存しない。
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
BRANCH = "claude/data-cache"
FILE = "edinet-cache.tar.gz"
KEEP_DAYS = 5 * 366 + 600  # 5年前の有報を探す書類一覧（期末の 30 日前〜）と、最新の有報の探し幅（460日）の分


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], input=data, check=True, capture_output=True).stdout


def prune(as_of: date) -> tuple[int, int]:
    """古い書類一覧と、古い決算期の有報を消す。消した数を返す."""
    limit = as_of - timedelta(days=KEEP_DAYS)
    lists = reports = 0
    for f in (CACHE / "edinet" / "lists").glob("*.json"):
        try:
            if date.fromisoformat(f.stem) < limit:
                f.unlink()
                lists += 1
        except ValueError:
            continue
    for f in (CACHE / "edinet" / "reports").glob("*.json.gz"):
        try:
            facts = json.loads(gzip.decompress(f.read_bytes())).get("facts", {})
            end = (facts.get("CurrentFiscalYearEndDateDEI") or {}).get("FilingDateInstant")
            if end and date.fromisoformat(end) < limit:
                f.unlink()
                reports += 1
        except (OSError, ValueError, EOFError):
            continue
    return lists, reports


def save(as_of: date) -> None:
    lists, reports = prune(as_of)
    edinet = CACHE / "edinet"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / FILE
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(edinet, arcname="edinet")
        blob = git("hash-object", "-w", str(archive)).decode().strip()
        size = archive.stat().st_size
    tree = git("mktree", data=f"100644 blob {blob}\t{FILE}\n".encode()).decode().strip()
    commit = git("commit-tree", tree, "-m", f"有報のキャッシュ（{as_of}、{size / 1e6:.1f}MB）").decode().strip()
    git("push", "--force", "origin", f"{commit}:refs/heads/{BRANCH}")
    files = sum(1 for p in edinet.rglob("*") if p.is_file())
    print(f"saved {BRANCH}/{FILE}: {size / 1e6:.1f}MB・{files} ファイル（古い書類一覧 {lists}・有報 {reports} を削除）")


def restore() -> None:
    try:
        git("fetch", "--depth", "1", "origin", BRANCH)
    except subprocess.CalledProcessError:
        print(f"{BRANCH} が無いので、キャッシュなしで始める（初回は有報のダウンロードに数時間かかる）")
        return
    data = git("cat-file", "blob", f"FETCH_HEAD:{FILE}")
    CACHE.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name == "edinet" or m.name.startswith("edinet/")]
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(CACHE, members=members, **kwargs)
    files = sum(1 for p in (CACHE / "edinet").rglob("*") if p.is_file())
    print(f"restored {len(data) / 1e6:.1f}MB → {CACHE / 'edinet'}（{files} ファイル）")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["restore", "save"])
    p.add_argument("--as-of", help="save の基準日（古いデータを消す基準）")
    a = p.parse_args()
    if a.action == "restore":
        restore()
    else:
        if not a.as_of:
            p.error("save には --as-of が要る")
        save(date.fromisoformat(a.as_of))
    return 0


if __name__ == "__main__":
    sys.exit(main())
