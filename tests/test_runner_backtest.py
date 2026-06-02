from kxian_bot.config import RuntimeConfig
from kxian_bot.models import BacktestResult, Candle
from kxian_bot.runner import TradingRunner
from kxian_bot.storage import SQLiteStorage
import zipfile


def _write_price_csv(path, prices, start_time=1704067200000):
    path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{start_time + index * 60000},{price},{price + 1},{price - 1},{price},1"
                for index, price in enumerate(prices)
            ]
        ),
        encoding="utf-8",
    )


def test_runner_backtest_persists_run_summary_for_strategy_gate(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
        )
    )

    result = runner.backtest(limit=100)

    saved_storage = SQLiteStorage(db_path)
    runs = saved_storage.fetch_all("backtest_runs")
    gate_run = saved_storage.latest_backtest_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)
    trades = saved_storage.load_backtest_trades(result["run_id"])
    assert result["run_id"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == result["run_id"]
    assert gate_run["run_id"] == result["run_id"]
    assert gate_run["metrics"]["trade_count"] == result["trade_count"]
    assert len(trades) == result["trade_count"]


def test_runner_backtest_parameters_include_protective_exits(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            stop_loss_pct=4,
            take_profit_pct=8,
            trailing_stop_pct=3,
            cooldown_seconds=120,
        )
    )

    result = runner.backtest(limit=100)

    saved_storage = SQLiteStorage(db_path)
    gate_run = saved_storage.latest_backtest_run(
        "binance",
        "BTCUSDT",
        "1m",
        short_window=3,
        long_window=5,
        parameters={
            "short_window": 3,
            "long_window": 5,
            "stop_loss_pct": 4.0,
            "take_profit_pct": 8.0,
            "trailing_stop_pct": 3.0,
            "cooldown_seconds": 120,
        },
    )
    assert gate_run["run_id"] == result["run_id"]
    assert gate_run["parameters"]["trailing_stop_pct"] == 3.0
    assert gate_run["parameters"]["cooldown_seconds"] == 120


def test_runner_stress_backtest_persists_summary_for_stress_gate(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=1,
            min_order_usdt=1,
        )
    )

    result = runner.stress_backtest(limit=100)

    saved_storage = SQLiteStorage(db_path)
    gate_run = saved_storage.latest_stress_backtest_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)
    assert result["run_id"]
    assert result["scenario_count"] == 5
    assert len(result["scenarios"]) == 5
    assert gate_run["run_id"] == result["run_id"]
    assert gate_run["metrics"]["scenario_count"] == 5
    assert gate_run["metrics"]["min_trade_count"] == result["min_trade_count"]


def test_runner_walk_forward_persists_summary_for_walk_forward_gate(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.walk_forward(limit=100, segments=3)

    saved_storage = SQLiteStorage(db_path)
    gate_run = saved_storage.latest_walk_forward_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)
    assert result["run_id"]
    assert result["segment_count"] == 3
    assert len(result["segments"]) == 3
    assert sum(segment["candle_count"] for segment in result["segments"]) == len(prices)
    assert gate_run["run_id"] == result["run_id"]
    assert gate_run["metrics"]["segment_count"] == 3
    assert gate_run["metrics"]["total_trade_count"] == result["total_trade_count"]


def test_runner_walk_forward_treats_flat_no_trade_segments_as_cash_preservation(tmp_path):
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            min_gate_profit_factor=1,
            min_gate_return_pct=0,
            min_walk_forward_trades=30,
        )
    )
    flat_segment = BacktestResult(
        initial_equity=1000,
        trade_count=0,
        final_equity=1000,
        return_pct=0,
        max_drawdown_pct=0,
        win_rate=0,
        profit_factor=0,
        fees_paid=0,
        slippage_paid=0,
        usdt_balance=1000,
        asset_balance=0,
        trades=[],
    )

    assert runner._walk_forward_segment_passed(flat_segment) is True
    gate = runner._walk_forward_gate_result_from_summary(
        {
            "run_id": "walk",
            "segment_count": 3,
            "pass_rate": 100,
            "total_trade_count": 0,
            "worst_return_pct": 0,
            "worst_drawdown_pct": 0,
            "worst_profit_factor": 0,
        }
    )

    assert gate["allowed"] is False
    assert gate["reason"] == "walk_forward_gate_insufficient_trades"


def test_runner_walk_forward_samples_reports_failed_segments(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9] * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, [12, 11, 10, 9, 8, 7, 8, 7, 6, 7, 6, 5] * 3, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.walk_forward_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
    )

    assert result["sample_count"] == 2
    assert result["resample_interval"] is None
    assert result["runtime_interval"] == "1m"
    assert result["passed_samples"] + result["failed_samples"] == 2
    assert len(result["samples"]) == 2
    assert all("walk_forward" in sample for sample in result["samples"])
    assert all("failed_segments" in sample for sample in result["samples"])
    assert "min_pass_rate" in result["summary"]


def test_runner_validate_strategy_runs_all_validation_gates(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.validate_strategy(limit=100, segments=3)

    saved_storage = SQLiteStorage(db_path)
    assert result["status"] == "pass"
    assert result["candle_count"] == len(prices)
    assert result["backtest"]["candle_count"] == len(prices)
    assert result["stress"]["candle_count"] == len(prices)
    assert result["walk_forward"]["candle_count"] == len(prices)
    assert result["backtest"]["run_id"]
    assert result["stress"]["run_id"]
    assert result["walk_forward"]["run_id"]
    assert result["gates"]["strategy_gate"]["allowed"] is True
    assert result["gates"]["stress_gate"]["allowed"] is True
    assert result["gates"]["walk_forward_gate"]["allowed"] is True
    assert len(saved_storage.fetch_all("backtest_runs")) == 1
    assert len(saved_storage.fetch_all("stress_backtest_runs")) == 1
    assert len(saved_storage.fetch_all("walk_forward_runs")) == 1


def test_runner_validate_strategy_rejects_insufficient_candles_without_persisting_runs(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
        )
    )

    result = runner.validate_strategy(limit=100, segments=3)

    saved_storage = SQLiteStorage(db_path)
    assert result["status"] == "fail"
    assert result["reason"] == "insufficient_validation_candles"
    assert result["candle_count"] == len(prices)
    assert result["required_candles"] == 18
    assert result["gates"]["data_gate"]["allowed"] is False
    assert len(saved_storage.fetch_all("backtest_runs")) == 0
    assert len(saved_storage.fetch_all("stress_backtest_runs")) == 0
    assert len(saved_storage.fetch_all("walk_forward_runs")) == 0


def test_runner_validate_samples_requires_every_sample_to_pass(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
    ]
    csv_header = ["timestamp,open,high,low,close,volume"]
    first_path.write_text(
        "\n".join(
            csv_header
            + [
                f"{1704067200000 + index * 60000},{price},{price + 1},{price - 1},{price},1"
                for index, price in enumerate(prices)
            ]
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        "\n".join(
            csv_header
            + [
                f"{1704077200000 + index * 60000},{price},{price + 1},{price - 1},{price},1"
                for index, price in enumerate(prices)
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.validate_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
    )

    assert result["status"] == "pass"
    assert result["reason"] == "all_samples_passed"
    assert result["sample_count"] == 2
    assert result["passed_samples"] == 2
    assert result["failed_samples"] == 0
    assert result["samples"][0]["input_file"] == str(first_path)
    assert result["samples"][0]["backtest"]["candle_count"] == len(prices)
    assert "trades" not in result["samples"][0]["backtest"]
    assert result["summary"]["total_trade_count"] >= 0
    assert len(SQLiteStorage(db_path).fetch_all("backtest_runs")) == 2


def test_runner_validate_samples_fails_when_one_sample_has_insufficient_candles(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    first_path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{1704067200000 + index * 60000},{10 + index},{11 + index},{9 + index},{10 + index},1"
                for index in range(18)
            ]
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{1704077200000 + index * 60000},{10 + index},{11 + index},{9 + index},{10 + index},1"
                for index in range(4)
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.validate_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
    )

    assert result["status"] == "fail"
    assert result["reason"] == "sample_validation_failed"
    assert result["passed_samples"] == 1
    assert result["failed_samples"] == 1
    assert result["samples"][1]["status"] == "fail"
    assert result["samples"][1]["reason"] == "insufficient_validation_candles"


def test_runner_select_strategy_ranks_validated_candidates(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=3,
        input_file=None,
        short_windows=[2, 3],
        long_windows=[5, 6],
        top=3,
    )

    assert result["status"] == "pass"
    assert result["selected"]["status"] == "pass"
    assert len(result["candidates"]) == 3
    assert result["total_combinations"] == 4
    assert result["selected"]["strategy"] == "moving_average_cross"
    assert result["selected"]["parameters"]["strategy"] == "moving_average_cross"
    assert result["selected"]["parameters"]["short_window"] in {2, 3}
    assert result["selected"]["parameters"]["long_window"] in {5, 6}


def test_runner_select_strategy_can_grid_protective_exits(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=2,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=2,
        input_file=None,
        short_windows=[2],
        long_windows=[5],
        top=10,
        stop_loss_pcts=[0, 2],
        take_profit_pcts=[0, 4],
        trailing_stop_pcts=[0, 3],
    )

    parameter_sets = {tuple(sorted(candidate["parameters"].items())) for candidate in result["candidates"]}
    assert result["total_combinations"] == 8
    assert result["stop_loss_pcts"] == [0, 2]
    assert result["take_profit_pcts"] == [0, 4]
    assert result["trailing_stop_pcts"] == [0, 3]
    assert len(parameter_sets) == 8
    assert any(candidate["parameters"].get("stop_loss_pct") == 2.0 for candidate in result["candidates"])
    assert any(candidate["parameters"].get("take_profit_pct") == 4.0 for candidate in result["candidates"])
    assert any(candidate["parameters"].get("trailing_stop_pct") == 3.0 for candidate in result["candidates"])


def test_runner_select_strategy_can_promote_selected_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
            stop_loss_pct=2,
            cooldown_seconds=120,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=3,
        input_file=None,
        short_windows=[2],
        long_windows=[5],
        top=3,
        promote=True,
    )
    restored = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite"))

    assert result["status"] == "pass"
    assert result["promoted"]["parameters"]["short_window"] == 2
    assert result["promoted"]["parameters"]["strategy"] == "moving_average_cross"
    assert result["promoted"]["parameters"]["long_window"] == 5
    assert result["promoted"]["parameters"]["cooldown_seconds"] == 120
    assert result["promoted"]["evidence"]["backtest"]["run_id"]
    assert restored.config.short_window == 2
    assert restored.config.long_window == 5
    assert restored.config.stop_loss_pct == 2.0
    assert restored.config.cooldown_seconds == 120
    assert restored.strategy.short_window == 2
    assert restored.strategy.long_window == 5


def test_runner_select_samples_requires_candidate_to_pass_every_sample(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[2, 3],
        long_windows=[5],
        top=3,
    )

    assert result["status"] == "pass"
    assert result["reason"] == "selected_strategy_found"
    assert result["sample_count"] == 2
    assert result["selected"]["status"] == "pass"
    assert result["selected"]["passed_samples"] == 2
    assert result["selected"]["failed_samples"] == 0
    assert len(result["selected"]["samples"]) == 2
    assert result["selected"]["samples"][0]["input_file"] == str(first_path)
    assert "trades" not in result["selected"]["samples"][0]["backtest"]
    assert result["selected"]["summary"]["total_trade_count"] >= 0
    assert result["validated_candidates"] >= 1


def test_runner_select_samples_reports_when_a_sample_blocks_candidates(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    _write_price_csv(first_path, [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9, 10, 11, 12, 11, 10, 9])
    _write_price_csv(second_path, [10, 11, 12, 13], start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[3],
        long_windows=[5],
        top=3,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "no_candidate_passed_validation"
    assert result["candidates"][0]["failed_samples"] == 1
    assert result["candidates"][0]["samples"][1]["reason"] == "insufficient_validation_candles"
    assert result["failure_matrix"]["sample_failures"][0]["input_file"] == second_path.name
    assert result["failure_matrix"]["sample_failures"][0]["top_reasons"] == [
        {"reason": "insufficient_validation_candles", "count": 1}
    ]
    assert result["failure_matrix"]["strategy_failures"][0]["strategy"] == "moving_average_cross"
    assert result["failure_matrix"]["gate_failures"] == [{"reason": "insufficient_validation_candles", "count": 1}]
    assert result["failure_matrix"]["worst_samples"][0]["input_file"] == second_path.name


def test_runner_select_samples_can_promote_multi_sample_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
            stop_loss_pct=2,
        )
    )

    result = runner.select_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[2],
        long_windows=[5],
        top=3,
        promote=True,
    )
    restored = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite"))

    assert result["status"] == "pass"
    assert result["promoted"]["parameters"]["short_window"] == 2
    assert result["promoted"]["evidence"]["sample_validation"]["sample_count"] == 2
    assert result["promoted"]["evidence"]["sample_validation"]["failed_samples"] == 0
    assert result["promoted"]["evidence"]["backtest"]["run_id"]
    assert restored.config.short_window == 2
    assert restored.config.long_window == 5


def test_runner_select_samples_promotes_resampled_runtime_interval(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[1],
        long_windows=[2],
        top=3,
        promote=True,
        resample_interval="5m",
    )
    storage = SQLiteStorage(db_path)
    one_minute_profile = storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m")
    five_minute_profile = storage.active_strategy_profile("paper", "binance", "BTCUSDT", "5m")

    assert result["status"] == "pass"
    assert result["runtime_interval"] == "5m"
    assert result["promoted"]["profile_key"] == "paper:binance:BTCUSDT:5m"
    assert one_minute_profile is None
    assert five_minute_profile["evidence"]["runtime_interval"] == "5m"
    assert five_minute_profile["evidence"]["sample_validation"]["resample_interval"] == "5m"


def test_runner_select_sample_intervals_picks_passing_interval(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_sample_intervals(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[1],
        long_windows=[2],
        top=3,
        resample_intervals=["raw", "5m"],
    )

    assert result["status"] == "pass"
    assert result["reason"] == "selected_interval_found"
    assert result["resample_intervals"] == [None, "5m"]
    assert result["selected_interval"]["status"] == "pass"
    assert result["selected_interval"]["runtime_interval"] in {"1m", "5m"}
    assert result["passing_interval_count"] >= 1


def test_runner_select_sample_intervals_promotes_best_runtime_interval(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_sample_intervals(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[1],
        long_windows=[2],
        top=3,
        resample_intervals=["5m"],
        promote=True,
    )
    restored = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            interval="5m",
        )
    )

    assert result["status"] == "pass"
    assert result["runtime_interval"] == "5m"
    assert result["promoted"]["profile_key"] == "paper:binance:BTCUSDT:5m"
    assert restored.config.interval == "5m"
    assert restored.config.short_window == 1
    assert restored.config.long_window == 2


def test_runner_screen_samples_prefilters_without_promotion(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 4
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=3,
        input_files=[str(first_path), str(second_path)],
        short_windows=[1, 2],
        long_windows=[3],
        top=4,
        resample_intervals=["raw", "5m"],
        stop_loss_pcts=[0, 2],
    )
    storage = SQLiteStorage(db_path)

    assert result["status"] == "pass"
    assert result["reason"] == "prefilter_candidate_found"
    assert result["screen_only"] is True
    assert result["validated_candidates"] == 0
    assert "promoted" not in result
    assert result["resample_intervals"] == [None, "5m"]
    assert result["sample_count"] == 2
    assert result["total_combinations"] == 8
    assert result["max_combinations"] is None
    assert result["skip_combinations"] == 0
    assert result["skipped_by_offset"] == 0
    assert result["seen_combinations"] == 8
    assert result["evaluated_combinations"] == 8
    assert result["budget_exhausted"] is False
    assert result["prefilter_pass_count"] >= 1
    assert result["selected"]["status"] == "prefilter_pass"
    assert result["selected"]["passed_samples"] == 2
    assert result["selected"]["failed_samples"] == 0
    assert result["selected"]["runtime_interval"] in {"1m", "5m"}
    assert "stress" not in result["selected"]["samples"][0]
    assert "walk_forward" not in result["selected"]["samples"][0]
    assert len(result["intervals"]) == 2
    assert len(result["candidates"]) == 4
    assert storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m") is None
    assert storage.active_strategy_profile("paper", "binance", "BTCUSDT", "5m") is None


def test_runner_screen_samples_can_stop_at_combination_budget(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9] * 4
    _write_price_csv(first_path, prices)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(first_path)],
        short_windows=[1, 2, 3],
        long_windows=[4, 5],
        top=10,
        resample_intervals=["raw", "5m"],
        stop_loss_pcts=[0, 2],
        max_combinations=3,
    )

    assert result["total_combinations"] == 24
    assert result["max_combinations"] == 3
    assert result["skip_combinations"] == 0
    assert result["skipped_by_offset"] == 0
    assert result["seen_combinations"] == 3
    assert result["evaluated_combinations"] == 3
    assert result["budget_exhausted"] is True
    assert len(result["candidates"]) <= 3


def test_runner_screen_samples_can_skip_to_combination_offset(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    first_path = tmp_path / "first.csv"
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9] * 4
    _write_price_csv(first_path, prices)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(first_path)],
        short_windows=[1, 2, 3],
        long_windows=[4, 5],
        top=10,
        resample_intervals=["raw", "5m"],
        stop_loss_pcts=[0, 2],
        max_combinations=4,
        skip_combinations=5,
    )

    assert result["total_combinations"] == 24
    assert result["skip_combinations"] == 5
    assert result["skipped_by_offset"] == 5
    assert result["seen_combinations"] == 9
    assert result["evaluated_combinations"] == 4
    assert result["budget_exhausted"] is True


def test_runner_screen_samples_reports_no_input_files(tmp_path):
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=3,
        input_files=[],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw", "5m"],
    )

    assert result["status"] == "fail"
    assert result["reason"] == "no_input_files"
    assert result["resample_intervals"] == [None, "5m"]
    assert result["selected"] is None


def test_runner_screen_samples_reports_input_file_load_failure(tmp_path):
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=3,
        input_files=[str(tmp_path / "missing.csv")],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
    )

    assert result["status"] == "fail"
    assert result["reason"] == "input_file_load_failed"
    assert result["evaluated_combinations"] == 0
    assert result["selected"] is None
    assert result["candidates"] == []
    assert "missing.csv" in result["error"]


def test_runner_screen_samples_stops_candidate_after_first_failed_sample(tmp_path, monkeypatch):
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9] * 4
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
            min_gate_trades=999,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )
    calls = 0
    original = runner._screen_backtest_from_candles

    def counted_screen(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "_screen_backtest_from_candles", counted_screen)

    result = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(first_path), str(second_path)],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
    )

    assert calls == 1
    assert result["evaluated_combinations"] == 1
    assert result["candidates"][0]["failed_samples"] == 1
    assert result["candidates"][0]["evaluated_sample_count"] == 1
    assert result["candidates"][0]["total_sample_count"] == 2
    assert len(result["candidates"][0]["samples"]) == 1
    failed = result["candidates"][0]["failed_sample_examples"][0]
    assert failed["input_file"] == str(second_path)
    assert failed["backtest"]["trade_count"] < 999
    assert "strategy_gate_insufficient_trades" in failed["failed_gates"]
    assert result["decision"] == "blocked"
    assert {"reason": "strategy_gate_insufficient_trades", "count": 1} in result["top_failure_reasons"]
    assert {"reason": "strategy_gate_insufficient_trades", "count": 1} in result["failed_gate_counts"]
    assert result["best_failed_candidate"]["strategy"] == "moving_average_cross"
    assert result["best_failed_candidate"]["failed_sample_examples"][0]["input_file"] == str(second_path)
    assert result["diagnostics"][0]["code"] == "strategy_gate_insufficient_trades"
    assert result["failure_matrix"]["sample_failures"][0]["input_file"] == second_path.name
    assert result["failure_matrix"]["strategy_failures"][0]["strategy"] == "moving_average_cross"
    assert result["failure_matrix"]["gate_failures"] == [{"reason": "strategy_gate_insufficient_trades", "count": 1}]
    assert result["failure_matrix"]["worst_samples"][0]["input_file"] == second_path.name
    assert any("do not promote" in action for action in result["recommended_actions"])
    assert any("screen-samples only as a research prefilter" in action for action in result["recommended_actions"])


def test_runner_screen_samples_early_failure_includes_empty_failure_matrix(tmp_path):
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
        )
    )

    result = runner.screen_samples(
        limit=100,
        segments=3,
        input_files=[],
        short_windows=[3],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
    )

    assert result["status"] == "fail"
    assert result["reason"] == "no_input_files"
    assert result["failure_matrix"] == {
        "sample_failures": [],
        "strategy_failures": [],
        "gate_failures": [],
        "worst_samples": [],
    }


def test_runner_screen_samples_can_relax_trade_count_prefilter_only(tmp_path, monkeypatch):
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    prices = [10, 11, 12, 13, 14, 15] * 12
    _write_price_csv(first_path, prices)
    _write_price_csv(second_path, prices, start_time=1704077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
            min_gate_trades=999,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )

    def low_trade_backtest(*args, **kwargs):
        return {
            "run_id": "",
            "candle_count": 72,
            "return_pct": 1.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 2.0,
            "trade_count": 2,
        }

    monkeypatch.setattr(runner, "_screen_backtest_from_candles", low_trade_backtest)

    strict = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(first_path), str(second_path)],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
    )
    relaxed = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(first_path), str(second_path)],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
        screen_min_trades=2,
    )

    assert strict["status"] == "fail"
    assert strict["candidates"][0]["samples"][0]["gates"]["strategy_gate"]["checks"]["min_trade_count"] == 999
    assert relaxed["status"] == "pass"
    assert relaxed["screen_min_trades"] == 2
    assert relaxed["selected"]["screen_min_trades"] == 2
    assert relaxed["selected"]["samples"][0]["gates"]["strategy_gate"]["checks"]["min_trade_count"] == 2
    assert runner._strategy_gate_result_from_backtest(low_trade_backtest())["allowed"] is False


def test_runner_screen_samples_checks_latest_sample_first(tmp_path, monkeypatch):
    older_path = tmp_path / "older.csv"
    newer_path = tmp_path / "newer.csv"
    prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9] * 4
    _write_price_csv(older_path, prices, start_time=1704077200000)
    _write_price_csv(newer_path, prices, start_time=1705077200000)
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
            min_gate_trades=999,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_order_usdt=1,
        )
    )
    seen_first_open_times: list[int] = []
    original = runner._screen_backtest_from_candles

    def counted_screen(candles, *args, **kwargs):
        seen_first_open_times.append(candles[0].open_time)
        return original(candles, *args, **kwargs)

    monkeypatch.setattr(runner, "_screen_backtest_from_candles", counted_screen)

    result = runner.screen_samples(
        limit=100,
        segments=2,
        input_files=[str(older_path), str(newer_path)],
        short_windows=[2],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
    )

    assert result["evaluated_combinations"] == 1
    assert seen_first_open_times == [1705077200000]
    assert result["candidates"][0]["samples"][0]["input_file"] == str(newer_path)


def test_runner_select_strategy_can_compare_multiple_strategy_types(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 10, 10, 10, 10, 11, 12, 13, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=2,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=2,
        input_file=None,
        short_windows=[2],
        long_windows=[5],
        top=5,
        strategies=["moving_average_cross", "donchian_breakout"],
    )

    strategies = {candidate["strategy"] for candidate in result["candidates"]}
    assert result["total_combinations"] == 2
    assert strategies == {"moving_average_cross", "donchian_breakout"}
    assert all(candidate["parameters"]["strategy"] == candidate["strategy"] for candidate in result["candidates"])


def test_runner_select_strategy_can_compare_trend_pullback(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 11, 12, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20, 19, 21, 22, 21]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=2,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=2,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["trend_pullback"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "trend_pullback"
    assert result["candidates"][0]["parameters"]["strategy"] == "trend_pullback"


def test_runner_select_strategy_can_compare_mean_reversion(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [100, 100, 100, 100, 100, 96, 99, 101, 100, 99, 96, 99, 101, 100]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["mean_reversion"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "mean_reversion"
    assert result["candidates"][0]["parameters"]["strategy"] == "mean_reversion"


def test_runner_select_strategy_can_compare_rsi_mean_reversion(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [100, 101, 102, 100, 98, 96, 99, 101, 102, 100, 98, 96, 99, 101]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["rsi_mean_reversion"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "rsi_mean_reversion"
    assert result["candidates"][0]["parameters"]["strategy"] == "rsi_mean_reversion"


def test_runner_select_strategy_can_compare_momentum_breakout(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 11, 12, 13, 14, 15, 16, 15, 17, 18, 19, 18, 20, 21]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["momentum_breakout"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "momentum_breakout"
    assert result["candidates"][0]["parameters"]["strategy"] == "momentum_breakout"


def test_runner_select_strategy_can_compare_bollinger_mean_reversion(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [100, 100, 100, 100, 100, 94, 98, 100, 99, 96, 98, 101, 100, 97, 99]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["bollinger_mean_reversion"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "bollinger_mean_reversion"
    assert result["candidates"][0]["parameters"]["strategy"] == "bollinger_mean_reversion"


def test_runner_select_strategy_can_compare_regime_breakout(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 17, 19, 20, 21, 20, 22, 23]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["regime_breakout"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "regime_breakout"
    assert result["candidates"][0]["parameters"]["strategy"] == "regime_breakout"


def test_runner_select_strategy_can_compare_trend_filtered_ma_cross(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 10, 11, 12, 13, 14, 13, 15, 16, 15, 17, 18, 19, 18, 20, 21]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["trend_filtered_ma_cross"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "trend_filtered_ma_cross"
    assert result["candidates"][0]["parameters"]["strategy"] == "trend_filtered_ma_cross"


def test_runner_select_strategy_can_compare_regime_filtered_ma_cross(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        100.0,
        100.6,
        101.2,
        101.8,
        102.4,
        103.0,
        103.6,
        104.2,
        104.8,
        105.4,
        106.0,
        106.6,
        107.2,
        107.8,
        108.4,
        109.0,
        109.6,
        110.2,
        109.7,
        108.7,
        107.7,
        113.7,
        114.2,
        113.6,
        115.1,
        115.8,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["regime_filtered_ma_cross"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "regime_filtered_ma_cross"
    assert result["candidates"][0]["parameters"]["strategy"] == "regime_filtered_ma_cross"


def test_runner_select_strategy_can_compare_defensive_trend(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 11, 12, 13, 14, 15, 14.5, 16, 17, 16, 18, 19, 20, 19, 21, 22]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["defensive_trend"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "defensive_trend"
    assert result["candidates"][0]["parameters"]["strategy"] == "defensive_trend"


def test_runner_select_strategy_can_compare_panic_rebound(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [100, 100, 100, 100, 98, 92, 96, 99, 97, 92, 96, 99, 98, 93, 97, 100]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["panic_rebound"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "panic_rebound"
    assert result["candidates"][0]["parameters"]["strategy"] == "panic_rebound"


def test_runner_select_strategy_can_compare_regime_adaptive_long(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 11, 12, 13, 14, 15, 14.5, 16, 17, 16, 18, 19, 20, 19, 21, 22]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["regime_adaptive_long"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "regime_adaptive_long"
    assert result["candidates"][0]["parameters"]["strategy"] == "regime_adaptive_long"


def test_runner_select_strategy_can_compare_volatility_breakout_trend(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 106, 108, 110, 109, 111, 112, 113, 112, 114, 116]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=None,
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["volatility_breakout_trend"],
    )

    assert result["total_combinations"] == 1
    assert result["candidates"][0]["strategy"] == "volatility_breakout_trend"
    assert result["candidates"][0]["parameters"]["strategy"] == "volatility_breakout_trend"


def test_runner_select_strategy_can_compare_research_only_synthetic_short(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 99, 98, 97, 96, 95, 94, 90, 88, 86, 84, 82, 81, 79, 78, 76, 75, 74, 73, 72, 71, 70],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["downtrend_breakdown_short"],
    )

    assert result["candidates"][0]["strategy"] == "downtrend_breakdown_short"
    assert result["candidates"][0]["parameters"]["position_mode"] == "synthetic_short"
    assert result["candidates"][0]["parameters"]["research_only"] is True
    assert result["candidates"][0]["backtest"]["return_pct"] > 0


def test_runner_synthetic_short_stress_uses_short_backtest_engine(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    candle_path = tmp_path / "candles.csv"
    _write_price_csv(
        candle_path,
        [100, 99, 98, 97, 96, 95, 94, 90, 88, 86, 84, 82, 81, 79, 78, 76, 75, 74, 73, 72, 71, 70],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            strategy="downtrend_breakdown_short",
            short_window=3,
            long_window=6,
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
        )
    )

    backtest = runner.backtest(limit=100, input_file=str(candle_path))
    stress = runner.stress_backtest(limit=100, input_file=str(candle_path))

    assert backtest["return_pct"] > 0
    assert stress["worst_return_pct"] > 0
    assert all(scenario["return_pct"] > 0 for scenario in stress["scenarios"])
    assert stress["min_trade_count"] == backtest["trade_count"]


def test_runner_does_not_promote_research_only_synthetic_short(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 99, 98, 97, 96, 95, 94, 90, 88, 86, 84, 82, 81, 79, 78, 76, 75, 74, 73, 72, 71, 70],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        promote=True,
        strategies=["downtrend_breakdown_short"],
    )

    assert result["promoted"]["status"] == "blocked"
    assert result["promoted"]["reason"] == "research_only_strategy_not_promotable"
    assert runner.storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m") is None


def test_runner_select_strategy_can_compare_research_only_adaptive_range(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 101, 100, 101, 100, 98, 96, 99, 100, 103, 106, 104, 101, 98, 96, 99, 100, 103],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["adaptive_range_reclaim"],
    )

    assert result["candidates"][0]["strategy"] == "adaptive_range_reclaim"
    assert result["candidates"][0]["parameters"]["research_only"] is True


def test_runner_does_not_promote_research_only_adaptive_range(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 101, 100, 101, 100, 98, 96, 99, 100, 103, 106, 104, 101, 98, 96, 99, 100, 103],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        promote=True,
        strategies=["adaptive_range_reclaim"],
    )

    assert result["promoted"]["status"] == "blocked"
    assert result["promoted"]["reason"] == "research_only_strategy_not_promotable"
    assert runner.storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m") is None


def test_runner_select_strategy_can_compare_research_only_volatility_regime_pullback_reclaim(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 104, 108, 112, 108, 112, 115, 113, 114, 115, 116, 114, 112, 113, 115, 116],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        strategies=["volatility_regime_pullback_reclaim"],
    )

    assert result["candidates"][0]["strategy"] == "volatility_regime_pullback_reclaim"
    assert result["candidates"][0]["parameters"]["research_only"] is True
    assert result["candidates"][0]["backtest"]["trade_count"] > 0


def test_runner_does_not_promote_research_only_volatility_regime_pullback_reclaim(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_price_csv(
        tmp_path / "candles.csv",
        [100, 104, 108, 112, 108, 112, 115, 113, 114, 115, 116, 114, 112, 113, 115, 116],
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_trades=0,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            require_sample_validation_gate=False,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=1,
        input_file=str(tmp_path / "candles.csv"),
        short_windows=[3],
        long_windows=[6],
        top=3,
        promote=True,
        strategies=["volatility_regime_pullback_reclaim"],
    )

    assert result["promoted"]["status"] == "blocked"
    assert result["promoted"]["reason"] == "research_only_strategy_not_promotable"
    assert result["candidates"][0]["backtest"]["trade_count"] > 0
    assert runner.storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m") is None


def test_runner_candidate_selection_ignores_existing_active_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
    ]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 7, "long_window": 12},
        evidence={"backtest": {"run_id": "old"}},
        updated_by="test",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=3,
        input_file=None,
        short_windows=[2],
        long_windows=[5],
        top=3,
    )

    assert runner.config.short_window == 7
    assert result["selected"]["parameters"]["short_window"] == 2
    assert result["selected"]["parameters"]["long_window"] == 5


def test_runner_select_strategy_reports_when_no_candidate_has_enough_candles(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_order_usdt=1,
        )
    )

    result = runner.select_strategy(
        limit=100,
        segments=3,
        input_file=None,
        short_windows=[2],
        long_windows=[5],
        top=3,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "no_candidate_passed_validation"
    assert result["candidates"][0]["reason"] == "insufficient_validation_candles"


def test_runner_imports_candles_from_file_for_sqlite_replay(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
        )
    )

    result = runner.import_candles("sample_data/binance_btcusdt_1m.json", "BTCUSDT", "1m")

    candles = runner.storage.load_candles("binance", "BTCUSDT", "1m")
    assert result["status"] == "ok"
    assert result["imported_candles"] == len(candles)
    assert result["changed_rows"] == len(candles)
    assert candles[0].open_time == result["first_open_time"]


def test_runner_imports_candles_from_csv_file(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    csv_path = tmp_path / "ohlcv.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp,open,high,low,close,volume",
                "1704067200000,10,11,9,10.5,100",
                "1704067260000,10.5,12,10,11.5,120",
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
        )
    )

    result = runner.import_candles(str(csv_path), "BTCUSDT", "1m")

    candles = runner.storage.load_candles("binance", "BTCUSDT", "1m")
    assert result["status"] == "ok"
    assert result["imported_candles"] == 2
    assert candles[0].open_time == 1704067200000
    assert candles[1].close == 11.5


def test_runner_imports_candle_archive_directory(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    first = archive_dir / "BTCUSDT-1m-2024-01.zip"
    second = archive_dir / "BTCUSDT-1m-2024-02.zip"
    with zipfile.ZipFile(first, "w") as archive:
        archive.writestr(
            "BTCUSDT-1m-2024-01.csv",
            "1704067200000,10,11,9,10.5,100,1704067259999,0,0,0,0,0\n",
        )
    with zipfile.ZipFile(second, "w") as archive:
        archive.writestr(
            "BTCUSDT-1m-2024-02.csv",
            "1706745600000,11,12,10,11.5,120,1706745659999,0,0,0,0,0\n",
        )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
        )
    )

    result = runner.import_candle_archives(str(archive_dir), "BTCUSDT", "1m")

    candles = runner.storage.load_candles("binance", "BTCUSDT", "1m")
    assert result["status"] == "ok"
    assert result["file_count"] == 2
    assert result["imported_file_count"] == 2
    assert result["failed_file_count"] == 0
    assert result["imported_candles"] == 2
    assert result["changed_rows"] == 2
    assert result["first_open_time"] == 1704067200000
    assert result["last_open_time"] == 1706745600000
    assert [candle.close for candle in candles] == [10.5, 11.5]


def test_runner_import_candle_archives_reports_empty_directory(tmp_path):
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            market_data_source="sqlite",
        )
    )

    result = runner.import_candle_archives(str(tmp_path), "BTCUSDT", "1m")

    assert result["status"] == "fail"
    assert result["reason"] == "no_archive_files"
    assert result["file_count"] == 0


def test_runner_prepare_samples_exports_local_candles_by_window(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    candles = [
        Candle(
            open_time=start_time + index * 60000,
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1,
            close_time=start_time + index * 60000 + 59999,
        )
        for index in range(6)
    ]
    storage.upsert_candles(candles, exchange="binance", symbol="BTCUSDT", interval="1m")
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite"))

    result = runner.prepare_samples(
        symbol="BTCUSDT",
        interval="1m",
        start_time=start_time,
        end_time=start_time + 6 * 60000,
        sample_days=1,
        output_dir=str(tmp_path / "samples"),
        source="sqlite",
        min_candles=1,
    )

    assert result["status"] == "ok"
    assert result["source_used"] == "sqlite"
    assert result["sample_count"] == 1
    assert result["local_candle_count"] == 6
    assert result["input_files_arg"] == result["input_files"][0]
    assert "select-sample-intervals" in result["next_command"]
    exported = runner.market_data.load_klines_from_file(result["input_files"][0])
    assert len(exported) == 6
    assert exported[0].open_time == candles[0].open_time
    assert exported[-1].close == candles[-1].close


def test_runner_prepare_samples_reports_skipped_sparse_windows(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    storage.upsert_candles(
        [
            Candle(
                open_time=start_time,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
                close_time=start_time + 59999,
            )
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite"))

    result = runner.prepare_samples(
        symbol="BTCUSDT",
        interval="1m",
        start_time=start_time,
        end_time=start_time + 2 * 86_400_000,
        sample_days=1,
        output_dir=str(tmp_path / "samples"),
        source="sqlite",
        min_candles=2,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "no_samples_prepared"
    assert result["sample_count"] == 0
    assert result["skipped_window_count"] == 2
    assert result["skipped_windows"][0]["reason"] == "insufficient_candles"


def test_runner_research_strategy_runs_prepare_and_selection_without_promotion(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    prices = [
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
        10,
        9,
        8,
        9,
        10,
        11,
        12,
        11,
    ]
    prices = prices * 3
    candles = [
        Candle(
            open_time=start_time + index * 60000,
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1,
            close_time=start_time + index * 60000 + 59999,
        )
        for index, price in enumerate(prices)
    ]
    storage.upsert_candles(candles, exchange="binance", symbol="BTCUSDT", interval="1m")
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            min_gate_trades=0,
            min_gate_return_pct=-100,
            max_gate_drawdown_pct=100,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=3,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
            min_order_usdt=1,
        )
    )

    result = runner.research_strategy(
        symbol="BTCUSDT",
        interval="1m",
        start_time=start_time,
        end_time=start_time + len(candles) * 60000,
        sample_days=1,
        output_dir=str(tmp_path / "samples"),
        source="sqlite",
        limit_per_request=None,
        sleep_seconds=0,
        min_candles=1,
        limit=100,
        segments=3,
        short_windows=[1],
        long_windows=[2],
        top=3,
        resample_intervals=["raw"],
        promote=False,
    )

    assert result["status"] == "pass"
    assert result["ready_for_promotion"] is True
    assert result["promoted"] is None
    assert result["prepare"]["sample_count"] == 1
    assert result["selection"]["status"] == "pass"
    assert result["summary"]["status"] == "pass"
    assert result["summary"]["sample_count"] == 1
    assert result["summary"]["selected_runtime_interval"] == "1m"
    assert result["summary"]["best_candidate"]["status"] == "pass"
    assert result["summary"]["best_candidate"]["strategy"] == "moving_average_cross"
    assert result["summary"]["top_failure_reasons"] == []
    assert result["summary"]["decision"] == "promotable"
    assert result["summary"]["diagnostics"][0]["code"] == "candidate_passed_all_gates"
    assert "rerun research-strategy with --promote if this candidate is acceptable" in result["summary"]["recommended_actions"]
    assert SQLiteStorage(db_path).active_strategy_profile("paper", "binance", "BTCUSDT", "1m") is None


def test_runner_research_strategy_reports_preparation_failure(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite"))

    result = runner.research_strategy(
        symbol="BTCUSDT",
        interval="1m",
        start_time=1704067200000,
        end_time=1704067200000,
        sample_days=1,
        output_dir=str(tmp_path / "samples"),
        source="sqlite",
        limit_per_request=None,
        sleep_seconds=0,
        min_candles=1,
        limit=100,
        segments=3,
        short_windows=[1],
        long_windows=[2],
        top=3,
        resample_intervals=["raw"],
        promote=True,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "sample_preparation_failed"
    assert result["ready_for_promotion"] is False
    assert result["selection"] is None
    assert result["promoted"] is None
    assert result["summary"]["status"] == "fail"
    assert result["summary"]["reason"] == "sample_preparation_failed"
    assert result["summary"]["prepare_reason"] == "invalid_time_range"
    assert result["summary"]["best_candidate"] is None
    assert result["summary"]["top_failure_reasons"] == [{"reason": "invalid_time_range", "count": 1}]
    assert result["summary"]["decision"] == "blocked"
    assert result["summary"]["diagnostics"][0]["code"] == "invalid_time_range"
    assert "prepare a longer date range or reduce sample-days only after enough candles are available per window" in result["summary"]["recommended_actions"]


def test_runner_research_strategy_summarizes_selection_failure(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    candles = [
        Candle(
            open_time=start_time + index * 60000,
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1,
            close_time=start_time + index * 60000 + 59999,
        )
        for index in range(6)
    ]
    storage.upsert_candles(candles, exchange="binance", symbol="BTCUSDT", interval="1m")
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), market_data_source="sqlite", min_order_usdt=1))

    result = runner.research_strategy(
        symbol="BTCUSDT",
        interval="1m",
        start_time=start_time,
        end_time=start_time + len(candles) * 60000,
        sample_days=1,
        output_dir=str(tmp_path / "samples"),
        source="sqlite",
        limit_per_request=None,
        sleep_seconds=0,
        min_candles=1,
        limit=100,
        segments=3,
        short_windows=[3],
        long_windows=[5],
        top=3,
        resample_intervals=["raw"],
        promote=False,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "strategy_research_failed"
    assert result["summary"]["reason"] == "no_interval_passed_validation"
    assert result["summary"]["passing_interval_count"] == 0
    assert result["summary"]["best_candidate"]["reason"] == "sample_prefilter_failed"
    assert result["summary"]["best_candidate"]["failed_sample_examples"][0]["reason"] == "insufficient_validation_candles"
    assert {"reason": "insufficient_validation_candles", "count": 2} in result["summary"]["top_failure_reasons"]
    assert result["summary"]["decision"] == "blocked"
    assert any(item["code"] == "insufficient_validation_candles" for item in result["summary"]["diagnostics"])
    assert "do not promote this result" in result["summary"]["recommended_actions"]


def test_runner_validation_input_file_honors_limit(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    csv_path = tmp_path / "ohlcv.csv"
    csv_path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{1704067200000 + index * 60000},{10 + index},{11 + index},{9 + index},{10 + index},1"
                for index in range(12)
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=2,
            long_window=3,
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=2,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
        )
    )

    result = runner.validate_strategy(limit=5, segments=1, input_file=str(csv_path))

    assert result["candle_count"] == 5
    assert result["backtest"]["candle_count"] == 5


def test_runner_validation_input_file_can_resample_candles(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    csv_path = tmp_path / "ohlcv.csv"
    csv_path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{1704067200000 + index * 60000},{10 + index},{11 + index},{9 + index},{10 + index},1"
                for index in range(10)
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=2,
            long_window=3,
            min_order_usdt=1,
            min_gate_trades=0,
            min_gate_profit_factor=0,
            min_stress_pass_rate=0,
            max_stress_drawdown_pct=100,
            min_walk_forward_segments=1,
            min_walk_forward_pass_rate=0,
            min_walk_forward_trades=0,
        )
    )

    result = runner.validate_strategy(limit=100, segments=1, input_file=str(csv_path), resample_interval="5m")

    assert result["candle_count"] == 2
    assert result["status"] == "fail"
    assert result["reason"] == "insufficient_validation_candles"


def test_runner_market_diagnostics_can_resample_input_file(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    csv_path = tmp_path / "ohlcv.csv"
    csv_path.write_text(
        "\n".join(
            ["timestamp,open,high,low,close,volume"]
            + [
                f"{1704067200000 + index * 60000},{10 + index},{11 + index},{9 + index},{10 + index},1"
                for index in range(10)
            ]
        ),
        encoding="utf-8",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            fee_rate=0.001,
            slippage_rate=0.0005,
        )
    )

    result = runner.market_diagnostics(limit=100, segments=2, input_file=str(csv_path), resample_interval="5m")

    assert result["resample_interval"] == "5m"
    assert result["candle_count"] == 2
    assert result["requested_segments"] == 2
    assert result["segment_count"] == 2
    assert len(result["segments"]) == 2
    assert result["buy_hold_return_pct"] == 35.7143
    assert result["round_trip_friction_pct"] == 0.3
