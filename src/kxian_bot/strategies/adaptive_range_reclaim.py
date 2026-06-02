from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import relative_strength_index, simple_moving_average
from kxian_bot.models import Candle, Signal


class AdaptiveRangeReclaimStrategy:
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

        context_closes = closes[-self.context_window :]
        previous_context_closes = closes[-self.context_window - 1 : -1]
        deviation = pstdev(context_closes)
        previous_deviation = pstdev(previous_context_closes)
        if deviation <= 0 or previous_deviation <= 0 or current_context <= 0:
            return None

        context_slope_pct = (current_context - older_context) / older_context if older_context > 0 else 0.0
        fast_slope_pct = (current_fast - previous_fast) / previous_fast if previous_fast > 0 else 0.0
        volatility_pct = deviation / current_context
        efficiency = _trend_efficiency(context_closes)
        lower_band = current_context - 1.15 * deviation
        previous_lower_band = previous_context - 1.15 * previous_deviation
        upper_band = current_context + 0.95 * deviation
        previous_low = min(candle.low for candle in previous[-self.fast_window :])
        rolling_high = max(candle.high for candle in candles[-self.context_window :])
        drawdown_pct = (rolling_high - last.close) / rolling_high if rolling_high > 0 else 0.0

        tradable_range = 0.002 <= volatility_pct <= 0.09
        not_strong_downtrend = context_slope_pct >= -0.018 or efficiency < 0.55
        reclaimed_range = previous_close <= previous_lower_band and last.close > lower_band
        reclaimed_fast = previous_close <= previous_fast and last.close > current_fast
        panic_reclaim = previous_close <= previous_low * 1.001 and last.close >= previous_low * (1 + min(0.035, volatility_pct * 0.42))
        rsi_recovered = rsi >= 35
        drawdown_not_terminal = drawdown_pct <= max(0.045, min(0.18, volatility_pct * 2.4))
        if (
            tradable_range
            and not_strong_downtrend
            and drawdown_not_terminal
            and rsi_recovered
            and (reclaimed_range or reclaimed_fast or panic_reclaim)
            and fast_slope_pct >= -0.004
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="adaptive_range_reclaim_buy")

        fast_lost = previous_close >= previous_fast and last.close < current_fast and fast_slope_pct < 0
        target_reached = last.close >= upper_band or (last.close >= current_context and rsi >= 62)
        context_failed = last.close < lower_band and context_slope_pct < -0.004
        volatility_reversal = volatility_pct > 0.1 and last.close < current_fast
        if fast_lost or target_reached or context_failed or volatility_reversal:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="adaptive_range_reclaim_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
