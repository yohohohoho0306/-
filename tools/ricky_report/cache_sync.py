"""有報のキャッシュ（.cache/edinet）を、リポジトリのデータ用ブランチに圧縮して保存・復元する.

    python tools/ricky_report/cache_sync.py restore              # 実行の最初に（ブランチが無ければ何もしない）
    python tools/ricky_report/cache_sync.py save --as-of YYYY-MM-DD   # 実行の最後に

- 保存先はブランチ claude/data-cache の edinet-cache.tar.gz（1ファイル・1コミットだけ）。保存のたびにブランチを
  新しい1コミットで置き換えるので、前回までの圧縮ファイルはブランチの履歴に残らない。
- 保存の前に、もう使わない古いデータを消す: 基準日の 5 年＋600 日より前の書類一覧と、それより前に終わった
  決算期の有報（10期の系列は最新・4年前・5年前の有報で作るので、それより古いものは使わない）。
  さらに、決算期末が基準日の 800 日より前の有報は、第1段階を通った銘柄（--results の series.json にある銘柄）の
  分だけ残す（ほかの会社は最新の有報しか使わないため。毎月の保存で容量が増え続けないようにする）。
  消した有報が後で要るようになっても、判定のときに EDINET から取り直すので結果は変わらない。
- 株価のキャッシュ（.cache/prices）は日ごとのファイルで次回は使わないので保存しない。
- restore はブランチが無ければ何もしない（終了コード 0）。それ以外の失敗（ネットワーク・認証）は理由を出して
  終了コード 1 で終える（キャッシュなしで始めると有報のダウンロードに数時間かかるため、気づけるようにする）。
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import posixpath
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
RECENT_DAYS = 800  # すべての会社の有報を残す幅（最新の有報の探し幅 460 日に、前の期の分を足したもの）
IDENTITY = {"GIT_AUTHOR_NAME": "Claude", "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
            "GIT_COMMITTER_NAME": "Claude", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}


def git(*args: str, data: bytes | None = None, env: dict | None = None) -> bytes:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], input=data, check=True, capture_output=True,
                              env={**os.environ, **env} if env else None).stdout
    except subprocess.CalledProcessError as e:
        print(f"git {args[0]} が失敗した: {e.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        raise


def stage1_codes(results: Path | None) -> set[str] | None:
    """第1段階を通った銘柄（判定結果の series.json の銘柄）。無ければ None（銘柄で分けずに残す）."""
    f = results / "series.json" if results else None
    if not f or not f.exists():
        return None
    return set(json.loads(f.read_text(encoding="utf-8")))


def prune(as_of: date, keep_codes: set[str] | None = None) -> tuple[int, int]:
    """古い書類一覧と、古い決算期の有報を消す。消した数を返す.

    keep_codes を渡すと、決算期末が基準日の RECENT_DAYS 日より前の有報は、その銘柄の分だけ残す。"""
    limit = as_of - timedelta(days=KEEP_DAYS)
    recent = as_of - timedelta(days=RECENT_DAYS)
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
            sec = str((facts.get("SecurityCodeDEI") or {}).get("FilingDateInstant") or "")
            code = sec[:4] if len(sec) == 5 else sec
            old = end and date.fromisoformat(end) < limit
            other = keep_codes is not None and end and date.fromisoformat(end) < recent and code not in keep_codes
            if old or other:
                f.unlink()
                reports += 1
        except (OSError, ValueError, EOFError):
            continue
    return lists, reports


def save(as_of: date, results: Path | None) -> None:
    lists, reports = prune(as_of, stage1_codes(results))
    edinet = CACHE / "edinet"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / FILE
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(edinet, arcname="edinet")
        blob = git("hash-object", "-w", str(archive)).decode().strip()
        size = archive.stat().st_size
    tree = git("mktree", data=f"100644 blob {blob}\t{FILE}\n".encode()).decode().strip()
    named = subprocess.run(["git", "-C", str(ROOT), "config", "user.email"], capture_output=True).stdout.strip()
    env = None if named else IDENTITY  # 名前・メールが未設定のセッションでも commit-tree が通るように
    commit = git("commit-tree", tree, "-m", f"有報のキャッシュ（{as_of}、{size / 1e6:.1f}MB）", env=env).decode().strip()
    git("push", "--force", "origin", f"{commit}:refs/heads/{BRANCH}")
    files = sum(1 for p in edinet.rglob("*") if p.is_file())
    print(f"saved {BRANCH}/{FILE}: {size / 1e6:.1f}MB・{files} ファイル（古い書類一覧 {lists}・有報 {reports} を削除）")


def safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """edinet/ の下の普通のファイルとフォルダだけ（.. や絶対パス、リンクは除く）."""
    out = []
    for m in tar.getmembers():
        name = posixpath.normpath(m.name)
        if name.startswith("/") or ".." in name.split("/") or not (m.isfile() or m.isdir()):
            continue
        if name == "edinet" or name.startswith("edinet/"):
            out.append(m)
    return out


def restore() -> int:
    found = subprocess.run(["git", "-C", str(ROOT), "ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}"],
                           capture_output=True)
    if found.returncode == 2:
        print(f"{BRANCH} が無いので、キャッシュなしで始める（初回は有報のダウンロードに数時間かかる）")
        return 0
    if found.returncode:
        print(f"{BRANCH} を確かめられない: {found.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 1
    if not hasattr(tarfile, "data_filter"):
        print("この Python の tarfile には data_filter が無いので展開しない（Python 3.12 以降で実行する）", file=sys.stderr)
        return 1
    git("fetch", "--depth", "1", "origin", BRANCH)
    data = git("cat-file", "blob", f"FETCH_HEAD:{FILE}")
    CACHE.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(CACHE, members=safe_members(tar), filter="data")
    files = sum(1 for p in (CACHE / "edinet").rglob("*") if p.is_file())
    print(f"restored {len(data) / 1e6:.1f}MB → {CACHE / 'edinet'}（{files} ファイル）")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["restore", "save"])
    p.add_argument("--as-of", help="save の基準日（古いデータを消す基準）")
    p.add_argument("--results", default=str(ROOT / "results" / "full"),
                   help="save で第1段階の通過銘柄を読む判定結果のフォルダ（series.json）。無ければ銘柄で分けない")
    a = p.parse_args()
    if a.action == "restore":
        return restore()
    if not a.as_of:
        p.error("save には --as-of が要る")
    try:
        save(date.fromisoformat(a.as_of), Path(a.results))
    except subprocess.CalledProcessError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
