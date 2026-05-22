# 中東情勢產業週報 · 自行車產業（Azure Static Web Apps）

每週彙整中東情勢對台灣自行車產業的傳導影響的繁體中文靜態站，部署於 **Azure Static Web Apps**，整合 **Azure Functions** 提供讀者投票回饋。

- **線上網址**：（規劃中）Azure Static Web Apps 新 resource
- **首頁 (`index.html`)**：永遠是最新一期週報
- **歷史存檔**：透過右上角漢堡選單切換過往週報
- **GitHub repo**：（規劃中）

---

## 目錄

- [專案簡介](#專案簡介)
- [兩種使用情境](#兩種使用情境)
- [安裝步驟](#安裝步驟)
- [資料夾結構](#資料夾結構)
- [部署流程](#部署流程)
- [後端 API](#後端-api)
- [手動批次重建](#手動批次重建)
- [來源規則](#來源規則)
- [撰寫規則（文字風格）](#撰寫規則文字風格)
- [免責聲明](#免責聲明)

---

## 專案簡介

以 **Markdown 為單一事實來源（single source of truth）** 的靜態內容站。每週只需撰寫一份 Markdown 檔，整站（首頁、封存頁、manifest、漢堡選單）便自動一致更新。

### 核心架構

```
撰寫 Markdown  →  bulk_convert_bike.py 套模板  →  git push main  →  Azure SWA CI/CD  →  線上
```

每期會同時生成：

| 位置 | 內容 |
|---|---|
| `md_report/bike-weekly-<WEEK_ISO>.md` | 原始 Markdown（存檔用） |
| `html_report_archive/bike-weekly-<WEEK_ISO>.html` | 完整 HTML 快照（永久 URL） |
| `briefs-manifest.json` 內的一筆 | 漢堡選單 metadata |
| `index.html` | 最新那份的完整複本 |

### 設計原則

1. **作者體驗優先**：只要寫 Markdown，整站一致更新
2. **運維近乎零成本**：Azure SWA Free Tier + Managed Functions + Table Storage
3. **內容永久可追溯**：每期 Markdown、HTML 快照、manifest 三位一體
4. **最小可信計算範圍**：渲染在本機完成，推 main 只做靜態上傳

---

## 兩種使用情境

### 情境 A：只看週報（最常見）
線上網址直接打開，**任何裝置、任何瀏覽器、無需登入**。

### 情境 B：接手每週重跑（協作者）
需安裝下列依賴跑 fetch → verify → 編 Markdown → bulk_convert → push 流程。

---

## 安裝步驟

### 先決條件

1. **Python 3.10+**
2. **Git** + **GitHub CLI (`gh`)**：`gh auth login`
3. **Azure CLI** (`az`)（首次建立 SWA 時需要）
4. **Node.js 20.x**（本地開發 Functions 時需要）
5. **Playwright + chromium**：`python -m playwright install chromium`（JS-rendered 來源用）
6. **Tesseract OCR**：`winget install UB-Mannheim.TesseractOCR`（關務署 CAPTCHA 用）

### Python 套件

```bash
python -m pip install -r requirements.txt
```

---

## 資料夾結構

```
bike-weekly-v2/
├── README.md                       # 本檔
├── CLAUDE.md                       # AI 協作者指引
├── requirements.txt                # Python 套件清單
├── staticwebapp.config.json        # Azure SWA 設定
├── briefs-manifest.json            # 歷史週報目錄（由 bulk_convert_bike.py 產生）
├── index.html                      # 最新週報（永遠複製自最新一份 archive）
├── .claude/
│   └── commands/
│       └── bike-weekly-template.html  # HTML 模板
├── md_report/                      # ★ 單一事實來源：每週一份 Markdown
│   └── bike-weekly-<WEEK_ISO>.md
├── html_report_archive/            # 由 Markdown 生成的 HTML 快照
│   └── bike-weekly-<WEEK_ISO>.html
├── api/                            # Azure Functions (Node.js 20)
│   ├── host.json
│   ├── package.json
│   └── feedback/                   # POST /api/feedback (counter pattern)
│       ├── function.json
│       └── index.js
├── config/                         # 來源與監測 HS 碼設定
│   ├── sources.json
│   ├── companies.json
│   └── hs-monitoring.json
├── reference/
│   └── 自行車-HS碼對照表-基準版.xlsx
├── scripts/                        # 抓取與解析腳本
│   ├── bulk_convert_bike.py        # ★ Markdown → HTML（主要轉換器）
│   ├── fetch.py                    # requests-based 抓一般網頁
│   ├── fetch_browser.py            # Playwright 抓 JS-rendered（UKMTO）
│   ├── fetch_customs_auto.py       # 關務署 HS 5 碼（含 Tesseract OCR）
│   ├── fetch_customs_oneshot.py    # 關務署人工 CAPTCHA 版本
│   └── verify.py                   # 解析 → data/processed/<week>.md
├── data/
│   ├── raw/<week>/                 # 原始抓取（gitignored）
│   ├── processed/                  # verify.py 輸出
│   └── state/
│       └── drewry-weekly-history.json   # Drewry 跨週累積（下期讀上期實數用）
└── specs/                          # 設計文件（繼承自原 aiez-linenews）
```

---

## 部署流程

```
md_report/*.md
      │
      ▼
scripts/bulk_convert_bike.py
      │
      ├─► briefs-manifest.json
      ├─► html_report_archive/*.html
      └─► index.html
            │
            ▼
        git push main
            │
            ▼
   GitHub Actions CI/CD（Azure SWA 自動產生）
            │
            ▼
   Azure Static Web Apps
      ├── 靜態檔案（Edge CDN）
      └── /api/feedback（Managed Functions → Table Storage）
```

Push 到 `main` 觸發 CI/CD，Azure 將整個 repo 根目錄（`app_location: "/"`）直接上傳。**沒有 build step、也沒有測試**。

---

## 後端 API

### `POST /api/feedback`

記錄讀者對每篇週報的按讚／按爛。

**Request body：**

```json
{
  "page": "/html_report_archive/bike-weekly-2026-W20.html",
  "reaction": "like"
}
```

**Response：**

| HTTP Status | Body | 說明 |
|---|---|---|
| `200` | `{ "ok": true }` | 成功計次 |
| `400` | `{ "error": "bad request" }` | 格式錯誤 |
| `500` | `{ "error": "storage not configured" }` | 環境變數未設定 |
| `503` | `{ "error": "contention, try again" }` | 高競爭重試超限 |

**儲存位置**：Azure Table Storage，table 名稱 `feedbackCounts`，PartitionKey = `encodeURIComponent(page)`，RowKey = `like`/`dislike`，欄位 `count` 累加。

**環境變數**：`FEEDBACK_STORAGE_CONN`（Azure SWA → Configuration → Application settings 設定）

> 與 `aiez-linenews`（中東日報）後端**完全相容**，可共用同一個 Azure Storage Account；以 page 路徑做 partition 天然隔離不衝突。

---

## 手動批次重建

新增、修改、刪除任何 `md_report/*.md` 後，跑：

```bash
python scripts/bulk_convert_bike.py
```

會：
1. 解析 `md_report/bike-weekly-*.md` 全部檔案
2. 重產 `html_report_archive/bike-weekly-*.html` 全部
3. 重寫 `briefs-manifest.json`
4. 把最新一份複製到 `index.html`

接著 `git add -A && git commit && git push`。

---

## 來源規則

- 每個關鍵數字 ≥ 1 個 T1（官方/原始）來源 或 ≥ 2 個 T2（專業媒體）互證
- 衝突數字並列各方說法，不擅自取均值
- 抓不到 source 標「待補」，**禁止用 LLM 記憶填空**
- 付費資料庫一律只用公開摘要
- **HS 碼原則**：6 碼為預設；廣義碼（如 8506.50 鋰電池）標 ⚠ 註記；8 碼僅在 6 碼太寬時用
- **關務署數據原則**：當月公布為「初步值」，後續修正為「確定值」，引用時必須標示

---

## 撰寫規則（文字風格）

報告受眾為**台灣自行車產業中小企業**，撰寫時須遵守以下四項規則：

### 1. 出口動能指標 — 同月二次跑時沿用當月數據判讀

「自行車出口動能」屬於月度指標，每月只有一次新數據（關務署初步值次月公布、確定值翌月修正）。同月跑第二次週報時，仍依當月已公布的初步值給出判讀（如「分化（電動自行車續弱）」、「疲弱」、「整體下滑」等），**不可空白、也不可寫「待 X 月確定值」**。

### 2. 全文一律繁體中文，不留英文原文

從外電（Drewry、The Loadstar、Bike Europe、BRAIN 等）摘錄的內容、論點、引述語，一律翻譯為繁體中文。引述句不保留英文原文於正文中，可標示「（中譯）」說明為翻譯。**例外**：專有名詞與品牌名（Drewry、Shimano、SRAM、Trek、UKMTO、Pon Holdings 等）保留原文。

### 3. 「e-bike」一律寫「電動自行車」

所有 e-bike / E-bike / ebike 全部寫作「電動自行車」。**例外**：品牌或公司名中的 eBike（如 Porsche eBike Performance）可保留品牌原名。

### 4. 英文專有名詞首次出現時加註中文說明

文中第一次出現英文縮寫時，以括號形式標註中文全稱與說明，例如：

| 縮寫 | 標註寫法 |
|---|---|
| BAF | BAF（Bunker Adjustment Factor，燃油附加費） |
| PSS | PSS（Peak Season Surcharge，旺季附加費） |
| FAK | FAK（Freight All Kinds，整艙統一費率） |
| OEM | OEM（委託代工製造） |
| ODM | ODM（委託設計與製造） |
| WCI | WCI（World Container Index，全球貨櫃運價指數） |
| IACI | IACI（Intra-Asia Container Index，亞洲內部貨櫃運價指數） |
| SCFI | SCFI（上海貨櫃運價指數） |
| UCI | UCI（Union Cycliste Internationale，國際自由車總會） |
| HS code | HS code（Harmonized System，國際商品統一分類碼） |

同一份報告後續再出現可不重複標註。表格「來源」欄位下方的灰字機構說明（如 UKMTO、Drewry 註解）保留現行樣式。

---

## 免責聲明

> 本報告僅供參考，不構成任何投資或政策建議。

關務署初步值與 Drewry 反推上期值都明確標示在報告內。
