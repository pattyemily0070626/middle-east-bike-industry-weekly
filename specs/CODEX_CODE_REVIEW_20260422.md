# Codex 程式碼掃描報告

- 日期：2026-04-22
- 掃描工具：Codex rescue subagent (codex-cli 0.122.0)
- 掃描範圍：`/Users/joseph/Desktop/Side_Projects/20260420_AzureStaticWeb_test` 全專案

## 🟠 High（優先處理）

### 1. XSS 風險 — `ARCHIVE_ITEMS_JSON` 注入

- 檔案：
  - `.claude/commands/middle-east-analysis-template-aieztrade.html:1054, 1077`
  - `.firecrawl/scratchpad/bulk_convert.py:172-176, 296`
- 問題：archive metadata 以 JSON 直接注入 `<script>` block，之後用 `innerHTML` 渲染 DOM。若 `title` / `label` 含 `</script>`、HTML fragment 或事件屬性，會先破壞 script context，再進入 DOM，形成 XSS 漏洞。目前內容由 Claude 生成，風險可控，但架構上是危險的。
- 建議：
  - JSON 注入改成 script-safe escaping（如把 `</` 改為 `<\/`）
  - archive render 改用 `createElement` + `textContent` 取代 `innerHTML`

### 2. `md_report/` 與 `html_report_archive/` 檔名對不齊

- 檔案：`md_report/middle-east-brief-2026-03-07.md` vs `html_report_archive/middle-east-brief-20260307-103934.html`
- 問題：兩個目錄的檔名 stem 不一致，無法直接用 stem 比對，導致追溯、批次重建與自動化檢查都失去穩定對應關係。肇因是 `bulk_convert.py` 對無 `HHMMSS` 檔名用 `mtime` 合成 timestamp（見第 4 項）。
- 建議：統一檔名規格，將無 `HHMMSS` 舊 Markdown 補正，或建立明確的 stem mapping 表。

## 🟡 Medium

### 3. `specs/FEATURE_PLAN_feedback_widget.md` 殘留 `AzureWebJobsStorage`

- 檔案：`specs/FEATURE_PLAN_feedback_widget.md` 第 180、218、257、285 行
- 問題：Runtime code 已改為 `FEEDBACK_STORAGE_CONN`，但此文件仍指引操作者設定保留名 `AzureWebJobsStorage`，足以讓後續維運再踩回保留名陷阱、導致 Function 啟動失敗。
- 建議：全文改為 `FEEDBACK_STORAGE_CONN`，並明確標注 `AzureWebJobsStorage` 不可手動覆寫。

### 4. `bulk_convert.py` 用 `mtime` 合成 timestamp，重現性不佳

- 檔案：`.firecrawl/scratchpad/bulk_convert.py:63-70, 318`
- 問題：對無 `HHMMSS` 檔名的 Markdown，腳本用檔案 `mtime` 合成 timestamp，導致輸出 HTML 檔名與排序受本機觸檔時間影響、不具重現性。目前 `md_report/middle-east-brief-2026-03-07.md` 的對齊問題正是這條路徑造成的。
- 建議：停用 `mtime` 合成，改為要求補正檔名，或提供外部穩定的 timestamp mapping。

### 5. `md_inline()` 不做 HTML escaping

- 檔案：`.firecrawl/scratchpad/bulk_convert.py:29-36, 215-295`
- 問題：summary / table / source / assessment 內容若含原生 HTML，會原樣輸出到頁面。
- 建議：先 escape，再以白名單方式開放必要 markdown 語法。

### 6. `.firecrawl/scratchpad/render_today.py` 是錯的 dead code

- 檔案：`.firecrawl/scratchpad/render_today.py:12, 13, 203, 218`
- 問題：文件化流程只指向 `bulk_convert.py`，但此舊腳本仍留在 repo。它把 snapshot 寫到 repo root（而非 `html_report_archive/`），且用相對 `SNAPSHOT_HREF` 比對 manifest 的 site-absolute href，實際上無法正確排除自身，會破壞不變量 2 和 3。
- 建議：刪除、移出 repo，或至少加上明確 `DO NOT USE` 警告。

## 🟢 Low

### 7. `api/feedback/index.js` 錯誤處理不完整

- 檔案：`api/feedback/index.js:23, 29-55`
- 問題：`createTable()` 對所有錯誤一律靜默忽略，最外層也缺少統一 catch，遇到連線錯誤或權限問題時回應退化成不一致的 500，難以排障。
- 建議：只忽略「table 已存在」類錯誤，其餘統一記錄並回傳可診斷的 500。

### 8. 外部連結缺少 `rel="noopener noreferrer"`

- 檔案：`index.html:933`（所有 snapshot 同型）、模板第 919、1004、1035 行
- 問題：`target="_blank"` 未加 `rel="noopener noreferrer"`，允許新開頁面透過 `window.opener` 反向操作原頁面。
- 建議：在模板層全面補齊。

### 9. `.firecrawl/scratchpad/render.py` 為 dead code

- 檔案：`.firecrawl/scratchpad/render.py:7, 223`
- 問題：不在文件化流程內，且把 snapshot 寫到 repo root，與現行 artifact 佈局不一致。
- 建議：刪除或明確標注「僅供個人臨時實驗，不適用於正式流程」。

## ℹ️ Info

### 10. Placeholder 計數與文件不符

- 檔案：`.claude/commands/middle-east-analysis-template-aieztrade.html`、`CLAUDE.md:92`、`README.md:93`
- 問題：文件說「17 個 placeholder」，但實際計數為 18 次 `{{...}}` 出現、15 個 unique token（`DATE_FULL`、`DATE_ISO`、`DAY_COUNT` 各出現 2 次）。不影響運作，但文件口徑需同步。
- 建議：定義統一計數口徑（unique 或 occurrence），同步文件。

### 11. `api/local.settings.json` 不存在

- 本機開發無法直接跑 Function；需要手動建立。

## ✅ OK 的部分（明確通過的檢查）

- `briefs-manifest.json` 全部 10 筆 `href` 皆為 site-absolute
- `index.html` 注入內容等於 `manifest[1:]`
- 10 份 snapshot 的 archive 長度皆為 9，且都排除自身 `href`（三大不變量在已部署產物上都成立）
- Runtime 已改用 `FEEDBACK_STORAGE_CONN`
- `api/package.json`、`staticwebapp.config.json`、workflow 的 `api_location: "api"` 三者一致
- Workflow `app_location: "/"`、`output_location: ""`、Node runtime（`staticwebapp.config.json` 的 `node:20` 與 `api/package.json` 的 `~20`）一致
- 模板 empty-state 邏輯正確區分「無符合結果」與「尚無過往簡報」
- Indicator CSS classes `red` / `amber` / `green` 與 `dir-red` / `dir-green` / `dir-neutral` 符合需求
- `bulk_convert.py` 對中英文 heading、`- ` 與 `1. 2. 3.` bullet 樣式、`資料來源|Sources` 解析、Day 1 = `2026-03-01` 均正確實作
- `page` 參數僅作為 Table Storage key，未見 path traversal
- Repo 內未發現明文 secrets
- 已部署頁面未發現 live 的相對路徑壞連結

## 整體總結

目前線上內容模型的三個核心不變量在已產出的 `index.html` 與 snapshots 上大致成立，Workflow 與 runtime 沒有阻塞部署的結構性問題。

**最需要優先處理的是兩個安全面向**：

1. `ARCHIVE_ITEMS_JSON` 的 script-context 注入搭配 `innerHTML` 渲染（🟠 High XSS 風險）
2. `md_inline()` 完全不做 HTML escaping（🟡 Medium）

其次是 `bulk_convert.py` 對無 `HHMMSS` 檔名依賴 `mtime`，已實際造成 `md_report/` 與 `html_report_archive/` 對不齊。最後，`specs/FEATURE_PLAN_feedback_widget.md` 仍殘留 `AzureWebJobsStorage` 操作指引，雖非 runtime code，但很容易讓後續維運再踩回保留名問題。

## 建議處理順序

1. 先修 🟠 High 的 XSS（影響 production）
2. 清掉 dead scripts（`render_today.py`、`render.py`）與 spec 文件殘留（`FEATURE_PLAN_feedback_widget.md`）
3. 其他 Medium / Low 項目可一起收尾
