from __future__ import annotations

import uuid
from itertools import product

from kxian_bot.backtest import BacktestEngine
from kxian_bot.brokers.paper import PaperBroker
from kxian_bot.config import RuntimeConfig
from kxian_bot.models import BacktestRunSummary, BatchBacktestResult, Candle, Exchange
from kxian_bot.risk import RiskManager
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_parameters import strategy_parameters
from kxian_bot.strategies.factory import create_strategy


SORT_FIELDS = {"return_pct", "profit_factor", "max_drawdown_pct"}


def run_batch_backtest(
    config: RuntimeConfig,
    storage: SQLiteStorage,
    exchange: Exchange,
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    short_windows: list[int],
    long_windows: list[int],
    sort_by: str = "return_pct",
    top: int = 20,
) -> BatchBacktestResult:
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"sort_by must be one of: {', '.join(sorted(SORT_FIELDS))}")
    if top <= 0:
        raise ValueError("top must be greater than zero")

    candles = storage.load_candles(exchange, symbol, interval, start_time=start_time, end_time=end_time)
    total_combinations = len(short_windows) * len(long_windows)
    summaries: list[BacktestRunSummary] = []

    for short_window, long_window in product(short_windows, long_windows):
        if short_window >= long_window:
            continue
        summary = _run_single_backtest(
            config=config,
            storage=storage,
            candles=candles,
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            short_window=short_window,
            long_window=long_window,
        )
        summaries.append(summary)

    results = _sort_summaries(summaries, sort_by)[:top]
    return BatchBacktestResult(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
        candle_count=len(candles),
        total_combinations=total_combinations,
        valid_combinations=len(summaries),
        skipped_combinations=total_combinations - len(summaries),
        sort_by=sort_by,
        results=results,
    )


def _run_single_backtest(
    config: RuntimeConfig,
    storage: SQLiteStorage,
    candles: list[Candle],
    exchange: Exchange,
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    short_window: int,
    long_window: int,
) -> BacktestRunSummary:
    strategy = create_strategy(config.strategy, short_window=short_window, long_window=long_window, symbol=symbol)
    engine = BacktestEngine(
        strategy,
        _create_risk_manager(config),
        PaperBroker(config.starting_usdt),
        fee_rate=config.fee_rate,
        slippage_rate=config.slippage_rate,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        trailing_stop_pct=config.trailing_stop_pct,
    )
    result = engine.run(candles, symbol)
    run_id = str(uuid.uuid4())
    parameters = strategy_parameters(
        config.strategy,
        short_window,
        long_window,
        config.stop_loss_pct,
        config.take_profit_pct,
        config.trailing_stop_pct,
        config.cooldown_seconds,
    )
    summary = BacktestRunSummary(
        run_id=run_id,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
        strategy=config.strategy,
        parameters=parameters,
        candle_count=len(candles),
        initial_equity=result.initial_equity,
        final_equity=result.final_equity,
        return_pct=result.return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        trade_count=result.trade_count,
        fees_paid=result.fees_paid,
        slippage_paid=result.slippage_paid,
    )
    storage.record_backtest_run(summary)
    for trade in result.trades:
        storage.record_backtest_trade(trade, run_id=run_id)
    return summary


def _sort_summaries(summaries: list[BacktestRunSummary], sort_by: str) -> list[BacktestRunSummary]:
    reverse = sort_by != "max_drawdown_pct"
    return sorted(summaries, key=lambda summary: getattr(summary, sort_by), reverse=reverse)


def _create_risk_manager(config: RuntimeConfig) -> RiskManager:
    return RiskManager(
        risk_per_trade=config.risk_per_trade,
        max_position_usdt=config.max_position_usdt,
        min_order_usdt=config.min_order_usdt,
        max_daily_trades=config.max_daily_trades,
        max_daily_loss_usdt=config.max_daily_loss_usdt,
        cooldown_seconds=config.cooldown_seconds,
        allow_sell_without_position=config.allow_sell_without_position,
    )
