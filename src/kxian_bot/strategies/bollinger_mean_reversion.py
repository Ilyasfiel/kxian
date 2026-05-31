from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class BollingerMeanReversionStrategy:
    def __init__(self, band_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if band_window >= trend_window:
            raise ValueError("band_window must be smaller than trend_window")
        self.band_window = band_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.band_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(closes) < self.trend_window + 1:
            return None

        current_mean = simple_moving_average(closes, self.band_window)
        previous_mean = simple_moving_average(closes[:-1], self.band_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        if None in {current_mean, previous_mean, current_trend, previous_trend}:
            return None

        current_band_closes = closes[-self.band_window :]
        previous_band_closes = closes[-self.band_window - 2 : -2]
        current_deviation = pstdev(current_band_closes)
        previous_deviation = pstdev(previous_band_closes)
        if current_deviation <= 0:
            return None

        lower_band = current_mean - 1.6 * current_deviation
        middle_band = current_mean
        previous_lower_band = previous_mean - 1.6 * previous_deviation
        previous_close = closes[-2]
        last_price = closes[-1]
        trend_not_collapsing = current_trend >= previous_trend * 0.992
        price_not_far_below_trend = last_price >= current_trend * 0.965
        reclaimed_lower_band = previous_close < previous_lower_band and last_price >= lower_band

        if reclaimed_lower_band and trend_not_collapsing and price_not_far_below_trend:
            return Signal(symbol=self.symbol, side="buy", price=last_price, reason="bollinger_mean_reversion_buy")
        if last_price >= middle_band or last_price < current_trend * 0.955:
            return Signal(symbol=self.symbol, side="sell", price=last_price, reason="bollinger_mean_reversion_sell")
        return None
