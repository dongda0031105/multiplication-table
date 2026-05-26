# CLAUDE.md — AI ETF Auto-Trading System

Developer reference for AI agents and future maintainers.

## Project Purpose

Fully automated ETF-style trading system that:
- Selects top-ranked NASDAQ/NYSE stocks daily using a JSON-defined strategy
- Places market orders via Alpaca API (paper or live)
- Sends daily 6 AM ET email reports (P&L, top-10, risk disclaimer)
- Publishes a GitHub Pages dashboard with NAV charts and holdings
- Supports multiple accounts; each account runs one strategy at a time

## Architecture

```
strategies/          JSON strategy files (no Python needed for new strategies)
accounts/            accounts.json — stores env var NAMES, never raw keys
src/
  account_manager.py   Load accounts, resolve credentials from os.environ
  strategy_loader.py   Load + validate strategy JSON
  data_pipeline.py     OHLCV + fundamentals with day-level file cache
  indicator_engine.py  Pure pandas/numpy: SMA/EMA/RSI/MACD/ATR/ADX/BB/OBV/VWAP
  derived_factor_engine.py  Formula eval from JSON (uses eval with empty builtins)
  universe_filter.py   Market-cap, volume, sector exclusion filters
  filter_engine.py     Fundamental + technical AND/OR filters from JSON
  ranking_engine.py    Cross-sectional percentile scoring (11 factors)
  signal_engine.py     Entry/exit signals + RiskGuard drawdown halt
  execution_engine.py  Whole-share orders, retry logic, Rebalancer
  notifier.py          SMTP email; no-op when credentials missing
  report_generator.py  ReportModel (JSON) + ReportView (Jinja2 HTML)
  dashboard_builder.py Static GitHub Pages site from JSON reports
  e2e_runner.py        Wires all components; injectable for testing
.github/workflows/
  trade-execute.yml    Cron 09:30 ET Mon-Fri
  daily-report.yml     Cron 06:00 ET Mon-Fri → GitHub Pages deploy
  rebalance.yml        Cron 09:45 ET on 1st of month
reports/YYYY-MM-DD/  Persisted daily JSON reports per account
docs/                GitHub Pages output (index.html, history.html, data/)
dashboard/templates/ Jinja2 HTML templates
```

## Key Design Decisions

### Strategy is pure JSON
All trading logic lives in `strategies/*.json`. To add a new strategy,
create a JSON file — no Python changes required. Fields: universe, indicators,
derived_factors, filters, ranking, entry_signals, exit_signals, portfolio,
risk_management, execution.

### Credentials never in code
`accounts.json` stores the **name** of the environment variable, e.g.
`"alpaca_key_env": "ACC_001_ALPACA_KEY"`. `AccountManager.get_credentials()`
reads `os.environ[account["alpaca_key_env"]]`. Keys live in GitHub Secrets.

### Whole shares only
`ExecutionEngine.calc_shares(target_value, price)` always returns
`math.floor(target_value / price)`. Fractional shares are never requested.

### 10% per position, 15% cap
`calc_target_values(nav, target_pct=0.10, max_single_pct=0.15)`.

### Rebalance triggers (NOT daily)
1. Monthly — first calendar day (`Rebalancer.is_monthly_rebalance_day`)
2. New cash — when uninvested cash > threshold% of NAV
   (`Rebalancer.cash_threshold_exceeded`)

### RiskGuard
Halts new entries when drawdown from peak NAV exceeds `halt_drawdown_pct`
(default 10%). Existing positions can still be exited.

### Report Model/View separation
`ReportModel.build()` returns a pure dict (JSON-serialisable).
`ReportView.render()` converts it to HTML via Jinja2. Stored at
`reports/YYYY-MM-DD/{account_id}.json`.

### GitHub Pages
`DashboardBuilder.build(account_id)` writes to `docs/`. GitHub Pages serves
`docs/` as the public site. Chart.js loaded from CDN; no build step needed.

## Running Tests

```bash
# All phases
python3 -m pytest tests/ -v

# Single phase
python3 -m pytest tests/phase7/ -v
```

All 217 tests must pass before merging to main.

## Adding a New Strategy

1. Copy `strategies/toprank_ma_momentum_v2.json` → `strategies/my_strategy.json`
2. Edit the JSON fields (universe, indicators, ranking weights, etc.)
3. Set `"enabled": true`
4. In `accounts.json`, set `"active_strategy_id": "my_strategy"` for target account
5. Run tests — no Python changes needed

## Switching to Live Trading

Use `GoLiveChecklist` in `src/e2e_runner.py`. All 7 items must pass:
- paper_trading_tested
- live_credentials_set
- strategy_json_validated
- max_drawdown_limit_set
- notify_email_configured
- github_actions_enabled
- github_pages_deployed

## GitHub Actions

All workflows use dynamic account matrix from `accounts.json`.
Each account's secrets are named `{ACCOUNT_ID_UPPER}_ALPACA_KEY` etc.

| Workflow | Schedule | Trigger |
|---|---|---|
| trade-execute.yml | 09:30 ET Mon-Fri | cron + manual |
| daily-report.yml | 06:00 ET Mon-Fri | cron + manual |
| rebalance.yml | 09:45 ET 1st of month | cron + manual |

## Risk Disclaimer

Every email and HTML report includes:
> ⚠️ 風險提示：本通知所有內容僅供資訊整理與研究參考，不構成投資建議。
> 股票投資有風險，過去績效不代表未來獲利。
