from kxian_bot.backtest import BacktestEngine, SyntheticShortBacktestEngine
from kxian_bot.brokers.paper import PaperBroker
from kxian_bot.models import Candle, Signal
from kxian_bot.risk import RiskManager
from kxian_bot.strategies.moving_average_cross import MovingAverageCrossStrategy


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


def build_ohlc_candle(idx: int, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        open_time=idx,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_time=idx + 1,
    )


def build_ms_candle(idx: int, close: float) -> Candle:
    open_time = 1_704_067_200_000 + (idx * 60_000)
    return Candle(
        open_time=open_time,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        close_time=open_time + 59_999,
    )


def test_backtest_generates_trade_history():
    candles = [
        build_candle(i, price)
        for i, price in enumerate([10, 9, 8, 9, 10, 11, 12, 11, 10, 9])
    ]
    strategy = MovingAverageCrossStrategy(short_window=3, long_window=5)
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker).run(candles, "BTCUSDT")

    assert result.trade_count >= 1
    assert result.final_equity > 0
    assert result.initial_equity == 1000
    assert result.return_pct < 0
    assert isinstance(result.trades, list)


class ScriptedStrategy:
    def __init__(self, signals: dict[int, str]) -> None:
        self.signals = signals

    def generate(self, candles):
        idx = candles[-1].open_time
        side = self.signals.get(idx)
        if side is None:
            return None
        return Signal(symbol="BTCUSDT", side=side, price=candles[-1].close, reason=f"scripted_{side}")


def test_backtest_records_round_trip_trade_with_fees_slippage_and_pnl():
    candles = [build_candle(i, price) for i, price in enumerate([100, 110, 105])]
    strategy = ScriptedStrategy({0: "buy", 1: "sell"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(
        strategy,
        risk,
        broker,
        fee_rate=0.001,
        slippage_rate=0.01,
    ).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert len(result.trades) == 2
    assert result.trades[0].side == "buy"
    assert result.trades[0].execution_price == 101
    assert result.trades[0].fee == 0.999
    assert result.trades[0].slippage == 9.8911
    assert result.trades[1].side == "sell"
    assert result.trades[1].execution_price == 108.9
    assert result.trades[1].pnl == 77.0625
    assert result.fees_paid == 2.0761
    assert result.slippage_paid == 20.7713
    assert result.win_rate == 100
    assert result.profit_factor == 77.0625


def test_backtest_accepts_exchange_millisecond_timestamps():
    candles = [build_ms_candle(i, price) for i, price in enumerate([100, 110, 105])]
    strategy = ScriptedStrategy({candles[0].open_time: "buy", candles[1].open_time: "sell"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[0].timestamp == 1_704_067_200_000


def test_backtest_metrics_include_drawdown_and_profit_factor():
    candles = [build_candle(i, price) for i, price in enumerate([100, 90, 80, 100, 70])]
    strategy = ScriptedStrategy({0: "buy", 2: "sell", 3: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.max_drawdown_pct == 20.2396
    assert result.win_rate == 0
    assert result.profit_factor == 0
    assert result.final_equity == 797.6
    assert result.return_pct == -20.2396


def test_backtest_liquidates_open_position_at_end_for_realized_metrics():
    candles = [build_candle(i, price) for i, price in enumerate([100, 110, 120])]
    strategy = ScriptedStrategy({0: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, fee_rate=0.001, slippage_rate=0.01).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.asset_balance == 0
    assert result.trades[-1].side == "sell"
    assert result.trades[-1].reason == "end_of_backtest_liquidation"
    assert result.trades[-1].execution_price == 118.8
    assert result.trades[-1].pnl > 0
    assert result.win_rate == 100
    assert result.profit_factor > 0


def test_backtest_ignores_buy_signal_while_position_is_open():
    candles = [build_candle(i, price) for i, price in enumerate([100, 105, 110])]
    strategy = ScriptedStrategy({0: "buy", 1: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, fee_rate=0.001, slippage_rate=0.0).run(candles, "BTCUSDT")

    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    assert result.trades[-1].reason == "end_of_backtest_liquidation"
    assert result.asset_balance == 0


def test_backtest_applies_stop_loss_before_strategy_exit():
    candles = [build_candle(i, price) for i, price in enumerate([100, 94, 93])]
    strategy = ScriptedStrategy({0: "buy", 2: "sell"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1, cooldown_seconds=3600)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, stop_loss_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].side == "sell"
    assert result.trades[1].reason == "stop_loss_triggered"
    assert result.trades[1].signal_price == 95.0475
    assert result.trades[1].execution_price == 94.99997625


def test_backtest_stop_loss_uses_intrabar_low_trigger_price():
    candles = [
        build_ohlc_candle(0, 100, 100, 100, 100),
        build_ohlc_candle(1, 100, 103, 94, 101),
    ]
    strategy = ScriptedStrategy({0: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, stop_loss_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].reason == "stop_loss_triggered"
    assert result.trades[1].signal_price == 95.0475
    assert result.trades[1].execution_price == 94.99997625


def test_backtest_applies_take_profit_before_strategy_exit():
    candles = [build_candle(i, price) for i, price in enumerate([100, 106, 107])]
    strategy = ScriptedStrategy({0: "buy", 2: "sell"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1, cooldown_seconds=3600)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, take_profit_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].side == "sell"
    assert result.trades[1].reason == "take_profit_triggered"
    assert result.trades[1].signal_price == 105.0525
    assert result.trades[1].execution_price == 104.99997375


def test_backtest_take_profit_uses_intrabar_high_trigger_price():
    candles = [
        build_ohlc_candle(0, 100, 100, 100, 100),
        build_ohlc_candle(1, 100, 106, 99, 101),
    ]
    strategy = ScriptedStrategy({0: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, take_profit_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].reason == "take_profit_triggered"
    assert result.trades[1].signal_price == 105.0525
    assert result.trades[1].execution_price == 104.99997375


def test_backtest_applies_trailing_stop_after_price_reversal():
    candles = [build_candle(i, price) for i, price in enumerate([100, 110, 104, 103])]
    strategy = ScriptedStrategy({0: "buy", 3: "sell"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1, cooldown_seconds=3600)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, trailing_stop_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].side == "sell"
    assert result.trades[1].reason == "trailing_stop_triggered"
    assert result.trades[1].signal_price == 104.5
    assert result.trades[1].execution_price == 104.44775


def test_backtest_trailing_stop_uses_intrabar_high_and_low_trigger_price():
    candles = [
        build_ohlc_candle(0, 100, 100, 100, 100),
        build_ohlc_candle(1, 100, 112, 104, 109),
    ]
    strategy = ScriptedStrategy({0: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)
    broker = PaperBroker(starting_usdt=1000)

    result = BacktestEngine(strategy, risk, broker, trailing_stop_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].reason == "end_of_backtest_liquidation"


def test_synthetic_short_backtest_profits_from_price_drop():
    candles = [build_candle(i, price) for i, price in enumerate([100, 90, 85])]
    strategy = ScriptedStrategy({0: "sell", 2: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1)

    result = SyntheticShortBacktestEngine(strategy, risk, starting_usdt=1000, fee_rate=0.001, slippage_rate=0.0).run(
        candles,
        "BTCUSDT",
    )

    assert result.trade_count == 2
    assert [trade.side for trade in result.trades] == ["sell", "buy"]
    assert result.trades[1].pnl > 0
    assert result.final_equity > result.initial_equity
    assert result.asset_balance == 0


def test_synthetic_short_backtest_applies_short_stop_loss():
    candles = [build_candle(i, price) for i, price in enumerate([100, 106, 107])]
    strategy = ScriptedStrategy({0: "sell", 2: "buy"})
    risk = RiskManager(risk_per_trade=1.0, max_position_usdt=1000, min_order_usdt=1, cooldown_seconds=3600)

    result = SyntheticShortBacktestEngine(strategy, risk, starting_usdt=1000, stop_loss_pct=5).run(candles, "BTCUSDT")

    assert result.trade_count == 2
    assert result.trades[1].side == "buy"
    assert result.trades[1].reason == "short_stop_loss_triggered"
