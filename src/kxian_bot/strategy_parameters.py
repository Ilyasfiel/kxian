from __future__ import annotations


def strategy_parameters(
    strategy: str,
    short_window: int,
    long_window: int,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    trailing_stop_pct: float = 0.0,
    cooldown_seconds: int = 0,
) -> dict:
    parameters = {"strategy": strategy, "short_window": short_window, "long_window": long_window}
    if stop_loss_pct > 0:
        parameters["stop_loss_pct"] = float(stop_loss_pct)
    if take_profit_pct > 0:
        parameters["take_profit_pct"] = float(take_profit_pct)
    if trailing_stop_pct > 0:
        parameters["trailing_stop_pct"] = float(trailing_stop_pct)
    if cooldown_seconds > 0:
        parameters["cooldown_seconds"] = int(cooldown_seconds)
    return parameters
