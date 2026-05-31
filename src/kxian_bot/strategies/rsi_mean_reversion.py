from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import relative_strength_index, simple_moving_average
from kxian_bot.models import Candle, Signal


class RsiMeanReversionStrategy:
    def __init__(self, rsi_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if rsi_window >= trend_window:
            raise ValueError("rsi_window must be smaller than trend_window")
        self.rsi_window = rsi_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.rsi_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(closes) < self.trend_window + 1:
            return None

        current_rsi = relative_strength_index(closes, self.rsi_window)
        previous_rsi = relative_strength_index(closes[:-1], self.rsi_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        if None in {current_rsi, previous_rsi, current_trend, previous_trend}:
            return None

        last_price = closes[-1]
        trend_not_collapsing = current_trend >= previous_trend * 0.995
        price_near_trend = last_price >= current_trend * 0.97
        recovered_from_oversold = previous_rsi <= 30 < current_rsi

        if recovered_from_oversold and trend_not_collapsing and price_near_trend:
            return Signal(symbol=self.symbol, side="buy", price=last_price, reason="rsi_mean_reversion_buy")
        if current_rsi >= 70 or last_price < current_trend * 0.975:
            return Signal(symbol=self.symbol, side="sell", price=last_price, reason="rsi_mean_reversion_sell")
        return None
