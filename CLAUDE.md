# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Content repo for a static site deployed to **Azure Static Web Apps**. The live site publishes a rolling archive of daily Middle-East-war intelligence briefs in 繁體中文.

- GitHub repo: `JoeW00/AzureStaticWebApp` (connected to Azure SWA)
- Live URL: `https://gentle-forest-09c056000.7.azurestaticapps.net/`
- The URL's **`.7.`** region shard is real — see "Resolving the live URL" below.

There is no build step and no test suite. Pushing to `main` triggers `.github/workflows/azure-static-web-apps-*.yml`, which uploads the repo root (`app_location: "/"`) to Azure SWA.

## Deploy pipeline

```
markdown brief  →  HTML (template-filled)  →  git push main  →  Azure SWA CI/CD  →  live
```

The user-facing slash command that drives this end-to-end is **`/middle-east-analysis-Azure`** (defined in `.claude/commands/middle-east-analysis-Azure.md`, checked into this repo). It: searches news → writes MD → renders HTML via template → pushes → waits for SWA run → reports URL. A separate global `/middle-east-analysis` command deploys to a throwaway GitHub Pages repo instead; **don't confuse the two**.

### Deploying a change (no new content)

```bash
git add <files>
git commit -m "…"
git pull --rebase origin main   # avoid non-fast-forward rejects
git push origin main
```

Then wait for the workflow:

```bash
RUN_ID=$(gh run list --workflow "Azure Static Web Apps CI/CD" --branch main --limit 1 --json databaseId -q '.[0].databaseId')
until gh run view $RUN_ID --json status -q '.status' | grep -qv "in_progress\|queued"; do sleep 10; done
gh run view $RUN_ID --json status,conclusion
```

### Resolving the live URL

**Do not** construct the URL from the workflow yaml's resource name — Azure SWA prepends a region shard like `.7.` that is only visible in the deploy log:

```bash
gh run view $RUN_ID --log | grep -oE "https://[a-z0-9-]+(\.[0-9]+)?\.azurestaticapps\.net" | head -1
```

## Content model

Directory layout:

```
/                                                 ← repo root
├── index.html                                    ← newest snapshot (homepage)
├── briefs-manifest.json                          ← archive index (source of truth)
├── md_report/
│   └── middle-east-brief-YYYYMMDD-HHMMSS.md      ← source markdown (archival)
└── html_report_archive/
    └── middle-east-brief-YYYYMMDD-HHMMSS.html    ← rendered snapshot (permanent URL)
```

Each brief has three sibling artifacts living in three places:

| Artifact | Location |
|---|---|
| Source markdown | `md_report/middle-east-brief-<TS>.md` |
| Rendered snapshot | `html_report_archive/middle-east-brief-<TS>.html` |
| Manifest entry | `briefs-manifest.json` (at repo root) |

- **`index.html`** = byte-identical copy of the **newest** snapshot. The homepage is never regenerated separately — rendered once for the newest brief, dropped at site root.

### `briefs-manifest.json` (single source of truth for the archive)

Array sorted **newest-to-oldest**. Each entry: `{date, day, title, href, ind, label}`. The hamburger menu in every HTML page is populated from this via the placeholder `{{ARCHIVE_ITEMS_JSON}}`.

**`href` format:** must be **site-absolute**, i.e. begin with `/` — e.g. `"/html_report_archive/middle-east-brief-20260420-205755.html"`. This is required so the same manifest works from *both* `index.html` (at site root) and snapshots (which live inside `html_report_archive/`). Bare filenames and plain relative paths break one side or the other.

### The three critical invariants

1. **Homepage shows newest; hamburger menu shows *only older* briefs.** The newest item is on the home page itself; listing it again in the menu is duplication (this mistake was fixed in commit 395a0e7).
2. **Each snapshot's menu excludes that snapshot's own `href`.** So for N briefs in the manifest, each HTML page injects an archive of length N−1. Never inject the full manifest unfiltered.
3. **Manifest `href` values are site-absolute** (`/html_report_archive/<file>.html`). Same manifest can then be injected into both `index.html` and every snapshot without per-location rewriting.

Concrete rules:
- `index.html`'s injected archive = `manifest[1:]` (drop the newest, which is what index itself is)
- `html_report_archive/middle-east-brief-<ts>.html`'s injected archive = manifest filtered to exclude its own `/html_report_archive/middle-east-brief-<ts>.html` href

### HTML template

Location: `.claude/commands/middle-east-analysis-template-aieztrade.html` (same `.claude/commands/` folder as the slash command).

- Contains 18 unique `{{PLACEHOLDER}}` tokens (21 total occurrences — `DATE_FULL`, `DATE_ISO`, `DAY_COUNT` each appear twice). Never edit the CSS/structure — only replace tokens.
- Has `<!-- EXAMPLE ROW -->` / `<!-- EXAMPLE ITEM -->` comments showing exact row HTML to emit for each table. These comments stay in the output; they're inert.
- Archive rendering: template JS filters by search term, distinguishes empty-via-filter ("無符合結果") from empty-via-no-history ("尚無過往簡報"). Don't regress this.
- The indicator CSS classes are `red` / `amber` / `green`; direction cells use `dir-red` / `dir-green` / `dir-neutral`.

### Bulk re-conversion (when MD history is edited or new old files are added)

`scripts/bulk_convert.py` is the reference implementation: reads every `md_report/middle-east-brief-*.md`, rebuilds manifest sorted desc with site-absolute `href`s, renders each snapshot into `html_report_archive/` with its own archive-minus-self view, and renders `index.html` at root using the newest brief with `manifest[1:]` as its menu. It tolerates:

- English headings (`Escalation Gauge`, `Sources`) and level words (`High`/`Medium`/`Low`)
- Both `- ` and `1. 2. 3.` bullet styles in **implications** and **sources** sections
- Canonical filename is `middle-east-brief-YYYYMMDD-HHMMSS.md` — missing the HHMMSS suffix is now a hard error (raises `ValueError`). Rename any outliers before running the script.

Day numbering convention: **Day 1 = 2026-03-01**.

## Prerequisites for first-time setup elsewhere

The `/middle-east-analysis-Azure` command assumes the working directory is a git clone of a GitHub repo **already linked to an Azure Static Web App** (i.e., `.github/workflows/azure-static-web-apps-*.yml` exists). To bootstrap that linkage on a fresh repo:

```bash
az staticwebapp create \
  --name <swa-name> --resource-group <rg> --location "eastasia" \
  --source https://github.com/<owner>/<repo> --branch main \
  --app-location "/" --login-with-github
```
