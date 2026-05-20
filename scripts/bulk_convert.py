#!/usr/bin/env python3
"""
Bulk-convert all middle-east-brief-*.md in the working directory into HTML
using the aieztrade template. Build a manifest sorted newest-to-oldest, then
for each snapshot inject an archive that excludes itself; copy the newest
snapshot to index.html.
"""
import datetime
import html
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent  # scripts/ → repo root
MD_DIR = BASE / "md_report"
HTML_DIR = BASE / "html_report_archive"
HTML_SITE_PREFIX = "/html_report_archive"  # site-absolute prefix used in manifest hrefs
TEMPLATE = BASE / ".claude/commands/middle-east-analysis-template-aieztrade.html"
WAR_START = datetime.date(2026, 3, 1)  # Day 1 = 2026-03-01


def normalize_level(s: str) -> str:
    return (s.replace("High", "高")
             .replace("Medium", "中")
             .replace("Low", "低")
             .strip())


def md_inline(s: str) -> str:
    """Minimal markdown-inline → HTML conversion."""
    s = html.escape(s.strip(), quote=True)
    # Links first so **bold** inside link text still works afterwards
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def parse_md_table_rows(body: str) -> list[list[str]]:
    """Extract data rows (skipping header + separator) from a markdown table section."""
    lines = [l.strip() for l in body.split("\n") if l.strip().startswith("|")]
    rows = []
    for line in lines[2:]:  # skip header + ---|---| separator
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # Skip accidental separator lines
        if all(set(c) <= set("-: ") for c in cells if c):
            continue
        rows.append(cells)
    return rows


def parse_file(md_path: pathlib.Path) -> dict:
    txt = md_path.read_text(encoding="utf-8")
    stat = md_path.stat()
    name = md_path.stem

    # Timestamp / date from filename — require canonical YYYYMMDD-HHMMSS form.
    # Filenames like middle-east-brief-YYYY-MM-DD.md (no HHMMSS) are rejected
    # because mtime-synthesized timestamps produce non-reproducible output
    # names and break md/html stem alignment.
    m = re.match(r"middle-east-brief-(\d{8})-(\d{6})$", name)
    if not m:
        raise ValueError(
            f"Missing HHMMSS in filename: {name}. "
            f"Rename to middle-east-brief-YYYYMMDD-HHMMSS.md."
        )
    ymd, hms = m.groups()
    ts = f"{ymd}-{hms}"
    date_iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"

    yy, mm, dd = date_iso.split("-")
    date_full = f"{int(yy)}年{int(mm)}月{int(dd)}日"
    day_num = (datetime.date(int(yy), int(mm), int(dd)) - WAR_START).days + 1
    day_count = f"DAY {day_num}"
    day_label = f"Day {day_num}"

    # Indicators
    ind_row = re.search(r"整體衝突[^|]*\|\s*([^|]+?)\s*\|", txt)
    esc_row = re.search(r"未來\s*7\s*[日天]升級[^|]*\|\s*([^|]+?)\s*\|", txt)
    spill_row = re.search(r"區域外溢風險[^|]*\|\s*([^|]+?)\s*\|", txt)
    conflict_raw = ind_row.group(1).strip() if ind_row else "🔴 升級"
    escalation = normalize_level(esc_row.group(1).strip() if esc_row else "高")
    spillover = normalize_level(spill_row.group(1).strip() if spill_row else "高")

    # Conflict direction
    if "🔴" in conflict_raw:
        label = conflict_raw.replace("🔴", "").strip() or "升級"
        # Drop verbose tails like "持續升級" → "升級" for chip brevity, but keep full for display
        conflict = f"🔴 {label}"
        ind_cls_conflict = "red"
        ind_tag, label_tag = "red", label
    elif "🟢" in conflict_raw:
        label = conflict_raw.replace("🟢", "").strip() or "趨緩"
        conflict = f"🟢 {label}"
        ind_cls_conflict = "green"
        ind_tag, label_tag = "green", label
    elif "⚪" in conflict_raw:
        label = conflict_raw.replace("⚪", "").strip() or "持平"
        conflict = f"⚪ {label}"
        ind_cls_conflict = "amber"
        ind_tag, label_tag = "amber", label
    else:
        conflict = conflict_raw
        ind_cls_conflict = "amber"
        ind_tag, label_tag = "amber", conflict_raw.strip()

    level_to_cls = {"高": "red", "中": "amber", "低": "green"}
    ind_cls_esc = level_to_cls.get(escalation, "amber")
    ind_cls_spill = level_to_cls.get(spillover, "amber")

    # Assessment text
    ass = re.search(r"\*\*評估(?:依據|說明)\s*[:：]\*\*\s*(.*?)(?=\n\s*---|\n\s*##)",
                    txt, re.DOTALL)
    if ass:
        assessment = ass.group(1).strip()
    else:
        tbl_end = re.search(r"\|\s*區域外溢[^\n]*\n", txt)
        if tbl_end:
            after = txt[tbl_end.end():]
            nxt = re.search(r"\n---|\n##", after)
            assessment = (after[:nxt.start()] if nxt else after).strip()
        else:
            assessment = ""
    # Strip bold leader like "**評估說明**：" if it remained
    assessment = re.sub(r"^\*\*[^*]+\*\*\s*[:：]?\s*", "", assessment).strip()
    assessment = normalize_level(assessment)

    # Summary
    sm = re.search(r"##\s*(?:執行)?摘要\s*\n+(.*?)(?=\n##|\n---\s*$|\Z)",
                   txt, re.DOTALL | re.MULTILINE)
    summary = sm.group(1).strip() if sm else ""
    summary = re.sub(r"\n---\s*$", "", summary).strip()

    # Tables — grab body text of each section
    def grab(pat):
        m = re.search(pat + r"\n+(.*?)(?=\n##|\n---\s*\n|\Z)",
                      txt, re.DOTALL | re.MULTILINE)
        return m.group(1) if m else ""
    t1 = parse_md_table_rows(grab(r"##\s*表一[^\n]*"))
    t2 = parse_md_table_rows(grab(r"##\s*表二[^\n]*"))
    t3 = parse_md_table_rows(grab(r"##\s*表三[^\n]*"))

    # Implications bullets — handle both "- " and "1. / 2. / 3." styles
    imp_body = grab(r"##\s*戰略意涵")
    implications = []
    # Try dash-bullet style first
    for m in re.finditer(r"(?:^|\n)\s*-\s+(.+?)(?=\n\s*-\s|\n\s*\n|\Z)",
                         imp_body, re.DOTALL):
        implications.append(m.group(1).strip().replace("\n", " "))
    # Fall back to numbered style if no dash bullets found
    if not implications:
        for m in re.finditer(r"(?:^|\n)\s*\d+\.\s+(.+?)(?=\n\s*\d+\.\s|\n\s*\n|\Z)",
                             imp_body, re.DOTALL):
            implications.append(m.group(1).strip().replace("\n", " "))

    # Sources — handle both "- " and "1. / 2. ..." styles
    src_body_match = re.search(r"##\s*(?:資料來源|Sources)\s*\n+(.*?)\Z",
                               txt, re.DOTALL)
    sources = []
    if src_body_match:
        src_body = src_body_match.group(1)
        for m in re.finditer(r"(?:^|\n)\s*-\s+(.+?)(?=\n\s*-|\Z)",
                             src_body, re.DOTALL):
            sources.append(m.group(1).strip().replace("\n", " "))
        if not sources:
            for m in re.finditer(r"(?:^|\n)\s*\d+\.\s+(.+?)(?=\n\s*\d+\.|\Z)",
                                 src_body, re.DOTALL):
                sources.append(m.group(1).strip().replace("\n", " "))

    # Short title for manifest — first sentence of assessment or summary
    src = assessment or summary or ""
    first = re.split(r"[。.！!；;]", src, maxsplit=1)[0].strip()
    if len(first) > 55:
        first = first[:55] + "…"
    short_title = first or f"{date_full} 情報簡報"

    return {
        "md_path": md_path,
        "ts": ts,
        "date_iso": date_iso,
        "date_full": date_full,
        "day_count": day_count,
        "day_label": day_label,
        "conflict": conflict,
        "escalation": escalation,
        "spillover": spillover,
        "ind_cls_conflict": ind_cls_conflict,
        "ind_cls_esc": ind_cls_esc,
        "ind_cls_spill": ind_cls_spill,
        "ind_tag": ind_tag,
        "label_tag": label_tag,
        "assessment": assessment,
        "summary": summary,
        "t1": t1, "t2": t2, "t3": t3,
        "implications": implications,
        "sources": sources,
        "short_title": short_title,
    }


# --- Row generators ---------------------------------------------------------

def row_t1(r: list[str]) -> str:
    while len(r) < 7:
        r.append("")
    num, direction, importance, source, event, summary, impact = r[:7]
    dcls = "dir-red" if "🔴" in direction else \
           "dir-green" if "🟢" in direction else "dir-neutral"
    if "Major" in importance or "重大" in importance:
        imp_cls, imp_text = "badge-major", "重大"
    else:
        imp_cls, imp_text = "badge-medium", "中等"
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f'            <td class="{dcls}">{direction}</td>\n'
        f'            <td><span class="badge {imp_cls}">{imp_text}</span></td>\n'
        f"            <td>{md_inline(source)}</td>\n"
        f"            <td>{md_inline(event)}</td>\n"
        f"            <td>{md_inline(summary)}</td>\n"
        f"            <td>{md_inline(impact)}</td>\n"
        "          </tr>"
    )


def row_t2(r: list[str]) -> str:
    while len(r) < 8:
        r.append("")
    num, actor, mil, mil24, civ, civ24, tot, force = r[:8]
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f"            <td>{md_inline(actor)}</td>\n"
        f"            <td>{md_inline(mil)}</td>\n"
        f"            <td>{md_inline(mil24)}</td>\n"
        f"            <td>{md_inline(civ)}</td>\n"
        f"            <td>{md_inline(civ24)}</td>\n"
        f"            <td>{md_inline(tot)}</td>\n"
        f"            <td>{md_inline(force)}</td>\n"
        "          </tr>"
    )


def row_t3(r: list[str]) -> str:
    while len(r) < 8:
        r.append("")
    num, country, total, navy, miss, fight, d24, src = r[:8]
    return (
        "          <tr>\n"
        f"            <td>{num}</td>\n"
        f"            <td>{md_inline(country)}</td>\n"
        f"            <td>{md_inline(total)}</td>\n"
        f"            <td>{md_inline(navy)}</td>\n"
        f"            <td>{md_inline(miss)}</td>\n"
        f"            <td>{md_inline(fight)}</td>\n"
        f"            <td>{md_inline(d24)}</td>\n"
        f"            <td>{md_inline(src)}</td>\n"
        "          </tr>"
    )


def render(entry: dict, archive: list[dict]) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")

    t1_rows = "\n".join(row_t1(r) for r in entry["t1"]) or \
              '          <tr><td colspan="7" style="text-align:center; color:var(--text-tertiary);">無表格資料</td></tr>'
    t2_rows = "\n".join(row_t2(r) for r in entry["t2"]) or \
              '          <tr><td colspan="8" style="text-align:center; color:var(--text-tertiary);">無表格資料</td></tr>'
    t3_rows = "\n".join(row_t3(r) for r in entry["t3"]) or \
              '          <tr><td colspan="8" style="text-align:center; color:var(--text-tertiary);">無表格資料</td></tr>'

    imp_html = "\n".join(f"      <li>{md_inline(i)}</li>" for i in entry["implications"]) or \
               '      <li style="color:var(--text-tertiary);">無戰略意涵資料</li>'
    src_html = "\n".join(f"      <li>{md_inline(s)}</li>" for s in entry["sources"]) or \
               '      <li style="color:var(--text-tertiary);">無資料來源</li>'

    subs = {
        "{{DATE_FULL}}": entry["date_full"],
        "{{DATE_ISO}}": entry["date_iso"],
        "{{DAY_COUNT}}": entry["day_count"],
        "{{WAR_SUBTITLE}}": "美以對伊朗戰爭",
        "{{INDICATOR_CONFLICT}}": entry["conflict"],
        "{{INDICATOR_ESCALATION}}": entry["escalation"],
        "{{INDICATOR_SPILLOVER}}": entry["spillover"],
        "{{INDICATOR_CLASS_CONFLICT}}": entry["ind_cls_conflict"],
        "{{INDICATOR_CLASS_ESCALATION}}": entry["ind_cls_esc"],
        "{{INDICATOR_CLASS_SPILLOVER}}": entry["ind_cls_spill"],
        "{{ASSESSMENT_TEXT}}": md_inline(entry["assessment"]),
        "{{SUMMARY_TEXT}}": md_inline(entry["summary"]),
        "{{TABLE1_ROWS}}": t1_rows,
        "{{TABLE2_ROWS}}": t2_rows,
        "{{TABLE3_ROWS}}": t3_rows,
        "{{IMPLICATIONS_ITEMS}}": imp_html,
        "{{SOURCES_ITEMS}}": src_html,
        # Script-safe JSON: escape `</` so no archive item can break out of
        # the enclosing <script> tag by injecting `</script>`.
        "{{ARCHIVE_ITEMS_JSON}}": json.dumps(archive, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", tpl)
    if leftover:
        print(f"LEFTOVER in {entry['ts']}: {leftover}", file=sys.stderr)
        sys.exit(1)
    return tpl


def main():
    md_files = sorted(MD_DIR.glob("middle-east-brief-*.md"))
    if not md_files:
        print(f"No MD files found under {MD_DIR}.")
        return

    HTML_DIR.mkdir(parents=True, exist_ok=True)

    entries = [parse_file(p) for p in md_files]
    # Sort by timestamp descending (newest first)
    entries.sort(key=lambda e: e["ts"], reverse=True)

    # Manifest: full list of metadata (for hamburger menu).
    # href is site-absolute so the same entry works from index.html (at site root)
    # and from each snapshot inside html_report_archive/.
    manifest = [{
        "date": e["date_iso"],
        "day": e["day_label"],
        "title": e["short_title"],
        "href": f"{HTML_SITE_PREFIX}/middle-east-brief-{e['ts']}.html",
        "ind": e["ind_tag"],
        "label": e["label_tag"],
        "ts": e["ts"],  # helper field for sorting; removed before injection
    } for e in entries]

    BASE.joinpath("briefs-manifest.json").write_text(
        json.dumps([{k: v for k, v in m.items() if k != "ts"} for m in manifest],
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    def clean(m):
        return {k: v for k, v in m.items() if k != "ts"}

    # For each entry, render its snapshot HTML with archive = manifest minus self
    for e in entries:
        self_href = f"{HTML_SITE_PREFIX}/middle-east-brief-{e['ts']}.html"
        archive = [clean(m) for m in manifest if m["href"] != self_href]
        html = render(e, archive)
        out_path = HTML_DIR / f"middle-east-brief-{e['ts']}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"Wrote: {out_path.relative_to(BASE)} ({len(html):,} chars)")

    # index.html = newest snapshot with its own archive-minus-self render.
    # Keep the same exclusion rule (archive = manifest[1:]) so the menu only
    # lists *older* briefs; the homepage itself is the newest.
    newest = entries[0]
    newest_archive = [clean(m) for m in manifest[1:]]
    index_html = render(newest, newest_archive)
    (BASE / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\nindex.html ← newest (ts={newest['ts']})")
    print(f"Total entries in manifest: {len(manifest)}")


if __name__ == "__main__":
    main()
