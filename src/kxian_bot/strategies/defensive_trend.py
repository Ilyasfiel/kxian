from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class DefensiveTrendStrategy:
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
        current_fast = simple_moving_average(closes, self.short_window)
        previous_fast = simple_moving_average(closes[:-1], self.short_window)
        current_trend = simple_moving_average(closes, self.long_window)
        previous_trend = simple_moving_average(closes[:-1], self.long_window)
        older_trend = simple_moving_average(closes[: -self.short_window], self.long_window)
        if None in {current_fast, previous_fast, current_trend, previous_trend, older_trend}:
            return None

        trend_slope_pct = (current_trend - older_trend) / older_trend if older_trend > 0 else 0.0
        fast_slope_pct = (current_fast - previous_fast) / previous_fast if previous_fast > 0 else 0.0
        trend_efficiency = _trend_efficiency(closes[-self.long_window :])
        rolling_high = max(candle.high for candle in candles[-self.long_window :])
        drawdown_from_high_pct = (rolling_high - last.close) / rolling_high if rolling_high > 0 else 0.0
        previous_high = max(candle.high for candle in previous[-self.short_window :])
        breakout_margin_pct = (last.close - previous_high) / previous_high if previous_high > 0 else 0.0

        trend_is_rising = current_trend >= previous_trend and trend_slope_pct >= 0.0006
        trend_is_orderly = trend_efficiency >= 0.16
        price_has_trend_support = last.close > current_trend * 1.002
        fast_leads_trend = current_fast > current_trend * 1.001 and fast_slope_pct >= 0
        shallow_pullback = drawdown_from_high_pct <= 0.065
        reclaimed_fast = previous_close <= previous_fast and last.close > current_fast
        short_breakout = last.close > previous_high and breakout_margin_pct >= 0.0008

        if (
            trend_is_rising
            and trend_is_orderly
            and price_has_trend_support
            and fast_leads_trend
            and shallow_pullback
            and (reclaimed_fast or short_breakout)
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="defensive_trend_buy")

        fast_lost = previous_close >= previous_fast and last.close < current_fast
        trend_floor_lost = last.close < current_trend * 0.995
        trend_rolled_over = current_trend < previous_trend and last.close < current_fast
        risk_off_pullback = drawdown_from_high_pct >= 0.08 and last.close < current_fast
        if fast_lost or trend_floor_lost or trend_rolled_over or risk_off_pullback:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="defensive_trend_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
