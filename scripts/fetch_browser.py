"""Playwright-based fetcher for JS-rendered sources.

使用方式：
    python scripts/fetch_browser.py --week 2026-W20 --target ukmto
    python scripts/fetch_browser.py --week 2026-W20 --target customs --hs 87120010
    python scripts/fetch_browser.py --week 2026-W20 --target all

支援的 target：
    ukmto       — https://www.ukmto.org/recent-incidents（等 IncidentList 內容載入）
    customs     — 海關進出口統計（多步 form submission，每 HS 碼一次）

設計原則：
- 使用 headless chromium，user_agent 設為瀏覽器標準值
- 等待具體元素出現才 dump，避免拿到空殼
- 失敗（timeout、selector 不存在）一律記錄並繼續下一個
- 不模擬資料：拿不到就標 fail
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
RAW_BASE = ROOT / "data" / "raw"

UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# UKMTO Recent Incidents
# ============================================================

def fetch_ukmto(playwright, out_dir: Path) -> dict:
    """等 UKMTO IncidentList 內容載入後 dump HTML。"""
    meta = {
        "id": "ME-02",
        "name": "UKMTO Recent Incidents",
        "url": "https://www.ukmto.org/recent-incidents",
        "fetched_at": utcnow_iso(),
        "engine": "playwright",
        "saved_to": None,
        "error": None,
    }
    try:
        browser = playwright.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA_BROWSER, locale="en-US")
        page = ctx.new_page()
        page.goto(meta["url"], wait_until="domcontentloaded", timeout=30000)
        # 等 IncidentList 出現實際內容（不只是空殼）
        # IncidentList_incidentList__pr7vi 內應該會出現 li/div 子元素
        try:
            page.wait_for_function(
                """() => {
                    const list = document.querySelector('[class*="IncidentList_incidentList"]');
                    if (!list) return false;
                    return list.children.length > 0 || list.textContent.trim().length > 50;
                }""",
                timeout=20000,
            )
        except Exception:
            # 即使等不到完整內容也 dump 看看
            page.wait_for_timeout(5000)
        html = page.content()
        out_file = out_dir / "ME-02.html"
        out_file.write_text(html, encoding="utf-8")
        meta["saved_to"] = str(out_file.relative_to(ROOT))
        meta["bytes"] = len(html)
        browser.close()
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
    return meta


# ============================================================
# 關務署 — 海關進出口統計
# ============================================================

CUSTOMS_URL = "https://portal.sw.nat.gov.tw/APGA/GA03"

L1_HS_CODES = [
    "87120010", "87116000",
    "87149100", "87149200", "87149300", "87149400",
    "87149500", "87149600", "87149900",
    "85013100", "85065000",
]


def fetch_customs(playwright, out_dir: Path, hs_codes: list[str], year_month: str) -> list[dict]:
    """以 Playwright 操作 portal.sw.nat.gov.tw 查詢 HS 碼月度出口。

    多步流程：
    1. GA03 splash → 選『出口』+『月』→ submit
    2. 下一頁應出現 HS 碼/年月/國別 表單 → 為每個 HS 碼填寫並 submit
    3. 結果頁 → dump 表格
    """
    results = []
    meta = {
        "id": "BIKE-02-STEP",
        "name": "關務署進出口統計（多步 probe）",
        "url": CUSTOMS_URL,
        "fetched_at": utcnow_iso(),
        "engine": "playwright",
        "steps": [],
        "error": None,
    }
    try:
        browser = playwright.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA_BROWSER,
            locale="zh-TW",
            ignore_https_errors=True,
        )
        page = ctx.new_page()

        # Step 1: splash
        page.goto(CUSTOMS_URL, wait_until="networkidle", timeout=30000)
        # 選 export + month + submit
        page.locator("input[name='c1TypePort'][value='export']").check()
        page.locator("input[name='c1TypeTime'][value='month']").check()
        # 找 submit button
        # 表單 onsubmit/javascript driven
        page.locator("form").evaluate("f => f.submit()")
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        html1 = page.content()
        (out_dir / "BIKE-02-step1.html").write_text(html1, encoding="utf-8")
        meta["steps"].append({"step": 1, "url": page.url, "bytes": len(html1)})

        # 輸出 step1 form 結構供分析
        forms_info = page.evaluate("""() => {
            const forms = document.querySelectorAll('form');
            return Array.from(forms).map(f => ({
                action: f.action,
                method: f.method,
                fields: Array.from(f.elements).slice(0, 60).map(e => ({
                    name: e.name, type: e.type, value: (e.value || '').slice(0,80), tag: e.tagName.toLowerCase()
                }))
            }));
        }""")
        (out_dir / "BIKE-02-step1.form_info.json").write_text(
            json.dumps(forms_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        browser.close()
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
    results.append(meta)
    return results


# ============================================================
# Main
# ============================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--week", required=True)
    p.add_argument("--target", default="all", choices=["ukmto", "customs", "all"])
    p.add_argument("--hs", default=",".join(L1_HS_CODES), help="逗號分隔 HS 碼")
    p.add_argument("--year-month", default="11504", help="ROC 年月（預設 115/4 = 2026/4）")
    args = p.parse_args()

    out_dir = RAW_BASE / args.week
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    print(f"=== Bike Weekly Browser Fetch (Playwright) ===")
    print(f"Week: {args.week}  |  Target: {args.target}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        if args.target in ("ukmto", "all"):
            print(f"\n[ukmto] fetching...")
            meta = fetch_ukmto(pw, out_dir)
            summary.append(meta)
            status = "FAIL " + meta["error"] if meta["error"] else f"OK  {meta.get('bytes', 0)} bytes"
            print(f"  {status}")

        if args.target in ("customs", "all"):
            hs = args.hs.split(",")
            print(f"\n[customs] probe form structure (HS: {hs[:3]}...)")
            metas = fetch_customs(pw, out_dir, hs, args.year_month)
            summary.extend(metas)
            for m in metas:
                status = "FAIL " + m["error"] if m["error"] else f"OK  {m.get('bytes', 0)} bytes"
                print(f"  {status}  {m['id']}")

    # 合併到既有 fetch_summary（不覆蓋 requests 抓的）
    sum_path = out_dir / "fetch_browser_summary.json"
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary: {sum_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
