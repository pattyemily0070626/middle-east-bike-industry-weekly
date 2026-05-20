"""一次性抓取關務署 GA31 多 HS 碼結果。

工作流：
1. 開瀏覽器、goto GA31
2. 抓 CAPTCHA 圖到 data/raw/<week>/captcha-live.png
3. 等候 data/raw/<week>/captcha-answer.txt 出現（由人類填入）
4. 填表 + CAPTCHA + 提交
5. 儲存結果 HTML 到 data/raw/<week>/customs-<hs>-<ym>.html

使用方式：
    python scripts/fetch_customs_oneshot.py --week 2026-W20 --hs 87120010 --rocy 115 --rocm 4

需要 watcher 在另一邊（Claude / 人）讀圖並寫 answer 檔。
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True)
    ap.add_argument("--hs", required=True, help="HS code, 8-digit, e.g. 87120010")
    ap.add_argument("--rocy", required=True, help="ROC year, e.g. 115")
    ap.add_argument("--rocm", required=True, help="month, e.g. 4")
    ap.add_argument("--end-rocy", default=None)
    ap.add_argument("--end-rocm", default=None)
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for captcha answer")
    args = ap.parse_args()

    end_y = args.end_rocy or args.rocy
    end_m = args.end_rocm or args.rocm

    out_dir = ROOT / "data" / "raw" / args.week
    out_dir.mkdir(parents=True, exist_ok=True)
    captcha_img = out_dir / "captcha-live.png"
    answer_file = out_dir / "captcha-answer.txt"
    answer_file.unlink(missing_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="zh-TW", ignore_https_errors=True)
        page = ctx.new_page()
        page.goto("https://portal.sw.nat.gov.tw/APGA/GA31", wait_until="networkidle", timeout=30000)

        # Snap CAPTCHA
        src = page.evaluate("() => document.getElementById('captchaPic').src")
        resp = page.context.request.get(src)
        captcha_img.write_bytes(resp.body())
        print(f"CAPTCHA saved: {captcha_img.relative_to(ROOT)}")
        print(f"Now write the answer (digits only) to: {answer_file.relative_to(ROOT)}")
        print(f"Waiting up to {args.timeout}s...")

        deadline = time.time() + args.timeout
        captcha_val = ""
        while time.time() < deadline:
            if answer_file.exists():
                content = answer_file.read_text(encoding="utf-8").strip()
                if content and len(content) >= 4 and content.isdigit():
                    captcha_val = content
                    break
            time.sleep(1)

        if not captcha_val:
            print("ERROR: no CAPTCHA answer received")
            browser.close()
            sys.exit(2)

        print(f"CAPTCHA answer received: {captcha_val}")

        # Fill form
        page.locator("input#Export").check()
        page.locator("input#REPORT_TYPE_0").check()
        page.locator("select#START_YEAR").select_option(args.rocy)
        page.locator("select#END_YEAR").select_option(end_y)
        page.locator("select#START_MONTH").select_option(args.rocm)
        page.locator("select#END_MONTH").select_option(end_m)
        page.locator("input#HS_TYPE_2").check()
        # 支援多 HS：用逗號分隔或空白
        hs_value = args.hs.replace(",", " ").replace("  ", " ").strip()
        page.locator("input#goodsCodeValue").fill(hs_value)
        page.locator("input#COUNTRY_TYPE_0").check()
        page.locator("input#Statistics1").check()
        page.locator("input#EXPORT_TYPE_1").check()
        page.locator("input#checkNo").fill(captcha_val)

        # Use the official submit button (clicks check())
        page.locator("button#FORM_CHECK").click()
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        result_html = page.content()
        out_file = out_dir / f"customs-{args.hs}-{args.rocy}-{args.rocm}.html"
        out_file.write_text(result_html, encoding="utf-8")
        print(f"Saved {len(result_html)} bytes -> {out_file.relative_to(ROOT)}")

        # Quick check: does body contain "驗證碼錯誤" ?
        body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
        if "驗證碼錯誤" in body_text:
            print("✗ CAPTCHA REJECTED")
            sys.exit(3)
        if "無查詢結果" in body_text or "查無" in body_text:
            print("✓ no data for this query")
        else:
            print("✓ result page captured")

        # Clean up
        answer_file.unlink(missing_ok=True)
        browser.close()


if __name__ == "__main__":
    main()
