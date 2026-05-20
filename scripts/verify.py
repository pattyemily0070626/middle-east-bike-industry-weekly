"""把 data/raw/<week>/ 各來源 HTML 解析成結構化清單，輸出 data/processed/<week>.md。

使用方式：
    python scripts/verify.py --week 2026-W20

輸出 Markdown 內含每個來源的 article list (title / url / date / summary)
與 Drewry WCI 抽出的運價數字，供人工 review 後再餵給 render.py。

設計原則：
- 每個來源獨立 parser，一個壞掉不影響其他
- 沒抓到的欄位一律寫『—』，不模擬資料
- 連結保留原始絕對網址，方便 reviewer 點開驗證
- 不做 NLP 摘要或翻譯（避免幻覺），summary 直接取頁面上的 description/excerpt
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

# Source base URLs for converting relative links to absolute
BASE_URLS = {
    "ME-02": "https://www.ukmto.org/",
    "ME-06": "https://theloadstar.com/",
    "ME-10": "https://www.drewry.co.uk/",
    "BIKE-01A": "https://tw.stock.yahoo.com/",
    "BIKE-01B": "https://tw.stock.yahoo.com/",
    "BIKE-05": "https://www.bike-eu.com/",
    "BIKE-06": "https://www.bicycleretailer.com/",
}

# Yahoo TW Stock 公司中文標籤
YAHOO_LABELS = {
    "BIKE-01A": "Giant 巨大 (9921)",
    "BIKE-01B": "Merida 美利達 (9914)",
}


def clean_text(t: str | None) -> str:
    if not t:
        return ""
    return re.sub(r"\s+", " ", t).strip()


def absurl(href: str | None, base: str) -> str:
    if not href:
        return ""
    return urljoin(base, href)


# ============================================================
# Source parsers — return list[dict] with at minimum: title, url
# Optional: date, summary
# ============================================================

def parse_ukmto(soup: BeautifulSoup, base: str) -> list[dict]:
    """UKMTO Recent Incidents 頁面（Playwright 渲染後）。
    每個 <li class=IncidentList_incident__*> 含 title / date / details / pin colour（嚴重性）。
    """
    items = []
    inc_list = soup.find(class_=re.compile(r"IncidentList_incidentList"))
    if not inc_list:
        # 退回到舊 ContentCard（homepage 模式）
        for card in soup.find_all(class_=re.compile(r"^ContentCard_contentCard__")):
            title_el = card.find(["h1", "h2", "h3", "h4"])
            link = card.find("a", href=True)
            para = card.find("p")
            if not title_el and not link:
                continue
            items.append({
                "title": clean_text(title_el.get_text() if title_el else (link.get_text() if link else "")),
                "url": absurl(link["href"], base) if link else "",
                "date": "",
                "summary": clean_text(para.get_text()) if para else "",
                "severity": "",
            })
        return items
    for li in inc_list.find_all("li", class_=re.compile(r"IncidentList_incident__")):
        title_el = li.find(class_=re.compile(r"IncidentList_title"))
        title = clean_text(title_el.get_text()) if title_el else ""
        # pin colour (severity)
        pin = li.find(class_=re.compile(r"^Pin_pin__"))
        severity = pin.get("data-colour", "") if pin else ""
        # date in meta
        meta = li.find(class_=re.compile(r"IncidentList_meta"))
        date = ""
        if meta:
            sp = meta.find("span")
            if sp:
                date = clean_text(sp.get_text())
        details = li.find(class_=re.compile(r"IncidentList_details"))
        summary = clean_text(details.get_text()) if details else ""
        items.append({
            "title": title,
            "url": "https://www.ukmto.org/recent-incidents",
            "date": date,
            "summary": summary[:400],
            "severity": severity,
        })
    return items


def parse_loadstar(soup: BeautifulSoup, base: str) -> list[dict]:
    """The Loadstar — <article class="clear pad"> 區塊，h2 + body text 平鋪。"""
    items = []
    for art in soup.find_all("article"):
        h2 = art.find(["h2", "h3"])
        if not h2:
            continue
        # 找主文章連結（避開 /tag/、/category/）
        link_el = None
        for a in art.find_all("a", href=True):
            href = a["href"]
            if "/tag/" in href or "/category/" in href or "/author/" in href:
                continue
            if "theloadstar.com" in href or href.startswith("/"):
                link_el = a
                break
        if not link_el:
            link_el = art.find("a", href=True)
        title = clean_text(h2.get_text())
        full = clean_text(art.get_text(" ", strip=True))
        # 摘要 = 文字內容去掉標題，再去掉尾端 tag 列表（heuristic）
        excerpt = full[len(title):].strip() if full.startswith(title) else full
        # 切掉常見的尾端類別列表（Asia-Mediterranean、Asia-North Europe 等出現後就停）
        excerpt = re.split(r"\s+(?:Asia-(?:Mediterranean|North Europe|US|Europe)|Categories?:|Tags?:|Topics?:)\b", excerpt)[0]
        items.append({
            "title": title,
            "url": absurl(link_el["href"], base) if link_el else "",
            "date": "",
            "summary": excerpt[:280],
        })
    return items


def parse_drewry(soup: BeautifulSoup, base: str) -> dict:
    """Drewry WCI 頁面 — 抽出『航線 → 變化% → 美元/40ft』組合。"""
    text = soup.get_text(" ", strip=True)
    page_title = clean_text(soup.title.get_text()) if soup.title else ""

    # 抓 'Shanghai to <City> ... X% to $Y per 40ft' 與類似句式
    # 動詞：rose / jumped / increased / climbed / fell / dropped / decreased / decline
    route_pattern = re.compile(
        r"(?P<from>Shanghai|Rotterdam|Genoa|New York|Los Angeles|Hong Kong)"
        r"\s+to\s+"
        r"(?P<to>Shanghai|Rotterdam|Genoa|New York|Los Angeles|Hong Kong|Singapore|Antwerp)"
        r"[^.$]{0,80}?"
        r"(?P<verb>rose|jumped|increased|climbed|fell|dropped|decreased|declined|surged|advanced)"
        r"[^$]{0,40}?"
        r"(?P<pct>\d+(?:\.\d+)?)\s*%"
        r"[^$]{0,40}?"
        r"\$\s?(?P<usd>\d{1,2},?\d{3})",
        re.IGNORECASE,
    )
    routes = []
    seen = set()
    for m in route_pattern.finditer(text):
        key = (m.group("from").title(), m.group("to").title())
        if key in seen:
            continue
        seen.add(key)
        routes.append({
            "route": f"{m.group('from').title()} → {m.group('to').title()}",
            "direction": m.group("verb").lower(),
            "change_pct": m.group("pct") + "%",
            "price_usd_40ft": "$" + m.group("usd"),
        })

    # 也補抓「composite WCI」如 "World Container Index ... rose 8% to $2,553"
    composite = re.search(
        r"(?:World Container Index|WCI|composite)"
        r"[^$]{0,100}?"
        r"(?P<verb>rose|jumped|increased|climbed|fell|dropped|decreased|declined)"
        r"[^$]{0,40}?"
        r"(?P<pct>\d+(?:\.\d+)?)\s*%"
        r"[^$]{0,40}?"
        r"\$\s?(?P<usd>\d{1,2},?\d{3})",
        text, re.IGNORECASE,
    )
    composite_info = None
    if composite:
        composite_info = {
            "direction": composite.group("verb").lower(),
            "change_pct": composite.group("pct") + "%",
            "value_usd_40ft": "$" + composite.group("usd"),
        }

    return {
        "page_title": page_title,
        "composite": composite_info,
        "routes": routes,
    }


def parse_bike_europe(soup: BeautifulSoup, base: str) -> list[dict]:
    """Bike Europe — 11 個 .article-list-item。"""
    items = []
    for art in soup.select(".article-list-item"):
        link = art.find("a", href=True)
        title_el = art.find(["h2", "h3", "h4"]) or link
        date_el = art.find("time") or art.find(class_=re.compile(r"date|time", re.I))
        para = art.find("p")
        if not title_el:
            continue
        items.append({
            "title": clean_text(title_el.get_text()),
            "url": absurl(link["href"], base) if link else "",
            "date": clean_text(date_el.get("datetime") or date_el.get_text()) if date_el else "",
            "summary": clean_text(para.get_text()) if para else "",
        })
    return items


def parse_brain(soup: BeautifulSoup, base: str) -> list[dict]:
    """Bicycle Retailer & Industry News (Drupal — view-news / article-meta)。"""
    items = []
    # BRAIN 的文章通常在 .views-row 或 article 下
    rows = soup.select(".views-row") or soup.select("article") or soup.select(".view-content .item")
    for row in rows:
        title_el = row.find(["h2", "h3"])
        link = (title_el.find("a", href=True) if title_el else None) or row.find("a", href=True)
        date_el = row.find("time") or row.find(class_=re.compile(r"date|time", re.I))
        summary_el = row.find("p") or row.find(class_=re.compile(r"summary|teaser|body|field--name-body", re.I))
        if not title_el and not link:
            continue
        items.append({
            "title": clean_text((title_el or link).get_text()),
            "url": absurl(link["href"], base) if link else "",
            "date": clean_text(date_el.get_text()) if date_el else "",
            "summary": clean_text(summary_el.get_text()) if summary_el else "",
        })
    # 過濾標題太短的（避免抓到 nav）
    items = [x for x in items if len(x["title"]) > 8]
    return items


def parse_yahoo_revenue(soup: BeautifulSoup, base: str) -> list[dict]:
    """Yahoo 股市月營收頁面 — 抓最近月份的營收 / MoM / YoY。
    欄位順序：年/月 月營收 月增率 去年同月 年增率 累計營收 去年累計 累計年增率
    回傳近 6 個月（最新在前）。
    """
    text = soup.get_text(" ", strip=True)
    # 8 個欄位：YYYY/MM rev mom% prev_yr_rev yoy% cum prev_yr_cum cum_yoy%
    pat = re.compile(
        r"(20\d{2}/\d{2})\s+([\d,]+)\s+(-?[\d.]+%)\s+([\d,]+)\s+(-?[\d.]+%)\s+([\d,]+)\s+([\d,]+)\s+(-?[\d.]+%)"
    )
    items = []
    for m in pat.finditer(text):
        items.append({
            "ym": m.group(1),
            "revenue_kntd": m.group(2),   # 千元
            "mom_pct": m.group(3),
            "prev_yr_revenue": m.group(4),
            "yoy_pct": m.group(5),
            "cum_revenue": m.group(6),
            "cum_yoy_pct": m.group(8),
        })
        if len(items) >= 6:
            break
    return items


PARSERS = {
    "ME-02": parse_ukmto,
    "ME-06": parse_loadstar,
    "BIKE-05": parse_bike_europe,
    "BIKE-06": parse_brain,
}

YAHOO_PARSERS = {
    "BIKE-01A": parse_yahoo_revenue,
    "BIKE-01B": parse_yahoo_revenue,
}


# ============================================================
# Markdown 輸出
# ============================================================

def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def render_items_md(items: list[dict], max_items: int = 15) -> str:
    if not items:
        return "（無項目）"
    lines = []
    for i, it in enumerate(items[:max_items], 1):
        title = md_escape(it["title"]) or "（無標題）"
        url = it.get("url") or ""
        date = it.get("date") or "—"
        summary = md_escape(it.get("summary") or "")[:280]
        severity = it.get("severity") or ""
        link = f"[{title}]({url})" if url else title
        sev_tag = f" [{severity}]" if severity else ""
        lines.append(f"{i}.{sev_tag} {link}")
        lines.append(f"   - 日期：{date}")
        if summary:
            lines.append(f"   - 摘要：{summary}")
    if len(items) > max_items:
        lines.append(f"\n_（共 {len(items)} 項，僅顯示前 {max_items}）_")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--week", required=True)
    args = p.parse_args()

    raw_dir = ROOT / "data" / "raw" / args.week
    if not raw_dir.exists():
        sys.exit(f"raw dir not found: {raw_dir}")

    out_path = ROOT / "data" / "processed" / f"{args.week}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []
    sections.append(f"# Bike Weekly · {args.week} · 解析結果（人工 review 用）\n")
    sections.append(f"_產出時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")
    sections.append("> 此檔為原始抓取資料的結構化摘錄，**未經查證**。Review 後選擇要納入週報的項目，再餵 render.py。\n")

    # Source-specific parsing
    counts: dict[str, int] = {}
    for sid, parser in PARSERS.items():
        ext = "html"
        f = raw_dir / f"{sid}.{ext}"
        if not f.exists():
            sections.append(f"\n## {sid}\n\n（未找到原始檔 {f.name}）\n")
            continue
        html = f.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        try:
            items = parser(soup, BASE_URLS[sid])
        except Exception as e:
            sections.append(f"\n## {sid}\n\n**解析失敗**：{type(e).__name__}: {e}\n")
            continue
        counts[sid] = len(items)
        sections.append(f"\n## {sid} — {f.name} （{len(items)} 項）\n")
        sections.append(render_items_md(items))
        sections.append("")

    # Yahoo TW Stock 月營收（Giant 9921 / Merida 9914）
    for sid, parser in YAHOO_PARSERS.items():
        f = raw_dir / f"{sid}.html"
        if not f.exists():
            continue
        soup = BeautifulSoup(f.read_text(encoding="utf-8", errors="replace"), "lxml")
        try:
            rows = parser(soup, BASE_URLS[sid])
        except Exception as e:
            sections.append(f"\n## {sid} — Yahoo 解析失敗\n\n{type(e).__name__}: {e}\n")
            continue
        label = YAHOO_LABELS.get(sid, sid)
        sections.append(f"\n## {sid} — {label} 月營收（Yahoo TW Stock，{len(rows)} 個月）\n")
        if not rows:
            sections.append("（未抓到月度資料）")
        else:
            sections.append("| 年/月 | 月營收 (千元) | MoM% | 年增率 (YoY%) | 累計營收 (千元) | 累計 YoY% |")
            sections.append("|---|---:|---:|---:|---:|---:|")
            for r in rows:
                sections.append(
                    f"| {r['ym']} | {r['revenue_kntd']} | {r['mom_pct']} | {r['yoy_pct']} | {r['cum_revenue']} | {r['cum_yoy_pct']} |"
                )
        counts[sid] = len(rows)
        sections.append("")

    # Drewry — 特殊處理
    drewry_file = raw_dir / "ME-10.html"
    if drewry_file.exists():
        soup = BeautifulSoup(drewry_file.read_text(encoding="utf-8", errors="replace"), "lxml")
        try:
            d = parse_drewry(soup, BASE_URLS["ME-10"])
        except Exception as e:
            d = {"error": f"{type(e).__name__}: {e}"}
        sections.append("\n## ME-10 — Drewry WCI 抽出\n")
        sections.append(f"- 頁面標題：{d.get('page_title','—')}")
        if d.get("composite"):
            c = d["composite"]
            sections.append(f"- **WCI 綜合指數**：{c['direction']} {c['change_pct']} → {c['value_usd_40ft']} /40ft")
        else:
            sections.append("- **WCI 綜合指數**：未直接抓到（請查頁面正文）")
        sections.append("\n### 主要航線運價變化\n")
        routes = d.get("routes", [])
        if routes:
            sections.append("| 航線 | 變化 | 本週運價 (USD/40ft) |")
            sections.append("|---|---|---|")
            for r in routes:
                sections.append(f"| {r['route']} | {r['direction']} {r['change_pct']} | {r['price_usd_40ft']} |")
        else:
            sections.append("（未抓到航線變化句式）")
        sections.append(f"\n- 來源連結：[Drewry WCI]({BASE_URLS['ME-10']}supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry)\n")
        counts["ME-10"] = len(routes)

    # 統計
    sections.append("\n---\n## 解析統計\n")
    for sid in ("ME-02", "ME-06", "ME-10", "BIKE-05", "BIKE-06"):
        sections.append(f"- {sid}: {counts.get(sid, '—')} 項")

    out_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"OK: {out_path.relative_to(ROOT)}")
    print(f"Counts: {counts}")


if __name__ == "__main__":
    main()
