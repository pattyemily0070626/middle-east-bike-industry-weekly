# 執行計畫｜讀者喜歡／不喜歡回饋功能

> 對應需求：讀者捲動至「04 戰略意涵」區段時彈出背景 Blur 對話框，以 👍／👎 收集回饋，每頁獨立計數。

## Context

`index.html` 與 `html_report_archive/*.html` 目前是純靜態閱讀頁，沒有讀者互動數據。使用者希望在讀者捲到「04 戰略意涵」時跳出背景 Blur 的對話框，用按讚／按爛收集意見；**每一頁獨立計次**（index 首頁 vs. 每篇歷史快照各自一組數字）。

已確認的產品決策：
- 後端＝**Azure Functions + Azure Table Storage**（與既有 Azure SWA 同帳下，成本接近零）
- Modal 內**只收集、不顯示票數**，投完只出現「謝謝你的回饋」
- 同一頁**每位讀者一生只彈一次**（localStorage 永久旗標，不論有無投票）

---

## 架構總覽

```
Browser (reader)
   │ ① IntersectionObserver 偵測 #card-04-implications 進入視窗
   │ ② 若 localStorage['fb_shown_' + location.pathname] 為空 → 開啟 Modal、寫旗標
   │ ③ 讀者點 👍 / 👎
   │ ④ fetch POST /api/feedback  { page, reaction }
   ▼
Azure Static Web Apps
   ├─ 靜態資源（既有）
   └─ /api/feedback ← 新增 Azure Function（Node 20）
   ▼
Azure Table Storage「feedbackCounts」
   PartitionKey = 頁面路徑, RowKey = like|dislike, count = 累計票數
```

Azure SWA 原生支援「同一 repo 放 `/api` 資料夾 = 自動部署為 Managed Functions」，推上 `main` 即部署。

---

## A. 前端 Modal

### A1. 在 template 的「04 戰略意涵」卡片加錨點

檔案：`.claude/commands/middle-east-analysis-template-aieztrade.html`

```html
<div class="card" id="card-04-implications">
  <div class="card-head">
    <h2><span class="num">04</span>戰略意涵</h2>
```

### A2. 在 `</body>` 前注入 Modal 的 HTML + CSS + JS

**HTML 骨架**
```html
<div class="fb-overlay" id="fbOverlay" aria-hidden="true">
  <div class="fb-modal" role="dialog" aria-labelledby="fbTitle" aria-describedby="fbSub">
    <button class="fb-close" id="fbClose" aria-label="關閉">×</button>
    <h3 id="fbTitle">這篇簡報對你有幫助嗎？</h3>
    <p id="fbSub" class="fb-sub">你的回饋會幫助我們改善每日情報內容</p>
    <div class="fb-actions">
      <button class="fb-btn fb-like" data-reaction="like">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 22V11M2 13v7a2 2 0 002 2h3M20.5 11H13l1.5-5.5a1.5 1.5 0 00-2.9-.8L7 11v11h11.7a2 2 0 001.98-1.7l1.3-7A2 2 0 0020.5 11z"/></svg>
        <span>喜歡</span>
      </button>
      <button class="fb-btn fb-dislike" data-reaction="dislike">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 2v11M22 11V4a2 2 0 00-2-2h-3M3.5 13H11l-1.5 5.5a1.5 1.5 0 002.9.8L17 13V2H5.3a2 2 0 00-1.98 1.7l-1.3 7A2 2 0 003.5 13z"/></svg>
        <span>不喜歡</span>
      </button>
    </div>
    <div class="fb-thanks" hidden>謝謝你的回饋！</div>
  </div>
</div>
```

**CSS 重點**（沿用既有 design tokens：`--bg-frost-strong`、`--accent-blue`、`--accent-green`、`--accent-red`、`--radius-lg`、`--shadow-frost`）
- `.fb-overlay`：`position:fixed; inset:0; background:rgba(16,24,40,0.35); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); opacity:0; pointer-events:none; transition:opacity .3s; z-index:2000;`
- `.fb-overlay.open`：`opacity:1; pointer-events:auto;`
- `.fb-modal`：白色卡片、`border-radius:var(--radius-lg)`、`box-shadow:var(--shadow-frost)`、`padding:2rem`、`max-width:440px`；`transform:scale(.96)` → `scale(1)` 進場動畫
- `.fb-btn`：大按鈕；`.fb-like:hover { background:rgba(48,164,108,0.08); color:var(--accent-green); }`、`.fb-dislike:hover { background:rgba(229,72,77,0.08); color:var(--accent-red); }`
- 手機 `@media (max-width:480px)`：Modal 改為底部抽屜（`bottom:0; border-radius:20px 20px 0 0; transform:translateY(100%)` → `translateY(0)`）

**JS 行為**（約 60 行，IIFE 包起來）
```js
(function(){
  const KEY = 'fb_shown_' + location.pathname;
  if (localStorage.getItem(KEY)) return; // 本頁曾彈過 → 不裝觀察者

  const overlay = document.getElementById('fbOverlay');
  const target  = document.getElementById('card-04-implications');
  const closeBtn = document.getElementById('fbClose');
  const thanks = overlay.querySelector('.fb-thanks');
  const actions = overlay.querySelector('.fb-actions');
  if (!overlay || !target) return;

  function open(){
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden','false');
    localStorage.setItem(KEY, Date.now().toString()); // 不論有無投都不再彈
    closeBtn.focus();
  }
  function close(){
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden','true');
  }

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) { open(); io.disconnect(); break; }
    }
  }, { threshold: 0.3 });
  io.observe(target);

  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  closeBtn.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.classList.contains('open')) close();
  });

  overlay.querySelectorAll('.fb-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const reaction = btn.dataset.reaction;
      actions.style.display = 'none';
      thanks.hidden = false;
      try {
        await fetch('/api/feedback', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ page: location.pathname, reaction })
        });
      } catch (_) { /* 靜默失敗，不中斷使用者體驗 */ }
      setTimeout(close, 1200);
    }, { once: true });
  });
})();
```

---

## B. 後端 `/api/feedback`

### B1. 新增三個檔案

**`/api/package.json`**
```json
{
  "name": "api",
  "version": "1.0.0",
  "dependencies": {
    "@azure/data-tables": "^13.3.0"
  }
}
```

**`/api/feedback/function.json`**
```json
{
  "bindings": [
    { "authLevel":"anonymous", "type":"httpTrigger", "direction":"in",
      "name":"req", "methods":["post"] },
    { "type":"http", "direction":"out", "name":"res" }
  ]
}
```

**`/api/feedback/index.js`**
```js
const { TableClient } = require('@azure/data-tables');

const TABLE = 'feedbackCounts';
const PAGE_RE = /^[A-Za-z0-9/_.\-]{1,256}$/;
const REACTIONS = new Set(['like', 'dislike']);

module.exports = async function (context, req) {
  const page = req.body?.page;
  const reaction = req.body?.reaction;

  if (!page || !PAGE_RE.test(page) || !REACTIONS.has(reaction)) {
    context.res = { status: 400, body: { error: 'bad request' } };
    return;
  }

  const conn = process.env.FEEDBACK_STORAGE_CONN;
  const client = TableClient.fromConnectionString(conn, TABLE);
  try { await client.createTable(); } catch (_) { /* already exists */ }

  const pk = encodeURIComponent(page);
  const rk = reaction;

  // 樂觀鎖 + retry 3 次處理並發
  for (let i = 0; i < 3; i++) {
    try {
      const entity = await client.getEntity(pk, rk);
      entity.count = (entity.count || 0) + 1;
      await client.updateEntity(entity, 'Replace', { etag: entity.etag });
      context.res = { status: 200, body: { ok: true } };
      return;
    } catch (e) {
      if (e.statusCode === 404) {
        try {
          await client.createEntity({ partitionKey: pk, rowKey: rk, count: 1 });
          context.res = { status: 200, body: { ok: true } };
          return;
        } catch (ce) {
          if (ce.statusCode !== 409) throw ce;
          // 被別人搶先建 → 下一輪重試
        }
      } else if (e.statusCode !== 412) {
        throw e; // 412 = etag mismatch → 重試
      }
    }
  }
  context.res = { status: 503, body: { error: 'contention' } };
};
```

### B2. Azure 端一次性設定（不在 repo 內）

1. `az storage account create --name <storageName> --resource-group <rg> --location eastasia --sku Standard_LRS`
2. `az storage account show-connection-string --name <storageName> --resource-group <rg>` → 複製連線字串
3. 在 SWA 的 **Environment variables / Application settings** 新增 `FEEDBACK_STORAGE_CONN=<連線字串>`
   - CLI：`az staticwebapp appsettings set --name <swaName> --setting-names FEEDBACK_STORAGE_CONN="<連線字串>"`
   - ⚠️ **不要**使用 `AzureWebJobsStorage` 作為 App Setting 名稱 —— 此為 Azure Functions runtime 保留名，SWA managed Functions 會因保留名衝突而啟動失敗（本專案 commit 2a60600 由此修正）。
4. Table `feedbackCounts` 不需手動建，function 第一次呼叫會自動建立

---

## C. 一次性 patch 腳本（套用到既有 11 個檔案）

檔案：`.firecrawl/scratchpad/inject_feedback_widget.py`

**行為：**
1. 定義常數：
   - `CARD_ANCHOR_REGEX`：抓「04 戰略意涵」那張 card 的 `<div class="card">`（定位：往下查到 `<h2><span class="num">04</span>戰略意涵`）→ 替換為 `<div class="card" id="card-04-implications">`
   - `MODAL_BLOCK`：完整的 HTML+CSS+JS 合併字串（含 sentinel 註解 `<!-- feedback-widget:v1 -->`）
2. 掃 `index.html` 與 `html_report_archive/middle-east-brief-*.html`（共 11 檔）
3. 對每個檔案：
   - 若已見 sentinel → skip（冪等可重跑）
   - 否則 regex 注入錨點，並在 `</body>` 前插入 `MODAL_BLOCK`
4. 輸出：列出已修改／已略過的檔案

這樣 template 同步更新後，未來新 brief 自帶 Modal；此腳本只為回填歷史。

---

## 要改／要新增的檔案清單

**改：**
- `.claude/commands/middle-east-analysis-template-aieztrade.html`（加 id、加 Modal 區塊）
- `index.html`（由 patch 腳本注入）
- `html_report_archive/middle-east-brief-*.html` × 10（由 patch 腳本注入）

**新增：**
- `/api/package.json`
- `/api/feedback/function.json`
- `/api/feedback/index.js`
- `.firecrawl/scratchpad/inject_feedback_widget.py`

**Azure 側（不在 repo）：**
- 1 個 Storage Account（eastasia, Standard LRS）
- SWA App Setting：`FEEDBACK_STORAGE_CONN=<連線字串>`

**不動：**
- `briefs-manifest.json`（格式不變）
- `staticwebapp.config.json`（不需要新路由規則，`/api/*` 由 SWA 自動代理）
- 既有 hamburger menu / CSS tokens / design system 完全不動

---

## 驗證步驟

1. 本機執行 patch 腳本：`python3 .firecrawl/scratchpad/inject_feedback_widget.py`，確認 11 檔都被改
2. 瀏覽器開啟 `index.html`（`file://` 即可），捲到第 04 卡 → Modal 自動彈出；點喜歡 → 按鈕消失、顯示「謝謝你的回饋」、1.2s 後關閉；fetch 會失敗（本機無 API）但 UX 流程正確
3. 重新整理 → Modal **不應再彈**
4. 換開另一篇 archive → 應再彈一次（key 隨 `pathname` 變）
5. 推上 `main`，等 SWA 部署完，造訪 `https://gentle-forest-09c056000.7.azurestaticapps.net/` 重跑以上流程，這次 fetch 應回 200
6. 在 Azure Storage Explorer 看 `feedbackCounts`：`PartitionKey=%2F, RowKey=like, count=1`（首頁）；每篇 archive 各自有獨立 PartitionKey
7. 手機 viewport 確認 Modal 為底部抽屜、按鈕可點
8. DevTools → Application → Local Storage 看到 `fb_shown_<path>` 鍵被寫入
9. Network 面板確認 `/api/feedback` 是 POST + 200

---

## 風險與備註

- **灌水風險**：前端 localStorage 是軟擋，要刷仍可清 localStorage。若日後灌水嚴重再加 IP daily rate-limit（另起 `feedbackRateLimit` table）或匿名指紋去重。此版先不做。
- **CORS**：同源呼叫 `/api/feedback`，SWA 自動處理。
- **Node runtime**：SWA Managed Functions 預設 Node 20，`@azure/data-tables` 相容。
- **部署順序建議**：先在 Portal 設好 `FEEDBACK_STORAGE_CONN` App Setting，再 push `main`；若順序相反，Function 會 500，但前端 fetch 靜默失敗、UX 不崩。

---

## 執行順序（預計動手時的步驟）

1. 先在 Azure Portal（或 `az` CLI）建 Storage Account、拿連線字串、設到 SWA App Setting
2. 本地寫 `/api/` 三個檔
3. 本地改 template（加 id + Modal 區塊）
4. 本地寫 `.firecrawl/scratchpad/inject_feedback_widget.py` 並跑一次回填 11 個既有檔案
5. 本地用 `file://` 驗證 UX 正確（步驟 1–4 驗證）
6. `git add` 全部 → `git commit` → `git pull --rebase origin main` → `git push origin main`
7. 輪詢 SWA workflow 到 completed
8. 從部署 log 抓真實 URL，線上驗證（步驟 5–9 驗證）
9. Azure Storage Explorer 確認票數寫入
