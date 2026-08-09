# ms_starforce_optimizer

新楓之谷（台服）**星力強化模擬器與成本計算器**。回答一個問題：把某件裝備衝到 N 星，
哪種打法最省，要花多少。

輸出兩種東西：`starforce/sim_data/` 的模擬資料集，以及 `docs/` 的 GitHub Pages 網站。

---

## 1. 執行指令速查

Python 3.14，**零第三方依賴**，測試用標準庫 `unittest`。

```bash
# 測試（273 個）
cd C:\ms_program\ms_starforce_optimizer; python -m unittest discover -s tests -t .

# 本地預覽網站 → http://localhost:8000
cd C:\ms_program\ms_starforce_optimizer; python -m http.server -d docs 8000

# 互動式手動模擬
cd C:\ms_program\ms_starforce_optimizer; python play.py

# 單次批次模擬（改檔頭 SETTINGS 區塊）
cd C:\ms_program\ms_starforce_optimizer; python main.py
```

Windows 上若中文輸出亂碼，先 `$env:PYTHONIOENCODING = "utf-8"`。
Python 絕對路徑：`C:\Users\asus\AppData\Local\Programs\Python\Python314\python.exe`

---

## 2. 架構地圖

資料刻意分成**固定**與**浮動**兩層——官方改版才會變的放程式碼，隨市場波動的放 JSON。

### `starforce/`（2,613 行）

| 模組 | 行 | 職責 |
|---|---|---|
| `static_data.py` | 355 | 固定資料：強化機率、強化費用、修復楓幣、修復裝備數、突破星捲清單 |
| `volatile_data.py` | 227 | 讀 `data/volatile.json`：星捲價、突破星捲價、裝備目錄（含別名正規化） |
| `rules.py` | 171 | 規則查詢層：星力上限、費用、修復、痕跡星力、星捲價格 |
| `engine.py` | 321 | `RunConfig` / `RunResult` / `simulate_once`——單趟模擬 |
| `policy.py` | 519 | **策略迭代求解**：`optimal_policy` / `expected_total` / `sweep_policies` |
| `stats.py` | 231 | 蒙地卡羅彙總、分位數、`to_dict()` |
| `session.py` | 405 | 手動模擬：一次一個動作，可重播 |
| `autorun.py` | 181 | 自動驅動 `Session` 直到停止條件 |
| `sim_data_loader.py` | 123 | 從 `simulations.json` 取出重建成本 |
| `units.py` | 20 | 楓幣顯示單位（億） |

### 根目錄腳本

| 腳本 | 行 | 用途 |
|---|---|---|
| `sweep.py` | 350 | 從零開始的掃描 → `sim_data/simulations.json` |
| `sweep_marginal.py` | 212 | 已持有 22 星以上的邊際成本 → `sim_data/marginal.json` |
| `build_site_data.py` | 708 | 轉出 `docs/data/*.json` 給網站 |
| `main.py` / `play.py` | 191 / 302 | 批次與互動入口 |

### `docs/`（GitHub Pages，14 支 JS、2,545 行）

五個分頁：手動模擬、懶人包、數據瀏覽、機率表、物價設定。
`app.js` 是進入點，`ui-*.js` 各管一頁，`rules.js` / `policy.js` / `session.js` 是引擎。

---

## 3. 資料流與再生順序

```
data/volatile.json  ──┐
                      ├─→ sweep.py ──→ sim_data/simulations.json ──┐
starforce/static_data ┘                                            │
                                                                   ↓
                        sweep_marginal.py ──→ sim_data/marginal.json
                                                                   ↓
                        build_site_data.py ──→ docs/data/*.json ──→ 網站
```

**順序不可顛倒。** `sweep_marginal.py` 的「重建成本」是從 `simulations.json` 取
「該裝備點到 22 星的最低平均成本」。改完物價先跑 marginal，會用到舊價格算出來的重建成本。

改價後的完整流程：改 `data/volatile.json` → `sweep.py` → `sweep_marginal.py` → `build_site_data.py`。
全套約 20 分鐘。**這類長時間腳本交給使用者自己執行，不要代跑。**

兩份資料集的 `meta.prices` 都存有當次價格快照，`meta.targets_completed` 可判斷是否跑完
（sweep 每完成一個目標星就寫檔一次）。

---

## 4. 領域規則速查

**一次強化有三種結果**：成功（+1 星）、維持（不變）、破壞（變成裝備痕跡）。
V272 已移除下滑與「連續失敗必成功」，所以每次嘗試是無記憶的——這是 `policy.py`
能用封閉解求最佳策略的前提。

**破壞從 15 星才開始**，23 星以上破壞率 18%、成功率僅 8.5%。

**痕跡封頂 22 星**：在 23~30 星被破壞，痕跡也只有 22 星。

**兩種修復策略**（`RepairPolicy`）
- `FULL`：付修復楓幣 + 1~4 件同款裝備，回到痕跡的星力
- `TO_12`：付 1 件裝備回到 12 星，再用星捲爬回起始星力（`OWNED` 模式則套用固定重建成本回到 22 星）

**兩種起始模式**（`StartMode`）
- `SCROLL`：買一張星捲起手，因此 `start_star` 限 15~20
- `OWNED`：手上已有該星裝備，開局不花錢——用來問「已經 22 星了，衝 25 星要多少」

**突破星捲**：對單一星階做一次額外嘗試，成功 +1 星，失敗原地不動，**不會破壞、不吃裝備**。
以 `(上限星, 成功率萬分位)` 識別，如 `(23, 3000)` = 突破23星30%。只能在 `星力+1 ≤ 上限星` 時使用。
它讓高星階的最佳解變成「完全不強化」——零破壞、零裝備消耗。

**成本三流**：`total_meso`（強化費+修復楓幣+星捲）、`equipment_cost`（修復吃掉的裝備）、
`rebuild_cost`（OWNED 模式的重建）。開局那件基礎裝備**不計成本**（比較策略時是常數）。

---

## 5. Python ↔ JS 雙實作與對拍機制

**最容易踩的坑。** 規則層與求解層在兩邊各有一份實作：

| Python | JS | 內容 |
|---|---|---|
| `rules.py` + `static_data.py` | `docs/js/rules.js` | 規則與費用表 |
| `policy.py` | `docs/js/policy.js` | 策略求解 |
| `session.py` | `docs/js/session.js` | 手動模擬引擎 |
| `autorun.py` | `docs/js/autorun.js` | 自動驅動 |

**改動規則或求解邏輯時，兩邊都要改。**

驗證手段是 `docs/data/parity.json` + `docs/selftest.html`（頁尾「引擎對拍」連結）：
`build_site_data.py` 產生腳本化骰子的重播案例、策略求解案例、重新計價案例，
JS 端重播必須得到相同結果。`tests/test_site_data.py` 檢查這些資料的完整性。

⚠️ 對拍**沒有涵蓋蒙地卡羅分位數**——JS 端目前不跑 MC。

**JS 已能即時重算的**：平均成本（`reprice.js`，因為成本對價格是線性的）、最佳策略
（`policy.js` 即時求解）。**不能重算的**：分位數 p5~p99，換價格會改變試驗間的排序。

---

## 6. 常見陷阱

- **改價後要重跑三支腳本**，順序見第 3 節
- **130 等已完全移除**（官方修復表無該欄位），星捲只剩 **15~20 星**（10~14 同價、無破壞風險）
- **`marginal.json` 的 TO_12 列分位數偏樂觀**：重建成本以固定平均值代入，總平均正確但上緣分位數偏低
- **突破星捲清單不是公告數據**，是遊戲內販售品項，沒有 URL 可對照，但仍屬固定資料
- **機率與費用來自 2025-06-26 的 V272 事前公告**，原文註明費率可能調整
- Windows / PowerShell 5.1 不支援 `&&`、`||`、三元運算子

---

## 7. Git

分支流程走 `feature/*` + PR。歷史上多數變更都經 `feature/github-pages-frontend` 併入 `main`。
Commit message 標題英文、內容繁中（Conventional Commits）。

---

## 8. 目前狀態

> 這一節會過時，改動時記得更新。

- 分支：`feature/github-pages-frontend`，最新 commit `aa9caac`（移除三個分頁的說明文字卡與匯出功能）
- 測試：**273 個全過**
- `simulations.json`：645 列，目標 17~22 星，起始 15~20 星，50,000 次／組，產生於 2026-08-05
- `marginal.json`：306 列，目標 23~25 星，起始 22~24 星，50,000 次／組，產生於 2026-08-07
- 兩份資料集皆已涵蓋 `none` / `optimal` / `safe` 三種突破星捲策略
- 網站五個分頁皆可用；懶人包、數據瀏覽、物價設定三頁的說明文字卡已移除

---

## 9. 待辦與未決

> 這一節會過時，改動時記得更新。

- **把 sweep 搬到 JS 跑**：提案已評估但未定案。結論是全套約 13.3 億次抽樣、JS 估計約 1 分鐘可行，
  但**平均值與最佳策略本來就已即時重算**，真正缺的只有分位數。建議只重算螢幕上可見的列，
  而非搬整套。需先補：`session.js` 的 OWNED 模式與重建成本、可設種子的 PRNG、Web Worker
- **`data/volatile.json` 的 `aliases` 全是空陣列**——正規化已能處理中文數字／全形數字／空白，
  但沒有圈內常用簡稱
- **`marginal` 分位數的精度問題**：若要讓 TO_12 的 p90／p99 可信，需改成從已存分位數做逆 CDF 抽樣，
  或保留每趟原始樣本
