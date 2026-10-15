"""「億り人の必勝法」の動画の字幕（文字起こし）を取り、.cache/zai_transcripts/<vol>_<id>.txt に保存する.

    python tools/zai_okuribito/fetch_transcripts.py --discover   # YouTube の検索で id が空の回を埋めてから取る
    python tools/zai_okuribito/fetch_transcripts.py --vol 15     # 1本だけ

字幕は YouTube の日本語字幕（無ければ自動生成の字幕）。文字起こしは著作物なのでリポジトリには入れない（.cache は .gitignore 済み）。
要約は research/zai_okuribito/ に自分の言葉で書く。接続先は www.youtube.com。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEOS = Path(__file__).with_name("videos.json")
SERIES = "億り人の必勝法"


def discover(data: dict) -> int:
    """yt-dlp の検索結果から「億り人の必勝法 vol.N」の id とタイトルを埋める。埋めた本数を返す."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
        info = ydl.extract_info(f"ytsearch60:{SERIES} ザイの資産形成塾", download=False)
    by_vol = {v["vol"]: v for v in data["series"]}
    filled = 0
    for e in info.get("entries") or []:
        title = e.get("title") or ""
        m = re.search(SERIES + r"\s*vol\.?\s*(\d+)", title, re.I)
        if not m:
            continue
        vol = int(m.group(1))
        v = by_vol.setdefault(vol, {"vol": vol, "investor": None, "id": None, "title": None})
        if v not in data["series"]:
            data["series"].append(v)
        if not v["id"]:
            v["id"], v["title"] = e["id"], title
            filled += 1
    data["series"].sort(key=lambda v: v["vol"])
    return filled


def fetch_text(video_id: str) -> tuple[str, str]:
    """字幕を [mm:ss] 付きの行で返す。2つ目は字幕の種類（手動／自動生成）."""
    from youtube_transcript_api import YouTubeTranscriptApi

    listing = YouTubeTranscriptApi().list(video_id)
    try:
        tr, kind = listing.find_manually_created_transcript(["ja"]), "手動"
    except Exception:
        tr, kind = listing.find_generated_transcript(["ja"]), "自動生成"
    lines = []
    for s in tr.fetch():
        t = int(s.start)
        lines.append(f"[{t // 60:02d}:{t % 60:02d}] {s.text.replace(chr(10), ' ')}")
    return "\n".join(lines), kind


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--discover", action="store_true", help="YouTube の検索で id が空の回を埋め、videos.json を書き直す")
    p.add_argument("--vol", type=int, action="append", help="取る回（複数可）。既定はすべて")
    p.add_argument("--extra", action="store_true", help="編集部の解説動画（videos.json の extra）も取る")
    p.add_argument("--out", default=str(ROOT / ".cache" / "zai_transcripts"), help="保存先")
    p.add_argument("--force", action="store_true", help="保存済みでも取り直す")
    args = p.parse_args()

    data = json.loads(VIDEOS.read_text(encoding="utf-8"))
    if args.discover:
        n = discover(data)
        VIDEOS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"検索で {n} 本の id を埋めた", file=sys.stderr)

    targets = [v for v in data["series"] if v["id"] and (not args.vol or v["vol"] in args.vol)]
    if args.extra:
        targets += [dict(e, vol=0) for e in data["extra"]]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for v in targets:
        path = out / f"{v['vol']:02d}_{v['id']}.txt"
        if path.exists() and not args.force:
            print(f"vol.{v['vol']:02d} 保存済み {path.name}", file=sys.stderr)
            continue
        try:
            text, kind = fetch_text(v["id"])
        except Exception as e:  # noqa: BLE001  1本の失敗で止めない
            failed += 1
            print(f"vol.{v['vol']:02d} {v['id']} 失敗: {type(e).__name__}: {str(e).splitlines()[0]}", file=sys.stderr)
            continue
        header = f"# vol.{v['vol']:02d} {v.get('investor') or ''} {v.get('title') or ''}\n# https://www.youtube.com/watch?v={v['id']}（字幕: {kind}）\n\n"
        path.write_text(header + text + "\n", encoding="utf-8")
        print(f"vol.{v['vol']:02d} {path.name} {len(text)}字（{kind}）", file=sys.stderr)
    missing = [v["vol"] for v in data["series"] if not v["id"]]
    if missing:
        print(f"id が分からない回: {missing}（--discover で探す）", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
