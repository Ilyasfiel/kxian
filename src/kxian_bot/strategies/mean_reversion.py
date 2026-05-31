from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class MeanReversionStrategy:
    def __init__(self, lookback_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if lookback_window >= trend_window:
            raise ValueError("lookback_window must be smaller than trend_window")
        self.lookback_window = lookback_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.lookback_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(closes) < self.trend_window + 1:
            return None

        current_mean = simple_moving_average(closes, self.lookback_window)
        previous_mean = simple_moving_average(closes[:-1], self.lookback_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        if None in {current_mean, previous_mean, current_trend, previous_trend}:
            return None

        recent_closes = closes[-self.lookback_window :]
        deviations = [abs(close - current_mean) for close in recent_closes]
        average_deviation = sum(deviations) / len(deviations)
        lower_band = current_mean - average_deviation
        upper_band = current_mean + average_deviation
        previous_close = closes[-2]
        last_price = closes[-1]
        trend_floor_ok = last_price >= current_trend * 0.985
        trend_not_collapsing = current_trend >= previous_trend * 0.995

        if previous_close < lower_band <= last_price and trend_floor_ok and trend_not_collapsing:
            return Signal(symbol=self.symbol, side="buy", price=last_price, reason="mean_reversion_buy")
        if last_price >= upper_band or last_price < current_trend * 0.975:
            return Signal(symbol=self.symbol, side="sell", price=last_price, reason="mean_reversion_sell")
        return None
