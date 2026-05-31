from __future__ import annotations

from kxian_bot.strategies.bollinger_mean_reversion import BollingerMeanReversionStrategy
from kxian_bot.strategies.defensive_trend import DefensiveTrendStrategy
from kxian_bot.strategies.downtrend_breakdown_short import DowntrendBreakdownShortStrategy
from kxian_bot.strategies.donchian_breakout import DonchianBreakoutStrategy
from kxian_bot.strategies.mean_reversion import MeanReversionStrategy
from kxian_bot.strategies.momentum_breakout import MomentumBreakoutStrategy
from kxian_bot.strategies.moving_average_cross import MovingAverageCrossStrategy
from kxian_bot.strategies.panic_rebound import PanicReboundStrategy
from kxian_bot.strategies.regime_adaptive_long import RegimeAdaptiveLongStrategy
from kxian_bot.strategies.regime_breakout import RegimeBreakoutStrategy
from kxian_bot.strategies.regime_filtered_ma_cross import RegimeFilteredMovingAverageCrossStrategy
from kxian_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from kxian_bot.strategies.trend_filtered_ma_cross import TrendFilteredMovingAverageCrossStrategy
from kxian_bot.strategies.trend_pullback import TrendPullbackStrategy
from kxian_bot.strategies.volatility_breakout_trend import VolatilityBreakoutTrendStrategy


SUPPORTED_STRATEGIES = (
    "moving_average_cross",
    "donchian_breakout",
    "trend_pullback",
    "mean_reversion",
    "rsi_mean_reversion",
    "momentum_breakout",
    "bollinger_mean_reversion",
    "regime_breakout",
    "regime_filtered_ma_cross",
    "trend_filtered_ma_cross",
    "defensive_trend",
    "panic_rebound",
    "regime_adaptive_long",
    "volatility_breakout_trend",
    "downtrend_breakdown_short",
)

RESEARCH_ONLY_STRATEGIES = frozenset({"downtrend_breakdown_short"})


def create_strategy(name: str, short_window: int, long_window: int, symbol: str):
    if name == "moving_average_cross":
        return MovingAverageCrossStrategy(short_window=short_window, long_window=long_window, symbol=symbol)
    if name == "donchian_breakout":
        return DonchianBreakoutStrategy(entry_window=long_window, exit_window=short_window, symbol=symbol)
    if name == "mean_reversion":
        return MeanReversionStrategy(lookback_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "rsi_mean_reversion":
        return RsiMeanReversionStrategy(rsi_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "trend_pullback":
        return TrendPullbackStrategy(pullback_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "momentum_breakout":
        return MomentumBreakoutStrategy(momentum_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "bollinger_mean_reversion":
        return BollingerMeanReversionStrategy(band_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "regime_breakout":
        return RegimeBreakoutStrategy(breakout_window=short_window, regime_window=long_window, symbol=symbol)
    if name == "regime_filtered_ma_cross":
        return RegimeFilteredMovingAverageCrossStrategy(short_window=short_window, long_window=long_window, symbol=symbol)
    if name == "trend_filtered_ma_cross":
        return TrendFilteredMovingAverageCrossStrategy(short_window=short_window, long_window=long_window, symbol=symbol)
    if name == "defensive_trend":
        return DefensiveTrendStrategy(short_window=short_window, long_window=long_window, symbol=symbol)
    if name == "panic_rebound":
        return PanicReboundStrategy(rebound_window=short_window, context_window=long_window, symbol=symbol)
    if name == "regime_adaptive_long":
        return RegimeAdaptiveLongStrategy(fast_window=short_window, context_window=long_window, symbol=symbol)
    if name == "volatility_breakout_trend":
        return VolatilityBreakoutTrendStrategy(breakout_window=short_window, trend_window=long_window, symbol=symbol)
    if name == "downtrend_breakdown_short":
        return DowntrendBreakdownShortStrategy(breakdown_window=short_window, trend_window=long_window, symbol=symbol)
    raise ValueError(f"Unsupported strategy: {name}")
