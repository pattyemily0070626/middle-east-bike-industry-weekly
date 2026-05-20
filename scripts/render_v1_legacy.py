"""把 data/processed/<label>.json 的 token 替換進 templates/weekly-template.html，
產出 reports/bike-weekly-<label>.html。

使用方式：
    python scripts/render.py --label 2026-W20-preview
    python scripts/render.py --label 2026-W20-preview --data path/to/data.json --template path/to/tpl.html --out path/to/out.html

JSON 內容是一組 key→value（純文字或 HTML 片段）；模板裡的 {{KEY}} 會被該 value 取代。
未在 JSON 出現的 token 一律留下警告並標 [missing] — 絕對不靜默吞錯。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def render(template: str, data: dict[str, object]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in data:
            v = data[key]
            return "" if v is None else str(v)
        missing.append(key)
        return f"[missing:{key}]"

    return TOKEN_RE.sub(sub, template), missing


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True, help="例：2026-W20-preview")
    p.add_argument("--data", default=None, help="預設：data/processed/<label>.json")
    p.add_argument("--template", default=None, help="預設：templates/weekly-template.html")
    p.add_argument("--out", default=None, help="預設：reports/bike-weekly-<label>.html")
    args = p.parse_args()

    data_path = Path(args.data) if args.data else ROOT / "data" / "processed" / f"{args.label}.json"
    tpl_path = Path(args.template) if args.template else ROOT / "templates" / "weekly-template.html"
    out_path = Path(args.out) if args.out else ROOT / "reports" / f"bike-weekly-{args.label}.html"

    if not data_path.exists():
        sys.exit(f"data file not found: {data_path}")
    if not tpl_path.exists():
        sys.exit(f"template not found: {tpl_path}")

    data = json.loads(data_path.read_text(encoding="utf-8"))
    template = tpl_path.read_text(encoding="utf-8")

    rendered, missing = render(template, data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")

    print(f"OK: {out_path}")
    if missing:
        print(f"WARN: {len(missing)} unresolved tokens — {sorted(set(missing))}")


if __name__ == "__main__":
    main()
