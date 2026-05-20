# Software Design Document — 中東戰爭每日情報簡報（Azure Static Web App）

- **文件版本**：1.0
- **撰寫日期**：2026-04-22（v1.1 依 Codex review 修訂）
- **適用 commit**：`17d78c3`（branch `Code_Review_Fix_20260422`）
- **線上站台**：<https://gentle-forest-09c056000.7.azurestaticapps.net/>
- **GitHub repo**：`JoeW00/AzureStaticWebApp`

---

## 1. 系統定位與目標

本系統是一個**以 Markdown 為單一事實來源（single source of truth）的靜態內容站**，用來每日發布繁體中文的中東戰爭情報簡報，並具備極輕量的讀者互動（按讚／按爛）。設計原則優先順序如下：

1. **作者體驗優先**：作者（或 Claude Code agent）只要寫一份 Markdown，整站（首頁、封存頁、manifest、漢堡選單）就會一致地更新。
2. **運維近乎零成本**：Azure Static Web Apps Free Tier + Managed Functions + Table Storage，無 build step、無測試矩陣、無容器。
3. **內容永久可追溯**：每期簡報的 Markdown 原稿、HTML 快照、manifest 條目都三位一體保存，永遠有穩定 URL。
4. **最小可信計算範圍**：渲染只發生在本機（`scripts/bulk_convert.py`），推上 main 只做靜態上傳 + Functions 部署；無 Node 前端框架、無 SSR。

**非目標**：

- 不處理即時新聞流（每期報告由作者／agent 批次產生）。
- 不做全文檢索（漢堡選單內前端即時過濾已足夠）。
- 不追求 100+ QPS 規模；預期讀者同時在線數 < 100。
- 不做使用者帳號、留言、或雙向互動。

---

## 2. 總體架構

```
┌──────────────────────── Authoring (local) ─────────────────────────┐
│                                                                    │
│  Claude Code + /middle-east-analysis-Azure                         │
│     │                                                              │
│     ├── 搜新聞 → 產 Markdown → md_report/middle-east-brief-*.md    │
│     │                                                              │
│     └── 呼叫 scripts/bulk_convert.py                               │
│              │                                                     │
│              ├─► briefs-manifest.json  (site-absolute hrefs)       │
│              ├─► html_report_archive/*.html  (N 份 snapshot)       │
│              └─► index.html            (= 最新 snapshot 的複本)    │
│                                                                    │
│  git push main                                                     │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌───────────────────── GitHub Actions (CI/CD) ───────────────────────┐
│                                                                    │
│  .github/workflows/azure-static-web-apps-*.yml                     │
│     └── Azure/static-web-apps-deploy@v1                            │
│           ├── app_location: "/"   ← 靜態上傳整個 repo              │
│           └── api_location: "api" ← 部署 Managed Functions         │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌──────────────────── Azure Static Web Apps (prod) ──────────────────┐
│                                                                    │
│   Edge CDN  ───── GET /, /html_report_archive/*, briefs-manifest   │
│      │                                                             │
│      └── /api/feedback  ──► Managed Azure Functions (Node 20)      │
│                                  │                                 │
│                                  └─► Azure Table Storage           │
│                                         (table: feedbackCounts)    │
└────────────────────────────────────────────────────────────────────┘
```

**三個邊界**：

| 邊界 | 位置 | 介面 | 協定 |
|---|---|---|---|
| Authoring ↔ Repo | 本機 | 檔案系統 + git | shell / git push |
| Repo ↔ SWA | GitHub Actions | Azure SWA deploy action | HTTPS, deployment token |
| Browser ↔ Backend | 讀者瀏覽器 | `/api/feedback` | POST JSON |

---

## 3. 目錄結構與部署對應

```
/                                      ← SWA app_location = "/"
├── index.html                         ← 最新一期 snapshot 的完整複本
├── briefs-manifest.json               ← 漢堡選單資料源（唯一事實）
├── staticwebapp.config.json           ← SWA 平台設定（僅 apiRuntime=node:20）
│
├── md_report/                         ← Markdown 原稿（永久保存）
│   └── middle-east-brief-YYYYMMDD-HHMMSS.md
│
├── html_report_archive/               ← 每期 HTML 快照（permalink）
│   └── middle-east-brief-YYYYMMDD-HHMMSS.html
│
├── api/                               ← SWA api_location = "api"
│   ├── host.json                      ← Functions runtime config（extensionBundle v4）
│   ├── package.json                   ← 相依：@azure/data-tables
│   ├── .gitignore                     ← 忽略 local.settings.json / node_modules
│   ├── local.settings.json.example    ← 本地開發環境變數範本
│   └── feedback/
│       ├── function.json              ← HTTP POST binding（authLevel anonymous）
│       └── index.js                   ← handler：validate → Table upsert with retry
│
├── scripts/
│   └── bulk_convert.py                ← 批次 md → manifest + HTML（唯一渲染路徑）
│
├── .claude/commands/                  ← Claude Code 專案級指令與模板
│   ├── middle-east-analysis-Azure.md
│   └── middle-east-analysis-template-aieztrade.html   ← HTML 模板（18 unique tokens）
│
├── .github/workflows/
│   └── azure-static-web-apps-*.yml    ← SWA CI/CD（push main + PR preview）
│
├── specs/                             ← 設計文件、code review、retrospective
│   ├── SDD_architecture.md            ← 本文件
│   ├── CODEX_CODE_REVIEW_20260422.md
│   ├── FEATURE_PLAN_feedback_widget.md
│   └── RETROSPECTIVE_feedback_widget.md
│
├── CLAUDE.md                          ← 專案說明（給 Claude Code）
├── README.md                          ← 專案說明（給開發者）
└── .gitignore                         ← 忽略 .firecrawl/, .DS_Store, .idea/
```

**關鍵路徑對應**：

- 任何放在 repo 根目錄、非 `api/` 的檔案都會以原路徑上架到 CDN。
- `api/<funcName>/index.js` + `function.json` 會被 SWA 打包成 `/api/<funcName>` HTTP endpoint。
- `.claude/`、`specs/`、`scripts/` 目錄會**隨靜態站一併部署**。目前 `staticwebapp.config.json` 未設 route / header 規則，是否可被直接存取取決於 SWA 平台行為，需以實際站台驗證。若要明確阻擋，應在 `staticwebapp.config.json` 加入 `routes` deny 規則或改以子目錄存放。

---

## 4. 內容模型（Content Model）

### 4.1 單期簡報三位一體

每期簡報對應三個 artifacts，缺一不可：

| Artifact | 位置 | 檔名格式 | 用途 |
|---|---|---|---|
| 原稿 Markdown | `md_report/` | `middle-east-brief-YYYYMMDD-HHMMSS.md` | 永久保存、可重新渲染 |
| HTML 快照 | `html_report_archive/` | `middle-east-brief-YYYYMMDD-HHMMSS.html` | 穩定 URL，任何時候都能被引用 |
| manifest 條目 | `briefs-manifest.json` | JSON object | 供漢堡選單與首頁讀取 |

檔名唯一鍵為時間戳 `YYYYMMDD-HHMMSS`。此格式為強制硬性規範：`scripts/bulk_convert.py:62` 在無 HHMMSS 時會 `raise ValueError`，不再用 mtime 合成。

### 4.2 `briefs-manifest.json` schema

陣列，由新到舊排序。每一筆：

```json
{
  "date":  "2026-04-21",                                          // ISO date
  "day":   "Day 52",                                              // 戰爭天數（Day 1 = 2026-03-01）
  "title": "美伊兩週停火將於本週三（4月22日）到期…",               // 20–55 字摘要
  "href":  "/html_report_archive/middle-east-brief-20260421-100756.html",  // 必須以 / 開頭
  "ind":   "red",                                                 // red | amber | green
  "label": "升級"                                                 // 中文標籤
}
```

**設計關鍵：`href` 必須為 site-absolute**（以 `/` 開頭）。這讓同一份 manifest 可以同時被注入至：

- 根目錄的 `index.html`
- 子目錄 `html_report_archive/` 內每份快照

而不需要依相對位置改寫連結。這個不變量由 `scripts/bulk_convert.py:18, 329` 集中控管。

### 4.3 三大內容不變量（絕對不可回歸）

| # | 規則 | 由誰保證 |
|---|------|----------|
| I-1 | 首頁 `index.html` = 最新 snapshot 的**完整**複本；漢堡選單**不**包含最新那筆 | `bulk_convert.py:355–358` 用 `manifest[1:]` 為 index 渲染 |
| I-2 | 每份 snapshot 的漢堡選單**排除自己的 `href`**，因此長度恆為 N−1 | `bulk_convert.py:344–346` 用 `filter(m["href"] != self_href)` |
| I-3 | manifest `href` 一律 site-absolute（以 `/` 開頭） | `bulk_convert.py:329` 固定 `HTML_SITE_PREFIX = "/html_report_archive"` |

歷史上 I-1 曾被破壞（見 commit `395a0e7`），觸發重複連結 bug；之後把 index.html 視為「丟掉最新那筆之後的 render」制度化。

### 4.4 Day 編號

- **Day 1 = 2026-03-01**（戰爭起始日，硬編碼於 `bulk_convert.py:20`）
- `day_label = (date - 2026-03-01).days + 1`，以 `Day N` 呈現。
- 若未來需要多戰役或不同起算基準，應改為從 `briefs-manifest.json` 或獨立 config 讀取，而非散落在腳本常數。

---

## 5. 前端渲染管線

### 5.1 HTML 模板

位置：`.claude/commands/middle-east-analysis-template-aieztrade.html`（1,338 行，單一檔案包含 CSS + HTML + JS）。

- **18 個 unique `{{PLACEHOLDER}}` tokens**，共出現 21 次。重複使用者：`DATE_FULL`、`DATE_ISO`、`DAY_COUNT` 各 2 次。
- 命名慣例：前端顯示文字用 `Day N`（首字大寫）；模板 token 與 `{{DAY_COUNT}}` 注入為 `DAY N`（全大寫）作為視覺風格。manifest 欄位 `day` 採 `Day N`。
- 包含 `<!-- EXAMPLE ROW -->` / `<!-- EXAMPLE ITEM -->` 註解範例，**留在輸出內**（對瀏覽器無影響）作為下游作者的格式提示。
- 內嵌兩段 inline JS：
  1. **漢堡選單 / 封存清單**（約行 1050–1167）：讀 `{{ARCHIVE_ITEMS_JSON}}`，用 DOM API 渲染，附 href 白名單。
  2. **按讚／按爛 Modal**（約行 1278–1334）：`IntersectionObserver` 監聽 `#card-04-implications`，首次進入視窗時開啟；`localStorage` 永久旗標防重複。

**關鍵 token 清單**：

| Token | 作用 |
|---|---|
| `{{DATE_FULL}}` / `{{DATE_ISO}}` | 標題與 footer 日期 |
| `{{DAY_COUNT}}` | 戰爭天數字串（`DAY N`） |
| `{{WAR_SUBTITLE}}` | 戰役副標 |
| `{{INDICATOR_CONFLICT/ESCALATION/SPILLOVER}}` | 三個風險儀表文字 |
| `{{INDICATOR_CLASS_*}}` | 對應的 CSS class（`red` / `amber` / `green`） |
| `{{ASSESSMENT_TEXT}}` / `{{SUMMARY_TEXT}}` | 文字段落 |
| `{{TABLE1_ROWS}}` / `{{TABLE2_ROWS}}` / `{{TABLE3_ROWS}}` | 三個表格 `<tr>` HTML |
| `{{IMPLICATIONS_ITEMS}}` / `{{SOURCES_ITEMS}}` | `<li>` 清單 |
| `{{ARCHIVE_ITEMS_JSON}}` | 注入給漢堡選單的 JSON 陣列（已做 `</` → `<\/` 字符轉義） |

### 5.2 `scripts/bulk_convert.py`（唯一渲染器）

單一 Python 檔、無第三方相依（只用 stdlib：`datetime`, `html`, `json`, `pathlib`, `re`, `sys`；`sys` 用於渲染後偵測到未替換 token 時 `sys.exit(1)` 強制失敗）。處理流程：

```
md_report/*.md  ──► parse_file()  ──► entry dict
                                        │
                                        ▼
                     entries.sort(key=ts, reverse=True)
                                        │
                     ┌──────────────────┼───────────────────┐
                     ▼                  ▼                   ▼
              briefs-manifest     render(each)           render(newest,
                  .json           ──► html_report_        manifest[1:])
                                      archive/*.html      ──► index.html
```

- **Markdown → HTML**：手寫 regex，非 `markdown` library。理由：簡報格式受控（只有表格、清單、連結、粗體），不值得引入相依；而且必須自己控制 HTML escape 以對抗 XSS。
- **inline escape 順序**：`html.escape(s, quote=True)` → 連結 regex → 粗體 regex。escape 先行確保 `<script>` 類標籤轉成文字；連結 regex 後續不會再遇到原始 `<`，因此不會被誤判。
- **執行路徑**：腳本從 `__file__` 解出 repo 根目錄（`pathlib.Path(__file__).resolve().parent.parent`），不依賴當前工作目錄。
- **Markdown 不支援 raw HTML**：`md_inline()` 先做 `html.escape(..., quote=True)`，任何 `<span class="data">…</span>` 等 inline HTML 會被轉義為字面文字。雖然現有 MD 檔偶有這類寫法，但實際渲染後只會呈現為純文字，不會套 CSS；作者若要凸顯數據，應改用 `**bold**`。若未來真的需要 inline HTML，需引入 allowlist（目前刻意不做）。

### 5.3 XSS 防護兩層

Codex code review 指出 manifest metadata 來源雖是作者自己，但架構上有 `</script>` 跳出與 `javascript:` URL 兩個洞。修復採兩層防護：

1. **上游（Python）**：`json.dumps(...).replace("</", "<\\/")` 防止 JSON 字串內含 `</script>` 能跳出 `<script>` context。(`bulk_convert.py:298`)
2. **下游（Template JS）**：`populateArchiveList()` 已棄用 `innerHTML`，全改 `document.createElement()` + `textContent` / `setAttribute`；`href` 走 `safeHref()` 白名單（只允許 `/` 或 `#` 開頭），擋 `javascript:`, `data:` 與跨站 origin。(`.claude/commands/middle-east-analysis-template-aieztrade.html:1065–1068, 1089–1135`)

### 5.4 生命週期與再生策略

- **加新簡報**：`/middle-east-analysis-Azure` 產生 MD → 自動跑 `bulk_convert.py` → `git push`。
- **改舊簡報**：直接編輯 `md_report/xxx.md` → 跑 `bulk_convert.py` → `git push`。manifest、所有 snapshot、index 都會被**重新渲染**，差異由 git diff 一目了然。
- **改模板**：編輯 `.claude/commands/middle-east-analysis-template-aieztrade.html` → 跑 `bulk_convert.py` → 所有頁面刷新。

渲染是**純冪等**的：同一份輸入永遠產出同一份輸出（除了檔名自動排序），可隨時重跑。

### 5.5 Feedback Modal 的前端降級策略

Modal 的 `fetch('/api/feedback', …).catch(function(){})` **刻意靜默失敗**：不論 API 回 500、網路斷線、或 Function cold start 逾時，使用者都只會看到「謝謝你的回饋」並 1.2 秒後關閉 Modal。

取捨：
- ✅ 優先讀者 UX：不把後端故障暴露給讀者。
- ✅ `localStorage` 旗標無論 API 成敗都已寫入，確保不會重複彈窗。
- ⚠️ 代價：讀者投了也不知道有沒有被計入；維運端必須主動監控（見 §11）才能察覺。

若未來改成要求「寫入成功才算」，必須同時加上錯誤 UI、重試邏輯、以及旗標寫入時機的調整。

---

## 6. 後端 API：`/api/feedback`

### 6.1 功能規格

- **路徑**：`POST /api/feedback`
- **Request body**：
  ```json
  { "page": "/html_report_archive/middle-east-brief-20260421-100756.html",
    "reaction": "like" }
  ```
- **Response**：
  - `200 { "ok": true }` — 成功計次
  - `400 { "error": "bad request" }` — 格式錯誤
  - `500 { "error": "storage not configured" | "internal error", "code"?: ... }` — 伺服器端錯誤
  - `503 { "error": "contention, try again" }` — 3 次重試後仍高競爭

### 6.2 驗證規則（`api/feedback/index.js`）

- `page`：必須符合 regex `^[A-Za-z0-9/_.\-]{1,256}$`（擋 query string、Unicode、過長 payload）。
- `reaction`：僅允許 `"like"` 或 `"dislike"`。
- 不合規格一律 400，不寫入 Table Storage。

### 6.3 儲存模型

Azure Table Storage，單一 table：`feedbackCounts`

| 欄位 | 值 | 說明 |
|---|---|---|
| `PartitionKey` | `encodeURIComponent(page)` | 每篇簡報獨立分區 |
| `RowKey` | `"like"` 或 `"dislike"` | 只有兩列 |
| `count` | int | 累計票數 |

- **PK/RK 設計**：每頁各有 2 個 entity；查詢永遠走 PK+RK 直取，無需 scan。
- **併發控制**：讀 entity → +1 → `updateEntity(..., 'Replace', { etag })`。ETag 失配 (HTTP 412) 代表有人先寫，迴圈重試最多 3 次。
- **冷啟動**：entity 不存在時（HTTP 404）改用 `createEntity`；若建立時又撞到別人剛建好（HTTP 409），把 409 當作 "race-recovered"，下一輪迴圈就會讀到 entity 再走 update 路徑。
- **錯誤分層**：
  - `createTable()` 只吞 409 / `TableAlreadyExists`，其餘網路或授權錯誤會 throw。
  - handler 最外層 try/catch 兜回 500，不回傳 stack（只回 `code`）。

### 6.4 環境變數

| 變數 | 來源 | 用途 |
|---|---|---|
| `FEEDBACK_STORAGE_CONN` | SWA App Settings（production） / `api/local.settings.json`（dev） | Azure Storage connection string |
| `FUNCTIONS_WORKER_RUNTIME` | `node`（固定） | SWA Managed Functions runtime |
| `AzureWebJobsStorage` | 僅本地開發使用 `UseDevelopmentStorage=true` | **不要**在 SWA 上手動覆寫此保留名，會導致 Managed Functions 啟動失敗（見 commit `2a60600`） |

### 6.5 資料生命週期與觀測性

目前系統**只寫不讀**，且無自動清理：

| 面向 | 現況 | 缺口 |
|---|---|---|
| 讀取 | 無 API；只能在 Azure Portal → Storage Account → Table Explorer 手動查 | 需要儀表板時要自寫 `GET /api/feedback/summary`（並加 SWA auth） |
| 備份 | Azure Storage 預設有 soft-delete 與跨區冗餘 | 無邏輯層備份；若 entity 被誤寫入錯誤 PK 無法回溯 |
| 保留期 | 無限期 | 若改為僅保留 N 月，需寫排程 Function 清理 |
| 匯出 | 無 | 可用 `az storage entity query` 或 AzCopy 一次性匯出 |
| 告警 | 無 | 建議至少加上 Application Insights → Function 失敗率告警 |

### 6.6 不做的事

- 不做反濫用：無 rate limit、無 IP 記錄、無 captcha。信任前端 `localStorage` 已擋每頁一次，承擔低流量的誤用風險（更深入的風險分析見 §9）。
- 不讀：後端只收寫入，前端永遠不顯示票數。若未來要做儀表板需再加 `GET /api/feedback/summary` 與 auth。

---

## 7. CI/CD 與部署

### 7.1 觸發條件

`.github/workflows/azure-static-web-apps-*.yml`：

- `push` → `main`：部署到 production（`gentle-forest-09c056000.7.azurestaticapps.net`）
- `pull_request` → `main`（opened / synchronize / reopened）：建立 **preview environment**（URL 帶 PR 編號，如 `gentle-forest-09c056000-1.eastasia.7.azurestaticapps.net`）
- `pull_request` closed：呼叫 `action: "close"` 清理 preview

### 7.2 部署步驟

1. `actions/checkout@v3`（含 submodules，不含 LFS）
2. `Azure/static-web-apps-deploy@v1` 上傳：
   - `app_location: "/"`：整個 repo 根當靜態檔
   - `api_location: "api"`：`api/` 資料夾被 SWA 打包為 Managed Functions
   - `output_location: ""`：無 build artifact，直接 1:1 上傳

### 7.3 SWA 平台設定

`staticwebapp.config.json`：

```json
{ "platform": { "apiRuntime": "node:20" } }
```

僅鎖定 runtime 版本；無 route、auth、fallback 設定。

### 7.4 Live URL 解析

Azure SWA 會在網域內加 region shard（如 `.7.`），**不可**由 yml 檔名拼 URL。正確作法是從 deploy log 抓：

```bash
gh run view $RUN_ID --log \
  | grep -oE "https://[a-z0-9-]+(\.[0-9]+)?\.azurestaticapps\.net" | head -1
```

### 7.5 第一次連結 SWA（Bootstrap）

當 repo 尚未綁 SWA 時一次性執行：

```bash
az staticwebapp create \
  --name <swa-name> --resource-group <rg> --location "eastasia" \
  --source https://github.com/<owner>/<repo> --branch main \
  --app-location "/" --login-with-github
```

---

## 8. 本地開發

### 8.1 渲染流程

```bash
# 安裝時只需 Python 3.10+，無 pip 相依
python3 scripts/bulk_convert.py

# 啟動靜態預覽
python3 -m http.server 8000
# 打開 http://localhost:8000
```

### 8.2 Functions 本地測試

**前置條件（首次執行必備）**：

| 工具 | 版本 | 安裝 | 用途 |
|---|---|---|---|
| Node.js | **20.x（必須與 SWA `node:20` 一致）** | `nvm install 20 && nvm use 20` | Function runtime |
| Azure Functions Core Tools | v4 | `npm i -g azure-functions-core-tools@4 --unsafe-perm true` 或 `brew tap azure/functions && brew install azure-functions-core-tools@4` | 提供 `func start` CLI |
| Azurite（若用本地儲存） | 最新 | `npm i -g azurite`，另開一個 terminal 執行 `azurite --silent --location /tmp/azurite` | 模擬 Azure Table Storage，對應 `UseDevelopmentStorage=true` |

> 如果機器上的 `node -v` 不是 v20.x、或 `which func` 找不到，`func start` 會失敗；照下表排錯：
>
> - `command not found: func` → Core Tools 沒裝或沒加入 PATH
> - `The listener for function 'feedback' was unable to start` → 環境變數 `FEEDBACK_STORAGE_CONN` 未設或 Azurite 未啟動
> - `Worker was unable to load entry point 'feedback/index.js'` → 先執行 `npm install`

**啟動步驟**：

```bash
cd api
npm install
cp local.settings.json.example local.settings.json
# 編輯 local.settings.json，將 FEEDBACK_STORAGE_CONN 換成：
#   - 實際 Azure Storage connection string，或
#   - UseDevelopmentStorage=true（需先啟動 Azurite，見前置條件）
func start
```

`local.settings.json` 被 `api/.gitignore` 忽略，永不進 repo。

### 8.3 Preview 環境 smoke test

```bash
PREVIEW=https://gentle-forest-09c056000-1.eastasia.7.azurestaticapps.net
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" $PREVIEW/
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" $PREVIEW/briefs-manifest.json
curl -s -X POST $PREVIEW/api/feedback \
     -H 'Content-Type: application/json' \
     -d '{"page":"/","reaction":"like"}'
```

---

## 9. 安全考量

### 9.1 威脅矩陣（已防護）

| 威脅 | 緩解 |
|---|------|
| XSS via manifest metadata | (a) Python 端 `</` → `<\/` 轉義；(b) template JS 全 DOM API，無 `innerHTML`；(c) `href` 白名單（只允許 `/` / `#`） |
| XSS via MD content | `html.escape(s, quote=True)` 先於 regex，再允許 `**bold**` 與 `[link](url)` |
| `target="_blank"` reverse tabnabbing | 模板所有 3 處範例、`md_inline()` 生成的連結、封存清單連結都附 `rel="noopener noreferrer"` |
| Secret leak | `api/local.settings.json` 在 `api/.gitignore`；SWA connection string 只在 App Settings |
| Reserved App Setting 誤用 | 文件（README, CLAUDE.md, FEATURE_PLAN）明確警告 `AzureWebJobsStorage` 為 Functions runtime 保留名，使用 `FEEDBACK_STORAGE_CONN` |

### 9.2 已識別但目前未處理的風險

以下為可接受但應明確記錄的風險，未來嚴格化時可從此清單下手：

| 風險 | 現況 | 未處理的理由 | 未來強化選項 |
|---|------|---|---|
| **Clickjacking** | `staticwebapp.config.json` 無任何 header 設定；站台可被第三方以 `<iframe>` 嵌入 | Feedback Modal 是被動彈窗，沒有敏感操作；內容本身為公開情報 | 在 `staticwebapp.config.json` 加 `globalHeaders.X-Frame-Options: DENY` 或 `Content-Security-Policy: frame-ancestors 'none'` |
| **Cross-origin POST 污染** | `/api/feedback` 為 anonymous，未驗 `Origin`/`Referer`；第三方站可偽造請求灌票 | 後端只記計數、前端永不顯示；風險等級為 integrity 汙染而非資安事件 | 驗 `Origin` 必須等於站台網域；或改 SWA Auth；或加 rate limit |
| **Table Storage 權限過大** | `FEEDBACK_STORAGE_CONN` 為 account-level connection string，擁有全帳號讀寫權 | 單一用途、單一 Function；爆炸半徑局限於 storage account | 改以 SAS token（限定 table + 時效）、或 User-Assigned Managed Identity + Table Data Contributor RBAC |
| **Rate limit / 反濫用** | 前端 `localStorage` 旗標 + 後端 regex 擋格式 | 預期流量 < 100 同時在線；Azure Functions consumption plan 的帳單上限為天然上限 | 若流量上升，可加 IP-based rate limit（Azure Front Door / API Management）或 turnstile captcha |
| **Secret rotation** | 手動 rotation | 單一 secret、低頻更動 | 改 Managed Identity 可以移除 rotation 需求 |

### 9.3 明確不適用的威脅

| 威脅 | 不適用理由 |
|---|---|
| SSRF | `/api/feedback` 只操作內部 Table Storage，沒有依使用者輸入發出 outbound HTTP |
| SQL injection | 無 SQL 後端；Table Storage 以 PK/RK 直取，且 `page` 已 `encodeURIComponent` |
| CSRF (with cookie) | API 不使用 cookie／session；無可偽造的認證態（但 cross-origin POST 污染另列於 9.2） |
| CSP for inline scripts | CSS/JS 皆 inline 在單一 HTML 檔，加 CSP 需逐行 hash，對公開靜態站成本過高 |

---

## 10. 已知限制與未來擴充空間

### 10.1 目前的限制

1. **單戰役硬編碼**：`WAR_START = 2026-03-01` 在 Python 腳本。若要支援多戰役需重構成 config。
2. **Markdown 解析脆弱**：表格解析依賴 `|` 符號與固定欄數；若作者漏寫欄位會 silent fallback。可接受因為 Claude agent 是主要作者。
3. **無測試套件**：沒有 unit test、integration test。依賴 preview environment 的手動 smoke test 驗證。
4. **模板是單一 HTML 檔**：1,338 行、CSS + HTML + JS 糾纏，難以進行元件化或主題切換。
5. **Feedback 資料無讀取介面**：Azure Portal 看原始 entity，或自寫臨時 query script。

### 10.2 未來擴充點

> **估算前提**：單人、延伸現行架構、不含正式測試套件與監控建置、不含 Azure 資源額度申請、以「可上線最小可行版」為邊界。實際時程依驗收標準可能翻倍。

**前台功能類：**

| 擴充需求 | 影響面 | 粗估成本 |
|---|---|---|
| 多語系（英文版） | 新增模板 + i18n token；manifest 增 `lang` 欄 | 1–2 天 |
| Feedback 儀表板 | 新 Function `GET /api/feedback/summary` + SWA Auth（GitHub / AAD） | 3–5 天 |
| 全文檢索 | 靜態站離線建 Lunr index，或上 Algolia | 1–2 天 |
| RSS / Atom | `bulk_convert.py` 另輸出 feed.xml | 0.5 天 |
| PDF 匯出 | Playwright headless Chrome 渲染 snapshot | 1 天 |
| Alert 通知 | 新期簡報時發 Slack/Email 給訂閱者 | 需加訂閱模型，2–3 天 |

**觀測與治理類：**

| 擴充需求 | 影響面 | 粗估成本 |
|---|---|---|
| Feedback 定期匯出 | 排程 Function + AzCopy；輸出 CSV 到另一個 storage container | 1 天 |
| Function 失敗率告警 | Application Insights + Azure Monitor alert rule | 0.5 天 |
| Managed Identity 取代 connection string | 改 Function 讀取方式 + 設 RBAC | 0.5–1 天 |
| 靜態資產曝光控管 | `staticwebapp.config.json` 加 route deny（`.claude/`, `specs/`, `scripts/`, `md_report/`） | 0.5 天 |
| 內容校驗 pre-commit hook | 跑 `bulk_convert.py --dry-run` 偵測解析失敗 | 0.5–1 天 |
| Security headers | `globalHeaders` 加 `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` | 0.5 天 |

---

## 11. 維運紀律與 Playbook

### 11.1 常見情境

**Case A — 部署失敗：**

```bash
RUN_ID=$(gh run list --workflow "Azure Static Web Apps CI/CD" --branch main \
         --limit 1 --json databaseId -q '.[0].databaseId')
gh run view $RUN_ID --log-failed        # 只看失敗 step 的 log
gh run view $RUN_ID --json status,conclusion
```

**Case B — manifest 與 HTML 不一致：**

```bash
python3 scripts/bulk_convert.py         # 冪等，直接重跑
git diff briefs-manifest.json           # 應該為 0 變動
git diff index.html html_report_archive/
```

**Case C — 加入舊日 Markdown（補填歷史）：**

1. 放入 `md_report/middle-east-brief-YYYYMMDD-HHMMSS.md`（檔名必須含 HHMMSS）
2. `python3 scripts/bulk_convert.py`
3. 檢查 `briefs-manifest.json` 新項目位置正確（依時間降序）
4. 提交 push

**Case D — Feedback 後端異常：**

先跑一次 smoke test：

```bash
curl -sS -X POST https://<site>/api/feedback \
     -H 'Content-Type: application/json' \
     -d '{"page":"/","reaction":"like"}' -w "\n%{http_code}\n"
```

對照症狀 → 可能原因 → 檢查點：

| 症狀 | 可能原因 | 檢查點 |
|---|---|---|
| `500 { "error":"storage not configured" }` | App Setting 沒設 | Azure Portal → SWA → Configuration → 確認 `FEEDBACK_STORAGE_CONN` 存在且非空 |
| `500 { "error":"internal error", "code":"ENOTFOUND"|"AuthenticationFailed" }` | connection string 錯誤或 storage key rotate | 重新產生 connection string 並更新 App Setting |
| `500` 且 `code` 為 `403` / `AuthorizationFailure` | Function 的身分未獲授權存取該 storage | 檢查 storage account RBAC / 網路規則 |
| `400 { "error":"bad request" }` | 請求 body 格式不符 regex | 確認 `page` 為 `^[A-Za-z0-9/_.\-]{1,256}$` 且 `reaction` 為 `like` 或 `dislike` |
| `503 { "error":"contention, try again" }` | 同一 entity 併發寫入 ≥ 3 次都 ETag 失配 | 通常瞬時即恢復；若頻繁出現代表流量超出單 entity 可撐範圍，需改 sharding |
| 前端看起來成功但 Table 內沒有 count | 前端 silent catch 吃掉錯誤（見 §5.5） | 打開 DevTools → Network 看 `/api/feedback` 實際 response |
| API 完全 timeout | Function cold start 或被 disable | Azure Portal → Function App → Functions → 確認 status；看 Application Insights |

最後：Azure Portal → 對應 Storage Account → Table service → 確認 `feedbackCounts` table 存在且有資料。

### 11.2 危險操作清單

| 操作 | 風險 | 安全做法 |
|---|---|---|
| 手動編輯 `briefs-manifest.json` | 破壞 site-absolute href 不變量 | 只改 `md_report/`，跑 bulk_convert 自動重建 |
| 手動編輯 `html_report_archive/*.html` | 會在下次 bulk_convert 被覆寫 | 永遠先改 MD 或模板 |
| 改 `WAR_START` 常數 | 所有 Day N 標籤漂移 | 不改；若真要改須全量回溯通告 |
| 新增 SWA App Setting 名稱含 `AzureWebJobs*` | 覆蓋 Functions runtime 保留名 | 自訂設定永遠用專案前綴（如 `FEEDBACK_*`） |

---

## 12. 文件交叉索引

| 文件 | 作用 |
|---|---|
| `CLAUDE.md` | 給 Claude Code 的專案速查（deploy 指令、content 模型、三大不變量） |
| `README.md` | 給開發者的入門指南（目錄、部署流程、如何產新簡報） |
| `specs/FEATURE_PLAN_feedback_widget.md` | 按讚／按爛功能的詳細實作計畫 |
| `specs/RETROSPECTIVE_feedback_widget.md` | Feedback 功能導入的事後檢討 |
| `specs/CODEX_CODE_REVIEW_20260422.md` | Codex 掃描結果與修復對照 |
| `specs/SDD_architecture.md` | 本文件——整體架構設計 |

---

## 附錄 A：關鍵檔案行號索引

| 元素 | 位置 |
|---|---|
| 三大不變量實作 | `scripts/bulk_convert.py:344–358` |
| XSS 上游防護 | `scripts/bulk_convert.py:298` |
| XSS 下游防護 | `.claude/commands/middle-east-analysis-template-aieztrade.html:1065–1068, 1089–1135` |
| MD inline escape 順序 | `scripts/bulk_convert.py:30–37` |
| 檔名硬驗證 | `scripts/bulk_convert.py:62–67` |
| Feedback handler | `api/feedback/index.js:13–77` |
| Feedback input validation | `api/feedback/index.js:4, 18` |
| SWA platform config | `staticwebapp.config.json` |
| SWA workflow | `.github/workflows/azure-static-web-apps-gentle-forest-09c056000.yml` |

---

**End of Document**
