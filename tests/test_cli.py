import json

from kxian_bot import cli
from kxian_bot.config import RuntimeConfig
from kxian_bot.models import Candle, LoopEvent


class FakeBroker:
    def submit_order(self, order):
        return {
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": order.price,
            "status": "submitted",
            "exchange_order_id": "123",
            "reason": "",
        }

    def order_status(self, symbol, order_id):
        return {"symbol": symbol, "exchange_order_id": order_id, "status": "filled"}

    def cancel_order(self, symbol, order_id):
        return {"symbol": symbol, "exchange_order_id": order_id, "status": "canceled"}

    def account_balance(self, symbol):
        return {
            "symbol": symbol,
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "usdt_balance": 100,
            "asset_balance": 0.01,
            "status": "synced",
        }

    def trade_history(self, symbol, limit=500):
        return []


class FakeRunner:
    instances = []

    def __init__(self, config):
        self.config = config
        self.sync_limits = []
        self.loop_calls = []
        FakeRunner.instances.append(self)

    def run_loop(self, max_iterations=None, sleep_seconds=None):
        self.loop_calls.append({"max_iterations": max_iterations, "sleep_seconds": sleep_seconds})
        return {
            "loop_id": "loop-1",
            "iterations": max_iterations,
            "sleep_seconds": sleep_seconds,
            "last_result": {"status": "idle"},
        }

    def run_once(self):
        return {"status": "idle", "reason": "no_signal"}

    def download_history(self, symbol, interval, start_time, end_time, limit_per_request, sleep_seconds):
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "downloaded_candles": 3,
            "changed_rows": 3,
        }

    def import_candles(self, input_file, symbol, interval):
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "input_file": input_file,
            "imported_candles": 6,
            "changed_rows": 6,
        }

    def import_candle_archives(self, input_dir, symbol, interval, pattern="*.zip", recursive=False):
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "input_dir": input_dir,
            "pattern": pattern,
            "recursive": recursive,
            "file_count": 2,
            "imported_file_count": 2,
            "failed_file_count": 0,
            "imported_candles": 12,
            "changed_rows": 12,
        }

    def prepare_samples(
        self,
        symbol,
        interval,
        start_time,
        end_time,
        sample_days,
        output_dir,
        source="auto",
        limit_per_request=None,
        sleep_seconds=0.0,
        min_candles=1,
    ):
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "sample_days": sample_days,
            "output_dir": output_dir,
            "source_requested": source,
            "limit_per_request": limit_per_request,
            "sleep_seconds": sleep_seconds,
            "min_candles": min_candles,
            "input_files": [f"{output_dir}/sample.csv"],
            "next_command": "kxian-bot select-sample-intervals --input-files sample.csv",
        }

    def research_strategy(
        self,
        symbol,
        interval,
        start_time,
        end_time,
        sample_days,
        output_dir,
        source,
        limit_per_request,
        sleep_seconds,
        min_candles,
        limit,
        segments,
        short_windows,
        long_windows,
        top,
        resample_intervals,
        promote=False,
        strategies=None,
        stop_loss_pcts=None,
        take_profit_pcts=None,
        trailing_stop_pcts=None,
    ):
        return {
            "status": "pass",
            "reason": "strategy_research_passed",
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "sample_days": sample_days,
            "output_dir": output_dir,
            "source": source,
            "limit_per_request": limit_per_request,
            "sleep_seconds": sleep_seconds,
            "min_candles": min_candles,
            "limit": limit,
            "segments": segments,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "top": top,
            "resample_intervals": resample_intervals,
            "promote_requested": promote,
            "strategies": strategies,
            "stop_loss_pcts": stop_loss_pcts,
            "take_profit_pcts": take_profit_pcts,
            "trailing_stop_pcts": trailing_stop_pcts,
            "ready_for_promotion": True,
            "prepare": {"status": "ok", "input_files": [f"{output_dir}/sample.csv"]},
            "selection": {"status": "pass", "selected_interval": {"runtime_interval": "15m"}},
            "summary": {
                "status": "pass",
                "sample_count": 1,
                "selected_runtime_interval": "15m",
                "best_candidate": {"status": "pass"},
                "top_failure_reasons": [],
                "decision": "promotable",
                "diagnostics": [{"code": "candidate_passed_all_gates"}],
                "recommended_actions": ["rerun research-strategy with --promote if this candidate is acceptable"],
            },
            "next_steps": ["run readiness and testnet-dry-run after promotion"],
            "promoted": {"profile_key": "paper:binance:BTCUSDT:15m"} if promote else None,
        }

    def batch_backtest(self, symbol, interval, start_time, end_time, short_windows, long_windows, sort_by, top):
        return {
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "candle_count": 100,
            "total_combinations": len(short_windows) * len(long_windows),
            "valid_combinations": 1,
            "skipped_combinations": 1,
            "sort_by": sort_by,
            "results": [{"run_id": "run-1", "return_pct": 1.2}],
        }

    def sync_exchange_fills(self, limit=500):
        self.sync_limits.append(limit)
        return {
            "status": "synced",
            "symbol": self.config.symbol,
            "seen_fills": limit,
            "imported_fills": 1,
            "average_entry_price": 100,
        }

    def stress_backtest(self, limit, input_file, resample_interval=None):
        return {
            "run_id": "stress-1",
            "scenario_count": 5,
            "input_file": input_file,
            "resample_interval": resample_interval,
            "limit": limit,
            "pass_rate": 100,
        }

    def walk_forward(self, limit, segments, input_file, resample_interval=None):
        return {
            "run_id": "walk-1",
            "segment_count": segments,
            "input_file": input_file,
            "resample_interval": resample_interval,
            "limit": limit,
            "pass_rate": 75,
        }

    def walk_forward_samples(self, limit, segments, input_files, resample_interval=None):
        return {
            "status": "pass",
            "reason": "all_samples_passed",
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "resample_interval": resample_interval,
            "sample_count": len(input_files),
            "passed_samples": len(input_files),
            "failed_samples": 0,
            "summary": {"min_pass_rate": 75},
            "samples": [
                {
                    "input_file": input_file,
                    "status": "pass",
                    "reason": "walk_forward_gate_passed",
                    "walk_forward": {"pass_rate": 75, "segment_count": segments},
                    "gate": {"allowed": True, "reason": "walk_forward_gate_passed"},
                    "failed_segments": [],
                    "segments": [{"index": 1}],
                }
                for input_file in input_files
            ],
        }

    def validate_strategy(self, limit, segments, input_file, resample_interval=None):
        return {
            "status": "pass",
            "limit": limit,
            "segments": segments,
            "input_file": input_file,
            "resample_interval": resample_interval,
            "gates": {"strategy_gate": {"allowed": True}},
        }

    def validate_samples(self, limit, segments, input_files, resample_interval=None):
        return {
            "status": "pass",
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "resample_interval": resample_interval,
            "sample_count": len(input_files),
            "passed_samples": len(input_files),
            "failed_samples": 0,
            "samples": [{"input_file": input_file, "status": "pass"} for input_file in input_files],
        }

    def market_diagnostics(self, limit, segments, input_file, resample_interval=None):
        return {
            "symbol": self.config.symbol,
            "limit": limit,
            "requested_segments": segments,
            "input_file": input_file,
            "resample_interval": resample_interval,
            "buy_hold_return_pct": 1.25,
            "segment_count": 4,
            "segments": [],
            "classification": {"regime": "mixed", "cost_pressure": "medium"},
        }

    def select_strategy(
        self,
        limit,
        segments,
        input_file,
        short_windows,
        long_windows,
        top,
        promote=False,
        strategies=None,
        stop_loss_pcts=None,
        take_profit_pcts=None,
        trailing_stop_pcts=None,
        resample_interval=None,
    ):
        return {
            "status": "pass",
            "limit": limit,
            "segments": segments,
            "input_file": input_file,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "strategies": strategies,
            "stop_loss_pcts": stop_loss_pcts,
            "take_profit_pcts": take_profit_pcts,
            "trailing_stop_pcts": trailing_stop_pcts,
            "resample_interval": resample_interval,
            "top": top,
            "promote": promote,
            "selected": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}},
            "promoted": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}} if promote else None,
        }

    def select_samples(
        self,
        limit,
        segments,
        input_files,
        short_windows,
        long_windows,
        top,
        promote=False,
        strategies=None,
        stop_loss_pcts=None,
        take_profit_pcts=None,
        trailing_stop_pcts=None,
        resample_interval=None,
    ):
        return {
            "status": "pass",
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "strategies": strategies,
            "stop_loss_pcts": stop_loss_pcts,
            "take_profit_pcts": take_profit_pcts,
            "trailing_stop_pcts": trailing_stop_pcts,
            "resample_interval": resample_interval,
            "top": top,
            "promote": promote,
            "sample_count": len(input_files),
            "selected": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}},
            "promoted": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}} if promote else None,
        }

    def select_sample_intervals(
        self,
        limit,
        segments,
        input_files,
        short_windows,
        long_windows,
        top,
        resample_intervals,
        promote=False,
        strategies=None,
        stop_loss_pcts=None,
        take_profit_pcts=None,
        trailing_stop_pcts=None,
    ):
        return {
            "status": "pass",
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "strategies": strategies,
            "stop_loss_pcts": stop_loss_pcts,
            "take_profit_pcts": take_profit_pcts,
            "trailing_stop_pcts": trailing_stop_pcts,
            "resample_intervals": resample_intervals,
            "top": top,
            "promote": promote,
            "runtime_interval": resample_intervals[0],
            "selected_interval": {
                "resample_interval": resample_intervals[0],
                "runtime_interval": resample_intervals[0],
                "selected": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}},
            },
            "promoted": {"parameters": {"short_window": short_windows[0], "long_window": long_windows[0]}} if promote else None,
        }

    def screen_samples(
        self,
        limit,
        segments,
        input_files,
        short_windows,
        long_windows,
        top,
        resample_intervals,
        strategies=None,
        stop_loss_pcts=None,
        take_profit_pcts=None,
        trailing_stop_pcts=None,
        max_combinations=None,
        skip_combinations=0,
        screen_min_trades=None,
    ):
        normalized_intervals = [None if interval in {"raw", "none", "native", "source"} else interval for interval in resample_intervals]
        return {
            "status": "pass",
            "reason": "prefilter_candidate_found",
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "strategies": strategies,
            "stop_loss_pcts": stop_loss_pcts,
            "take_profit_pcts": take_profit_pcts,
            "trailing_stop_pcts": trailing_stop_pcts,
            "resample_intervals": normalized_intervals,
            "top": top,
            "max_combinations": max_combinations,
            "skip_combinations": skip_combinations,
            "screen_min_trades": screen_min_trades,
            "screen_only": True,
            "runtime_interval": normalized_intervals[0],
            "selected": {
                "status": "prefilter_pass",
                "runtime_interval": normalized_intervals[0],
                "parameters": {"short_window": short_windows[0], "long_window": long_windows[0]},
            },
            "candidates": [
                {
                    "status": "prefilter_pass",
                    "runtime_interval": normalized_intervals[0],
                    "screen_min_trades": screen_min_trades,
                    "parameters": {"short_window": short_windows[0], "long_window": long_windows[0]},
                    "failed_sample_examples": [
                        {
                            "input_file": input_files[0],
                            "reason": "strategy_gate_return_too_low",
                            "backtest": {"return_pct": -1.0},
                        }
                    ],
                    "samples": [{"input_file": input_files[0], "backtest": {"return_pct": 1.0}}],
                }
            ],
        }


def test_preflight_cli(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(db_path=str(tmp_path / "test.sqlite3"))
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "run_preflight", lambda received: {"status": "pass", "db_path": received.db_path})
    monkeypatch.setattr("sys.argv", ["kxian-bot", "preflight"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "pass", "db_path": str(tmp_path / "test.sqlite3")}


def test_readiness_cli_uses_relaxed_config_and_redacts_credentials(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "test.sqlite3"),
        binance_api_key="api-key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "readiness"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output["mode"] == "testnet"
    assert output["credentials"]["binance_api_key"] is True
    assert output["credentials"]["binance_api_secret"] is True
    assert "api-key" not in json.dumps(output)
    assert '"secret"' not in json.dumps(output)


def test_exchange_health_cli_uses_relaxed_config(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"))
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    def fake_exchange_health(received_config, timeout_seconds=5.0):
        return {
            "status": "pass",
            "mode": received_config.mode,
            "timeout_seconds": timeout_seconds,
            "checks": [],
        }

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "run_exchange_health_check", fake_exchange_health)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "exchange-health", "--timeout-seconds", "1.5"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output == {"status": "pass", "mode": "testnet", "timeout_seconds": 1.5, "checks": []}


def test_exchange_health_cli_exits_when_exchange_unreachable(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(
        cli,
        "run_exchange_health_check",
        lambda config, timeout_seconds=5.0: {
            "status": "fail",
            "reason": "exchange_unreachable",
            "next_steps": ["verify this machine or deployment host can reach the selected exchange endpoints"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "exchange-health"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected exchange-health to exit when checks fail")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"


def test_launch_checklist_cli_uses_relaxed_config(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(mode="paper", db_path=str(tmp_path / "test.sqlite3"))
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    def fake_launch_checklist(received_config, target_mode=None):
        return {"status": "blocked", "db_path": received_config.db_path, "target_mode": target_mode}

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "run_launch_checklist", fake_launch_checklist)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "launch-checklist", "--target", "live"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output == {"status": "blocked", "db_path": str(tmp_path / "test.sqlite3"), "target_mode": "live"}


def test_testnet_setup_check_cli_uses_relaxed_config_and_redacts_credentials(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "test.sqlite3"),
        binance_api_key="api-key",
        binance_api_secret="super-secret-value",
    )
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    def fake_setup_check(received_config, timeout_seconds=5.0):
        return {
            "status": "fail",
            "mode": received_config.mode,
            "timeout_seconds": timeout_seconds,
            "credentials": {
                "present": {"binance_api_key": bool(received_config.binance_api_key), "binance_api_secret": bool(received_config.binance_api_secret)},
                "failures": [],
            },
            "next_steps": ["set KXIAN_ENABLE_TESTNET_AUTOTRADE=true only after credentials and exchange-health pass"],
        }

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "run_testnet_setup_check", fake_setup_check)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-setup-check", "--timeout-seconds", "1.5"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected testnet-setup-check to exit when setup is not ready")

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output["timeout_seconds"] == 1.5
    assert output["credentials"]["present"]["binance_api_key"] is True
    assert "api-key" not in json.dumps(output)
    assert "super-secret-value" not in json.dumps(output)


def test_run_once_cli_uses_relaxed_config_for_structured_launch_gate(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h")
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda received_config, target_mode=None: {
            "status": "blocked",
            "reason": "testnet_launch_blocked",
            "phase": "blocked_before_testnet",
            "target_mode": target_mode,
            "next_steps": ["set sandbox API credentials for the selected exchange"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "run-once"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected run-once to exit with structured launch gate output")

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output["reason"] == "launch_checklist_blocked"
    assert output["checklist"]["reason"] == "testnet_launch_blocked"


def test_pause_resume_and_status_cli(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path)))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "pause", "--reason", "review"])

    cli.main()

    paused = json.loads(capsys.readouterr().out)
    assert paused["paused"] is True
    assert paused["reason"] == "review"

    monkeypatch.setattr("sys.argv", ["kxian-bot", "automation-status"])
    cli.main()

    status = json.loads(capsys.readouterr().out)
    assert status["paused"] is True

    monkeypatch.setattr("sys.argv", ["kxian-bot", "resume", "--reason", "ready"])
    cli.main()

    resumed = json.loads(capsys.readouterr().out)
    assert resumed["paused"] is False
    assert resumed["reason"] == "ready"


def test_test_order_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "create_broker", lambda config: FakeBroker())
    monkeypatch.setattr(
        "sys.argv",
        ["kxian-bot", "test-order", "--side", "buy", "--quantity", "0.01", "--price", "100"],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "submitted"
    assert output["exchange_order_id"] == "123"


def test_order_status_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "create_broker", lambda config: FakeBroker())
    monkeypatch.setattr("sys.argv", ["kxian-bot", "order-status", "--order-id", "123"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "filled"


def test_cancel_order_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "create_broker", lambda config: FakeBroker())
    monkeypatch.setattr("sys.argv", ["kxian-bot", "cancel-order", "--order-id", "123"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "canceled"


def test_account_balance_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "create_broker", lambda config: FakeBroker())
    monkeypatch.setattr("sys.argv", ["kxian-bot", "account-balance", "--symbol", "BTCUSDT"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "synced"
    assert output["usdt_balance"] == 100
    assert output["asset_balance"] == 0.01


def test_sync_fills_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "sync-fills", "--limit", "25"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "synced"
    assert output["seen_fills"] == 25
    assert output["imported_fills"] == 1


def test_testnet_dry_run_rejects_non_testnet_mode(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-dry-run"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected non-testnet dry run to exit")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "testnet_mode_required"


def test_testnet_dry_run_reports_missing_credentials_as_json(monkeypatch, capsys, tmp_path):
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return RuntimeConfig(
            mode="testnet",
            db_path=str(tmp_path / "test.sqlite3"),
            interval="4h",
            binance_api_key="",
            binance_api_secret="",
        )

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-dry-run"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected missing credentials dry run to exit")

    raw_output = capsys.readouterr().out
    output = json.loads(raw_output)
    assert received["validate_execution"] is False
    assert output["status"] == "fail"
    assert output["reason"] == "missing_exchange_credentials"
    assert output["credentials"]["failures"] == ["missing_binance_api_key", "missing_binance_api_secret"]
    assert output["credentials"]["present"]["binance_api_key"] is False
    assert output["credentials"]["present"]["binance_api_secret"] is False
    assert output["next_steps"][0] == "set sandbox API credentials for the selected exchange"


def test_testnet_dry_run_runs_checks_and_fill_sync_without_loop(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "test.sqlite3"),
        binance_api_key="key",
        binance_api_secret="secret",
    )
    received = {}

    def fake_run_testnet_dry_run(received_config, sync_limit, execute_loop, sleep_seconds):
        received.update(
            {
                "config": received_config,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
            }
        )
        return {
            "status": "pass",
            "mode": received_config.mode,
            "symbol": received_config.symbol,
            "fill_sync": {"seen_fills": sync_limit},
            "loop": None,
        }

    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: config)
    monkeypatch.setattr(cli, "run_testnet_dry_run", fake_run_testnet_dry_run)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-dry-run", "--sync-limit", "25"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["fill_sync"]["seen_fills"] == 25
    assert output["loop"] is None
    assert received["config"] == config
    assert received["sync_limit"] == 25
    assert received["execute_loop"] is False
    assert received["sleep_seconds"] == 0.0


def test_testnet_dry_run_execute_loop_runs_one_iteration(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "test.sqlite3"),
        binance_api_key="key",
        binance_api_secret="secret",
    )
    received = {}

    def fake_run_testnet_dry_run(received_config, sync_limit, execute_loop, sleep_seconds):
        received.update(
            {
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
            }
        )
        return {
            "status": "pass",
            "mode": received_config.mode,
            "symbol": received_config.symbol,
            "fill_sync": {"seen_fills": sync_limit},
            "loop": {"iterations": 1},
        }

    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: config)
    monkeypatch.setattr(cli, "run_testnet_dry_run", fake_run_testnet_dry_run)
    monkeypatch.setattr(
        "sys.argv",
        ["kxian-bot", "testnet-dry-run", "--sync-limit", "25", "--execute-loop", "--sleep-seconds", "0"],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["loop"]["iterations"] == 1
    assert received == {"sync_limit": 25, "execute_loop": True, "sleep_seconds": 0.0}


def test_testnet_observe_cli_runs_relaxed_config_and_passes_options(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "test.sqlite3"),
        binance_api_key="key",
        binance_api_secret="secret",
    )
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    def fake_observation(received_config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure):
        received.update(
            {
                "config": received_config,
                "cycles": cycles,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
                "continue_on_failure": continue_on_failure,
            }
        )
        return {"status": "pass", "cycles_completed": cycles, "failures": 0}

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "run_testnet_observation", fake_observation)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "testnet-observe",
            "--cycles",
            "4",
            "--sync-limit",
            "25",
            "--sleep-seconds",
            "0",
            "--execute-loop",
            "--continue-on-failure",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["cycles_completed"] == 4
    assert received == {
        "validate_execution": False,
        "config": config,
        "cycles": 4,
        "sync_limit": 25,
        "execute_loop": True,
        "sleep_seconds": 0.0,
        "continue_on_failure": True,
    }


def test_testnet_observe_cli_defaults_to_six_cycles(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"))
    received = {}

    def fake_observation(received_config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure):
        received.update(
            {
                "cycles": cycles,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
                "continue_on_failure": continue_on_failure,
            }
        )
        return {"status": "pass", "cycles_requested": cycles, "cycles_completed": cycles, "failures": 0}

    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: config)
    monkeypatch.setattr(cli, "run_testnet_observation", fake_observation)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-observe"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["cycles_requested"] == 6
    assert output["cycles_completed"] == 6
    assert received == {
        "cycles": 6,
        "sync_limit": 500,
        "execute_loop": False,
        "sleep_seconds": 60.0,
        "continue_on_failure": False,
    }


def test_testnet_observe_cli_exits_on_failed_observation(monkeypatch, capsys, tmp_path):
    config = RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"))
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: config)
    monkeypatch.setattr(
        cli,
        "run_testnet_observation",
        lambda config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure: {
            "status": "fail",
            "reason": "missing_exchange_credentials",
            "cycles_completed": 1,
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "testnet-observe", "--cycles", "2", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected failed testnet observation to exit")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "missing_exchange_credentials"
    assert output["cycles_completed"] == 1


def test_paper_dry_run_cli_uses_relaxed_config_and_forces_sqlite_paper(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return RuntimeConfig(
            mode="testnet",
            market_data_source="exchange",
            db_path=str(tmp_path / "test.sqlite3"),
        )

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config, storage=None: {"status": "pass", "mode": config.mode, "source": config.market_data_source})
    monkeypatch.setattr("sys.argv", ["kxian-bot", "paper-dry-run", "--max-iterations", "1", "--sleep-seconds", "0"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output["status"] == "pass"
    assert output["mode"] == "paper"
    assert output["market_data_source"] == "sqlite"
    assert output["loop"]["iterations"] == 1
    assert FakeRunner.instances[0].config.mode == "paper"
    assert FakeRunner.instances[0].config.market_data_source == "sqlite"


def test_paper_dry_run_records_loop_evidence_with_sqlite_data(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_candles(
        [
            Candle(open_time=index * 60_000, open=price, high=price + 1, low=price - 1, close=price, volume=1, close_time=index * 60_000 + 59_000)
            for index, price in enumerate([10, 9, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    config = RuntimeConfig(
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
    )

    output = cli._run_paper_dry_run(config, input_file=None, max_iterations=1, sleep_seconds=0)

    assert output["status"] == "pass"
    assert output["mode"] == "paper"
    assert output["market_data_source"] == "sqlite"
    assert output["preflight"]["status"] == "pass"
    assert output["post_preflight"]["status"] == "pass"
    assert output["loop"]["iterations"] == 1
    assert output["evidence"]["candle_count"] == 12
    assert output["evidence"]["required_candles"] == 10
    assert output["evidence"]["table_count_delta"]["loop_events"] == 1
    assert output["evidence"]["table_counts_after"]["loop_events"] == 1


def test_download_history_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "download-history",
            "--exchange",
            "okx",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1m",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--limit-per-request",
            "100",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["exchange"] == "okx"
    assert output["downloaded_candles"] == 3
    assert output["start_time"] == 1704067200000


def test_import_candles_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "import-candles",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["imported_candles"] == 6
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"


def test_import_candle_archives_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "import-candle-archives",
            "--input-dir",
            "data",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1m",
            "--pattern",
            "*.zip",
            "--recursive",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["input_dir"] == "data"
    assert output["pattern"] == "*.zip"
    assert output["recursive"] is True
    assert output["file_count"] == 2
    assert output["imported_candles"] == 12


def test_import_candle_archives_cli_exits_when_import_fails(monkeypatch, capsys, tmp_path):
    class FailingArchiveRunner(FakeRunner):
        def import_candle_archives(self, input_dir, symbol, interval, pattern="*.zip", recursive=False):
            return {
                "status": "fail",
                "reason": "no_archive_files",
                "input_dir": input_dir,
                "pattern": pattern,
                "file_count": 0,
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingArchiveRunner)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "import-candle-archives", "--input-dir", "missing"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected SystemExit")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "no_archive_files"


def test_prepare_samples_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "prepare-samples",
            "--exchange",
            "okx",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1m",
            "--start",
            "2024-01-01",
            "--end",
            "2024-04-01",
            "--sample-days",
            "30",
            "--output-dir",
            "data/samples",
            "--source",
            "sqlite",
            "--limit-per-request",
            "100",
            "--sleep-seconds",
            "0.1",
            "--min-candles",
            "20",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["exchange"] == "okx"
    assert output["symbol"] == "BTCUSDT"
    assert output["start_time"] == 1704067200000
    assert output["end_time"] == 1711929600000
    assert output["sample_days"] == 30
    assert output["output_dir"] == "data/samples"
    assert output["source_requested"] == "sqlite"
    assert output["limit_per_request"] == 100
    assert output["sleep_seconds"] == 0.1
    assert output["min_candles"] == 20
    assert "select-sample-intervals" in output["next_command"]


def test_research_strategy_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "research-strategy",
            "--exchange",
            "binance",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1m",
            "--start",
            "2024-01-01",
            "--end",
            "2024-04-01",
            "--sample-days",
            "30",
            "--output-dir",
            "data/samples",
            "--source",
            "sqlite",
            "--limit-per-request",
            "100",
            "--sleep-seconds",
            "0.1",
            "--min-candles",
            "20",
            "--limit",
            "900",
            "--segments",
            "4",
            "--resample-intervals",
            "raw,15m",
            "--short-windows",
            "3,5",
            "--long-windows",
            "10,20",
            "--stop-loss-pcts",
            "0,1.5",
            "--take-profit-pcts",
            "0,3",
            "--trailing-stop-pcts",
            "0,2",
            "--strategies",
            "moving_average_cross,mean_reversion,momentum_breakout",
            "--top",
            "2",
            "--promote",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["start_time"] == 1704067200000
    assert output["end_time"] == 1711929600000
    assert output["sample_days"] == 30
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["resample_intervals"] == ["raw", "15m"]
    assert output["short_windows"] == [3, 5]
    assert output["long_windows"] == [10, 20]
    assert output["strategies"] == ["moving_average_cross", "mean_reversion", "momentum_breakout"]
    assert output["stop_loss_pcts"] == [0.0, 1.5]
    assert output["take_profit_pcts"] == [0.0, 3.0]
    assert output["trailing_stop_pcts"] == [0.0, 2.0]
    assert output["top"] == 2
    assert output["promote_requested"] is True
    assert output["promoted"]["profile_key"] == "paper:binance:BTCUSDT:15m"
    assert output["summary"]["selected_runtime_interval"] == "15m"


def test_research_strategy_cli_summary_only(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "research-strategy",
            "--start",
            "2024-01-01",
            "--end",
            "2024-04-01",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
            "--summary-only",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["summary"]["selected_runtime_interval"] == "15m"
    assert output["summary"]["decision"] == "promotable"
    assert output["summary"]["recommended_actions"] == ["rerun research-strategy with --promote if this candidate is acceptable"]
    assert output["next_steps"] == ["run readiness and testnet-dry-run after promotion"]
    assert "prepare" not in output
    assert "selection" not in output


def test_research_strategy_cli_exits_when_selection_fails(monkeypatch, capsys, tmp_path):
    class FailingResearchRunner(FakeRunner):
        def research_strategy(self, *args, **kwargs):
            return {
                "status": "fail",
                "reason": "strategy_research_failed",
                "prepare": {"status": "ok"},
                "selection": {"status": "fail", "reason": "no_interval_passed_validation"},
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingResearchRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "research-strategy",
            "--start",
            "2024-01-01",
            "--end",
            "2024-04-01",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected research-strategy to exit when no candidate passes")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "strategy_research_failed"


def test_trading_rules_cli_sets_rule(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path)))
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "trading-rules",
            "--symbol",
            "BTCUSDT",
            "--price-step",
            "0.1",
            "--quantity-step",
            "0.001",
            "--min-quantity",
            "0.001",
            "--min-notional",
            "10",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["price_step"] == 0.1
    assert output["quantity_step"] == 0.001
    stored = cli.SQLiteStorage(db_path).latest_trading_rule("binance", "BTCUSDT")
    assert stored["min_notional"] == 10


def test_batch_backtest_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "batch-backtest",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--short-windows",
            "2,3",
            "--long-windows",
            "3",
            "--top",
            "5",
            "--sort-by",
            "profit_factor",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["total_combinations"] == 2
    assert output["sort_by"] == "profit_factor"
    assert output["results"][0]["run_id"] == "run-1"


def test_stress_backtest_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "stress-backtest",
            "--limit",
            "500",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--resample-interval",
            "5m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "stress-1"
    assert output["scenario_count"] == 5
    assert output["limit"] == 500
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"
    assert output["resample_interval"] == "5m"


def test_walk_forward_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "walk-forward",
            "--limit",
            "900",
            "--segments",
            "3",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--resample-interval",
            "5m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "walk-1"
    assert output["segment_count"] == 3
    assert output["limit"] == 900
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"
    assert output["resample_interval"] == "5m"


def test_walk_forward_samples_cli_summary_only(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "walk-forward-samples",
            "--limit",
            "900",
            "--segments",
            "3",
            "--input-files",
            "sample_data/january.csv, sample_data/february.csv",
            "--resample-interval",
            "5m",
            "--summary-only",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 3
    assert output["sample_count"] == 2
    assert output["resample_interval"] == "5m"
    assert output["samples"][0]["input_file"] == "sample_data/january.csv"
    assert output["samples"][0]["walk_forward"]["pass_rate"] == 75
    assert "segments" not in output["samples"][0]


def test_walk_forward_samples_cli_exits_when_any_sample_fails(monkeypatch, capsys, tmp_path):
    class FailingWalkForwardSamplesRunner(FakeRunner):
        def walk_forward_samples(self, limit, segments, input_files, resample_interval=None):
            return {
                "status": "fail",
                "reason": "sample_walk_forward_failed",
                "sample_count": len(input_files),
                "passed_samples": 0,
                "failed_samples": len(input_files),
                "samples": [{"input_file": input_file, "status": "fail"} for input_file in input_files],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingWalkForwardSamplesRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "walk-forward-samples",
            "--input-files",
            "sample_data/january.csv,sample_data/february.csv",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected walk-forward-samples to exit when a sample fails")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "sample_walk_forward_failed"


def test_validate_strategy_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "validate-strategy",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--resample-interval",
            "5m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"
    assert output["resample_interval"] == "5m"


def test_validate_strategy_cli_exits_when_gate_fails(monkeypatch, capsys, tmp_path):
    class FailingValidationRunner(FakeRunner):
        def validate_strategy(self, limit, segments, input_file, resample_interval=None):
            return {
                "status": "fail",
                "limit": limit,
                "segments": segments,
                "gates": {"strategy_gate": {"allowed": False, "reason": "strategy_gate_insufficient_trades"}},
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingValidationRunner)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "validate-strategy", "--limit", "900"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected validate-strategy to exit when validation fails")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["gates"]["strategy_gate"]["allowed"] is False


def test_validate_samples_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "validate-samples",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-files",
            "sample_data/january.csv, sample_data/february.csv",
            "--resample-interval",
            "15m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_files"] == ["sample_data/january.csv", "sample_data/february.csv"]
    assert output["sample_count"] == 2
    assert output["resample_interval"] == "15m"


def test_validate_samples_cli_exits_when_any_sample_fails(monkeypatch, capsys, tmp_path):
    class FailingSamplesRunner(FakeRunner):
        def validate_samples(self, limit, segments, input_files, resample_interval=None):
            return {
                "status": "fail",
                "reason": "sample_validation_failed",
                "limit": limit,
                "segments": segments,
                "input_files": input_files,
                "failed_samples": 1,
                "samples": [{"input_file": input_files[0], "status": "fail"}],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingSamplesRunner)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "validate-samples", "--input-files", "sample_data/january.csv"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected validate-samples to exit when validation fails")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "sample_validation_failed"


def test_market_diagnostics_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "market-diagnostics",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--resample-interval",
            "15m",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["symbol"] == "BTCUSDT"
    assert output["limit"] == 900
    assert output["requested_segments"] == 4
    assert output["segment_count"] == 4
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"
    assert output["resample_interval"] == "15m"
    assert output["classification"]["regime"] == "mixed"


def test_select_strategy_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-strategy",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-file",
            "sample_data/binance_btcusdt_1m.json",
            "--resample-interval",
            "5m",
            "--short-windows",
            "3,5",
            "--long-windows",
            "10,20",
            "--stop-loss-pcts",
            "0,1.5",
            "--take-profit-pcts",
            "0,3",
            "--trailing-stop-pcts",
            "0,2",
            "--top",
            "2",
            "--promote",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_file"] == "sample_data/binance_btcusdt_1m.json"
    assert output["resample_interval"] == "5m"
    assert output["short_windows"] == [3, 5]
    assert output["long_windows"] == [10, 20]
    assert output["strategies"] is None
    assert output["stop_loss_pcts"] == [0.0, 1.5]
    assert output["take_profit_pcts"] == [0.0, 3.0]
    assert output["trailing_stop_pcts"] == [0.0, 2.0]
    assert output["top"] == 2
    assert output["promote"] is True
    assert output["promoted"]["parameters"]["short_window"] == 3


def test_select_strategy_cli_accepts_strategy_grid(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-strategy",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
            "--strategies",
            "moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["strategies"] == [
        "moving_average_cross",
        "donchian_breakout",
        "trend_pullback",
        "mean_reversion",
        "rsi_mean_reversion",
    ]


def test_select_strategy_cli_exits_when_no_candidate_passes(monkeypatch, capsys, tmp_path):
    class FailingSelectionRunner(FakeRunner):
        def select_strategy(
            self,
            limit,
            segments,
            input_file,
            short_windows,
            long_windows,
            top,
            promote=False,
            strategies=None,
            stop_loss_pcts=None,
            take_profit_pcts=None,
            trailing_stop_pcts=None,
            resample_interval=None,
        ):
            return {
                "status": "fail",
                "reason": "no_candidate_passed_validation",
                "candidates": [],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingSelectionRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-strategy",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected select-strategy to exit when no candidate passes")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "no_candidate_passed_validation"


def test_select_samples_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-samples",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-files",
            "sample_data/january.csv, sample_data/february.csv",
            "--resample-interval",
            "15m",
            "--short-windows",
            "3,5",
            "--long-windows",
            "10,20",
            "--stop-loss-pcts",
            "0,1.5",
            "--take-profit-pcts",
            "0,3",
            "--trailing-stop-pcts",
            "0,2",
            "--strategies",
            "moving_average_cross,mean_reversion",
            "--top",
            "2",
            "--promote",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_files"] == ["sample_data/january.csv", "sample_data/february.csv"]
    assert output["sample_count"] == 2
    assert output["resample_interval"] == "15m"
    assert output["short_windows"] == [3, 5]
    assert output["long_windows"] == [10, 20]
    assert output["strategies"] == ["moving_average_cross", "mean_reversion"]
    assert output["stop_loss_pcts"] == [0.0, 1.5]
    assert output["take_profit_pcts"] == [0.0, 3.0]
    assert output["trailing_stop_pcts"] == [0.0, 2.0]
    assert output["top"] == 2
    assert output["promote"] is True
    assert output["promoted"]["parameters"]["short_window"] == 3


def test_select_samples_cli_exits_when_no_candidate_passes(monkeypatch, capsys, tmp_path):
    class FailingSampleSelectionRunner(FakeRunner):
        def select_samples(
            self,
            limit,
            segments,
            input_files,
            short_windows,
            long_windows,
            top,
            promote=False,
            strategies=None,
            stop_loss_pcts=None,
            take_profit_pcts=None,
            trailing_stop_pcts=None,
            resample_interval=None,
        ):
            return {
                "status": "fail",
                "reason": "no_candidate_passed_validation",
                "candidates": [],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingSampleSelectionRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-samples",
            "--input-files",
            "sample_data/january.csv,sample_data/february.csv",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected select-samples to exit when no candidate passes")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "no_candidate_passed_validation"


def test_select_sample_intervals_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-sample-intervals",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-files",
            "sample_data/january.csv, sample_data/february.csv",
            "--resample-intervals",
            "15m,30m,1h",
            "--short-windows",
            "3,5",
            "--long-windows",
            "10,20",
            "--stop-loss-pcts",
            "0,1.5",
            "--take-profit-pcts",
            "0,3",
            "--trailing-stop-pcts",
            "0,2",
            "--strategies",
            "moving_average_cross,mean_reversion",
            "--top",
            "2",
            "--promote",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_files"] == ["sample_data/january.csv", "sample_data/february.csv"]
    assert output["resample_intervals"] == ["15m", "30m", "1h"]
    assert output["short_windows"] == [3, 5]
    assert output["long_windows"] == [10, 20]
    assert output["strategies"] == ["moving_average_cross", "mean_reversion"]
    assert output["stop_loss_pcts"] == [0.0, 1.5]
    assert output["take_profit_pcts"] == [0.0, 3.0]
    assert output["trailing_stop_pcts"] == [0.0, 2.0]
    assert output["top"] == 2
    assert output["promote"] is True
    assert output["selected_interval"]["runtime_interval"] == "15m"


def test_select_sample_intervals_cli_exits_when_no_interval_passes(monkeypatch, capsys, tmp_path):
    class FailingIntervalSelectionRunner(FakeRunner):
        def select_sample_intervals(
            self,
            limit,
            segments,
            input_files,
            short_windows,
            long_windows,
            top,
            resample_intervals,
            promote=False,
            strategies=None,
            stop_loss_pcts=None,
            take_profit_pcts=None,
            trailing_stop_pcts=None,
        ):
            return {
                "status": "fail",
                "reason": "no_interval_passed_validation",
                "intervals": [],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingIntervalSelectionRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "select-sample-intervals",
            "--input-files",
            "sample_data/january.csv,sample_data/february.csv",
            "--resample-intervals",
            "15m,30m",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected select-sample-intervals to exit when no interval passes")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "no_interval_passed_validation"


def test_screen_samples_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "screen-samples",
            "--limit",
            "900",
            "--segments",
            "4",
            "--input-files",
            "sample_data/january.csv, sample_data/february.csv",
            "--resample-intervals",
            "raw,15m,30m",
            "--short-windows",
            "3,5",
            "--long-windows",
            "10,20",
            "--stop-loss-pcts",
            "0,1.5",
            "--take-profit-pcts",
            "0,3",
            "--trailing-stop-pcts",
            "0,2",
            "--strategies",
            "moving_average_cross,mean_reversion",
            "--top",
            "2",
            "--max-combinations",
            "17",
            "--skip-combinations",
            "5",
            "--screen-min-trades",
            "5",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["reason"] == "prefilter_candidate_found"
    assert output["screen_only"] is True
    assert output["limit"] == 900
    assert output["segments"] == 4
    assert output["input_files"] == ["sample_data/january.csv", "sample_data/february.csv"]
    assert output["resample_intervals"] == [None, "15m", "30m"]
    assert output["short_windows"] == [3, 5]
    assert output["long_windows"] == [10, 20]
    assert output["strategies"] == ["moving_average_cross", "mean_reversion"]
    assert output["stop_loss_pcts"] == [0.0, 1.5]
    assert output["take_profit_pcts"] == [0.0, 3.0]
    assert output["trailing_stop_pcts"] == [0.0, 2.0]
    assert output["top"] == 2
    assert output["max_combinations"] == 17
    assert output["skip_combinations"] == 5
    assert output["screen_min_trades"] == 5
    assert output["candidates"][0]["screen_min_trades"] == 5
    assert output["selected"]["runtime_interval"] is None


def test_screen_samples_cli_summary_only(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "screen-samples",
            "--input-files",
            "sample_data/january.csv",
            "--resample-intervals",
            "raw",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
            "--summary-only",
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["screen_only"] is True
    assert "input_files" not in output
    assert "short_windows" not in output
    assert output["selected"]["runtime_interval"] is None
    assert output["candidates"][0]["runtime_interval"] is None
    assert output["candidates"][0]["failed_sample_examples"][0]["backtest"]["return_pct"] == -1.0
    assert "samples" not in output["candidates"][0]


def test_screen_samples_cli_exits_when_no_prefilter_candidate_passes(monkeypatch, capsys, tmp_path):
    class FailingScreenRunner(FakeRunner):
        def screen_samples(
            self,
            limit,
            segments,
            input_files,
            short_windows,
            long_windows,
            top,
            resample_intervals,
            strategies=None,
            stop_loss_pcts=None,
            take_profit_pcts=None,
            trailing_stop_pcts=None,
            max_combinations=None,
            skip_combinations=0,
            screen_min_trades=None,
        ):
            return {
                "status": "fail",
                "reason": "no_candidate_passed_prefilter",
                "candidates": [],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FailingScreenRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "screen-samples",
            "--input-files",
            "sample_data/january.csv,sample_data/february.csv",
            "--resample-intervals",
            "15m,30m",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected screen-samples to exit when no prefilter candidate passes")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "no_candidate_passed_prefilter"


def test_screen_samples_summary_includes_load_error(monkeypatch, capsys, tmp_path):
    class LoadFailureScreenRunner(FakeRunner):
        def screen_samples(
            self,
            limit,
            segments,
            input_files,
            short_windows,
            long_windows,
            top,
            resample_intervals,
            strategies=None,
            stop_loss_pcts=None,
            take_profit_pcts=None,
            trailing_stop_pcts=None,
            max_combinations=None,
            skip_combinations=0,
            screen_min_trades=None,
        ):
            return {
                "status": "fail",
                "reason": "input_file_load_failed",
                "error": "missing.csv not found",
                "screen_only": True,
                "candidates": [],
            }

    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", LoadFailureScreenRunner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "kxian-bot",
            "screen-samples",
            "--input-files",
            "missing.csv",
            "--resample-intervals",
            "raw",
            "--short-windows",
            "3",
            "--long-windows",
            "10",
            "--summary-only",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected screen-samples to exit when input loading fails")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["reason"] == "input_file_load_failed"
    assert output["error"] == "missing.csv not found"


def test_strategy_profile_cli_outputs_active_profile(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 10},
        evidence={"backtest": {"run_id": "run-1"}},
        updated_by="test",
    )
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path)))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "strategy-profile"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["profile_key"] == "paper:binance:BTCUSDT:1m"
    assert output["parameters"]["short_window"] == 3
    assert output["parameters"]["long_window"] == 10
    assert output["evidence"]["backtest"]["run_id"] == "run-1"


def test_strategy_profile_cli_outputs_empty_when_no_profile(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "strategy-profile"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "empty"
    assert output["symbol"] == "BTCUSDT"


def test_strategy_profile_cli_is_read_only_when_testnet_credentials_are_missing(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={"sample_validation": {"status": "pass"}},
        updated_by="test",
    )
    monkeypatch.setenv("KXIAN_MODE", "testnet")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("KXIAN_INTERVAL", "4h")
    monkeypatch.setenv("KXIAN_DB_PATH", str(db_path))
    monkeypatch.delenv("KXIAN_BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("KXIAN_BINANCE_API_SECRET", raising=False)
    monkeypatch.setattr("sys.argv", ["kxian-bot", "strategy-profile"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["profile_key"] == "testnet:binance:BTCUSDT:4h"
    assert output["parameters"]["short_window"] == 10


def test_promote_profile_to_testnet_cli_outputs_promoted_profile(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30, "stop_loss_pct": 2, "take_profit_pct": 8},
        evidence={"sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0}},
        updated_by="test",
    )
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-testnet", "--updated-by", "test-cli"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["promoted"]["profile_key"] == "testnet:binance:BTCUSDT:4h"
    assert output["promoted"]["updated_by"] == "test-cli"


def test_promote_profile_to_testnet_cli_exits_when_source_profile_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3"), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-testnet"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected profile promotion to exit when source profile is missing")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "missing_source_profile"


def test_promote_profile_to_live_cli_outputs_promoted_profile(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30, "stop_loss_pct": 2, "take_profit_pct": 8},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="test",
    )
    _record_testnet_observation(storage, execute_loop=False)
    _record_testnet_observation(storage, execute_loop=True)
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-live", "--updated-by", "test-cli"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["promoted"]["profile_key"] == "live:binance:BTCUSDT:4h"
    assert output["promoted"]["updated_by"] == "test-cli"
    assert output["promoted"]["evidence"]["testnet_observation"]["bounded_order"]["execute_loop"] is True


def test_promote_profile_to_live_cli_exits_when_bounded_observation_lacks_lifecycle(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30, "stop_loss_pct": 2, "take_profit_pct": 8},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="test",
    )
    _record_testnet_observation(storage, execute_loop=False)
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id="observe-legacy-order",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": "legacy-order",
                    "cycle": cycle,
                    "status": "pass",
                    "execute_loop": True,
                },
            )
        )
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-live"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected live profile promotion to exit when lifecycle is missing")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "source_profile_missing_passing_testnet_order_observation"
    assert "missing_order_lifecycle" in output["failures"]


def test_promote_profile_to_live_cli_exits_without_testnet_promotion_evidence(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={"sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0}},
        updated_by="test",
    )
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-live"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected live profile promotion to exit when evidence is missing")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "source_profile_missing_testnet_promotion_evidence"


def test_promote_profile_to_live_cli_exits_without_testnet_observation(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="test",
    )
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-live"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected live profile promotion to exit when testnet observations are missing")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "source_profile_missing_passing_testnet_observation"


def test_promote_profile_to_live_cli_exits_when_testnet_observation_cycles_are_insufficient(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.sqlite3"
    storage = cli.SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="test",
    )
    _record_testnet_observation(storage, execute_loop=False, cycles=5)
    _record_testnet_observation(storage, execute_loop=True, cycles=6)
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(db_path), interval="4h"))
    monkeypatch.setattr("sys.argv", ["kxian-bot", "promote-profile-to-live"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected live profile promotion to exit when testnet observation has fewer than six cycles")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "source_profile_missing_passing_testnet_observation"
    assert output["testnet_observation"]["cycles_completed"] == 5
    assert "insufficient_testnet_observation_cycles" in output["failures"]


def test_dashboard_cli(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(cli, "load_config", lambda: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(
        cli,
        "run_dashboard",
        lambda config, host, port: called.update({"db_path": config.db_path, "host": host, "port": port}),
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "dashboard", "--host", "127.0.0.1", "--port", "8123"])

    cli.main()

    assert called == {"db_path": str(tmp_path / "test.sqlite3"), "host": "127.0.0.1", "port": 8123}


def test_run_once_testnet_blocks_when_launch_checklist_fails(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "blocked",
            "reason": "testnet_launch_blocked",
            "phase": "blocked_before_testnet",
            "target_mode": target_mode,
            "next_steps": ["set sandbox API credentials for the selected exchange"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "run-once"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected run-once to exit when launch checklist is blocked")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert output["required_phase"] == "ready_for_testnet_dry_run"
    assert output["checklist"]["reason"] == "testnet_launch_blocked"
    assert FakeRunner.instances == []


def test_run_once_testnet_runs_when_launch_checklist_passes(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "pass",
            "reason": "testnet_launch_ready",
            "phase": "ready_for_testnet_dry_run",
            "target_mode": target_mode,
            "next_steps": [],
        },
    )
    monkeypatch.setattr(cli, "run_exchange_health_check", lambda config: {"status": "pass", "next_steps": []})
    monkeypatch.setattr("sys.argv", ["kxian-bot", "run-once"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "idle", "reason": "no_signal"}
    assert len(FakeRunner.instances) == 1


def test_run_once_testnet_blocks_when_exchange_health_fails(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "pass",
            "reason": "testnet_launch_ready",
            "phase": "ready_for_testnet_dry_run",
            "target_mode": target_mode,
            "next_steps": [],
        },
    )
    monkeypatch.setattr(
        cli,
        "run_exchange_health_check",
        lambda config: {
            "status": "fail",
            "checks": [{"name": "public_market_data", "status": "fail"}],
            "next_steps": ["verify this machine or deployment host can reach the selected exchange endpoints"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "run-once"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected run-once to exit when exchange health fails")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert output["exchange_health"]["status"] == "fail"
    assert "verify this machine" in output["next_steps"][0]
    assert FakeRunner.instances == []


def test_trade_loop_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        "sys.argv",
        ["kxian-bot", "trade-loop", "--max-iterations", "2", "--sleep-seconds", "0"],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["loop_id"] == "loop-1"
    assert output["iterations"] == 2
    assert output["sleep_seconds"] == 0.0


def test_trade_loop_cli_blocks_when_preflight_fails(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(
        cli,
        "run_preflight",
        lambda config: {
            "status": "fail",
            "checks": [
                {
                    "name": "market_data",
                    "status": "fail",
                    "message": "not enough local candles",
                    "details": {"candles": 0, "required": 25},
                }
            ],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "1"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected trade-loop to stop on failed preflight")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["reason"] == "preflight_failed"
    assert output["preflight"]["checks"][0]["name"] == "market_data"


def test_trade_loop_testnet_blocks_when_launch_checklist_fails(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "blocked",
            "reason": "testnet_launch_blocked",
            "phase": "blocked_before_testnet",
            "target_mode": target_mode,
            "next_steps": ["set sandbox API credentials for the selected exchange"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected trade-loop to stop on blocked launch checklist")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert output["required_phase"] == "ready_for_testnet_dry_run"
    assert output["checklist"]["target_mode"] == "testnet"
    assert FakeRunner.instances == []


def test_trade_loop_cli_uses_relaxed_config_for_structured_launch_gate(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    config = RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h")
    received = {}

    def fake_load_config(validate_execution=True):
        received["validate_execution"] = validate_execution
        return config

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda received_config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda received_config, target_mode=None: {
            "status": "blocked",
            "reason": "testnet_launch_blocked",
            "phase": "blocked_before_testnet",
            "target_mode": target_mode,
            "next_steps": ["set sandbox API credentials for the selected exchange"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected trade-loop to exit with structured launch gate output")

    output = json.loads(capsys.readouterr().out)
    assert received["validate_execution"] is False
    assert output["reason"] == "launch_checklist_blocked"
    assert FakeRunner.instances == []


def test_trade_loop_testnet_infinite_loop_requires_observed_testnet(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "pass",
            "reason": "testnet_launch_ready",
            "phase": "ready_for_testnet_dry_run",
            "target_mode": target_mode,
            "next_steps": ["run kxian-bot testnet-observe --cycles 6 --sleep-seconds 60"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected unbounded testnet loop to require observation evidence")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert output["required_phase"] == "testnet_observed_ready_for_live_review"
    assert output["checklist"]["phase"] == "ready_for_testnet_dry_run"
    assert FakeRunner.instances == []


def test_trade_loop_testnet_runs_when_launch_and_exchange_health_pass(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "pass",
            "reason": "testnet_launch_ready",
            "phase": "ready_for_testnet_dry_run",
            "target_mode": target_mode,
            "next_steps": [],
        },
    )
    monkeypatch.setattr(cli, "run_exchange_health_check", lambda config: {"status": "pass", "next_steps": []})
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["loop_id"] == "loop-1"
    assert output["iterations"] == 1
    assert len(FakeRunner.instances) == 1


def test_trade_loop_live_requires_live_launch_checklist(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="live", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "blocked",
            "reason": "live_launch_blocked",
            "phase": "blocked_before_live",
            "target_mode": target_mode,
            "next_steps": ["run kxian-bot promote-profile-to-live after both testnet observations pass"],
        },
    )
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected live trade-loop to require live launch checklist")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert output["required_phase"] == "ready_for_bounded_live_loop"
    assert output["checklist"]["target_mode"] == "live"
    assert FakeRunner.instances == []


def test_trade_loop_cli_skip_preflight_runs_loop(monkeypatch, capsys, tmp_path):
    def fail_if_called(config):
        raise AssertionError("preflight should be skipped")

    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", fail_if_called)
    monkeypatch.setattr(
        "sys.argv",
        ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0", "--skip-preflight"],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["loop_id"] == "loop-1"
    assert output["iterations"] == 1


def test_trade_loop_skip_preflight_still_enforces_testnet_launch_gate(monkeypatch, capsys, tmp_path):
    FakeRunner.instances = []

    def fail_if_called(config):
        raise AssertionError("preflight should be skipped")

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda validate_execution=True: RuntimeConfig(mode="testnet", db_path=str(tmp_path / "test.sqlite3"), interval="4h"),
    )
    monkeypatch.setattr(cli, "TradingRunner", FakeRunner)
    monkeypatch.setattr(cli, "run_preflight", fail_if_called)
    monkeypatch.setattr(
        cli,
        "run_launch_checklist",
        lambda config, target_mode=None: {
            "status": "blocked",
            "reason": "testnet_launch_blocked",
            "phase": "blocked_before_testnet",
            "target_mode": target_mode,
            "next_steps": ["set sandbox API credentials for the selected exchange"],
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        ["kxian-bot", "trade-loop", "--max-iterations", "1", "--sleep-seconds", "0", "--skip-preflight"],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected testnet trade-loop to enforce launch checklist even with --skip-preflight")

    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "launch_checklist_blocked"
    assert FakeRunner.instances == []


def test_trade_loop_cli_exits_when_circuit_breaker_trips(monkeypatch, capsys, tmp_path):
    class CircuitBreakerRunner(FakeRunner):
        def run_loop(self, max_iterations=None, sleep_seconds=None):
            return {
                "loop_id": "loop-1",
                "iterations": 3,
                "last_result": {"status": "error", "reason": "loop_circuit_breaker_tripped"},
            }

    monkeypatch.setattr(cli, "load_config", lambda validate_execution=True: RuntimeConfig(db_path=str(tmp_path / "test.sqlite3")))
    monkeypatch.setattr(cli, "TradingRunner", CircuitBreakerRunner)
    monkeypatch.setattr(cli, "run_preflight", lambda config: {"status": "pass", "checks": []})
    monkeypatch.setattr("sys.argv", ["kxian-bot", "trade-loop", "--max-iterations", "5", "--sleep-seconds", "0"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected trade-loop to exit when the circuit breaker trips")

    output = json.loads(capsys.readouterr().out)
    assert output["last_result"]["reason"] == "loop_circuit_breaker_tripped"


def test_cli_parses_timestamp_seconds_and_integer_lists():
    assert cli.parse_timestamp_ms("1704067200") == 1704067200000
    assert cli.parse_timestamp_ms("1704067200000") == 1704067200000
    assert cli.parse_int_list("2, 5,10") == [2, 5, 10]


def test_cli_expands_input_file_directories_and_globs(tmp_path):
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    first = sample_dir / "b.csv"
    second = sample_dir / "a.csv"
    ignored = sample_dir / "note.txt"
    first.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
    second.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
    ignored.write_text("ignore", encoding="utf-8")

    assert cli.parse_input_files(str(sample_dir)) == [str(second), str(first)]
    assert cli.parse_input_files(str(sample_dir / "*.csv")) == [str(second), str(first)]
    assert cli.parse_input_files(f"{first}, explicit.csv") == [str(first), "explicit.csv"]


def _record_testnet_observation(storage, execute_loop: bool, cycles: int = 6):
    observation_id = "order" if execute_loop else "check"
    for cycle in range(1, cycles + 1):
        storage.record_loop_event(
            LoopEvent(
                loop_id=f"observe-{observation_id}",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": observation_id,
                    "cycle": cycle,
                    "status": "pass",
                    "reason": "",
                    "execute_loop": execute_loop,
                    "order_lifecycle": {
                        "state": "healthy_idle" if execute_loop else "not_attempted",
                        "acceptable": True,
                        "open_order_count": 0,
                    },
                },
            )
        )
