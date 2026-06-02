from __future__ import annotations

import argparse
import contextlib
from datetime import date, datetime, time as datetime_time, timezone
from glob import glob
import io
import json
from pathlib import Path

from kxian_bot.bitget_live_gray import approve_bitget_live_gray
from kxian_bot.brokers.base import create_broker
from kxian_bot.config import load_config
from kxian_bot.dashboard import run_dashboard
from kxian_bot.evidence import build_testnet_evidence, write_evidence
from kxian_bot.exchange_health import run_exchange_health_check
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.live_setup import run_live_setup_check
from kxian_bot.market_data import MarketDataError, fetch_bitget_trading_rule
from kxian_bot.models import OrderRequest, TradingRule
from kxian_bot.preflight import run_preflight
from kxian_bot.readiness import run_readiness
from kxian_bot.runner import TradingRunner
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_parameters import strategy_parameters
from kxian_bot.strategies.factory import SUPPORTED_STRATEGIES
from kxian_bot.testnet_dry_run import run_testnet_dry_run, run_testnet_observation
from kxian_bot.testnet_close_loop import run_testnet_close_loop
from kxian_bot.testnet_setup import run_testnet_setup_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kxian-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run-once")
    subparsers.add_parser("preflight")
    subparsers.add_parser("readiness")
    health_parser = subparsers.add_parser("exchange-health")
    health_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    launch_parser = subparsers.add_parser("launch-checklist")
    launch_parser.add_argument("--target", choices=["testnet", "live"], default=None)
    launch_parser.add_argument("--evidence-out", type=str, default=None)
    setup_parser = subparsers.add_parser("testnet-setup-check")
    setup_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    live_setup_parser = subparsers.add_parser("live-setup-check")
    live_setup_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    bitget_live_gray_parser = subparsers.add_parser("approve-bitget-live-gray")
    bitget_live_gray_parser.add_argument("--updated-by", type=str, default="cli")
    bitget_live_gray_parser.add_argument("--confirmation", type=str, required=True)
    pause_parser = subparsers.add_parser("pause")
    pause_parser.add_argument("--reason", type=str, default="manual_pause")
    pause_parser.add_argument("--updated-by", type=str, default="cli")
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--reason", type=str, default="manual_resume")
    resume_parser.add_argument("--updated-by", type=str, default="cli")
    subparsers.add_parser("automation-status")

    loop_parser = subparsers.add_parser("trade-loop")
    loop_parser.add_argument("--max-iterations", type=int, default=None)
    loop_parser.add_argument("--sleep-seconds", type=float, default=None)
    loop_parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip startup safety checks. Use only for controlled local smoke tests.",
    )

    run_parser = subparsers.add_parser("backtest")
    run_parser.add_argument("--limit", type=int, default=200)
    run_parser.add_argument("--input-file", type=str, default=None)
    run_parser.add_argument("--resample-interval", type=str, default=None)

    stress_parser = subparsers.add_parser("stress-backtest")
    stress_parser.add_argument("--limit", type=int, default=200)
    stress_parser.add_argument("--input-file", type=str, default=None)
    stress_parser.add_argument("--resample-interval", type=str, default=None)

    walk_parser = subparsers.add_parser("walk-forward")
    walk_parser.add_argument("--limit", type=int, default=1000)
    walk_parser.add_argument("--segments", type=int, default=None)
    walk_parser.add_argument("--input-file", type=str, default=None)
    walk_parser.add_argument("--resample-interval", type=str, default=None)

    walk_samples_parser = subparsers.add_parser("walk-forward-samples")
    walk_samples_parser.add_argument("--limit", type=int, default=1000)
    walk_samples_parser.add_argument("--segments", type=int, default=None)
    walk_samples_parser.add_argument("--input-files", required=True)
    walk_samples_parser.add_argument("--resample-interval", type=str, default=None)
    walk_samples_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print sample-level walk-forward gates and failed segments without full segment history.",
    )

    validate_parser = subparsers.add_parser("validate-strategy")
    validate_parser.add_argument("--limit", type=int, default=1000)
    validate_parser.add_argument("--segments", type=int, default=None)
    validate_parser.add_argument("--input-file", type=str, default=None)
    validate_parser.add_argument("--resample-interval", type=str, default=None)

    validate_samples_parser = subparsers.add_parser("validate-samples")
    validate_samples_parser.add_argument("--limit", type=int, default=1000)
    validate_samples_parser.add_argument("--segments", type=int, default=None)
    validate_samples_parser.add_argument("--input-files", required=True)
    validate_samples_parser.add_argument("--resample-interval", type=str, default=None)

    diagnostics_parser = subparsers.add_parser("market-diagnostics")
    diagnostics_parser.add_argument("--limit", type=int, default=1000)
    diagnostics_parser.add_argument("--segments", type=int, default=None)
    diagnostics_parser.add_argument("--input-file", type=str, default=None)
    diagnostics_parser.add_argument("--resample-interval", type=str, default=None)

    select_parser = subparsers.add_parser("select-strategy")
    select_parser.add_argument("--limit", type=int, default=3000)
    select_parser.add_argument("--segments", type=int, default=None)
    select_parser.add_argument("--input-file", type=str, default=None)
    select_parser.add_argument("--resample-interval", type=str, default=None)
    select_parser.add_argument("--short-windows", required=True)
    select_parser.add_argument("--long-windows", required=True)
    select_parser.add_argument(
        "--stop-loss-pcts",
        default=None,
        help="Comma-separated stop-loss percentages. Defaults to KXIAN_STOP_LOSS_PCT.",
    )
    select_parser.add_argument(
        "--take-profit-pcts",
        default=None,
        help="Comma-separated take-profit percentages. Defaults to KXIAN_TAKE_PROFIT_PCT.",
    )
    select_parser.add_argument(
        "--trailing-stop-pcts",
        default=None,
        help="Comma-separated trailing-stop percentages. Defaults to KXIAN_TRAILING_STOP_PCT.",
    )
    select_parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy names. Defaults to KXIAN_STRATEGY.",
    )
    select_parser.add_argument("--top", type=int, default=10)
    select_parser.add_argument(
        "--promote",
        action="store_true",
        help="Save the best passing candidate as the active strategy profile for the current mode/exchange/symbol/interval.",
    )

    select_samples_parser = subparsers.add_parser("select-samples")
    select_samples_parser.add_argument("--limit", type=int, default=3000)
    select_samples_parser.add_argument("--segments", type=int, default=None)
    select_samples_parser.add_argument("--input-files", required=True)
    select_samples_parser.add_argument("--resample-interval", type=str, default=None)
    select_samples_parser.add_argument("--short-windows", required=True)
    select_samples_parser.add_argument("--long-windows", required=True)
    select_samples_parser.add_argument(
        "--stop-loss-pcts",
        default=None,
        help="Comma-separated stop-loss percentages. Defaults to KXIAN_STOP_LOSS_PCT.",
    )
    select_samples_parser.add_argument(
        "--take-profit-pcts",
        default=None,
        help="Comma-separated take-profit percentages. Defaults to KXIAN_TAKE_PROFIT_PCT.",
    )
    select_samples_parser.add_argument(
        "--trailing-stop-pcts",
        default=None,
        help="Comma-separated trailing-stop percentages. Defaults to KXIAN_TRAILING_STOP_PCT.",
    )
    select_samples_parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy names. Defaults to KXIAN_STRATEGY.",
    )
    select_samples_parser.add_argument("--top", type=int, default=10)
    select_samples_parser.add_argument(
        "--promote",
        action="store_true",
        help="Save the best candidate that passes every input sample as the active strategy profile.",
    )

    select_sample_intervals_parser = subparsers.add_parser("select-sample-intervals")
    select_sample_intervals_parser.add_argument("--limit", type=int, default=3000)
    select_sample_intervals_parser.add_argument("--segments", type=int, default=None)
    select_sample_intervals_parser.add_argument("--input-files", required=True)
    select_sample_intervals_parser.add_argument(
        "--resample-intervals",
        required=True,
        help="Comma-separated intervals to compare. Use raw or none for the source interval.",
    )
    select_sample_intervals_parser.add_argument("--short-windows", required=True)
    select_sample_intervals_parser.add_argument("--long-windows", required=True)
    select_sample_intervals_parser.add_argument(
        "--stop-loss-pcts",
        default=None,
        help="Comma-separated stop-loss percentages. Defaults to KXIAN_STOP_LOSS_PCT.",
    )
    select_sample_intervals_parser.add_argument(
        "--take-profit-pcts",
        default=None,
        help="Comma-separated take-profit percentages. Defaults to KXIAN_TAKE_PROFIT_PCT.",
    )
    select_sample_intervals_parser.add_argument(
        "--trailing-stop-pcts",
        default=None,
        help="Comma-separated trailing-stop percentages. Defaults to KXIAN_TRAILING_STOP_PCT.",
    )
    select_sample_intervals_parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy names. Defaults to KXIAN_STRATEGY.",
    )
    select_sample_intervals_parser.add_argument("--top", type=int, default=10)
    select_sample_intervals_parser.add_argument(
        "--promote",
        action="store_true",
        help="Save the best passing interval and parameters as the active strategy profile for its runtime interval.",
    )

    screen_samples_parser = subparsers.add_parser("screen-samples")
    screen_samples_parser.add_argument("--limit", type=int, default=3000)
    screen_samples_parser.add_argument("--segments", type=int, default=None)
    screen_samples_parser.add_argument("--input-files", required=True)
    screen_samples_parser.add_argument(
        "--resample-intervals",
        required=True,
        help="Comma-separated intervals to prefilter. Use raw or none for the source interval.",
    )
    screen_samples_parser.add_argument("--short-windows", required=True)
    screen_samples_parser.add_argument("--long-windows", required=True)
    screen_samples_parser.add_argument(
        "--stop-loss-pcts",
        default=None,
        help="Comma-separated stop-loss percentages. Defaults to KXIAN_STOP_LOSS_PCT.",
    )
    screen_samples_parser.add_argument(
        "--take-profit-pcts",
        default=None,
        help="Comma-separated take-profit percentages. Defaults to KXIAN_TAKE_PROFIT_PCT.",
    )
    screen_samples_parser.add_argument(
        "--trailing-stop-pcts",
        default=None,
        help="Comma-separated trailing-stop percentages. Defaults to KXIAN_TRAILING_STOP_PCT.",
    )
    screen_samples_parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy names. Defaults to KXIAN_STRATEGY.",
    )
    screen_samples_parser.add_argument("--top", type=int, default=10)
    screen_samples_parser.add_argument(
        "--max-combinations",
        type=int,
        default=None,
        help="Stop after this many parameter combinations. Use to keep large research grids bounded.",
    )
    screen_samples_parser.add_argument(
        "--skip-combinations",
        type=int,
        default=0,
        help="Skip this many parameter combinations before screening. Use with --max-combinations to page through a large grid.",
    )
    screen_samples_parser.add_argument(
        "--screen-min-trades",
        type=int,
        default=None,
        help=(
            "Override the minimum trade count only for the screen-samples prefilter. "
            "Formal select/validate/promote gates still use KXIAN_MIN_GATE_TRADES."
        ),
    )
    screen_samples_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print status, interval summaries, selected candidate, and compact candidate summaries only.",
    )

    subparsers.add_parser("strategy-profile")
    promote_profile_parser = subparsers.add_parser("promote-profile-to-testnet")
    promote_profile_parser.add_argument("--updated-by", type=str, default="cli")
    promote_live_profile_parser = subparsers.add_parser("promote-profile-to-live")
    promote_live_profile_parser.add_argument("--updated-by", type=str, default="cli")

    history_parser = subparsers.add_parser("download-history")
    history_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    history_parser.add_argument("--symbol", type=str, default=None)
    history_parser.add_argument("--interval", type=str, default=None)
    history_parser.add_argument("--start", required=True)
    history_parser.add_argument("--end", required=True)
    history_parser.add_argument("--limit-per-request", type=int, default=None)
    history_parser.add_argument("--sleep-seconds", type=float, default=0.0)

    import_parser = subparsers.add_parser("import-candles")
    import_parser.add_argument("--input-file", required=True)
    import_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    import_parser.add_argument("--symbol", type=str, default=None)
    import_parser.add_argument("--interval", type=str, default=None)

    import_archives_parser = subparsers.add_parser("import-candle-archives")
    import_archives_parser.add_argument("--input-dir", required=True)
    import_archives_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    import_archives_parser.add_argument("--symbol", type=str, default=None)
    import_archives_parser.add_argument("--interval", type=str, default=None)
    import_archives_parser.add_argument("--pattern", type=str, default="*.zip")
    import_archives_parser.add_argument("--recursive", action="store_true")

    prepare_samples_parser = subparsers.add_parser("prepare-samples")
    prepare_samples_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    prepare_samples_parser.add_argument("--symbol", type=str, default=None)
    prepare_samples_parser.add_argument("--interval", type=str, default=None)
    prepare_samples_parser.add_argument("--start", required=True)
    prepare_samples_parser.add_argument("--end", required=True)
    prepare_samples_parser.add_argument("--sample-days", type=int, default=30)
    prepare_samples_parser.add_argument("--output-dir", type=str, default="data/samples")
    prepare_samples_parser.add_argument("--source", choices=["auto", "sqlite", "exchange"], default="auto")
    prepare_samples_parser.add_argument("--limit-per-request", type=int, default=None)
    prepare_samples_parser.add_argument("--sleep-seconds", type=float, default=0.0)
    prepare_samples_parser.add_argument("--min-candles", type=int, default=1)

    research_parser = subparsers.add_parser("research-strategy")
    research_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    research_parser.add_argument("--symbol", type=str, default=None)
    research_parser.add_argument("--interval", type=str, default=None)
    research_parser.add_argument("--start", required=True)
    research_parser.add_argument("--end", required=True)
    research_parser.add_argument("--sample-days", type=int, default=30)
    research_parser.add_argument("--output-dir", type=str, default="data/samples")
    research_parser.add_argument("--source", choices=["auto", "sqlite", "exchange"], default="auto")
    research_parser.add_argument("--limit-per-request", type=int, default=None)
    research_parser.add_argument("--sleep-seconds", type=float, default=0.0)
    research_parser.add_argument("--min-candles", type=int, default=1000)
    research_parser.add_argument("--limit", type=int, default=3000)
    research_parser.add_argument("--segments", type=int, default=None)
    research_parser.add_argument(
        "--resample-intervals",
        default="raw,5m,15m,30m,1h",
        help="Comma-separated intervals to compare. Use raw or none for the source interval.",
    )
    research_parser.add_argument("--short-windows", required=True)
    research_parser.add_argument("--long-windows", required=True)
    research_parser.add_argument(
        "--stop-loss-pcts",
        default=None,
        help="Comma-separated stop-loss percentages. Defaults to KXIAN_STOP_LOSS_PCT.",
    )
    research_parser.add_argument(
        "--take-profit-pcts",
        default=None,
        help="Comma-separated take-profit percentages. Defaults to KXIAN_TAKE_PROFIT_PCT.",
    )
    research_parser.add_argument(
        "--trailing-stop-pcts",
        default=None,
        help="Comma-separated trailing-stop percentages. Defaults to KXIAN_TRAILING_STOP_PCT.",
    )
    research_parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated strategy names. Defaults to KXIAN_STRATEGY.",
    )
    research_parser.add_argument("--top", type=int, default=10)
    research_parser.add_argument(
        "--promote",
        action="store_true",
        help="Save the best passing candidate as the active strategy profile. Omit for research-only runs.",
    )
    research_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the compact research summary, status, and next steps.",
    )

    rules_parser = subparsers.add_parser("trading-rules")
    rules_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    rules_parser.add_argument("--symbol", type=str, default=None)
    rules_parser.add_argument("--price-step", type=float, default=None)
    rules_parser.add_argument("--quantity-step", type=float, default=None)
    rules_parser.add_argument("--min-quantity", type=float, default=None)
    rules_parser.add_argument("--min-notional", type=float, default=None)
    rules_parser.add_argument("--refresh-from-exchange", action="store_true")

    batch_parser = subparsers.add_parser("batch-backtest")
    batch_parser.add_argument("--exchange", choices=["binance", "okx", "bitget"], default=None)
    batch_parser.add_argument("--symbol", type=str, default=None)
    batch_parser.add_argument("--interval", type=str, default=None)
    batch_parser.add_argument("--start", required=True)
    batch_parser.add_argument("--end", required=True)
    batch_parser.add_argument("--short-windows", required=True)
    batch_parser.add_argument("--long-windows", required=True)
    batch_parser.add_argument("--top", type=int, default=20)
    batch_parser.add_argument("--sort-by", choices=["return_pct", "profit_factor", "max_drawdown_pct"], default="return_pct")

    dashboard_parser = subparsers.add_parser("dashboard")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8000)

    test_order_parser = subparsers.add_parser("test-order")
    test_order_parser.add_argument("--side", choices=["buy", "sell"], required=True)
    test_order_parser.add_argument("--quantity", type=float, required=True)
    test_order_parser.add_argument("--price", type=float, required=True)
    test_order_parser.add_argument("--symbol", type=str, default=None)

    status_parser = subparsers.add_parser("order-status")
    status_parser.add_argument("--order-id", required=True)
    status_parser.add_argument("--symbol", type=str, default=None)

    cancel_parser = subparsers.add_parser("cancel-order")
    cancel_parser.add_argument("--order-id", required=True)
    cancel_parser.add_argument("--symbol", type=str, default=None)

    balance_parser = subparsers.add_parser("account-balance")
    balance_parser.add_argument("--symbol", type=str, default=None)

    sync_fills_parser = subparsers.add_parser("sync-fills")
    sync_fills_parser.add_argument("--limit", type=int, default=500)

    dry_run_parser = subparsers.add_parser("testnet-dry-run")
    dry_run_parser.add_argument("--sync-limit", type=int, default=500)
    dry_run_parser.add_argument(
        "--execute-loop",
        action="store_true",
        help="After checks and fill sync pass, run one bounded testnet loop iteration.",
    )
    dry_run_parser.add_argument("--sleep-seconds", type=float, default=0.0)
    dry_run_parser.add_argument("--evidence-out", type=str, default=None)

    observe_parser = subparsers.add_parser("testnet-observe")
    observe_parser.add_argument("--cycles", type=int, default=6)
    observe_parser.add_argument("--sync-limit", type=int, default=500)
    observe_parser.add_argument("--sleep-seconds", type=float, default=60.0)
    observe_parser.add_argument(
        "--execute-loop",
        action="store_true",
        help="After each check and fill sync pass, run one bounded testnet loop iteration.",
    )
    observe_parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Keep observing after failed cycles instead of stopping on the first failure.",
    )
    observe_parser.add_argument("--evidence-out", type=str, default=None)

    close_loop_parser = subparsers.add_parser("testnet-close-loop")
    close_loop_parser.add_argument("--cycles", type=int, default=6)
    close_loop_parser.add_argument("--sync-limit", type=int, default=500)
    close_loop_parser.add_argument("--sleep-seconds", type=float, default=60.0)
    close_loop_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    close_loop_parser.add_argument("--evidence-dir", type=str, default=None)
    close_loop_parser.add_argument(
        "--confirm-bounded-testnet-order",
        action="store_true",
        help="Allow the command to run bounded Binance Spot Testnet --execute-loop observation.",
    )

    paper_dry_run_parser = subparsers.add_parser("paper-dry-run")
    paper_dry_run_parser.add_argument("--input-file", type=str, default=None)
    paper_dry_run_parser.add_argument("--max-iterations", type=int, default=1)
    paper_dry_run_parser.add_argument("--sleep-seconds", type=float, default=0.0)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    relaxed_config_commands = {
        "readiness",
        "exchange-health",
        "launch-checklist",
        "live-setup-check",
        "paper-dry-run",
        "promote-profile-to-live",
        "promote-profile-to-testnet",
        "run-once",
        "strategy-profile",
        "testnet-close-loop",
        "testnet-dry-run",
        "testnet-observe",
        "testnet-setup-check",
        "approve-bitget-live-gray",
        "trading-rules",
        "trade-loop",
    }
    config = load_config(validate_execution=False) if args.command in relaxed_config_commands else load_config()

    try:
        if getattr(args, "exchange", None):
            config = config.model_copy(update={"exchange": args.exchange})

        if args.command == "run-once":
            bitget_run_once_gate = _bitget_live_run_once_gate(config)
            if bitget_run_once_gate is not None:
                print(json.dumps(bitget_run_once_gate, ensure_ascii=False))
                raise SystemExit(2)
            gate = _runtime_launch_gate(config, require_observed_testnet=False)
            if gate is not None:
                print(json.dumps(gate, ensure_ascii=False))
                raise SystemExit(2)
            runner = TradingRunner(config)
            print(json.dumps(runner.run_once(), ensure_ascii=False))
            return

        if args.command == "preflight":
            print(json.dumps(run_preflight(config), ensure_ascii=False))
            return

        if args.command == "readiness":
            print(json.dumps(run_readiness(config), ensure_ascii=False))
            return

        if args.command == "exchange-health":
            result = run_exchange_health_check(config, timeout_seconds=args.timeout_seconds)
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "launch-checklist":
            target_for_evidence = args.target or (config.mode if config.mode in {"testnet", "live"} else "testnet")
            if args.evidence_out and target_for_evidence != "testnet":
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "testnet_evidence_requires_testnet_target",
                            "target_mode": target_for_evidence,
                            "next_steps": ["rerun launch-checklist --target testnet --evidence-out <path>"],
                        },
                        ensure_ascii=False,
                    )
                )
                raise SystemExit(2)
            result = run_launch_checklist(config, target_mode=args.target)
            _write_testnet_evidence_if_requested(
                args.evidence_out,
                config,
                command="launch-checklist",
                result=result,
                launch_checklist=result if target_for_evidence == "testnet" else None,
            )
            print(json.dumps(result, ensure_ascii=False))
            return

        if args.command == "testnet-setup-check":
            result = run_testnet_setup_check(config, timeout_seconds=args.timeout_seconds)
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "live-setup-check":
            result = run_live_setup_check(config, timeout_seconds=args.timeout_seconds)
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "approve-bitget-live-gray":
            result = approve_bitget_live_gray(
                config,
                updated_by=args.updated_by,
                confirmation=args.confirmation,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "pause":
            storage = SQLiteStorage(config.db_path)
            status = storage.set_automation_paused(
                config.mode,
                config.exchange,
                config.symbol,
                config.interval,
                True,
                reason=args.reason,
                updated_by=args.updated_by,
            )
            print(json.dumps(status, ensure_ascii=False))
            return

        if args.command == "resume":
            storage = SQLiteStorage(config.db_path)
            status = storage.set_automation_paused(
                config.mode,
                config.exchange,
                config.symbol,
                config.interval,
                False,
                reason=args.reason,
                updated_by=args.updated_by,
            )
            print(json.dumps(status, ensure_ascii=False))
            return

        if args.command == "automation-status":
            storage = SQLiteStorage(config.db_path)
            print(
                json.dumps(
                    storage.automation_control_status(config.mode, config.exchange, config.symbol, config.interval),
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "trade-loop":
            bitget_iteration_gate = _bitget_live_iteration_gate(config, args.max_iterations)
            if bitget_iteration_gate is not None:
                print(json.dumps(bitget_iteration_gate, ensure_ascii=False))
                raise SystemExit(2)
            gate = _runtime_launch_gate(config, require_observed_testnet=args.max_iterations is None)
            if gate is not None:
                print(json.dumps(gate, ensure_ascii=False))
                raise SystemExit(2)
            if not args.skip_preflight:
                preflight = run_preflight(config)
                if preflight["status"] != "pass":
                    print(
                        json.dumps(
                            {"status": "error", "reason": "preflight_failed", "preflight": preflight},
                            ensure_ascii=False,
                        )
                    )
                    raise SystemExit(2)
            runner = TradingRunner(config)
            result = runner.run_loop(args.max_iterations, args.sleep_seconds)
            print(json.dumps(result, ensure_ascii=False))
            if result.get("last_result", {}).get("reason") in {"loop_lock_active", "loop_circuit_breaker_tripped"}:
                raise SystemExit(2)
            return

        if args.command == "testnet-dry-run":
            result = run_testnet_dry_run(
                config,
                sync_limit=args.sync_limit,
                execute_loop=args.execute_loop,
                sleep_seconds=args.sleep_seconds,
            )
            _write_testnet_evidence_if_requested(
                args.evidence_out,
                config,
                command="testnet-dry-run",
                result=result,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "testnet-observe":
            result = run_testnet_observation(
                config,
                cycles=args.cycles,
                sync_limit=args.sync_limit,
                execute_loop=args.execute_loop,
                sleep_seconds=args.sleep_seconds,
                continue_on_failure=args.continue_on_failure,
            )
            _write_testnet_evidence_if_requested(
                args.evidence_out,
                config,
                command="testnet-observe",
                result=result,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "testnet-close-loop":
            result = run_testnet_close_loop(
                config,
                cycles=args.cycles,
                sync_limit=args.sync_limit,
                sleep_seconds=args.sleep_seconds,
                confirm_bounded_testnet_order=args.confirm_bounded_testnet_order,
                evidence_dir=args.evidence_dir,
                timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "paper-dry-run":
            result = _run_paper_dry_run(
                config,
                input_file=args.input_file,
                max_iterations=args.max_iterations,
                sleep_seconds=args.sleep_seconds,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "backtest":
            runner = TradingRunner(config)
            print(json.dumps(runner.backtest(args.limit, args.input_file, args.resample_interval), ensure_ascii=False))
            return

        if args.command == "stress-backtest":
            runner = TradingRunner(config)
            print(json.dumps(runner.stress_backtest(args.limit, args.input_file, args.resample_interval), ensure_ascii=False))
            return

        if args.command == "walk-forward":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            print(json.dumps(runner.walk_forward(args.limit, segments, args.input_file, args.resample_interval), ensure_ascii=False))
            return

        if args.command == "walk-forward-samples":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.walk_forward_samples(
                args.limit,
                segments,
                parse_input_files(args.input_files),
                args.resample_interval,
            )
            print(json.dumps(_walk_forward_samples_output(result, summary_only=args.summary_only), ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "validate-strategy":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.validate_strategy(args.limit, segments, args.input_file, args.resample_interval)
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "validate-samples":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.validate_samples(
                args.limit,
                segments,
                parse_input_files(args.input_files),
                args.resample_interval,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "market-diagnostics":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            print(json.dumps(runner.market_diagnostics(args.limit, segments, args.input_file, args.resample_interval), ensure_ascii=False))
            return

        if args.command == "select-strategy":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.select_strategy(
                limit=args.limit,
                segments=segments,
                input_file=args.input_file,
                short_windows=parse_int_list(args.short_windows),
                long_windows=parse_int_list(args.long_windows),
                top=args.top,
                promote=args.promote,
                strategies=parse_strategy_list(args.strategies) if args.strategies else None,
                stop_loss_pcts=parse_float_list(args.stop_loss_pcts) if args.stop_loss_pcts else None,
                take_profit_pcts=parse_float_list(args.take_profit_pcts) if args.take_profit_pcts else None,
                trailing_stop_pcts=parse_float_list(args.trailing_stop_pcts) if args.trailing_stop_pcts else None,
                resample_interval=args.resample_interval,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "select-samples":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.select_samples(
                limit=args.limit,
                segments=segments,
                input_files=parse_input_files(args.input_files),
                short_windows=parse_int_list(args.short_windows),
                long_windows=parse_int_list(args.long_windows),
                top=args.top,
                promote=args.promote,
                strategies=parse_strategy_list(args.strategies) if args.strategies else None,
                stop_loss_pcts=parse_float_list(args.stop_loss_pcts) if args.stop_loss_pcts else None,
                take_profit_pcts=parse_float_list(args.take_profit_pcts) if args.take_profit_pcts else None,
                trailing_stop_pcts=parse_float_list(args.trailing_stop_pcts) if args.trailing_stop_pcts else None,
                resample_interval=args.resample_interval,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "select-sample-intervals":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.select_sample_intervals(
                limit=args.limit,
                segments=segments,
                input_files=parse_input_files(args.input_files),
                short_windows=parse_int_list(args.short_windows),
                long_windows=parse_int_list(args.long_windows),
                top=args.top,
                resample_intervals=parse_string_list(args.resample_intervals),
                promote=args.promote,
                strategies=parse_strategy_list(args.strategies) if args.strategies else None,
                stop_loss_pcts=parse_float_list(args.stop_loss_pcts) if args.stop_loss_pcts else None,
                take_profit_pcts=parse_float_list(args.take_profit_pcts) if args.take_profit_pcts else None,
                trailing_stop_pcts=parse_float_list(args.trailing_stop_pcts) if args.trailing_stop_pcts else None,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "screen-samples":
            runner = TradingRunner(config)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.screen_samples(
                limit=args.limit,
                segments=segments,
                input_files=parse_input_files(args.input_files),
                short_windows=parse_int_list(args.short_windows),
                long_windows=parse_int_list(args.long_windows),
                top=args.top,
                resample_intervals=parse_string_list(args.resample_intervals),
                strategies=parse_strategy_list(args.strategies) if args.strategies else None,
                stop_loss_pcts=parse_float_list(args.stop_loss_pcts) if args.stop_loss_pcts else None,
                take_profit_pcts=parse_float_list(args.take_profit_pcts) if args.take_profit_pcts else None,
                trailing_stop_pcts=parse_float_list(args.trailing_stop_pcts) if args.trailing_stop_pcts else None,
                max_combinations=args.max_combinations,
                skip_combinations=args.skip_combinations,
                screen_min_trades=args.screen_min_trades,
            )
            print(json.dumps(_screen_samples_output(result, summary_only=args.summary_only), ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "strategy-profile":
            storage = SQLiteStorage(config.db_path)
            profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
            print(
                json.dumps(
                    profile
                    or {
                        "status": "empty",
                        "mode": config.mode,
                        "exchange": config.exchange,
                        "symbol": config.symbol,
                        "interval": config.interval,
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "promote-profile-to-testnet":
            storage = SQLiteStorage(config.db_path)
            result = storage.promote_strategy_profile_to_mode(
                source_mode="paper",
                target_mode="testnet",
                exchange=config.exchange,
                symbol=config.symbol,
                interval=config.interval,
                updated_by=args.updated_by,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "promote-profile-to-live":
            storage = SQLiteStorage(config.db_path)
            result = storage.promote_strategy_profile_to_mode(
                source_mode="testnet",
                target_mode="live",
                exchange=config.exchange,
                symbol=config.symbol,
                interval=config.interval,
                updated_by=args.updated_by,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "download-history":
            runner = TradingRunner(config)
            start_time = parse_timestamp_ms(args.start)
            end_time = parse_timestamp_ms(args.end)
            print(
                json.dumps(
                    runner.download_history(
                        symbol=args.symbol or config.symbol,
                        interval=args.interval or config.interval,
                        start_time=start_time,
                        end_time=end_time,
                        limit_per_request=args.limit_per_request,
                        sleep_seconds=args.sleep_seconds,
                    ),
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "import-candles":
            runner = TradingRunner(config)
            print(
                json.dumps(
                    runner.import_candles(
                        input_file=args.input_file,
                        symbol=args.symbol or config.symbol,
                        interval=args.interval or config.interval,
                    ),
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "import-candle-archives":
            runner = TradingRunner(config)
            result = runner.import_candle_archives(
                input_dir=args.input_dir,
                symbol=args.symbol or config.symbol,
                interval=args.interval or config.interval,
                pattern=args.pattern,
                recursive=args.recursive,
            )
            print(json.dumps(result, ensure_ascii=False))
            if result["status"] != "ok":
                raise SystemExit(2)
            return

        if args.command == "prepare-samples":
            runner = TradingRunner(config)
            start_time = parse_timestamp_ms(args.start)
            end_time = parse_timestamp_ms(args.end)
            print(
                json.dumps(
                    runner.prepare_samples(
                        symbol=args.symbol or config.symbol,
                        interval=args.interval or config.interval,
                        start_time=start_time,
                        end_time=end_time,
                        sample_days=args.sample_days,
                        output_dir=args.output_dir,
                        source=args.source,
                        limit_per_request=args.limit_per_request,
                        sleep_seconds=args.sleep_seconds,
                        min_candles=args.min_candles,
                    ),
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "research-strategy":
            runner = TradingRunner(config)
            start_time = parse_timestamp_ms(args.start)
            end_time = parse_timestamp_ms(args.end)
            segments = args.segments or config.min_walk_forward_segments
            result = runner.research_strategy(
                symbol=args.symbol or config.symbol,
                interval=args.interval or config.interval,
                start_time=start_time,
                end_time=end_time,
                sample_days=args.sample_days,
                output_dir=args.output_dir,
                source=args.source,
                limit_per_request=args.limit_per_request,
                sleep_seconds=args.sleep_seconds,
                min_candles=args.min_candles,
                limit=args.limit,
                segments=segments,
                short_windows=parse_int_list(args.short_windows),
                long_windows=parse_int_list(args.long_windows),
                top=args.top,
                resample_intervals=parse_string_list(args.resample_intervals),
                promote=args.promote,
                strategies=parse_strategy_list(args.strategies) if args.strategies else None,
                stop_loss_pcts=parse_float_list(args.stop_loss_pcts) if args.stop_loss_pcts else None,
                take_profit_pcts=parse_float_list(args.take_profit_pcts) if args.take_profit_pcts else None,
                trailing_stop_pcts=parse_float_list(args.trailing_stop_pcts) if args.trailing_stop_pcts else None,
            )
            print(json.dumps(_research_strategy_output(result, summary_only=args.summary_only), ensure_ascii=False))
            if result["status"] != "pass":
                raise SystemExit(2)
            return

        if args.command == "trading-rules":
            storage = SQLiteStorage(config.db_path)
            symbol = args.symbol or config.symbol
            exchange_rules = {}
            if args.refresh_from_exchange:
                if config.exchange != "bitget":
                    print(
                        json.dumps(
                            {
                                "status": "blocked",
                                "reason": "exchange_rule_refresh_not_supported",
                                "exchange": config.exchange,
                                "supported_exchanges": ["bitget"],
                            },
                            ensure_ascii=False,
                        )
                    )
                    raise SystemExit(2)
                exchange_rules = fetch_bitget_trading_rule(symbol)
            current = storage.latest_trading_rule(config.exchange, symbol) or {}
            rule = TradingRule(
                exchange=config.exchange,
                symbol=symbol,
                price_step=args.price_step if args.price_step is not None else float(exchange_rules.get("price_step", current.get("price_step", config.price_step))),
                quantity_step=args.quantity_step if args.quantity_step is not None else float(exchange_rules.get("quantity_step", current.get("quantity_step", config.quantity_step))),
                min_quantity=args.min_quantity if args.min_quantity is not None else float(exchange_rules.get("min_quantity", current.get("min_quantity", config.min_exchange_quantity))),
                min_notional=args.min_notional if args.min_notional is not None else float(exchange_rules.get("min_notional", current.get("min_notional", config.min_exchange_notional))),
            )
            if any(
                value is not None
                for value in [args.price_step, args.quantity_step, args.min_quantity, args.min_notional]
            ) or args.refresh_from_exchange:
                storage.upsert_trading_rule(rule)
            print(json.dumps(rule.model_dump(), ensure_ascii=False))
            return

        if args.command == "batch-backtest":
            runner = TradingRunner(config)
            start_time = parse_timestamp_ms(args.start)
            end_time = parse_timestamp_ms(args.end)
            print(
                json.dumps(
                    runner.batch_backtest(
                        symbol=args.symbol or config.symbol,
                        interval=args.interval or config.interval,
                        start_time=start_time,
                        end_time=end_time,
                        short_windows=parse_int_list(args.short_windows),
                        long_windows=parse_int_list(args.long_windows),
                        sort_by=args.sort_by,
                        top=args.top,
                    ),
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "dashboard":
            run_dashboard(config, host=args.host, port=args.port)
            return

        if args.command == "test-order":
            bitget_test_order_gate = _bitget_live_test_order_gate(config)
            if bitget_test_order_gate is not None:
                print(json.dumps(bitget_test_order_gate, ensure_ascii=False))
                raise SystemExit(2)
            broker = create_broker(config)
            storage = SQLiteStorage(config.db_path)
            order = OrderRequest(
                symbol=args.symbol or config.symbol,
                side=args.side,
                quantity=args.quantity,
                price=args.price,
            )
            result = broker.submit_order(order)
            if not isinstance(result, dict):
                storage.record_exchange_order(result, mode=config.mode, exchange=config.exchange)
            payload = result if isinstance(result, dict) else result.model_dump()
            print(json.dumps(payload, ensure_ascii=False))
            return

        if args.command == "order-status":
            broker = create_broker(config)
            storage = SQLiteStorage(config.db_path)
            result = broker.order_status(args.symbol or config.symbol, args.order_id)
            if not isinstance(result, dict):
                storage.record_exchange_order(result, mode=config.mode, exchange=config.exchange)
            payload = result if isinstance(result, dict) else result.model_dump()
            print(json.dumps(payload, ensure_ascii=False))
            return

        if args.command == "cancel-order":
            broker = create_broker(config)
            storage = SQLiteStorage(config.db_path)
            result = broker.cancel_order(args.symbol or config.symbol, args.order_id)
            if not isinstance(result, dict):
                storage.record_exchange_order(result, mode=config.mode, exchange=config.exchange)
            payload = result if isinstance(result, dict) else result.model_dump()
            print(json.dumps(payload, ensure_ascii=False))
            return

        if args.command == "account-balance":
            broker = create_broker(config)
            result = broker.account_balance(args.symbol or config.symbol)
            payload = result if isinstance(result, dict) else result.model_dump()
            print(json.dumps(payload, ensure_ascii=False))
            return

        if args.command == "sync-fills":
            runner = TradingRunner(config)
            print(json.dumps(runner.sync_exchange_fills(limit=args.limit), ensure_ascii=False))
            return
    except MarketDataError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc

    parser.error(f"Unknown command: {args.command}")


def _run_paper_dry_run(config, input_file: str | None, max_iterations: int, sleep_seconds: float) -> dict:
    iterations = max(1, int(max_iterations))
    paper_config = config.model_copy(update={"mode": "paper", "market_data_source": "sqlite"})
    import_result = None
    if input_file:
        import_runner = TradingRunner(paper_config)
        import_result = import_runner.import_candles(input_file, paper_config.symbol, paper_config.interval)

    storage = SQLiteStorage(paper_config.db_path)
    preflight = run_preflight(paper_config, storage)
    if preflight["status"] != "pass":
        return {
            "status": "fail",
            "reason": "preflight_failed",
            "mode": paper_config.mode,
            "market_data_source": paper_config.market_data_source,
            "input_file": input_file,
            "import": import_result,
            "preflight": preflight,
            "evidence": _paper_dry_run_evidence(storage, paper_config),
        }

    before = _paper_dry_run_table_counts(storage)
    runner = TradingRunner(paper_config)
    loop_stdout = io.StringIO()
    with contextlib.redirect_stdout(loop_stdout):
        loop_result = runner.run_loop(max_iterations=iterations, sleep_seconds=sleep_seconds)
    after = _paper_dry_run_table_counts(storage)
    post_preflight = run_preflight(paper_config, storage)
    last = loop_result.get("last_result", {})
    status = "fail" if last.get("status") == "error" or post_preflight["status"] != "pass" else "pass"
    reason = last.get("reason") if last.get("status") == "error" else None

    return {
        "status": status,
        "reason": reason,
        "mode": paper_config.mode,
        "exchange": paper_config.exchange,
        "symbol": paper_config.symbol,
        "interval": paper_config.interval,
        "market_data_source": paper_config.market_data_source,
        "input_file": input_file,
        "import": import_result,
        "preflight": preflight,
        "post_preflight": post_preflight,
        "loop": loop_result,
        "loop_stdout": [line for line in loop_stdout.getvalue().splitlines() if line.strip()],
        "evidence": {
            **_paper_dry_run_evidence(storage, paper_config),
            "table_counts_before": before,
            "table_counts_after": after,
            "table_count_delta": {key: after.get(key, 0) - before.get(key, 0) for key in sorted(after)},
        },
    }


def _runtime_launch_gate(config, require_observed_testnet: bool) -> dict | None:
    if config.mode not in {"testnet", "live"}:
        return None

    checklist = run_launch_checklist(config, target_mode=config.mode)
    required_phase = _required_launch_phase(config.mode, require_observed_testnet)
    checklist_ready = checklist.get("status") == "pass" and _phase_ready(checklist.get("phase"), required_phase)
    checklist_ready = checklist_ready or _bitget_first_canary_ready(config, checklist)
    if not checklist_ready:
        return {
            "status": "error",
            "reason": "launch_checklist_blocked",
            "mode": config.mode,
            "required_phase": required_phase,
            "checklist": checklist,
            "next_steps": checklist.get("next_steps", []),
        }

    exchange_health = run_exchange_health_check(config)
    if exchange_health.get("status") == "pass":
        return None
    return {
        "status": "error",
        "reason": "launch_checklist_blocked",
        "mode": config.mode,
        "required_phase": required_phase,
        "checklist": checklist,
        "exchange_health": exchange_health,
        "next_steps": [*checklist.get("next_steps", []), *exchange_health.get("next_steps", [])],
    }


def _required_launch_phase(mode: str, require_observed_testnet: bool) -> str:
    if mode == "live":
        return "ready_for_bounded_live_loop"
    if require_observed_testnet:
        return "testnet_observed_ready_for_live_review"
    return "ready_for_testnet_dry_run"


def _phase_ready(phase: object, required_phase: str) -> bool:
    if phase == required_phase:
        return True
    if required_phase == "ready_for_testnet_dry_run":
        return phase in {
            "ready_for_bounded_testnet_order_observation",
            "testnet_observed_ready_for_live_review",
        }
    if required_phase == "ready_for_bounded_testnet_order_observation":
        return phase == "testnet_observed_ready_for_live_review"
    return False


def _bitget_live_iteration_gate(config, max_iterations: int | None) -> dict | None:
    if config.mode != "live" or config.exchange != "bitget":
        return None
    if max_iterations == 1:
        return None
    return {
        "status": "blocked",
        "reason": "bitget_live_canary_single_iteration_required",
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "max_iterations": max_iterations,
        "required_max_iterations": 1,
        "next_steps": [
            "rerun Bitget live canary with kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0",
            "do not start an unbounded or multi-iteration Bitget live loop during the gray phase",
        ],
    }


def _bitget_live_test_order_gate(config) -> dict | None:
    if config.mode != "live" or config.exchange != "bitget":
        return None
    return {
        "status": "blocked",
        "reason": "bitget_live_test_order_disabled",
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "next_steps": [
            "use kxian-bot live-setup-check before the Bitget canary",
            "run the Bitget canary only through kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0",
        ],
    }


def _bitget_live_run_once_gate(config) -> dict | None:
    if config.mode != "live" or config.exchange != "bitget":
        return None
    return {
        "status": "blocked",
        "reason": "bitget_live_run_once_disabled",
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "next_steps": [
            "run Bitget live canary only with kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0",
            "do not use run-once for Bitget live gray execution",
        ],
    }


def _bitget_first_canary_ready(config, checklist: dict) -> bool:
    if config.mode != "live" or config.exchange != "bitget":
        return False
    if checklist.get("phase") != "blocked_before_bitget_live_canary":
        return False
    failed_checks = [check for check in checklist.get("checks", []) if check.get("status") != "pass"]
    if len(failed_checks) != 1:
        return False
    check = failed_checks[0]
    if check.get("name") != "bitget_live_canary_order":
        return False
    failures = check.get("details", {}).get("failures", [])
    return failures == ["missing_bitget_live_canary_order"]


def _paper_dry_run_evidence(storage: SQLiteStorage, config) -> dict:
    candles = storage.load_candles(config.exchange, config.symbol, config.interval)
    profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
    if profile is None:
        profile = {
            "status": "default",
            "source": "config",
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "interval": config.interval,
            "strategy": config.strategy,
            "parameters": strategy_parameters(
                config.strategy,
                config.short_window,
                config.long_window,
                config.stop_loss_pct,
                config.take_profit_pct,
                config.trailing_stop_pct,
                config.cooldown_seconds,
            ),
            "evidence": {},
        }
    return {
        "active_profile": profile,
        "candle_count": len(candles),
        "required_candles": config.long_window + 5,
        "first_open_time": candles[0].open_time if candles else None,
        "last_open_time": candles[-1].open_time if candles else None,
    }


def _research_strategy_output(result: dict, summary_only: bool = False) -> dict:
    if not summary_only:
        return result
    keys = (
        "status",
        "reason",
        "error",
        "exchange",
        "symbol",
        "interval",
        "promote_requested",
        "ready_for_promotion",
        "promoted",
        "summary",
        "next_steps",
    )
    return {key: result[key] for key in keys if key in result}


def _screen_samples_output(result: dict, summary_only: bool = False) -> dict:
    if not summary_only:
        return result
    keys = (
        "status",
        "reason",
        "error",
        "exchange",
        "symbol",
        "interval",
        "source_interval",
        "runtime_interval",
        "resample_intervals",
        "strategies",
        "limit",
        "segments",
        "sample_count",
        "total_combinations",
        "max_combinations",
        "skip_combinations",
        "screen_min_trades",
        "evaluated_combinations",
        "skipped_by_offset",
        "seen_combinations",
        "budget_exhausted",
        "skipped_combinations",
        "prefilter_pass_count",
        "screen_only",
        "decision",
        "top_failure_reasons",
        "failed_gate_counts",
        "best_failed_candidate",
        "diagnostics",
        "recommended_actions",
        "selected",
        "intervals",
        "next_steps",
    )
    output = {key: result[key] for key in keys if key in result}
    output["candidates"] = [_screen_candidate_summary(candidate) for candidate in result.get("candidates", [])]
    return output


def _screen_candidate_summary(candidate: dict) -> dict:
    keys = (
        "status",
        "reason",
        "strategy",
        "parameters",
        "source_interval",
        "runtime_interval",
        "resample_interval",
        "sample_count",
        "passed_samples",
        "failed_samples",
        "screen_min_trades",
        "summary",
        "failed_sample_examples",
    )
    return {key: candidate[key] for key in keys if key in candidate}


def _walk_forward_samples_output(result: dict, summary_only: bool = False) -> dict:
    if not summary_only:
        return result
    keys = (
        "status",
        "reason",
        "exchange",
        "symbol",
        "interval",
        "source_interval",
        "runtime_interval",
        "resample_interval",
        "strategy",
        "parameters",
        "limit",
        "segments",
        "sample_count",
        "passed_samples",
        "failed_samples",
        "summary",
    )
    output = {key: result[key] for key in keys if key in result}
    output["samples"] = [
        {
            "input_file": sample.get("input_file"),
            "status": sample.get("status"),
            "reason": sample.get("reason"),
            "candle_count": sample.get("candle_count"),
            "walk_forward": sample.get("walk_forward"),
            "gate": sample.get("gate"),
            "failed_segments": sample.get("failed_segments", []),
        }
        for sample in result.get("samples", [])
    ]
    return output


def _paper_dry_run_table_counts(storage: SQLiteStorage) -> dict[str, int]:
    tables = ("candles", "strategy_signals", "fills", "exchange_orders", "risk_state", "loop_events")
    return {table: len(storage.fetch_all(table)) for table in tables}


def _write_testnet_evidence_if_requested(
    evidence_out: str | None,
    config,
    *,
    command: str,
    result: dict,
    launch_checklist: dict | None = None,
) -> None:
    if not evidence_out:
        return
    storage = SQLiteStorage(config.db_path)
    write_evidence(
        evidence_out,
        build_testnet_evidence(
            config,
            storage,
            command=command,
            result=result,
            launch_checklist=launch_checklist,
        ),
    )


def parse_int_list(value: str) -> list[int]:
    try:
        parsed = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a comma-separated integer list") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("Expected at least one integer")
    if any(item <= 0 for item in parsed):
        raise argparse.ArgumentTypeError("Window values must be positive")
    return parsed


def parse_float_list(value: str) -> list[float]:
    try:
        parsed = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a comma-separated number list") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("Expected at least one number")
    if any(item < 0 for item in parsed):
        raise argparse.ArgumentTypeError("Percentage values cannot be negative")
    return parsed


def parse_string_list(value: str) -> list[str]:
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    if not parsed:
        raise argparse.ArgumentTypeError("Expected at least one value")
    return parsed


def parse_input_files(value: str) -> list[str]:
    files: list[str] = []
    for item in parse_string_list(value):
        path = Path(item)
        if path.is_dir():
            files.extend(str(candidate) for candidate in sorted(path.glob("*.csv")) if candidate.is_file())
            continue
        if any(char in item for char in "*?["):
            matches = [Path(match) for match in glob(item)]
            files.extend(str(candidate) for candidate in sorted(matches) if candidate.is_file())
            continue
        files.append(item)
    if not files:
        raise argparse.ArgumentTypeError("Expected at least one input file")
    return files


def parse_strategy_list(value: str) -> list[str]:
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    if not parsed:
        raise argparse.ArgumentTypeError("Expected at least one strategy")
    invalid = sorted({item for item in parsed if item not in SUPPORTED_STRATEGIES})
    if invalid:
        raise argparse.ArgumentTypeError(f"Unsupported strategy: {', '.join(invalid)}")
    return parsed


def parse_timestamp_ms(value: str) -> int:
    text = value.strip()
    if text.isdigit():
        numeric = int(text)
        return numeric if numeric > 10_000_000_000 else numeric * 1000
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            parsed_datetime = datetime.combine(parsed_date, datetime_time.min, tzinfo=timezone.utc)
        else:
            parsed_datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        return int(parsed_datetime.timestamp() * 1000)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD, ISO datetime, seconds, or milliseconds") from exc


if __name__ == "__main__":
    main()
