"""EDINET API v2 のクライアント（ディスクキャッシュ付き）.

- 書類一覧（documents.json）は日付ごとに、有価証券報告書の行だけをキャッシュする。
- 書類本体（type=1 の ZIP）は保存せず、主要な経営指標等の推移などの要素の値だけを
  gzip の JSON でキャッシュする（取り出し方を変えてもキャッシュから計算し直せる）。
- API キーは環境変数 EDINET_API_KEY から読む。エラーメッセージや例外に
  キーが混ざらないようにしている。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from .xbrl import (
    FACTS_VERSION, AnnualReport, build_report, extract_instance, facts_from_dict, facts_to_dict, parse_instance,
)

API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
CODELIST_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
API_KEY_ENV = "EDINET_API_KEY"

DOC_TYPE_ANNUAL = "120"  # 有価証券報告書
_KEEP_FIELDS = (
    "docID", "edinetCode", "secCode", "filerName", "docTypeCode",
    "periodStart", "periodEnd", "submitDateTime", "withdrawalStatus", "xbrlFlag",
)


class EdinetError(RuntimeError):
    pass


def _write_atomic(path: Path, data: bytes) -> None:
    """途中まで書いたファイルを別プロセスが読まないよう、一時ファイルに書いてから置き換える."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass
class Company:
    edinet_code: str
    sec_code: str  # 4 桁（英数字コードを含む）
    name: str
    industry: str
    fiscal_year_end: str
    consolidated: str


def _ticker4(sec_code: Optional[str]) -> Optional[str]:
    """EDINET の 5 桁証券コード（72030, 135A0）を 4 桁にする."""
    if not sec_code:
        return None
    s = sec_code.strip()
    return s[:4] if len(s) == 5 else s


class EdinetClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: str | Path = ".cache/edinet",
        sleep: float = 0.5,
        session=None,
        log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        self.cache_dir = Path(cache_dir)
        self.sleep = sleep
        self.log = log
        if session is None:
            import requests  # 遅延 import

            session = requests.Session()
        self.session = session
        (self.cache_dir / "lists").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "reports").mkdir(parents=True, exist_ok=True)
        self._lists: dict[date, list[dict]] = {}  # 第2段階で同じ日を何度も読むのでメモリにも置く

    # ---- HTTP -------------------------------------------------------------

    def _get(self, url: str, params: Optional[dict] = None, needs_key: bool = True):
        if needs_key and not self.api_key:
            raise EdinetError(f"環境変数 {API_KEY_ENV} が設定されていません")
        query = dict(params or {})
        if needs_key:
            query["Subscription-Key"] = self.api_key
        last_error = ""
        for attempt in range(4):
            try:
                resp = self.session.get(url, params=query, timeout=60)
            except Exception as exc:  # noqa: BLE001 - 接続失敗はリトライ
                last_error = type(exc).__name__
            else:
                if resp.status_code == 200:
                    time.sleep(self.sleep)
                    return resp
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code in (400, 401, 403, 404):
                    break
            time.sleep(min(2 ** attempt * 2, 16))
        # URL にはキーが入るので出さない
        raise EdinetError(f"EDINET への接続に失敗しました（{url.split('?')[0]}: {last_error}）")

    # ---- コードリスト -----------------------------------------------------

    def companies(self, max_age_days: int = 7) -> list[Company]:
        """上場会社の一覧（EDINET コードリスト）を返す."""
        path = self.cache_dir / "Edinetcode.csv"
        fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400
        if not fresh:
            resp = self._get(CODELIST_URL, needs_key=False)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                path.write_bytes(zf.read(name))
        return parse_code_list(path.read_bytes())

    # ---- 書類一覧 -----------------------------------------------------------

    def annual_reports_on(self, day: date) -> list[dict]:
        """その日に提出された有価証券報告書（取下げ分を除く）の一覧."""
        if day in self._lists:
            return self._lists[day]
        path = self.cache_dir / "lists" / f"{day.isoformat()}.json"
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            self._lists[day] = rows
            return rows
        resp = self._get(f"{API_BASE}/documents.json", {"date": day.isoformat(), "type": 2})
        data = resp.json()
        status = str((data.get("metadata") or {}).get("status") or data.get("StatusCode") or "")
        if status != "200":
            message = (data.get("metadata") or {}).get("message") or data.get("message") or ""
            raise EdinetError(f"書類一覧APIのエラー（{day}: status={status} {message}）")
        rows = [
            {k: r.get(k) for k in _KEEP_FIELDS}
            for r in data.get("results", [])
            if r.get("docTypeCode") == DOC_TYPE_ANNUAL and r.get("withdrawalStatus") in (None, "0")
        ]
        # 当日・前日分は後から追加される可能性があるのでキャッシュしない
        if day < date.today() - timedelta(days=1):
            _write_atomic(path, json.dumps(rows, ensure_ascii=False).encode("utf-8"))
            self._lists[day] = rows
        return rows

    def scan(self, start: date, end: date, progress: bool = False) -> Iterable[dict]:
        """start〜end（両端を含む）に提出された有価証券報告書を順に返す."""
        total = (end - start).days + 1
        for n in range(total):
            if progress and n and n % 50 == 0:
                self.log(f"  書類一覧 {n}/{total} 日分")
            yield from self.annual_reports_on(start + timedelta(days=n))

    def latest_annual_reports(self, start: date, end: date) -> dict[str, dict]:
        """期間内に提出された有価証券報告書のうち、会社ごとに最新の 1 通."""
        latest: dict[str, dict] = {}
        for row in self.scan(start, end, progress=True):
            code = row.get("edinetCode")
            if not code or not row.get("secCode") or row.get("xbrlFlag") != "1":
                continue
            key = (row.get("periodEnd") or "", row.get("submitDateTime") or "")
            cur = latest.get(code)
            if cur is None or key > (cur.get("periodEnd") or "", cur.get("submitDateTime") or ""):
                latest[code] = row
        return latest

    def find_annual_report(self, edinet_code: str, period_end: date) -> Optional[dict]:
        """指定した期末日に近い（±45日）有価証券報告書を探す."""
        best = None
        for row in self.scan(period_end - timedelta(days=30), period_end + timedelta(days=200)):
            if row.get("edinetCode") != edinet_code or row.get("xbrlFlag") != "1" or not row.get("periodEnd"):
                continue
            gap = abs((date.fromisoformat(row["periodEnd"]) - period_end).days)
            if gap <= 45 and (best is None or gap < best[0]):
                best = (gap, row)
        return best[1] if best else None

    # ---- 書類本体 -----------------------------------------------------------

    def annual_report(self, doc_id: str) -> AnnualReport:
        """有価証券報告書の XBRL を取得して AnnualReport にする.

        書類本体は保存せず、主要な経営指標等の推移・DEI・配当政策の要素だけを gzip の JSON で
        キャッシュする。指標の取り出し方を変えても、キャッシュから計算し直せる。
        """
        path = self.cache_dir / "reports" / f"{doc_id}.json.gz"
        if path.exists():
            cached = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            if cached.get("facts_version") == FACTS_VERSION:
                return build_report(*facts_from_dict(cached), doc_id=doc_id)
        resp = self._get(f"{API_BASE}/documents/{doc_id}", {"type": 1})
        if not resp.content.startswith(b"PK"):
            # エラー時は JSON（例: {"metadata": {"status": "404", ...}}）が返る
            raise EdinetError(f"書類 {doc_id} の取得結果が ZIP ではありません: {resp.content[:200]!r}")
        facts, contexts = parse_instance(extract_instance(resp.content))
        data = facts_to_dict(facts, contexts)
        _write_atomic(path, gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8")))
        return build_report(*facts_from_dict(data), doc_id=doc_id)


def parse_code_list(raw: bytes) -> list[Company]:
    """EDINET コードリスト（cp932 の CSV。1 行目は注記、2 行目が見出し）を読む."""
    text = raw.decode("cp932", errors="replace")
    lines = text.splitlines()
    header_at = next(i for i, line in enumerate(lines) if "ＥＤＩＮＥＴコード" in line or "EDINETコード" in line)
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_at:])))
    companies = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        code = row.get("ＥＤＩＮＥＴコード") or row.get("EDINETコード")
        sec = _ticker4(row.get("証券コード"))
        if not code or not sec or row.get("上場区分") != "上場":
            continue
        companies.append(Company(
            edinet_code=code,
            sec_code=sec,
            name=row.get("提出者名", ""),
            industry=row.get("提出者業種", ""),
            fiscal_year_end=row.get("決算日", ""),
            consolidated=row.get("連結の有無", ""),
        ))
    return companies
