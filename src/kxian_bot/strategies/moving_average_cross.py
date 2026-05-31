from __future__ import annotations

from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class MovingAverageCrossStrategy:
    def __init__(self, short_window: int, long_window: int, symbol: str = "BTCUSDT") -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.symbol = symbol

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(closes) < self.long_window + 1:
            return None

        prev_closes = closes[:-1]
        current_short = simple_moving_average(closes, self.short_window)
        current_long = simple_moving_average(closes, self.long_window)
        prev_short = simple_moving_average(prev_closes, self.short_window)
        prev_long = simple_moving_average(prev_closes, self.long_window)

        if None in {current_short, current_long, prev_short, prev_long}:
            return None

        last_price = closes[-1]
        if prev_short <= prev_long and current_short > current_long:
            return Signal(symbol=self.symbol, side="buy", price=last_price, reason="bullish_ma_cross")
        if prev_short >= prev_long and current_short < current_long:
            return Signal(symbol=self.symbol, side="sell", price=last_price, reason="bearish_ma_cross")
        return None
