"""依 config/sources.json 抓取週報來源原始資料。

使用方式：
    python scripts/fetch.py --week 2026-W20            # 抓 core 來源
    python scripts/fetch.py --week 2026-W20 --frequency all
    python scripts/fetch.py --week 2026-W20 --only ME-01,BIKE-05

設計原則：
- 每個來源獨立 try/except，一個失敗不影響其他。
- 原始 HTML/JSON/CSV 完整寫入 data/raw/<week>/<source-id>.<ext>。
- 每筆抓取輸出 .meta.json（status, content_type, fetched_at, bytes, error）。
- 抓取失敗一律寫進 fetch_errors.log + 終端顯示，不靜默吞錯。
- 同一週重複執行會覆寫（最新值為準）。
- 不模擬資料：抓不到就是抓不到。
"""
from __future__ import annotations
import argparse
import io
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

# 強制 stdout 使用 UTF-8（Windows 預設 cp950 會壞掉中文與 unicode 符號）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.json"

# 預設禮貌 User-Agent（讓被抓取網站知道是誰）
UA_POLITE = "AiEZ-Trade Bike-Weekly Fetcher / contact: TAITRA"
# 403/401 重試時使用的瀏覽器 UA
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
}
TIMEOUT = 20
SLEEP_BETWEEN = 1.5  # 秒，禮貌間隔

# 台灣 gov 域名常見舊憑證問題，需關閉 TLS 驗證（記錄在 meta.tls_verify=false）
TW_GOV_HOSTS = {
    "mops.twse.com.tw",
    "portal.sw.nat.gov.tw",
    "data.gov.tw",
    "stat.gov.tw",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ext_from_content_type(ct: str) -> str:
    ct = (ct or "").lower()
    if "json" in ct:
        return "json"
    if "xml" in ct or "rss" in ct or "atom" in ct:
        return "xml"
    if "csv" in ct:
        return "csv"
    if "text/plain" in ct:
        return "txt"
    return "html"


META_REFRESH_RE = re.compile(
    r'<meta\s+http-equiv=["\']refresh["\']\s+content=["\']?\s*\d+\s*;\s*url=([^"\'\s>]+)',
    re.IGNORECASE,
)


def _do_get(url: str, headers: dict, verify: bool) -> requests.Response:
    return requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True, verify=verify)


def _follow_meta_refresh(html_text: str, base_url: str) -> str | None:
    """偵測 <meta http-equiv="refresh" content="0; url=..."> 並回傳完整 URL。"""
    m = META_REFRESH_RE.search(html_text[:4000])  # 只看開頭就夠
    if m:
        return urljoin(base_url, m.group(1).strip())
    return None


def fetch_one(source: dict, out_dir: Path) -> dict:
    """抓一個來源，回傳 metadata dict（success/error 都有）。

    處理策略：
    1. 預設用禮貌 UA + TLS 驗證。
    2. 若 host 屬 TW gov（憑證常有問題），自動關 TLS 驗證並記錄。
    3. 若回傳 401/403，重試一次改用瀏覽器 UA。
    """
    sid = source["id"]
    url = source.get("url", "").strip()
    meta = {
        "id": sid,
        "tier": source["tier"],
        "name": source["name"],
        "url": url,
        "fetched_at": utcnow_iso(),
        "status": None,
        "content_type": None,
        "bytes": 0,
        "saved_to": None,
        "tls_verify": True,
        "ua_used": "polite",
        "retried": False,
        "error": None,
    }
    if not url:
        meta["error"] = "no url configured (manual source)"
        return meta
    if source.get("scrape_difficulty") in ("manual", "needs-api-key"):
        why = "manual fetch only" if source.get("scrape_difficulty") == "manual" else "needs API key"
        meta["error"] = f"skipped: {why}"
        return meta

    host = urlparse(url).hostname or ""
    verify = host not in TW_GOV_HOSTS
    meta["tls_verify"] = verify
    if not verify:
        # 抑制 InsecureRequestWarning（已知 TW gov 憑證問題）
        try:
            from urllib3.exceptions import InsecureRequestWarning
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        except Exception:
            pass

    headers = {**HEADERS_BASE, "User-Agent": UA_POLITE}

    try:
        r = _do_get(url, headers, verify)
        # 403/401 重試 with browser UA
        if r.status_code in (401, 403):
            meta["retried"] = True
            meta["ua_used"] = "browser"
            headers["User-Agent"] = UA_BROWSER
            r = _do_get(url, headers, verify)

        # 內容過小且偵測到 meta refresh，再跟一次（MOPS、部分政府站常見）
        if r.ok and len(r.content) < 4000:
            try:
                text = r.content.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            redirect = _follow_meta_refresh(text, r.url)
            if redirect and redirect != r.url:
                meta["meta_refresh_to"] = redirect
                r2 = _do_get(redirect, headers, verify)
                if r2.ok:
                    r = r2

        meta["status"] = r.status_code
        meta["content_type"] = r.headers.get("Content-Type", "")
        ext = ext_from_content_type(meta["content_type"])
        out_file = out_dir / f"{sid}.{ext}"
        out_file.write_bytes(r.content)
        meta["bytes"] = len(r.content)
        meta["saved_to"] = str(out_file.relative_to(ROOT))
        if not r.ok:
            meta["error"] = f"HTTP {r.status_code}"
    except requests.exceptions.SSLError as e:
        meta["error"] = f"SSL error: {type(e).__name__}"
    except requests.exceptions.ConnectionError as e:
        meta["error"] = f"Connection error: {type(e).__name__}"
    except requests.exceptions.Timeout:
        meta["error"] = "timeout"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
    return meta


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--week", required=True, help="ISO 週標籤，如 2026-W20")
    p.add_argument("--frequency", default="core", choices=["core", "trigger", "all"])
    p.add_argument("--only", default=None, help="逗號分隔的 source id，僅抓這些")
    args = p.parse_args()

    sources = json.loads(CONFIG.read_text(encoding="utf-8"))
    targets: list[tuple[str, dict]] = []
    for group in ("middle_east", "bicycle"):
        for s in sources[group]:
            if args.only:
                if s["id"] in args.only.split(","):
                    targets.append((group, s))
            else:
                if args.frequency == "all" or s.get("frequency") == args.frequency:
                    targets.append((group, s))

    out_dir = ROOT / "data" / "raw" / args.week
    out_dir.mkdir(parents=True, exist_ok=True)
    err_log = out_dir / "fetch_errors.log"
    summary_path = out_dir / "fetch_summary.json"

    print(f"=== Bike Weekly Fetch ===")
    print(f"Week: {args.week}  |  Frequency: {args.frequency}  |  Targets: {len(targets)}")
    print(f"Output: {out_dir.relative_to(ROOT)}")
    print()

    summary: list[dict] = []
    errors: list[str] = []

    for i, (group, s) in enumerate(targets, 1):
        print(f"[{i:2d}/{len(targets)}] {s['id']:<10} {s['name'][:50]}", flush=True)
        meta = fetch_one(s, out_dir)
        meta["group"] = group
        summary.append(meta)
        if meta["error"]:
            line = f"[{meta['id']}] {meta['error']}  ({meta['url']})"
            print(f"   FAIL  {meta['error']}")
            errors.append(line)
        else:
            print(f"   OK    HTTP {meta['status']}  {meta['bytes']:>8} bytes  -> {meta['saved_to']}")
        if i < len(targets):
            time.sleep(SLEEP_BETWEEN)

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        err_log.write_text("\n".join(errors) + "\n", encoding="utf-8")

    ok = sum(1 for m in summary if not m["error"])
    print()
    print(f"=== Summary: {ok}/{len(summary)} succeeded ===")
    print(f"Detailed: {summary_path.relative_to(ROOT)}")
    if errors:
        print(f"Errors:   {err_log.relative_to(ROOT)}")
        sys.exit(0)  # 0 因為錯誤已記錄；不要因為單筆失敗整個 pipeline 中止


if __name__ == "__main__":
    main()
