# 🚀 Alpaca 美股全自動投資系統 — 開發計劃書

> 版本：v1.0 | 日期：2026-05-24  
> **免責聲明：本系統所有輸出內容（排名、績效、通知）僅供資訊整理與研究參考，不構成任何投資建議。投資有風險，請使用者自行判斷。**

---

## 🗂 專案摘要（快速了解）

本專案是一套全自動美股投資輔助系統，核心功能：

| 功能 | 說明 |
|------|------|
| 自動下單 | 根據 JSON 策略自動執行買賣 |
| 每日報告 | Email 於每天上午 6 點發送 |
| Streamlit Dashboard | 視覺化帳戶、持倉、績效 |
| 多帳戶支援 | 每帳戶同時只能綁定一個策略 |
| 策略擴充 | 新增策略只需新增 JSON，不改 Python |
| GitHub Actions | 每日自動觸發所有帳戶的買賣流程 |

---

## 📁 專案目錄結構

```
alpaca-dashboard/
├── .github/
│   └── workflows/
│       └── daily_trade.yml          # 每日自動觸發工作流程
├── accounts/
│   └── accounts.json                # 多帳戶設定
├── strategies/
│   ├── top10_nasdaq.json            # 策略：NASDAQ 前十
│   ├── momentum.json                # 策略：動能
│   └── schema.json                  # 策略 JSON Schema 規範
├── reports/
│   ├── model/
│   │   └── YYYY-MM-DD_acct_id.json  # 每日報告（JSON Model）
│   └── view/
│       └── email_template.html      # 報告顯示模板
├── src/
│   ├── api/
│   │   └── alpaca_client.py         # Alpaca API 封裝
│   ├── data/
│   │   ├── market_data.py           # 市場資料抓取
│   │   └── pe_ratio.py              # 本益比計算
│   ├── engine/
│   │   ├── strategy_loader.py       # 讀取 JSON 策略
│   │   ├── trade_executor.py        # 執行買賣
│   │   └── rebalancer.py            # 再平衡邏輯
│   ├── report/
│   │   ├── report_generator.py      # 產生 JSON 報告
│   │   └── email_sender.py          # Email 發送
│   └── dashboard/
│       └── app.py                   # Streamlit 主程式
├── tests/
│   ├── test_api.py
│   ├── test_strategy.py
│   ├── test_executor.py
│   ├── test_rebalancer.py
│   ├── test_report.py
│   └── test_email.py
├── CLAUDE.md                        # 專案記憶文件（開發者快速上手）
├── requirements.txt
└── README.md
```

---

## 🔧 策略 JSON 規範

新增策略只需新增一個 JSON 檔案，**不需修改任何 Python 程式碼**。

### 策略 Schema（strategies/schema.json）

```json
{
  "strategy_id": "top10_nasdaq_v1",
  "name": "NASDAQ 前十強",
  "description": "每日選出 NASDAQ 市值前十，各投入 10%，只買整數股",
  "version": "1.0",
  "universe": "NASDAQ",
  "selection": {
    "method": "market_cap",
    "top_n": 10
  },
  "allocation": {
    "per_position_pct": 10,
    "whole_shares_only": true
  },
  "rebalance": {
    "on_new_funds": true,
    "monthly_first_day": true
  },
  "risk": {
    "max_single_position_pct": 10,
    "stop_loss_pct": null
  },
  "notify": {
    "on_trade": true,
    "daily_report": true
  }
}
```

---

## 🏦 多帳戶設定（accounts/accounts.json）

```json
{
  "accounts": [
    {
      "account_id": "PA3WI6CYDOR5",
      "name": "Paper Account 1",
      "endpoint": "https://paper-api.alpaca.markets/v2",
      "key_env": "ALPACA_KEY_1",
      "secret_env": "ALPACA_SECRET_1",
      "active_strategy": "top10_nasdaq_v1",
      "email": "user@example.com"
    }
  ]
}
```

> ⚠️ Key 與 Secret 儲存於 GitHub Secrets 環境變數，不寫入程式碼。

---

## 📊 每日報告 JSON Model（reports/model/）

```json
{
  "report_date": "2026-05-24",
  "account_id": "PA3WI6CYDOR5",
  "cash": 100000.00,
  "portfolio_value": 100000.00,
  "equity": 100000.00,
  "daily_pnl": { "amount": 0.00, "pct": 0.00 },
  "total_return": { "amount": 0.00, "pct": 0.00 },
  "drawdown": { "current_pct": 0.00, "max_pct": 0.00 },
  "nav_history": [
    { "date": "2026-05-24", "nav": 100000.00 }
  ],
  "benchmark": {
    "QQQ": { "1d": 0.0, "1w": 0.0, "1m": 0.0 },
    "SPY": { "1d": 0.0, "1w": 0.0, "1m": 0.0 }
  },
  "positions": [
    {
      "symbol": "AAPL",
      "shares": 10,
      "avg_cost": 180.00,
      "current_price": 182.00,
      "market_value": 1820.00,
      "weight_pct": 1.82,
      "pnl_1d_pct": 1.1,
      "pnl_1w_pct": 2.3,
      "pnl_1m_pct": 5.6,
      "pe_ratio": 28.5
    }
  ],
  "top10_today": ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","COST","NFLX"],
  "top10_predicted_tomorrow": [],
  "trades_today": [
    {
      "symbol": "AAPL",
      "action": "buy",
      "shares": 10,
      "price": 180.00,
      "time": "09:35:00"
    }
  ],
  "watchlist": {
    "tech": ["AAPL","MSFT","NVDA"],
    "finance": ["JPM","BAC","GS"],
    "etf": ["QQQ","SPY","VTI"]
  }
}
```

---

## 🗓 GitHub Actions 工作流程（.github/workflows/daily_trade.yml）

```yaml
name: Daily Trade & Report

on:
  schedule:
    - cron: '0 13 * * 1-5'   # UTC 13:00 = 台灣 21:00 / 美東 09:00
  workflow_dispatch:            # 允許手動觸發

jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: 走過所有帳戶並執行策略
        env:
          ALPACA_KEY_1: ${{ secrets.ALPACA_KEY_1 }}
          ALPACA_SECRET_1: ${{ secrets.ALPACA_SECRET_1 }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
        run: python src/engine/trade_executor.py --all-accounts

  report:
    needs: trade
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: 產生報告並發送 Email
        env:
          ALPACA_KEY_1: ${{ secrets.ALPACA_KEY_1 }}
          ALPACA_SECRET_1: ${{ secrets.ALPACA_SECRET_1 }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
        run: python src/report/report_generator.py --send-email
```

> 每日美股開盤時自動走過**所有帳戶**，依各帳戶的 `active_strategy` 執行。

---

## 📐 開發階段規劃

---

### 🔷 Phase 1：基礎建設與 Alpaca 串接

**目標：** 建立專案骨架，確認可正常與 Alpaca API 溝通。

#### 開發項目
- [ ] 建立專案目錄結構
- [ ] `alpaca_client.py`：封裝 Alpaca REST API（帳戶、持倉、下單）
- [ ] `accounts.json`：多帳戶設定檔
- [ ] 環境變數管理（`.env` + GitHub Secrets）
- [ ] `CLAUDE.md`：專案記憶文件初稿

#### ✅ Test Cases（Phase 1）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T1-01 | 讀取帳戶現金 | 回傳正確 cash 數值 |
| T1-02 | 讀取帳戶持倉清單 | 回傳 positions 列表 |
| T1-03 | 讀取多帳戶資訊 | 每個帳戶各自回傳正確資料 |
| T1-04 | 錯誤 Key 時拋出明確錯誤 | 拋出 `AuthenticationError` |
| T1-05 | 多帳戶設定 JSON 格式驗證 | 格式錯誤時拋出 `ValidationError` |

---

### 🔷 Phase 2：市場資料與本益比

**目標：** 可取得 NASDAQ 市值排名、股價、P/E ratio，並可計算 1d/1w/1m 績效。

#### 開發項目
- [ ] `market_data.py`：抓取 NASDAQ 前十市值股票
- [ ] `pe_ratio.py`：計算個股本益比（P/E = 股價 ÷ 每股盈餘）
- [ ] 取得個股 1 日、1 週、1 月報酬率
- [ ] 取得 QQQ / SPY 基準績效

#### ✅ Test Cases（Phase 2）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T2-01 | 取得 NASDAQ 市值前十 | 回傳 10 個股票代碼 |
| T2-02 | 計算個股 1d/1w/1m 報酬 | 數值合理（非 None、非 0） |
| T2-03 | 計算 P/E ratio | 回傳正數，或標記「無法計算」 |
| T2-04 | 取得 QQQ/SPY 基準 | 回傳同期績效 |
| T2-05 | 市場休市日處理 | 回傳最近一個交易日資料 |

---

### 🔷 Phase 3：策略引擎與自動下單

**目標：** 從 JSON 讀取策略，自動執行買賣，支援再平衡。

#### 開發項目
- [ ] `strategy_loader.py`：讀取並驗證策略 JSON
- [ ] `trade_executor.py`：根據策略執行買賣（只買整數股）
- [ ] `rebalancer.py`：月初再平衡 + 新資金再平衡
- [ ] 即時交易通知（Email/Log）
- [ ] 走過所有帳戶的主控程式

#### 再平衡規則
- 每月 1 日自動再平衡一次
- 偵測到新資金進帳時，立即再平衡
- 每個持倉目標權重 = 10%
- 只買整數股（無條件捨去）

#### ✅ Test Cases（Phase 3）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T3-01 | 載入合法策略 JSON | 成功回傳策略物件 |
| T3-02 | 載入不合法策略 JSON | 拋出 `StrategyValidationError` |
| T3-03 | 計算應買股數（10% 配置） | 只回傳整數股，無小數 |
| T3-04 | 月初再平衡觸發 | 正確計算超/低配，並調整 |
| T3-05 | 新資金再平衡 | 偵測現金增加後觸發再平衡 |
| T3-06 | 同帳戶只使用一個策略 | 不允許同時載入兩個策略 |
| T3-07 | 帳戶切換策略 | 舊策略停用，新策略啟用 |
| T3-08 | 多帳戶獨立執行 | 帳戶 A 的操作不影響帳戶 B |
| T3-09 | Paper 模式下單成功 | 收到 Alpaca order id |
| T3-10 | 即時交易通知發送 | Email/Log 含交易細節 |

---

### 🔷 Phase 4：Streamlit Dashboard

**目標：** 提供視覺化儀表板，支援多帳戶切換。

#### Dashboard 頁面設計

```
┌─────────────────────────────────────────────┐
│  帳戶選擇：[PA3WI6CYDOR5 ▼]  日期：[今天 ▼] │
├─────────────┬─────────────┬─────────────────┤
│  現金水位   │  組合市值   │  今日損益       │
│  $100,000   │  $100,000   │  +0.00%         │
├─────────────┴─────────────┴─────────────────┤
│  NAV 走勢圖                                  │
│  [☑ QQQ] [☑ SPY] 可勾選基準                │
│  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~    │
├─────────────────────────────────────────────┤
│  回撤對比圖（含 QQQ / SPY）                  │
├─────────────────────────────────────────────┤
│  持倉清單                                    │
│  # 股票  股價  均價  市值  權重  1d  1w  1m  P/E │
├─────────────────────────────────────────────┤
│  今日 NASDAQ 前十強                          │
├─────────────────────────────────────────────┤
│  明日預測前十檔                              │
├─────────────────────────────────────────────┤
│  關注股票分類                                │
│  [科技] [金融] [ETF]                        │
└─────────────────────────────────────────────┘
```

#### 開發項目
- [ ] `app.py`：Streamlit 主程式
- [ ] 帳戶切換下拉選單
- [ ] 現金 / 市值 / 損益 KPI 卡片
- [ ] NAV 折線圖（可疊加 QQQ / SPY，可勾選）
- [ ] 回撤圖（含基準對比）
- [ ] 持倉表（含 1d/1w/1m 報酬、P/E）
- [ ] 今日 / 明日前十強顯示
- [ ] 三大關注類別股票區塊
- [ ] 歷史報告回查（下拉選擇日期）

#### ✅ Test Cases（Phase 4）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T4-01 | Dashboard 成功啟動 | `streamlit run` 無錯誤 |
| T4-02 | 切換帳戶 | 資料切換為對應帳戶 |
| T4-03 | NAV 圖顯示 | 折線圖正確渲染 |
| T4-04 | 勾選/取消 QQQ/SPY | 圖表即時更新 |
| T4-05 | 持倉表顯示完整欄位 | 含 P/E ratio |
| T4-06 | 歷史報告回查 | 選擇過去日期，載入對應 JSON |
| T4-07 | 無持倉時正確顯示 | 顯示「目前無持倉」 |

---

### 🔷 Phase 5：報告系統（Model / View 分離）

**目標：** 每日自動產生 JSON 報告並儲存，歷史可回查。

#### 開發項目
- [ ] `report_generator.py`：產生 JSON 報告（Model）
- [ ] `email_template.html`：Email 呈現模板（View）
- [ ] 報告儲存至 `reports/model/YYYY-MM-DD_acct_id.json`
- [ ] 報告索引檔（方便回查）

#### ✅ Test Cases（Phase 5）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T5-01 | 產生當日報告 JSON | 檔案存在，格式符合 Schema |
| T5-02 | 報告包含所有必要欄位 | 無缺漏欄位 |
| T5-03 | NAV/回撤歷史累積 | 每日追加，不覆蓋舊資料 |
| T5-04 | 回查歷史報告 | 正確讀取指定日期 JSON |
| T5-05 | 多帳戶各自產生報告 | 每個帳戶獨立檔案 |

---

### 🔷 Phase 6：Email 通知系統

**目標：** 每天早上 6 點發送日報，交易時即時通知。

#### Email 日報內容
1. 帳戶現金與市值
2. 今日損益（%）
3. 持倉清單（含 P/E）
4. 今日 NASDAQ 前十強
5. 明日預測前十（含風險提醒）
6. 三大關注類別股票
7. 免責聲明

#### 開發項目
- [ ] `email_sender.py`：SMTP 發送 Email
- [ ] HTML Email 模板（響應式）
- [ ] 即時交易通知（買進/賣出）
- [ ] 排程：每日 06:00 觸發（GitHub Actions）

#### ✅ Test Cases（Phase 6）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T6-01 | 發送測試 Email | 收件人收到郵件 |
| T6-02 | Email 含所有必要區塊 | 無缺漏區塊 |
| T6-03 | 即時交易通知觸發 | 下單後 1 分鐘內發送 |
| T6-04 | 含免責聲明 | 每封 Email 均有 |
| T6-05 | SMTP 失敗時記錄 Log | 不中斷主程式 |

---

### 🔷 Phase 7：GitHub Actions 整合

**目標：** 全自動化，每日觸發，無需人工介入。

#### 開發項目
- [ ] `daily_trade.yml`：主工作流程
- [ ] GitHub Secrets 設定說明
- [ ] 執行記錄與失敗通知
- [ ] 手動觸發支援（`workflow_dispatch`）

#### ✅ Test Cases（Phase 7）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T7-01 | 手動觸發 workflow | 成功執行所有步驟 |
| T7-02 | 走過所有帳戶 | 每個帳戶均執行策略 |
| T7-03 | Secrets 正確注入 | 無金鑰洩漏風險 |
| T7-04 | 步驟失敗時通知 | 發送失敗 Email |
| T7-05 | 定時觸發正確 | 美東 09:00 準時執行 |

---

### 🔷 Phase 8：整合測試與上線

**目標：** 端到端測試，確保所有模組串接正確。

#### 開發項目
- [ ] End-to-end 測試腳本
- [ ] `CLAUDE.md` 完整更新
- [ ] `README.md` 使用者指南
- [ ] Streamlit Cloud / 本機部署說明

#### ✅ Test Cases（Phase 8）

| 測試編號 | 測試項目 | 預期結果 |
|---------|---------|---------|
| T8-01 | 完整日流程（Paper 帳戶）| 下單 → 報告 → Email 全通 |
| T8-02 | Dashboard 讀取歷史報告 | 正確顯示 |
| T8-03 | 新增策略 JSON | 不改 Python 即可使用 |
| T8-04 | 帳戶切換策略 | 新策略生效，舊策略停用 |
| T8-05 | 再平衡觸發 | 月初 + 新資金均正確執行 |

---

## 📦 依賴套件（requirements.txt）

```
alpaca-trade-api>=3.0.0
alpaca-py>=0.13.0
streamlit>=1.35.0
pandas>=2.0.0
plotly>=5.0.0
yfinance>=0.2.0
requests>=2.31.0
python-dotenv>=1.0.0
pytest>=8.0.0
jinja2>=3.1.0
```

---

## 🧠 CLAUDE.md（專案記憶文件）

> 此檔案讓任何開發者（或 AI）可以快速理解並接手專案。

```markdown
# 專案記憶：Alpaca 美股全自動投資系統

## 核心原則
- 策略用 JSON 描述，不寫在 Python 裡
- 報告 Model（JSON）與 View（HTML/Email）嚴格分離
- 每帳戶同一時間只能使用一個策略
- 只買整數股；月初 + 新資金進來時再平衡
- 前十檔各佔 10% 資金
- 所有 Key/Secret 存 GitHub Secrets，絕不寫在程式碼

## 重要檔案
- accounts/accounts.json：帳戶清單與策略綁定
- strategies/*.json：所有交易策略
- reports/model/：每日 JSON 報告（歷史保留）
- src/engine/trade_executor.py：主要執行入口
- .github/workflows/daily_trade.yml：每日自動觸發

## 開發階段狀態
- Phase 1~8（見 PROJECT_PLAN.md）

## 注意事項
- 所有輸出均需附免責聲明
- Paper Trading 帳戶用於測試，Live 帳戶需謹慎
```

---

## 📅 預估時程

| 階段 | 內容 | 預估天數 |
|------|------|---------|
| Phase 1 | 基礎建設 | 2 天 |
| Phase 2 | 市場資料 | 3 天 |
| Phase 3 | 策略引擎 | 4 天 |
| Phase 4 | Dashboard | 4 天 |
| Phase 5 | 報告系統 | 2 天 |
| Phase 6 | Email 通知 | 2 天 |
| Phase 7 | GitHub Actions | 2 天 |
| Phase 8 | 整合測試 | 3 天 |
| **合計** | | **約 22 天** |

---

> ⚠️ **風險提示：** 本系統為輔助工具，不保證投資獲利。所有交易決策請使用者自行負責。建議先以 Paper Trading 模式充分測試後，再考慮實盤操作。
