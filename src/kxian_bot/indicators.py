from __future__ import annotations

from typing import Sequence


def simple_moving_average(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    subset = values[-window:]
    return sum(subset) / window


def relative_strength_index(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window + 1:
        return None

    changes = [values[index] - values[index - 1] for index in range(len(values) - window, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [abs(min(change, 0.0)) for change in changes]
    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))
