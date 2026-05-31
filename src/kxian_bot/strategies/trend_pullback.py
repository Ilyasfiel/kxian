from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class TrendPullbackStrategy:
    def __init__(self, pullback_window: int, trend_window: int, symbol: str = "BTCUSDT") -> None:
        if pullback_window >= trend_window:
            raise ValueError("pullback_window must be smaller than trend_window")
        self.pullback_window = pullback_window
        self.trend_window = trend_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.pullback_window

    @property
    def long_window(self) -> int:
        return self.trend_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(closes) < self.trend_window + 1:
            return None

        current_pullback = simple_moving_average(closes, self.pullback_window)
        previous_pullback = simple_moving_average(closes[:-1], self.pullback_window)
        current_trend = simple_moving_average(closes, self.trend_window)
        previous_trend = simple_moving_average(closes[:-1], self.trend_window)
        if None in {current_pullback, previous_pullback, current_trend, previous_trend}:
            return None

        previous_close = closes[-2]
        last_price = closes[-1]
        trend_is_rising = current_trend > previous_trend
        price_above_trend = last_price > current_trend
        reclaimed_pullback_average = previous_close <= previous_pullback and last_price > current_pullback
        lost_pullback_average = previous_close >= previous_pullback and last_price < current_pullback

        if trend_is_rising and price_above_trend and reclaimed_pullback_average:
            return Signal(symbol=self.symbol, side="buy", price=last_price, reason="trend_pullback_buy")
        if lost_pullback_average or last_price < current_trend:
            return Signal(symbol=self.symbol, side="sell", price=last_price, reason="trend_pullback_sell")
        return None
