from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class RegimeAdaptiveLongStrategy:
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
        closes = [candle.close for candle in candles]
        if len(candles) < self.context_window + self.fast_window:
            return None

        previous = candles[:-1]
        last = candles[-1]
        previous_close = closes[-2]
        current_fast = simple_moving_average(closes, self.fast_window)
        previous_fast = simple_moving_average(closes[:-1], self.fast_window)
        current_context = simple_moving_average(closes, self.context_window)
        previous_context = simple_moving_average(closes[:-1], self.context_window)
        older_context = simple_moving_average(closes[: -self.fast_window], self.context_window)
        if None in {current_fast, previous_fast, current_context, previous_context, older_context}:
            return None

        context_closes = closes[-self.context_window :]
        previous_context_closes = closes[-self.context_window - 1 : -1]
        deviation = pstdev(context_closes)
        previous_deviation = pstdev(previous_context_closes)
        if deviation <= 0 or previous_deviation <= 0:
            return None

        context_slope_pct = (current_context - older_context) / older_context if older_context > 0 else 0.0
        fast_slope_pct = (current_fast - previous_fast) / previous_fast if previous_fast > 0 else 0.0
        efficiency = _trend_efficiency(context_closes)
        volatility_pct = deviation / current_context if current_context > 0 else 0.0
        rolling_high = max(candle.high for candle in candles[-self.context_window :])
        previous_high = max(candle.high for candle in previous[-self.fast_window :])
        previous_low = min(candle.low for candle in previous[-self.fast_window :])
        drawdown_from_high_pct = (rolling_high - last.close) / rolling_high if rolling_high > 0 else 0.0
        previous_drawdown_pct = (rolling_high - previous_close) / rolling_high if rolling_high > 0 else 0.0
        lower_band = current_context - 1.25 * deviation
        previous_lower_band = previous_context - 1.25 * previous_deviation
        upper_band = current_context + 0.8 * deviation

        strong_uptrend = context_slope_pct >= 0.0007 and efficiency >= 0.13 and last.close >= current_context * 0.995
        strong_downtrend = context_slope_pct <= -0.0014 and efficiency >= 0.15 and last.close <= current_context * 0.985
        choppy_or_mixed = not strong_uptrend and not strong_downtrend

        trend_reclaim = previous_close <= previous_fast and last.close > current_fast and fast_slope_pct >= 0
        trend_breakout = last.close > previous_high * 1.0005 and current_fast >= current_context * 0.998
        trend_support = last.close >= current_context * 0.998 and drawdown_from_high_pct <= 0.075
        if strong_uptrend and trend_support and (trend_reclaim or trend_breakout):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="regime_adaptive_long_buy")

        mean_reversion_reclaim = previous_close <= previous_lower_band and last.close > lower_band
        shallow_context_floor = last.close >= current_context * 0.955 and context_slope_pct >= -0.035
        if choppy_or_mixed and mean_reversion_reclaim and shallow_context_floor and fast_slope_pct >= -0.002:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="regime_adaptive_long_buy")

        panic_floor = max(0.02, min(0.075, volatility_pct * 0.85))
        rebound_floor = max(0.005, min(0.02, volatility_pct * 0.22))
        panic_rebound = (
            strong_downtrend
            and previous_drawdown_pct >= panic_floor
            and previous_close <= previous_lower_band
            and last.close >= previous_low * (1 + rebound_floor)
            and last.close > current_fast
            and last.close >= current_context * 0.9
        )
        if panic_rebound:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="regime_adaptive_long_buy")

        fast_lost = previous_close >= previous_fast and last.close < current_fast
        context_lost = last.close < current_context * 0.975 and context_slope_pct < 0
        rebound_target_hit = choppy_or_mixed and (last.close >= current_context or last.close >= upper_band)
        trend_risk_off = strong_uptrend and drawdown_from_high_pct >= 0.085 and last.close < current_fast
        renewed_breakdown = last.close < lower_band and last.close <= previous_low * 0.995
        if fast_lost or context_lost or rebound_target_hit or trend_risk_off or renewed_breakdown:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="regime_adaptive_long_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
