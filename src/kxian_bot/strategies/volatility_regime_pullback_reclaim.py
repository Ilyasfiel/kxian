from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import relative_strength_index, simple_moving_average
from kxian_bot.models import Candle, Signal


class VolatilityRegimePullbackReclaimStrategy:
    def __init__(self, fast_window: int, context_window: int, symbol: str = "BTCUSDT") -> None:
        if fast_window >= context_window:
            raise ValueError("fast_window must be smaller than context_window")
        self.fast_window = fast_window
        self.context_window = context_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.fast_window

    @property
    def long_window(self) -> int:
        return self.context_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        if len(candles) < self.context_window + self.fast_window + 1:
            return None

        closes = [candle.close for candle in candles]
        previous = candles[:-1]
        last = candles[-1]
        previous_close = closes[-2]
        current_fast = simple_moving_average(closes, self.fast_window)
        previous_fast = simple_moving_average(closes[:-1], self.fast_window)
        current_context = simple_moving_average(closes, self.context_window)
        previous_context = simple_moving_average(closes[:-1], self.context_window)
        older_context = simple_moving_average(closes[: -self.fast_window], self.context_window)
        rsi = relative_strength_index(closes, self.fast_window)
        if None in {current_fast, previous_fast, current_context, previous_context, older_context, rsi}:
            return None
        if current_context <= 0 or previous_fast <= 0 or older_context <= 0:
            return None

        context_closes = closes[-self.context_window :]
        previous_context_closes = closes[-self.context_window - 1 : -1]
        deviation = pstdev(context_closes)
        previous_deviation = pstdev(previous_context_closes)
        if deviation <= 0 or previous_deviation <= 0:
            return None

        volatility_pct = deviation / current_context
        trend_slope_pct = (current_context - older_context) / older_context
        fast_slope_pct = (current_fast - previous_fast) / previous_fast
        efficiency = _trend_efficiency(context_closes)
        lower_band = current_context - 1.05 * deviation
        previous_lower_band = previous_context - 1.05 * previous_deviation
        upper_band = current_context + 0.9 * deviation
        rolling_high = max(candle.high for candle in candles[-self.context_window :])
        previous_low = min(candle.low for candle in previous[-self.fast_window :])
        previous_high = max(candle.high for candle in previous[-self.fast_window :])
        drawdown_pct = (rolling_high - last.close) / rolling_high if rolling_high > 0 else 0.0
        pullback_depth_pct = (previous_high - previous_low) / previous_high if previous_high > 0 else 0.0
        context_extension_pct = (last.close - current_context) / current_context

        trend_quality_ok = (
            trend_slope_pct >= -0.0015
            and current_context >= previous_context * 0.998
            and efficiency >= 0.16
        )
        volatility_ok = 0.002 <= volatility_pct <= 0.085
        not_terminal_drawdown = drawdown_pct <= max(0.045, min(0.16, volatility_pct * 2.25))
        not_chasing_extension = context_extension_pct <= max(0.032, min(0.105, volatility_pct * 3.0))

        pullback_reclaim = (
            0.005 <= pullback_depth_pct <= max(0.026, min(0.11, volatility_pct * 2.7))
            and previous_close <= previous_fast
            and last.close > current_fast * 1.0004
            and last.close >= current_context * 0.992
        )
        range_mid_reclaim = (
            previous_close <= previous_lower_band
            and last.close > lower_band
            and last.close >= current_context * 0.965
            and fast_slope_pct >= -0.0025
        )
        momentum_ok = 38 <= rsi <= 72 and fast_slope_pct >= -0.002

        fast_lost = previous_close >= previous_fast and last.close < current_fast and fast_slope_pct < 0
        context_lost = last.close < current_context * 0.982 and current_context < previous_context
        target_reached = last.close >= upper_band or (last.close >= rolling_high * 0.998 and rsi >= 62)
        volatility_reversal = volatility_pct > 0.1 and last.close < current_fast
        if fast_lost or context_lost or target_reached or volatility_reversal:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="volatility_regime_pullback_reclaim_sell")

        if (
            trend_quality_ok
            and volatility_ok
            and not_terminal_drawdown
            and not_chasing_extension
            and momentum_ok
            and (pullback_reclaim or range_mid_reclaim)
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="volatility_regime_pullback_reclaim_buy")

        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
