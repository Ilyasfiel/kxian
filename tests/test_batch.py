from kxian_bot.batch import run_batch_backtest
from kxian_bot.config import RuntimeConfig
from kxian_bot.models import Candle
from kxian_bot.storage import SQLiteStorage


def build_candle(idx: int, close: float) -> Candle:
    return Candle(
        open_time=idx,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        close_time=idx + 1,
    )


def test_batch_backtest_runs_grid_skips_invalid_pairs_and_persists(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    candles = [
        build_candle(i, price)
        for i, price in enumerate([10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9, 10, 11])
    ]
    storage.upsert_candles(candles, exchange="binance", symbol="BTCUSDT", interval="1m")

    result = run_batch_backtest(
        config=RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3")),
        storage=storage,
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=0,
        end_time=20,
        short_windows=[2, 3, 5],
        long_windows=[3, 5],
        sort_by="return_pct",
        top=10,
    )

    assert result.total_combinations == 6
    assert result.valid_combinations == 3
    assert result.skipped_combinations == 3
    assert result.candle_count == len(candles)
    assert len(result.results) == 3
    assert storage.fetch_all("backtest_runs")
    assert {row["run_id"] for row in storage.fetch_all("backtest_runs")} == {
        summary.run_id for summary in result.results
    }


def test_batch_backtest_applies_top_and_drawdown_sort(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    candles = [build_candle(i, price) for i, price in enumerate([100, 90, 80, 100, 110, 90, 120, 80, 130])]
    storage.upsert_candles(candles, exchange="binance", symbol="BTCUSDT", interval="1m")

    result = run_batch_backtest(
        config=RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3")),
        storage=storage,
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=0,
        end_time=20,
        short_windows=[2, 3],
        long_windows=[4, 5],
        sort_by="max_drawdown_pct",
        top=2,
    )

    assert len(result.results) == 2
    assert result.results[0].max_drawdown_pct <= result.results[1].max_drawdown_pct
