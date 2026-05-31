from __future__ import annotations

from statistics import fmean
from typing import Sequence

from kxian_bot.models import Candle, Signal


class DowntrendBreakdownShortStrategy:
    """Research-only synthetic short strategy for validating downside edges."""

    def __init__(self, breakdown_window: int = 8, trend_window: int = 30, symbol: str = "BTCUSDT") -> None:
        if breakdown_window < 2:
            raise ValueError("breakdown_window must be >= 2")
        if trend_window <= breakdown_window:
            raise ValueError("trend_window must be greater than breakdown_window")
        self.breakdown_window = breakdown_window
        self.trend_window = trend_window
        self.symbol = symbol

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        required = self.trend_window + 1
        if len(candles) < required:
            return None

        last = candles[-1]
        closes = [candle.close for candle in candles]
        short_ma = fmean(closes[-self.breakdown_window :])
        long_ma = fmean(closes[-self.trend_window :])
        previous_long_ma = fmean(closes[-self.trend_window - 1 : -1])
        prior_window = candles[-self.breakdown_window - 1 : -1]
        prior_low = min(candle.low for candle in prior_window)
        prior_high = max(candle.high for candle in prior_window)

        breakdown = last.close < prior_low
        downtrend = short_ma < long_ma and long_ma <= previous_long_ma
        if breakdown and downtrend:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="downtrend_breakdown_short_entry")

        recovery = last.close > prior_high or (last.close > short_ma and short_ma >= long_ma)
        if recovery:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="downtrend_breakdown_short_exit")

        return None
