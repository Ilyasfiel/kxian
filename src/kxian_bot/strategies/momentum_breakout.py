from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class MomentumBreakoutStrategy:
    def __init__(self, momentum_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if momentum_window >= trend_window:
            raise ValueError("momentum_window must be smaller than trend_window")
        self.momentum_window = momentum_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.momentum_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.trend_window + 1:
            return None

        previous = candles[:-1]
        last = candles[-1]
        current_fast = simple_moving_average(closes, self.momentum_window)
        previous_fast = simple_moving_average(closes[:-1], self.momentum_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        if None in {current_fast, previous_fast, current_trend, previous_trend}:
            return None

        previous_high = max(candle.high for candle in previous[-self.momentum_window :])
        previous_low = min(candle.low for candle in previous[-self.momentum_window :])
        momentum_reference = closes[-self.momentum_window - 1]
        trend_slope_pct = (current_trend - previous_trend) / previous_trend if previous_trend > 0 else 0.0
        breakout_margin_pct = (last.close - previous_high) / previous_high if previous_high > 0 else 0.0
        trend_efficiency = _trend_efficiency(closes[-self.trend_window :])
        trend_is_rising = trend_slope_pct > 0.0002
        fast_above_trend = current_fast > current_trend * 1.001
        price_breakout = (
            last.close > previous_high
            and last.close > momentum_reference
            and breakout_margin_pct >= 0.0006
        )
        trend_is_orderly = trend_efficiency >= 0.18
        fast_rollover = current_fast < previous_fast and last.close < current_fast

        if trend_is_rising and fast_above_trend and price_breakout and trend_is_orderly:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="momentum_breakout_buy")
        if last.close < previous_low or fast_rollover or last.close < current_trend:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="momentum_breakout_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
