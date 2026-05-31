from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class TrendFilteredMovingAverageCrossStrategy:
    def __init__(self, short_window: int, long_window: int, symbol: str = "BTCUSDT") -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.symbol = symbol

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.long_window + self.short_window:
            return None

        previous = candles[:-1]
        last = candles[-1]
        previous_close = closes[-2]
        current_short = simple_moving_average(closes, self.short_window)
        previous_short = simple_moving_average(closes[:-1], self.short_window)
        current_long = simple_moving_average(closes, self.long_window)
        previous_long = simple_moving_average(closes[:-1], self.long_window)
        older_long = simple_moving_average(closes[: -self.short_window], self.long_window)
        if None in {current_short, previous_short, current_long, previous_long, older_long}:
            return None

        long_slope_pct = (current_long - older_long) / older_long if older_long > 0 else 0.0
        trend_efficiency = _trend_efficiency(closes[-self.long_window :])
        price_above_long = last.close > current_long * 1.001
        short_above_long = current_short > current_long * 1.0005
        long_filter = current_long >= previous_long and long_slope_pct >= 0.0004 and trend_efficiency >= 0.12

        bullish_cross = previous_short <= previous_long and current_short > current_long
        reclaimed_short = previous_close <= previous_short and last.close > current_short
        previous_high = max(candle.high for candle in previous[-self.short_window :])
        short_breakout = last.close > previous_high and current_short > previous_short
        if long_filter and price_above_long and short_above_long and (bullish_cross or reclaimed_short or short_breakout):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="trend_filtered_ma_buy")

        bearish_cross = previous_short >= previous_long and current_short < current_long
        trend_lost = last.close < current_long or (current_long < previous_long and last.close < current_short)
        if bearish_cross or trend_lost:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="trend_filtered_ma_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
