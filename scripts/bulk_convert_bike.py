#!/usr/bin/env python3
"""
Bulk-convert all bike-weekly-*.md in md_report/ into HTML using the
bike-weekly template. Build a manifest sorted newest-to-oldest, then for
each snapshot inject an archive that excludes itself; copy the newest
snapshot to index.html.

Markdown format expected per file (see md_report/bike-weekly-2026-W20.md):
  # 中東情勢產業週報 · 自行車產業 — 2026-W## (YYYY年M月D日)
  ## 產業風險指標         (table: 指標 / 評估; 3 rows)
  **評估依據**：...        (ASSESSMENT_TEXT)
  ## 摘要                 (SUMMARY_TEXT)
  ## 01 中東事件 → 自行車產業傳導   (table, 7 cols → TABLE1_ROWS)
  ## 02 主要廠商動態與營運訊號       (table, 7 cols → TABLE2_ROWS)
  ## 03 戰略意涵           (bullet list → IMPLICATIONS_ITEMS)
  ## 04 出口與運價快照     (table, 6 cols → TABLE3_ROWS  ← legacy token name)
  ## 05 資料來源           (numbered list → SOURCES_ITEMS)
"""
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent  # scripts/ → repo root
MD_DIR = BASE / "md_report"
HTML_DIR = BASE / "html_report_archive"
HTML_SITE_PREFIX = "/html_report_archive"
TEMPLATE = BASE / ".claude/commands/bike-weekly-template.html"

INDUSTRY_LABEL = "自行車產業"
INDUSTRY_BRANCH_TAG = "BICYCLE INDUSTRY"

# 指標值 → CSS 類別（red / amber / green）
INDICATOR_CLASS_MAP = {
    # 紅海航運風險
    "高": "red", "中": "amber", "低": "green",
    # WCI 運價走勢
    "上升": "red", "持平": "amber", "下降": "green",
    # 自行車出口動能
    "疲弱": "red", "弱": "red", "強": "green",
}


def md_inline(s: str) -> str:
    """
    把行內 markdown 轉 HTML。注意：**不做 html.escape**，允許作者寫 inline HTML
    （如 <span class="data">…</span>、<em>…</em>、<br>），方便保留來源註解、警語等格式。
    報告 markdown 進 git 前會 review，並非外部使用者輸入，故安全考量可接受。
    """
    s = s.strip()
    # Markdown 連結 → <a>（先做，避免 [link](url) 內的 ** 被優先處理錯）
    s = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        s,
    )
    # Markdown **bold** → <strong>
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def parse_md_table_rows(body: str) -> list[list[str]]:
    """從 markdown table 區塊抽出資料列（跳過 header + ---|---|---|分隔線）。"""
    lines = [l.strip() for l in body.split("\n") if l.strip().startswith("|")]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells if c):
            continue
        rows.append(cells)
    return rows


def parse_file(md_path: pathlib.Path) -> dict:
    txt = md_path.read_text(encoding="utf-8")
    name = md_path.stem  # e.g., bike-weekly-2026-W20

    m = re.match(r"bike-weekly-(\d{4})-W(\d{2})$", name)
    if not m:
        raise ValueError(
            f"Filename must match bike-weekly-YYYY-W##.md, got: {name}"
        )
    year, week = m.group(1), m.group(2)
    week_iso = f"{year}-W{week}"

    # 從 H1 抽出日期 — 例如「— 2026-W20 (2026年5月15日)」
    date_full = ""
    date_iso = ""
    h1 = re.search(r"^#\s+.+$", txt, re.MULTILINE)
    if h1:
        d = re.search(r"\((\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\)", h1.group(0))
        if d:
            y, mo, dy = d.group(1), d.group(2).zfill(2), d.group(3).zfill(2)
            date_iso = f"{y}-{mo}-{dy}"
            date_full = f"{int(y)} 年 {int(mo)} 月 {int(dy)} 日"
    if not date_iso:
        # fallback：用 ISO 週起算（W 第 1 天，週一）— 估算
        from datetime import date, timedelta
        jan4 = date(int(year), 1, 4)  # ISO 8601 第一週一定包含 1/4
        week1_monday = jan4 - timedelta(days=jan4.weekday())
        target = week1_monday + timedelta(weeks=int(week) - 1)
        date_iso = target.isoformat()
        date_full = f"{target.year} 年 {target.month} 月 {target.day} 日"

    # 指標表
    def find_indicator(label_keyword: str, default="—") -> str:
        m = re.search(
            r"\|\s*[^|]*?" + re.escape(label_keyword) + r"[^|]*?\|\s*([^|]+?)\s*\|",
            txt,
        )
        return m.group(1).strip() if m else default

    # 接受「中東航運風險」（新）與「紅海航運風險」（舊）兩種寫法
    redsea = find_indicator("中東航運風險")
    if redsea == "—":
        redsea = find_indicator("紅海航運風險")
    freight = find_indicator("WCI")  # 任何含 WCI 都符合
    export_ = find_indicator("自行車出口動能")

    def indicator_class(value: str) -> str:
        for k, cls in INDICATOR_CLASS_MAP.items():
            if k in value:
                return cls
        return "amber"

    # 評估依據（指標表後、## 摘要 前的文字）
    assessment = ""
    ass_match = re.search(
        r"\*\*評估依據\*\*\s*[:：]\s*(.+?)(?=\n##|\n---|\Z)",
        txt,
        re.DOTALL,
    )
    if ass_match:
        assessment = ass_match.group(1).strip()

    # 摘要
    summary = ""
    sm = re.search(
        r"##\s*摘要\s*\n+(.*?)(?=\n##|\n---|\Z)",
        txt,
        re.DOTALL | re.MULTILINE,
    )
    if sm:
        summary = sm.group(1).strip()

    def grab(pat: str) -> str:
        m = re.search(
            pat + r"\n+(.*?)(?=\n##\s|\n---\s*\n|\Z)",
            txt,
            re.DOTALL | re.MULTILINE,
        )
        return m.group(1) if m else ""

    t1 = parse_md_table_rows(grab(r"##\s*01\b[^\n]*"))
    t2 = parse_md_table_rows(grab(r"##\s*02\b[^\n]*"))
    t3 = parse_md_table_rows(grab(r"##\s*04\b[^\n]*"))  # 表 04 出口與運價 → TABLE3_ROWS

    # 戰略意涵 bullet
    imp_body = grab(r"##\s*03\b[^\n]*")
    implications = []
    for m in re.finditer(
        r"(?:^|\n)\s*-\s+(.+?)(?=\n\s*-\s|\n\s*\n|\Z)", imp_body, re.DOTALL
    ):
        implications.append(m.group(1).strip().replace("\n", " "))

    # 資料來源 numbered
    src_match = re.search(
        r"##\s*05\b[^\n]*\n+(.*?)(?=\n##\s|\n---\s*\n|\Z)",
        txt,
        re.DOTALL | re.MULTILINE,
    )
    sources = []
    if src_match:
        for m in re.finditer(
            r"(?:^|\n)\s*\d+\.\s+(.+?)(?=\n\s*\d+\.|\Z)",
            src_match.group(1),
            re.DOTALL,
        ):
            sources.append(m.group(1).strip().replace("\n", " "))

    # 短標題（manifest 用）— 從 ASSESSMENT 第一句
    src = assessment or summary or ""
    first = re.split(r"[。.；;]", src, maxsplit=1)[0].strip()
    if len(first) > 60:
        first = first[:60] + "…"
    short_title = first or f"{week_iso} 自行車產業週報"

    return {
        "md_path": md_path,
        "week_iso": week_iso,
        "date_iso": date_iso,
        "date_full": date_full,
        "redsea": redsea,
        "freight": freight,
        "export": export_,
        "ind_cls_redsea": indicator_class(redsea),
        "ind_cls_freight": indicator_class(freight),
        "ind_cls_export": indicator_class(export_),
        "assessment": assessment,
        "summary": summary,
        "t1": t1, "t2": t2, "t3": t3,
        "implications": implications,
        "sources": sources,
        "short_title": short_title,
    }


# --- Row generators ---------------------------------------------------------

def row_t1(r: list[str]) -> str:
    """表 01：# | 類別 | 重要性 | 事件 | 重點摘要 | 對自行車業傳導 | 來源 (7 cols)"""
    while len(r) < 7:
        r.append("")
    num, kind, importance, event, summary, impact, source = r[:7]
    dcls = "dir-red" if ("🔴" in kind or "⛽" in kind) else \
           "dir-green" if "🟢" in kind else "dir-neutral"
    if "重大" in importance or "Major" in importance:
        imp_cls, imp_text = "badge-major", "重大"
    else:
        imp_cls, imp_text = "badge-medium", "中等"
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f'            <td class="{dcls}">{md_inline(kind)}</td>\n'
        f'            <td><span class="badge {imp_cls}">{imp_text}</span></td>\n'
        f"            <td>{md_inline(event)}</td>\n"
        f"            <td>{md_inline(summary)}</td>\n"
        f"            <td>{md_inline(impact)}</td>\n"
        f"            <td>{md_inline(source)}</td>\n"
        "          </tr>"
    )


def row_t2(r: list[str]) -> str:
    """表 02：# | 廠商 | 類別 | 最新數據 | 週/月變化 | 與中東情勢關聯 | 來源 (7 cols)"""
    while len(r) < 7:
        r.append("")
    num, company, category, data, change, link, source = r[:7]
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f"            <td>{md_inline(company)}</td>\n"
        f"            <td>{md_inline(category)}</td>\n"
        f"            <td>{md_inline(data)}</td>\n"
        f"            <td>{md_inline(change)}</td>\n"
        f"            <td>{md_inline(link)}</td>\n"
        f"            <td>{md_inline(source)}</td>\n"
        "          </tr>"
    )


def row_t3(r: list[str]) -> str:
    """表 04（內部 token 仍叫 TABLE3）：# | 指標 | 本期 | 上期 | 變化 | 來源 (6 cols)"""
    while len(r) < 6:
        r.append("")
    num, indicator, this_period, prev_period, change, source = r[:6]
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f"            <td>{md_inline(indicator)}</td>\n"
        f"            <td>{md_inline(this_period)}</td>\n"
        f"            <td>{md_inline(prev_period)}</td>\n"
        f"            <td>{md_inline(change)}</td>\n"
        f"            <td>{md_inline(source)}</td>\n"
        "          </tr>"
    )


def render(entry: dict, archive: list[dict], logo_path: str = "assets/aiez-logo.png") -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")

    t1_rows = "\n".join(row_t1(r) for r in entry["t1"]) or \
        '          <tr><td colspan="7" style="text-align:center; color:var(--text-tertiary);">無事件資料</td></tr>'
    t2_rows = "\n".join(row_t2(r) for r in entry["t2"]) or \
        '          <tr><td colspan="7" style="text-align:center; color:var(--text-tertiary);">無廠商資料</td></tr>'
    t3_rows = "\n".join(row_t3(r) for r in entry["t3"]) or \
        '          <tr><td colspan="6" style="text-align:center; color:var(--text-tertiary);">無指標資料</td></tr>'

    imp_html = "\n".join(f"      <li>{md_inline(i)}</li>" for i in entry["implications"]) or \
               '      <li style="color:var(--text-tertiary);">無戰略意涵</li>'
    src_html = "\n".join(f"      <li>{md_inline(s)}</li>" for s in entry["sources"]) or \
               '      <li style="color:var(--text-tertiary);">無資料來源</li>'

    subs = {
        "{{DATE_FULL}}": entry["date_full"],
        "{{DATE_ISO}}": entry["date_iso"],
        "{{WEEK_ISO}}": entry["week_iso"],
        "{{INDUSTRY_LABEL}}": INDUSTRY_LABEL,
        "{{INDUSTRY_BRANCH_TAG}}": INDUSTRY_BRANCH_TAG,
        "{{INDICATOR_REDSEA}}": entry["redsea"],
        "{{INDICATOR_FREIGHT}}": entry["freight"],
        "{{INDICATOR_EXPORT}}": entry["export"],
        "{{INDICATOR_CLASS_REDSEA}}": entry["ind_cls_redsea"],
        "{{INDICATOR_CLASS_FREIGHT}}": entry["ind_cls_freight"],
        "{{INDICATOR_CLASS_EXPORT}}": entry["ind_cls_export"],
        "{{ASSESSMENT_TEXT}}": md_inline(entry["assessment"]),
        "{{SUMMARY_TEXT}}": md_inline(entry["summary"]),
        "{{TABLE1_ROWS}}": t1_rows,
        "{{TABLE2_ROWS}}": t2_rows,
        "{{TABLE3_ROWS}}": t3_rows,
        "{{IMPLICATIONS_ITEMS}}": imp_html,
        "{{SOURCES_ITEMS}}": src_html,
        "{{LOGO_PATH}}": logo_path,
        # Script-safe JSON：跳脫 </ 避免 archive 內容意外結束 <script>
        "{{ARCHIVE_ITEMS_JSON}}": json.dumps(archive, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)

    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", tpl)
    if leftover:
        print(f"LEFTOVER in {entry['week_iso']}: {leftover}", file=sys.stderr)
        sys.exit(1)
    return tpl


def main():
    md_files = sorted(MD_DIR.glob("bike-weekly-*.md"))
    if not md_files:
        print(f"No MD files found under {MD_DIR}.")
        return

    HTML_DIR.mkdir(parents=True, exist_ok=True)

    entries = [parse_file(p) for p in md_files]
    # 由新到舊（ISO 週標籤字串排序即可）
    entries.sort(key=lambda e: e["week_iso"], reverse=True)

    # manifest
    manifest = [{
        "date": e["date_iso"],
        "day": e["week_iso"],  # 漢堡選單以週標籤顯示
        "title": e["short_title"],
        "href": f"{HTML_SITE_PREFIX}/bike-weekly-{e['week_iso']}.html",
        "ind": e["ind_cls_redsea"],  # 用紅海風險顏色當主指標
        "label": e["redsea"],
        "ts": e["week_iso"],
    } for e in entries]

    BASE.joinpath("briefs-manifest.json").write_text(
        json.dumps([{k: v for k, v in m.items() if k != "ts"} for m in manifest],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def clean(m):
        return {k: v for k, v in m.items() if k != "ts"}

    for e in entries:
        self_href = f"{HTML_SITE_PREFIX}/bike-weekly-{e['week_iso']}.html"
        archive = [clean(m) for m in manifest if m["href"] != self_href]
        # archive 頁在 /html_report_archive/，logo 要往上一層找
        html_out = render(e, archive, logo_path="../assets/aiez-logo.png")
        out_path = HTML_DIR / f"bike-weekly-{e['week_iso']}.html"
        out_path.write_text(html_out, encoding="utf-8")
        print(f"Wrote: {out_path.relative_to(BASE)} ({len(html_out):,} chars)")

    # index.html = 最新（archive 排除自己）
    newest = entries[0]
    newest_archive = [clean(m) for m in manifest[1:]]
    index_html = render(newest, newest_archive, logo_path="assets/aiez-logo.png")
    (BASE / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\nindex.html ← newest ({newest['week_iso']})")
    print(f"Total entries: {len(manifest)}")


if __name__ == "__main__":
    main()
