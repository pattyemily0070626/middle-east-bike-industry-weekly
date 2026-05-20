"""關務署 GA31 自動抓取（OCR 解 CAPTCHA，不需人工）。

使用方式：
    python scripts/fetch_customs_auto.py --week 2026-W21 --hs 87120010,871160,871491,87149200,85065000 --rocy 115 --rocm 5
    python scripts/fetch_customs_auto.py --week 2026-W21 --hs 87120010 --rocy 115 --rocm 5 --end-rocy 115 --end-rocm 5

Tesseract OCR 解 6 位數字 CAPTCHA：
- 預期路徑 C:\\Users\\<user>\\AppData\\Local\\Programs\\Tesseract-OCR\\tesseract.exe（winget 安裝預設）
- 也找 C:\\Program Files\\Tesseract-OCR\\tesseract.exe 與 PATH
- 失敗自動 reload 新 CAPTCHA、重試最多 3 次／HS
- 3 連敗才放棄該 HS、紀錄到錯誤 log
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

TESSERACT_CANDIDATES = [
    Path(os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")),
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


def find_tesseract() -> Path:
    for p in TESSERACT_CANDIDATES:
        if p.exists():
            return p
    # Try PATH
    from shutil import which
    found = which("tesseract")
    if found:
        return Path(found)
    raise FileNotFoundError("tesseract.exe not found. Install via: winget install UB-Mannheim.TesseractOCR")


def ocr_captcha(image_path: Path, tess_exe: Path) -> str:
    """執行 tesseract 對 CAPTCHA 圖做 OCR，回傳 6 位數字字串。"""
    result = subprocess.run(
        [str(tess_exe), str(image_path), "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789"],
        capture_output=True, text=True, timeout=15,
    )
    raw = result.stdout.strip()
    # 取出純數字
    digits = re.sub(r"\D", "", raw)
    return digits


def fetch_one_hs(page, hs: str, rocy: str, rocm: str, end_rocy: str, end_rocm: str,
                 captcha_img: Path, tess_exe: Path, max_retries: int = 3) -> dict:
    """為單一 HS 跑完整查詢，含 OCR + 重試。"""
    meta = {
        "hs": hs,
        "rocy": rocy, "rocm": rocm, "end_rocy": end_rocy, "end_rocm": end_rocm,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "captcha_attempts": [],
        "status": None,  # "ok" | "no_data" | "tariff_not_found" | "captcha_failed" | "error"
        "result_html": None,
        "value_usd_thousand": None,
        "error": None,
    }
    for attempt in range(1, max_retries + 1):
        try:
            page.goto("https://portal.sw.nat.gov.tw/APGA/GA31", wait_until="networkidle", timeout=30000)
            # Save CAPTCHA image
            src = page.evaluate("() => document.getElementById('captchaPic').src")
            resp = page.context.request.get(src)
            captcha_img.write_bytes(resp.body())
            # OCR
            captcha_val = ocr_captcha(captcha_img, tess_exe)
            meta["captcha_attempts"].append({"attempt": attempt, "ocr": captcha_val})
            if len(captcha_val) != 6:
                continue  # 重抓

            # 填表
            page.locator("input#Export").check()
            page.locator("input#REPORT_TYPE_0").check()
            page.locator("select#START_YEAR").select_option(rocy)
            page.locator("select#END_YEAR").select_option(end_rocy)
            page.locator("select#START_MONTH").select_option(rocm)
            page.locator("select#END_MONTH").select_option(end_rocm)
            page.locator("input#HS_TYPE_2").check()
            page.locator("input#goodsCodeValue").fill(hs)
            page.locator("input#COUNTRY_TYPE_0").check()
            page.locator("input#Statistics1").check()
            page.locator("input#EXPORT_TYPE_1").check()
            page.locator("input#checkNo").fill(captcha_val)
            page.locator("button#FORM_CHECK").click()
            page.wait_for_load_state("networkidle", timeout=30000)
            # 等 AJAX 載入完成（『載入中』消失或出現實際資料）
            try:
                page.wait_for_function(
                    """() => {
                        const t = document.body ? document.body.innerText : '';
                        if (t.includes('載入中')) return false;
                        // 確認進入結果頁（其中之一）：有腳踏車/Bicycle 行 / 查無資料 / 驗證碼錯誤 / 查無此稅則
                        return t.includes('Bicycle') || t.includes('腳踏車') || t.includes('馬達')
                            || t.includes('電池') || t.includes('車架')
                            || t.includes('查無資料') || t.includes('無查詢結果')
                            || t.includes('查無此稅則') || t.includes('驗證碼錯誤');
                    }""",
                    timeout=20000,
                )
            except Exception:
                page.wait_for_timeout(3000)  # fallback 多等 3 秒

            html = page.content()
            body = page.evaluate("() => document.body ? document.body.innerText : ''")

            if "驗證碼錯誤" in body:
                meta["captcha_attempts"][-1]["result"] = "wrong_captcha"
                continue  # retry
            # Captured a result page
            out_dir = captcha_img.parent
            out_file = out_dir / f"customs-{hs}-{rocy}-{rocm}.html"
            if end_rocm != rocm:
                out_file = out_dir / f"customs-{hs}-{rocy}-{rocm}_to_{end_rocy}-{end_rocm}.html"
            out_file.write_text(html, encoding="utf-8")
            meta["result_html"] = str(out_file.relative_to(ROOT))

            if "查無此稅則" in body:
                meta["status"] = "tariff_not_found"
                return meta
            if "查無資料" in body or "無查詢結果" in body:
                meta["status"] = "no_data"
                return meta

            # 解析金額：找資料列（非查詢摘要），cells[2]=HS、cells[3]=中文品名、cells[5]=金額
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            value = None
            for tr in soup.find_all("tr"):
                cells = [c.get_text(" ", strip=True).replace(",", "") for c in tr.find_all(["td", "th"])]
                if len(cells) >= 6 and hs in cells:
                    # 跳過查詢摘要列（會含「105年起按一般貿易制度編製」等註腳）
                    last = cells[-1]
                    if last.replace(".", "").isdigit():
                        value = float(last)
                        break
            if value is None:
                meta["status"] = "parse_failed"
                meta["error"] = "result page loaded but value not parsed"
                return meta
            meta["value_usd_thousand"] = value
            meta["status"] = "ok"
            return meta
        except Exception as e:
            meta["error"] = f"{type(e).__name__}: {e}"
    # 3 連敗
    if not meta["status"]:
        meta["status"] = "captcha_failed"
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True)
    ap.add_argument("--hs", required=True, help="逗號分隔多個 HS 碼")
    ap.add_argument("--rocy", required=True)
    ap.add_argument("--rocm", required=True)
    ap.add_argument("--end-rocy", default=None)
    ap.add_argument("--end-rocm", default=None)
    ap.add_argument("--max-retries", type=int, default=3)
    args = ap.parse_args()

    end_y = args.end_rocy or args.rocy
    end_m = args.end_rocm or args.rocm

    hs_list = [h.strip() for h in args.hs.split(",") if h.strip()]
    out_dir = ROOT / "data" / "raw" / args.week
    out_dir.mkdir(parents=True, exist_ok=True)
    captcha_img = out_dir / "captcha-live.png"

    tess = find_tesseract()
    print(f"=== Customs Auto Fetch (OCR) ===")
    print(f"Tesseract: {tess}")
    print(f"Week: {args.week}  |  HS: {len(hs_list)} codes  |  Period: 民國{args.rocy}/{args.rocm} ~ {end_y}/{end_m}")
    print()

    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="zh-TW", ignore_https_errors=True)
        page = ctx.new_page()
        for i, hs in enumerate(hs_list, 1):
            print(f"[{i}/{len(hs_list)}] HS {hs} ...", end=" ", flush=True)
            meta = fetch_one_hs(page, hs, args.rocy, args.rocm, end_y, end_m,
                                captcha_img, tess, args.max_retries)
            results.append(meta)
            attempts = len(meta["captcha_attempts"])
            v = meta.get("value_usd_thousand")
            if meta["status"] == "ok" and v is not None:
                print(f"OK   USD {v:,.0f}K  ({attempts} captcha)")
            elif meta["status"] == "no_data":
                print(f"NO_DATA  (此期間查無資料，{attempts} captcha)")
            elif meta["status"] == "tariff_not_found":
                print(f"TARIFF_NOT_FOUND  (稅則不存在)")
            elif meta["status"] == "captcha_failed":
                print(f"CAPTCHA_FAILED  ({attempts} attempts)")
            elif meta["status"] == "parse_failed":
                print(f"PARSE_FAILED  ({meta.get('error')})")
            else:
                print(f"ERROR  status={meta['status']!r}  {meta.get('error')}")
            time.sleep(2)  # 禮貌
        browser.close()

    # Summary
    summary_path = out_dir / "customs_fetch_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {summary_path.relative_to(ROOT)}")

    # 統計與異常旗標
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n=== Summary: {ok}/{len(results)} OK ===")
    issues = [r for r in results if r["status"] != "ok"]
    if issues:
        print(f"⚠ 需要你確認的異常：")
        for r in issues:
            print(f"   HS {r['hs']}: {r['status']}  ({len(r['captcha_attempts'])} captcha attempts)")


if __name__ == "__main__":
    main()
