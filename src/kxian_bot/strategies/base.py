from __future__ import annotations

from typing import Protocol, Sequence

from kxian_bot.models import Candle, Signal


class Strategy(Protocol):
    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        ...
