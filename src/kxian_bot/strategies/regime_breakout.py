from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class RegimeBreakoutStrategy:
    def __init__(self, breakout_window: int, regime_window: int, symbol: str = "BTCUSDT") -> None:
        if breakout_window >= regime_window:
            raise ValueError("breakout_window must be smaller than regime_window")
        self.breakout_window = breakout_window
        self.regime_window = regime_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.breakout_window

    @property
    def long_window(self) -> int:
        return self.regime_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.regime_window + self.breakout_window:
            return None

        previous = candles[:-1]
        last = candles[-1]
        current_fast = simple_moving_average(closes, self.breakout_window)
        previous_fast = simple_moving_average(closes[:-1], self.breakout_window)
        current_regime = simple_moving_average(closes, self.regime_window)
        previous_regime = simple_moving_average(closes[:-1], self.regime_window)
        older_regime = simple_moving_average(closes[: -self.breakout_window], self.regime_window)
        if None in {current_fast, previous_fast, current_regime, previous_regime, older_regime}:
            return None

        previous_high = max(candle.high for candle in previous[-self.breakout_window :])
        previous_low = min(candle.low for candle in previous[-self.breakout_window :])
        regime_slope_pct = (current_regime - older_regime) / older_regime if older_regime > 0 else 0.0
        breakout_margin_pct = (last.close - previous_high) / previous_high if previous_high > 0 else 0.0
        trend_efficiency = _trend_efficiency(closes[-self.regime_window :])
        price_above_regime = last.close > current_regime * 1.002
        fast_above_regime = current_fast > current_regime * 1.001
        regime_is_rising = current_regime > previous_regime and regime_slope_pct >= 0.001
        orderly_trend = trend_efficiency >= 0.28
        breakout_confirmed = last.close > previous_high and breakout_margin_pct >= 0.001

        if regime_is_rising and orderly_trend and price_above_regime and fast_above_regime and breakout_confirmed:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="regime_breakout_buy")

        fast_rollover = current_fast < previous_fast and last.close < current_fast
        trend_lost = last.close < current_regime or last.close < previous_low
        regime_rolled_over = current_regime < previous_regime
        if fast_rollover or trend_lost or regime_rolled_over:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="regime_breakout_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
