---
title: tools/zai_okuribito の道具
date: 2026-10-15
tags: [zai-okuribito, tools]
---

# tools/zai_okuribito の道具

ダイヤモンドZAi の YouTube「億り人の必勝法」（ザイの資産形成塾）の字幕を取り、出演した個人投資家の投資手法をまとめるための準備。リポジトリの根元から実行する。

| ファイル | 中身 |
|---|---|
| `videos.json` | 回ごとの投資家・動画の id・タイトル（2026-10-15 に検索で見つけた分。vol.04・05・07〜10・14 は id が未確認） |
| `fetch_transcripts.py` | 字幕（無ければ自動生成の字幕）を `.cache/zai_transcripts/` に保存する。`--discover` で id が空の回を YouTube の検索から埋める |

```bash
pip install youtube-transcript-api yt-dlp
python tools/zai_okuribito/fetch_transcripts.py --discover --extra
```

- 接続先は `www.youtube.com`。クラウドの環境では、ネットワークの許可（Allowed domains）に入っていないと取れない。
- 文字起こしは著作物なのでリポジトリに入れない（`.cache/` は `.gitignore` 済み）。要約は自分の言葉で書く。
