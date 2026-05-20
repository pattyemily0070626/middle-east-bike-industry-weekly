#!/usr/bin/env python3
"""Generate today's HTML brief from the template and update briefs-manifest.json."""
import json, re, pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
TEMPLATE = ROOT / ".claude/commands/middle-east-analysis-template-aieztrade.html"
MANIFEST = ROOT / "briefs-manifest.json"
ARCHIVE_DIR = ROOT / "html_report_archive"
ARCHIVE_DIR.mkdir(exist_ok=True)

TS = "20260504-113655"
FILENAME = f"middle-east-brief-{TS}.html"
HREF = f"/html_report_archive/{FILENAME}"

# ── replacement values ─────────────────────────────────────────────────────
DATE_FULL = "2026年5月4日"
DATE_ISO  = "2026-05-04"
DAY_COUNT = "DAY 65"
WAR_SUBTITLE = "美以對伊朗戰爭"

INDICATOR_CONFLICT        = "🔴 升級"
INDICATOR_ESCALATION      = "高"
INDICATOR_SPILLOVER       = "高"
INDICATOR_CLASS_CONFLICT  = "red"
INDICATOR_CLASS_ESCALATION= "red"
INDICATOR_CLASS_SPILLOVER = "red"

ASSESSMENT_TEXT = (
    "川普5月3日正式拒絕伊朗十四點和平方案，稱德黑蘭「尚未付出足夠代價」；同日宣布「自由計畫」（Project Freedom），"
    "調動超過<strong>1.5萬名官兵</strong>及<strong>100架以上飛機</strong>護送第三方船隻穿越霍爾木茲海峽（Strait of Hormuz）。"
    "黎巴嫩（Lebanon）停火持續遭以軍空襲破壞，南黎已有<strong>7人遇難</strong>。"
    "伊朗石油儲量告急，可用儲油空間僅剩<strong>12至22天</strong>，談判僵局令戰火重燃風險升高。"
)

SUMMARY_TEXT = (
    "過去24至48小時，美伊對峙顯著升溫。川普總統於5月3日拒絕伊朗透過巴基斯坦斡旋提交的十四點方案，"
    "並宣布啟動「自由計畫」（Project Freedom），調派美軍艦艇引導受困商船安全穿越霍爾木茲海峽，"
    "中央司令部投入逾<span class=\"data\">1.5萬</span>名士兵、<span class=\"data\">100架以上</span>飛機及無人機平台。"
    "以色列在黎巴嫩停火仍持續的情況下加強南黎空襲，造成至少<span class=\"data\">7名</span>平民死亡，"
    "美黎兩國將領則在貝魯特就停火執行進行磋商。"
    "伊朗儲油空間持續縮減，多份分析報告指出德黑蘭最快5月中旬恐被迫削減高達<span class=\"data\">50%</span>的石油產量。"
    "外交僵局與軍事壓力並存，未來7日停火是否持守仍高度不確定。"
)

TABLE1_ROWS = """\
          <tr>
            <td>1</td>
            <td class="dir-red">🔴</td>
            <td><span class="badge badge-major">重大</span></td>
            <td><a href="https://www.aljazeera.com/news/2026/5/3/trump-reviews-iranian-peace-proposal-warns-strikes-could-resume" target="_blank" rel="noopener noreferrer">Al Jazeera / CNBC</a></td>
            <td>川普拒絕伊朗十四點和平方案</td>
            <td>川普稱伊朗提案「不可接受」，拒絕德黑蘭要求<span class="data">30天</span>內結束戰爭的訴求；伊朗收到美國透過巴基斯坦傳遞的回覆，正在審查中。</td>
            <td>外交僵局加深，停火脆弱性升高，戰爭重啟風險增加；和談時間壓力與軍事對峙同步加劇。</td>
          </tr>
          <tr>
            <td>2</td>
            <td class="dir-red">🔴</td>
            <td><span class="badge badge-major">重大</span></td>
            <td><a href="https://www.axios.com/2026/05/03/trump-us-navy-iran-ships-strait-hormuz" target="_blank" rel="noopener noreferrer">Axios / NBC News</a></td>
            <td>川普宣布「自由計畫」護航霍爾木茲海峽</td>
            <td>美軍從5月5日起引導中性國船隻穿越霍爾木茲海峽（Strait of Hormuz），中央司令部投入逾<span class="data">1.5萬</span>名官兵、<span class="data">100架以上</span>飛機及無人機平台。</td>
            <td>美伊直接對峙風險劇增；伊朗若阻撓護航，停火協議將立即崩潰，美軍已明言將動武回應。</td>
          </tr>
          <tr>
            <td>3</td>
            <td class="dir-red">🔴</td>
            <td><span class="badge badge-major">重大</span></td>
            <td><a href="https://www.thenationalnews.com/news/mena/2026/05/03/lebanese-and-us-top-generals-discuss-israel-hezbollah-ceasefire-in-beirut/" target="_blank" rel="noopener noreferrer">The National / The Swipe Up</a></td>
            <td>以色列持續空襲南黎巴嫩，停火屢遭破壞</td>
            <td>以軍5月3日空襲造成南黎至少<span class="data">7人死亡</span>；以軍並強制疏散南黎至少<span class="data">11個村莊</span>。美黎兩國將領在貝魯特（Beirut）磋商停火履行。</td>
            <td>黎以衝突持續升溫，三週延長停火面臨提前崩潰危機，區域外溢風險顯著上升。</td>
          </tr>
          <tr>
            <td>4</td>
            <td class="dir-red">🔴</td>
            <td><span class="badge badge-major">重大</span></td>
            <td><a href="https://www.bloomberg.com/news/articles/2026-05-02/iran-juggles-oil-cuts-and-storage-strain-to-resist-us-blockade" target="_blank" rel="noopener noreferrer">Bloomberg / Fortune / Al Jazeera</a></td>
            <td>伊朗石油儲量趨近臨界點</td>
            <td>伊朗可用儲油空間僅剩<span class="data">12至22天</span>，已開始主動削減產量；5月中旬前恐被迫每日削減達<span class="data">150萬桶</span>。</td>
            <td>美國封鎖效果持續顯現，德黑蘭經濟壓力攀升；急迫感可能加速讓步，亦可能激化強硬反應。</td>
          </tr>
          <tr>
            <td>5</td>
            <td class="dir-neutral">⚪</td>
            <td><span class="badge badge-medium">中等</span></td>
            <td><a href="https://www.npr.org/2026/05/02/nx-s1-5808924/iran-response-trump-proposal" target="_blank" rel="noopener noreferrer">NPR / CNBC</a></td>
            <td>伊朗確認收到美國對十四點方案的回覆</td>
            <td>伊朗外交部確認收到美國透過巴基斯坦傳達的回覆，正在評估中，為雙方至今最直接的外交互動管道。</td>
            <td>雙方仍保有外交溝通管道；若伊朗下調部分要求，外交突破仍有可能，但時間壓力極為迫切。</td>
          </tr>"""

TABLE2_ROWS = """\
          <tr>
            <td>1</td>
            <td>美國</td>
            <td><span class="data">~6</span> 陣亡 / <span class="data">~60+</span> 受傷</td>
            <td>無新數據</td>
            <td>不適用</td>
            <td>不適用</td>
            <td><span class="data">~66+</span></td>
            <td>「自由計畫」啟動，逾<span class="data">1.5萬</span>名官兵集結霍爾木茲海峽</td>
          </tr>
          <tr>
            <td>2</td>
            <td>以色列</td>
            <td><span class="data">~50+</span> 陣亡 / <span class="data">~300+</span> 受傷（估計）</td>
            <td>無新數據</td>
            <td>無新數據</td>
            <td>無新數據</td>
            <td><span class="data">~350+</span></td>
            <td>持續在南黎巴嫩（Lebanon）執行空中打擊</td>
          </tr>
          <tr>
            <td>3</td>
            <td>伊朗（Iran）及伊朗陣營代理武裝<br><small>含哈瑪斯（Hamas）、真主黨（Hezbollah）、胡塞武裝（Houthis）、伊拉克民兵</small></td>
            <td><span class="data">~3,375+</span> 陣亡 / 數萬受傷<br>（伊朗本土估計）</td>
            <td>無新數據</td>
            <td>伊朗~數千、黎巴嫩~<span class="data">2,509+</span></td>
            <td>黎巴嫩新增<span class="data">7名</span>平民死亡</td>
            <td><span class="data">~6,000+</span></td>
            <td>石油產量削減，儲油空間趨近臨界點</td>
          </tr>
          <tr>
            <td>4</td>
            <td>其他影響衝突的區域行為者</td>
            <td>伊拉克民兵（PMF）<span class="data">~118</span> 陣亡</td>
            <td>無新數據</td>
            <td>海灣國家<span class="data">~28+</span> 平民死亡</td>
            <td>無新數據</td>
            <td><span class="data">~150+</span></td>
            <td>海灣諸國持續尋求中立立場</td>
          </tr>"""

TABLE3_ROWS = """\
          <tr>
            <td>1</td>
            <td>美國</td>
            <td><span class="data">~214萬</span><br>（現役<span class="data">140萬</span>＋後備<span class="data">74萬</span>）</td>
            <td><span class="data">~490</span> 艘<br>（含航母<span class="data">11</span>艘）</td>
            <td>核彈頭估計<span class="data">5,500枚</span>＋大量常規彈道與巡航飛彈</td>
            <td><span class="data">~2,100</span> 架</td>
            <td>「自由計畫」啟動，第五艦隊（Fifth Fleet）主力集結霍爾木茲海峽</td>
            <td><a href="https://www.iiss.org/publications/the-military-balance/" target="_blank" rel="noopener noreferrer">IISS 軍事力量年鑑 2025</a></td>
          </tr>
          <tr>
            <td>2</td>
            <td>以色列</td>
            <td><span class="data">~73萬</span><br>（現役<span class="data">17萬</span>＋後備<span class="data">56萬</span>）</td>
            <td><span class="data">~65</span> 艘<br>（含飛彈艇及潛艦）</td>
            <td>估計<span class="data">~400顆</span>核武器，大量先進精確制導飛彈</td>
            <td><span class="data">~339</span> 架<br>（含F-35、F-16）</td>
            <td>持續在黎巴嫩執行空中作戰，地面部隊維持高度戰備；無重大變化</td>
            <td><a href="https://www.iiss.org/publications/the-military-balance/" target="_blank" rel="noopener noreferrer">IISS 軍事力量年鑑 2025</a></td>
          </tr>
          <tr>
            <td>3</td>
            <td>伊朗</td>
            <td><span class="data">~104萬</span><br>（現役<span class="data">52萬</span>＋後備<span class="data">52萬</span>）</td>
            <td><span class="data">~398</span> 艘<br>（含快艇及潛艦）</td>
            <td>估計<span class="data">3,000枚以上</span>彈道及巡航飛彈</td>
            <td><span class="data">~551</span> 架<br>（含大量老舊型號）</td>
            <td>繼續對霍爾木茲海峽（Strait of Hormuz）實施通行管制並徵收通行費；石油生產縮減壓力增大</td>
            <td><a href="https://www.iiss.org/publications/the-military-balance/" target="_blank" rel="noopener noreferrer">IISS 軍事力量年鑑 2025</a></td>
          </tr>"""

IMPLICATIONS_ITEMS = """\
      <li><strong>「自由計畫」引爆新危機：</strong>川普同時拒絕伊朗和平方案並宣布護航行動，釋出相互矛盾的訊號。「自由計畫」（Project Freedom）雖名為人道主義，實為對伊朗霍爾木茲通行控制的直接軍事挑戰。美中央司令部已投入<span class="data">1.5萬兵力</span>及<span class="data">100架以上飛機</span>，若伊朗試圖阻撓，雙方停火將立即崩潰。</li>
      <li><strong>伊朗經濟壓力達臨界點：</strong>儲油空間僅剩<span class="data">12至22天</span>，若5月中旬前無法達成外交突破，伊朗將被迫大幅削減石油產量，嚴重衝擊政府財政收入。此一壓力可能推動德黑蘭加快讓步，但同樣可能激化國內強硬派，增加衝突誤判與意外開戰的風險。</li>
      <li><strong>黎巴嫩停火岌岌可危：</strong>以色列持續在停火期間對南黎發動空襲，三週延長停火已遭多次違反，造成平民傷亡。若暴力持續升級，停火有提前破局的高度可能，進而動搖整體美伊停火框架，引發全面復戰，區域外溢態勢將急速惡化。</li>"""

SOURCES_ITEMS = """\
      <li><a href="https://www.aljazeera.com/news/liveblog/2026/5/3/iran-war-live-trump-says-reviewing-14-point-plan-israel-pounds-lebanon" target="_blank" rel="noopener noreferrer">Al Jazeera — 伊朗戰爭最新動態（5月3日直播）</a></li>
      <li><a href="https://www.npr.org/2026/05/02/nx-s1-5808924/iran-response-trump-proposal" target="_blank" rel="noopener noreferrer">NPR — 伊朗提交十四點方案回應</a></li>
      <li><a href="https://www.cnbc.com/2026/05/03/trump-iran-war-peace-proposal.html" target="_blank" rel="noopener noreferrer">CNBC — 伊朗和平提案最新動態</a></li>
      <li><a href="https://www.thenationalnews.com/news/mena/2026/05/03/irans-14-point-plan-demands-war-end-sanctions-relief-and-us-withdrawal/" target="_blank" rel="noopener noreferrer">The National — 伊朗十四點方案詳情</a></li>
      <li><a href="https://www.aljazeera.com/news/2026/5/3/trump-reviews-iranian-peace-proposal-warns-strikes-could-resume" target="_blank" rel="noopener noreferrer">Al Jazeera — 川普拒絕伊朗和平提案</a></li>
      <li><a href="https://www.newsweek.com/trump-iran-not-paid-big-enough-price-new-peace-plan-11907579" target="_blank" rel="noopener noreferrer">Newsweek — 川普稱伊朗「尚未付出足夠代價」</a></li>
      <li><a href="https://www.axios.com/2026/05/03/trump-us-navy-iran-ships-strait-hormuz" target="_blank" rel="noopener noreferrer">Axios — 川普宣布美軍護航霍爾木茲海峽</a></li>
      <li><a href="https://www.nbcnews.com/politics/donald-trump/trump-says-us-will-begin-escorting-ships-strait-hormuz-rcna343364" target="_blank" rel="noopener noreferrer">NBC News — 美軍引導船隻穿越霍爾木茲</a></li>
      <li><a href="https://www.voiceofemirates.com/en/news/2026/05/04/trump-announces-project-freedom-to-escort-ships-through-the-strait-of-hormuz/" target="_blank" rel="noopener noreferrer">Voice of Emirates — 「自由計畫」（Project Freedom）詳情</a></li>
      <li><a href="https://www.thenationalnews.com/news/mena/2026/05/03/lebanese-and-us-top-generals-discuss-israel-hezbollah-ceasefire-in-beirut/" target="_blank" rel="noopener noreferrer">The National — 美黎將領在貝魯特磋商停火</a></li>
      <li><a href="https://www.theswipeup.com/2026/05/israel-attacks-south-lebanon-killing.html" target="_blank" rel="noopener noreferrer">The Swipe Up — 以色列空襲南黎巴嫩</a></li>
      <li><a href="https://www.bloomberg.com/news/articles/2026-05-02/iran-juggles-oil-cuts-and-storage-strain-to-resist-us-blockade" target="_blank" rel="noopener noreferrer">Bloomberg — 伊朗石油削減與儲量壓力</a></li>
      <li><a href="https://fortune.com/2026/05/02/iran-oil-production-cuts-crude-storage-limits-tank-tops-us-naval-blockade-hormuz/" target="_blank" rel="noopener noreferrer">Fortune — 伊朗石油生產分析</a></li>
      <li><a href="https://www.aljazeera.com/economy/2026/4/29/is-irans-oil-storage-nearly-full-and-will-it-have-to-cut-production" target="_blank" rel="noopener noreferrer">Al Jazeera — 伊朗石油儲量分析</a></li>
      <li><a href="https://www.cnn.com/2026/05/02/world/live-news/iran-war-news" target="_blank" rel="noopener noreferrer">CNN — 中東衝突第64天</a></li>
      <li><a href="https://en.wikipedia.org/wiki/2026_Iran_war" target="_blank" rel="noopener noreferrer">Wikipedia — 2026年伊朗戰爭</a></li>"""

# ── load manifest, prepend new entry ──────────────────────────────────────
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
new_entry = {
    "date": DATE_ISO,
    "day": "Day 65",
    "title": "川普宣布「自由計畫」護航霍爾木茲海峽，拒絕伊朗十四點方案；伊朗儲油空間僅剩12至22天",
    "href": HREF,
    "ind": "red",
    "label": "升級"
}
# de-dup by href then prepend
manifest = [new_entry] + [e for e in manifest if e["href"] != HREF]
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Manifest updated: {len(manifest)} entries")

# archive items for this page = manifest[1:] (skip current)
archive_items_json = json.dumps(manifest[1:], ensure_ascii=False)

# ── load and fill template ─────────────────────────────────────────────────
tmpl = TEMPLATE.read_text(encoding="utf-8")

replacements = {
    "{{DATE_FULL}}":                DATE_FULL,
    "{{DATE_ISO}}":                 DATE_ISO,
    "{{DAY_COUNT}}":                DAY_COUNT,
    "{{WAR_SUBTITLE}}":             WAR_SUBTITLE,
    "{{INDICATOR_CONFLICT}}":       INDICATOR_CONFLICT,
    "{{INDICATOR_ESCALATION}}":     INDICATOR_ESCALATION,
    "{{INDICATOR_SPILLOVER}}":      INDICATOR_SPILLOVER,
    "{{INDICATOR_CLASS_CONFLICT}}": INDICATOR_CLASS_CONFLICT,
    "{{INDICATOR_CLASS_ESCALATION}}":INDICATOR_CLASS_ESCALATION,
    "{{INDICATOR_CLASS_SPILLOVER}}":INDICATOR_CLASS_SPILLOVER,
    "{{ASSESSMENT_TEXT}}":          ASSESSMENT_TEXT,
    "{{SUMMARY_TEXT}}":             SUMMARY_TEXT,
    "{{TABLE1_ROWS}}":              TABLE1_ROWS,
    "{{TABLE2_ROWS}}":              TABLE2_ROWS,
    "{{TABLE3_ROWS}}":              TABLE3_ROWS,
    "{{IMPLICATIONS_ITEMS}}":       IMPLICATIONS_ITEMS,
    "{{SOURCES_ITEMS}}":            SOURCES_ITEMS,
    "{{ARCHIVE_ITEMS_JSON}}":       archive_items_json,
}

html = tmpl
for k, v in replacements.items():
    html = html.replace(k, v)

import sys, re as _re
remaining = _re.findall(r'\{\{[A-Z_]+\}\}', html)
if remaining:
    print(f"WARNING: unreplaced placeholders: {remaining}", file=sys.stderr)
    sys.exit(1)

# ── write snapshot + index ─────────────────────────────────────────────────
snapshot = ARCHIVE_DIR / FILENAME
snapshot.write_text(html, encoding="utf-8")
print(f"Snapshot written: {snapshot}")

index = ROOT / "index.html"
index.write_text(html, encoding="utf-8")
print(f"index.html written: {index}")
