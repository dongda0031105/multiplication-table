"""
rebalancer.py — monthly rebalance runner.

Called by GitHub Actions rebalance.yml on the 1st of each month at 09:45 ET,
and also whenever new cash exceeds the threshold.

Usage:
    python src/rebalancer.py --all-accounts
    python src/rebalancer.py --account acc_001
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from account_manager import AccountManager
from execution_engine import ExecutionEngine, Rebalancer
from notifier import Notifier
from strategy_loader import StrategyLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _run_rebalance(account: dict, strategy: dict, alpaca_client, notifier: Notifier) -> list:
    """
    Fetch current positions + NAV, calculate diff, place orders.
    Returns list of order records placed.
    """
    # ── fetch account state ───────────────────────────────────────────────────
    acct_info = alpaca_client.get_account()
    nav  = float(acct_info.portfolio_value)
    cash = float(acct_info.cash)

    raw_positions = alpaca_client.get_all_positions()
    current_positions = {p.symbol: int(float(p.qty)) for p in raw_positions}
    prices = {p.symbol: float(p.current_price) for p in raw_positions}

    # ── get target tickers from ranking (simplified: use universe list) ───────
    portfolio_cfg = strategy.get("portfolio", {})
    target_pct    = portfolio_cfg.get("target_pct", 0.10)
    cash_buf_pct  = portfolio_cfg.get("cash_buffer", 0.10)

    # Target tickers come from the ranking engine in production; for the runner
    # we use current holdings as the baseline and apply any explicit exclusions.
    rebalance_cfg = strategy.get("rebalance", {})
    target_tickers = list(current_positions.keys())

    reb = Rebalancer(
        target_pct=target_pct,
        cash_buffer_pct=cash_buf_pct,
    )

    today = str(date.today())
    if not Rebalancer.is_monthly_rebalance_day(today):
        if not Rebalancer.cash_threshold_exceeded(cash, nav, threshold_pct=0.05):
            log.info("No rebalance trigger for %s — skipping", account["id"])
            return []

    # Add prices for any tickers in positions not already fetched
    for ticker in target_tickers:
        if ticker not in prices:
            try:
                bars = alpaca_client.get_latest_bar(ticker)
                prices[ticker] = float(bars.close)
            except Exception:
                pass

    diff = reb.calc_diff(current_positions, target_tickers, prices, nav)
    log.info("Rebalance diff for %s: %s", account["id"], diff)

    engine = ExecutionEngine(alpaca_client=alpaca_client, notifier=notifier, max_attempts=3)
    orders = []
    for ticker, order in diff.items():
        try:
            if order["action"] == "buy":
                rec = engine.buy(ticker, order["shares"], account["id"])
            else:
                rec = engine.sell(ticker, order["shares"], account["id"])
            orders.append(rec)
        except Exception as exc:
            log.error("Order failed for %s %s: %s", order["action"], ticker, exc)

    log.info("Rebalance placed %d orders for %s", len(orders), account["id"])
    return orders


def main() -> int:
    p = argparse.ArgumentParser(description="Monthly portfolio rebalancer")
    p.add_argument("--all-accounts", action="store_true")
    p.add_argument("--account", default="")
    p.add_argument("--accounts-path", default="accounts/accounts.json")
    p.add_argument("--strategies-dir", default="strategies")
    args = p.parse_args()

    am = AccountManager(args.accounts_path)
    sl = StrategyLoader(args.strategies_dir)
    notifier = Notifier()

    accounts = am.list_accounts()
    if args.account:
        accounts = [a for a in accounts if a["id"] == args.account]

    ok = 0
    for account in accounts:
        log.info("Rebalancing %s", account["id"])
        try:
            creds   = am.get_credentials(account)
            strategy = sl.load(account["active_strategy_id"])
            from alpaca.trading.client import TradingClient
            client = TradingClient(
                api_key=creds["key"],
                secret_key=creds["secret"],
                paper=account.get("paper_trading", True),
            )
            _run_rebalance(account, strategy, client, notifier)
            ok += 1
        except Exception as exc:
            log.error("Rebalance failed for %s: %s", account["id"], exc)
            notifier.send_trade_alert({
                "ticker": "REBALANCE",
                "side": "error",
                "shares": 0,
                "status": "failed",
                "account_id": account["id"],
                "error": str(exc),
            })

    return 0 if ok == len(accounts) else 1


if __name__ == "__main__":
    sys.exit(main())
