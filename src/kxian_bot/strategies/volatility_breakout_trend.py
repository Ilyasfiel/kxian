from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class VolatilityBreakoutTrendStrategy:
    def __init__(self, breakout_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if breakout_window >= trend_window:
            raise ValueError("breakout_window must be smaller than trend_window")
        self.breakout_window = breakout_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.breakout_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.trend_window + self.breakout_window:
            return None

        previous = candles[:-1]
        last = candles[-1]
        current_fast = simple_moving_average(closes, self.breakout_window)
        previous_fast = simple_moving_average(closes[:-1], self.breakout_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        older_trend = simple_moving_average(closes[: -self.breakout_window], self.trend_window)
        if None in {current_fast, previous_fast, current_trend, previous_trend, older_trend}:
            return None

        trend_closes = closes[-self.trend_window :]
        deviation = pstdev(trend_closes)
        if deviation <= 0 or current_trend <= 0:
            return None

        previous_high = max(candle.high for candle in previous[-self.breakout_window :])
        previous_low = min(candle.low for candle in previous[-self.breakout_window :])
        previous_close = closes[-2]
        volatility_pct = deviation / current_trend
        trend_slope_pct = (current_trend - older_trend) / older_trend if older_trend > 0 else 0.0
        fast_slope_pct = (current_fast - previous_fast) / previous_fast if previous_fast > 0 else 0.0
        trend_efficiency = _trend_efficiency(trend_closes)
        breakout_margin_pct = (last.close - previous_high) / previous_high if previous_high > 0 else 0.0
        extension_pct = (last.close - current_trend) / current_trend
        close_momentum_pct = (last.close - previous_close) / previous_close if previous_close > 0 else 0.0

        min_breakout_margin = max(0.0012, min(0.006, volatility_pct * 0.3))
        max_extension = max(0.025, min(0.09, volatility_pct * 3.0))
        min_fast_slope = max(0.0002, min(0.0015, volatility_pct * 0.06))
        min_close_momentum = max(0.0008, min(0.003, volatility_pct * 0.1))
        trend_is_rising = current_trend >= previous_trend and trend_slope_pct >= 0.001
        volatility_is_tradable = 0.002 <= volatility_pct <= 0.075
        trend_is_orderly = trend_efficiency >= 0.26
        price_has_support = last.close > current_trend * 1.003
        fast_confirms = (
            current_fast > current_trend * 1.001
            and fast_slope_pct >= min_fast_slope
            and last.close > current_fast * 1.0005
        )
        breakout_confirmed = last.close > previous_high and breakout_margin_pct >= min_breakout_margin
        close_confirms_breakout = close_momentum_pct >= min_close_momentum
        not_chasing_blowoff = extension_pct <= max_extension

        if (
            trend_is_rising
            and volatility_is_tradable
            and trend_is_orderly
            and price_has_support
            and fast_confirms
            and breakout_confirmed
            and close_confirms_breakout
            and not_chasing_blowoff
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="volatility_breakout_trend_buy")

        fast_lost = current_fast < previous_fast and last.close < current_fast
        trend_floor_lost = last.close < current_trend * 0.994
        channel_failed = last.close < previous_low
        trend_rolled_over = current_trend < previous_trend and last.close < current_fast
        volatility_spike_reversal = volatility_pct > 0.08 and last.close < current_fast
        if fast_lost or trend_floor_lost or channel_failed or trend_rolled_over or volatility_spike_reversal:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="volatility_breakout_trend_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
