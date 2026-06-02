from kxian_bot.models import Candle
from kxian_bot.strategies.adaptive_range_reclaim import AdaptiveRangeReclaimStrategy
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
from kxian_bot.strategies.volatility_regime_pullback_reclaim import VolatilityRegimePullbackReclaimStrategy
from kxian_bot.strategies.volatility_breakout_trend import VolatilityBreakoutTrendStrategy
from kxian_bot.strategies.factory import RESEARCH_ONLY_STRATEGIES, create_strategy


def build_candle(idx: int, close: float) -> Candle:
    return Candle(
        open_time=idx,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        close_time=idx + 1,
    )


def test_strategy_emits_buy_on_bullish_cross():
    strategy = MovingAverageCrossStrategy(short_window=3, long_window=5)
    candles = [build_candle(i, price) for i, price in enumerate([10, 9, 8, 9, 10, 11])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"


def test_strategy_emits_sell_on_bearish_cross():
    strategy = MovingAverageCrossStrategy(short_window=3, long_window=5)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 11, 10, 9])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"


def test_donchian_breakout_emits_buy_above_prior_channel():
    strategy = DonchianBreakoutStrategy(entry_window=5, exit_window=2)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 11, 10, 13])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "donchian_breakout_buy"


def test_donchian_breakout_emits_sell_below_prior_exit_channel():
    strategy = DonchianBreakoutStrategy(entry_window=5, exit_window=2)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 11, 10, 9])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "donchian_breakout_sell"


def test_trend_pullback_emits_buy_on_reclaimed_short_average_in_uptrend():
    strategy = TrendPullbackStrategy(pullback_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 13, 15])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "trend_pullback_buy"


def test_trend_pullback_emits_sell_when_short_average_is_lost():
    strategy = TrendPullbackStrategy(pullback_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 13])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "trend_pullback_sell"


def test_mean_reversion_emits_buy_when_price_reclaims_lower_band():
    strategy = MeanReversionStrategy(lookback_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 100, 100, 96, 99])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "mean_reversion_buy"


def test_mean_reversion_emits_sell_when_price_reaches_upper_band():
    strategy = MeanReversionStrategy(lookback_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 99, 98, 99, 103])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "mean_reversion_sell"


def test_rsi_mean_reversion_emits_buy_after_oversold_recovery():
    strategy = RsiMeanReversionStrategy(rsi_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 102, 100, 98, 96, 99])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "rsi_mean_reversion_buy"


def test_rsi_mean_reversion_emits_sell_when_rsi_is_overbought():
    strategy = RsiMeanReversionStrategy(rsi_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 99, 98, 99, 101, 103, 106])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "rsi_mean_reversion_sell"


def test_momentum_breakout_emits_buy_on_short_channel_breakout():
    strategy = MomentumBreakoutStrategy(momentum_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "momentum_breakout_buy"


def test_momentum_breakout_emits_sell_when_short_channel_breaks_down():
    strategy = MomentumBreakoutStrategy(momentum_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 11])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "momentum_breakout_sell"


def test_bollinger_mean_reversion_emits_buy_when_lower_band_is_reclaimed():
    strategy = BollingerMeanReversionStrategy(band_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 100, 100, 94, 98])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "bollinger_mean_reversion_buy"


def test_bollinger_mean_reversion_emits_sell_when_middle_band_is_reached():
    strategy = BollingerMeanReversionStrategy(band_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 99, 96, 98, 101])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "bollinger_mean_reversion_sell"


def test_regime_breakout_emits_buy_only_in_orderly_rising_regime():
    strategy = RegimeBreakoutStrategy(breakout_window=3, regime_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16, 17, 18])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "regime_breakout_buy"


def test_regime_breakout_stays_idle_when_regime_is_not_rising():
    strategy = RegimeBreakoutStrategy(breakout_window=3, regime_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([18, 17, 16, 15, 14, 13, 14, 15, 16])]

    signal = strategy.generate(candles)

    assert signal is None


def test_regime_breakout_emits_sell_when_regime_is_lost():
    strategy = RegimeBreakoutStrategy(breakout_window=3, regime_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16, 17, 12])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "regime_breakout_sell"


def test_trend_filtered_ma_emits_buy_in_filtered_uptrend():
    strategy = TrendFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 10, 11, 12, 13, 14, 13, 15, 16])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "trend_filtered_ma_buy"


def test_trend_filtered_ma_rejects_choppy_cross():
    strategy = TrendFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 12, 10, 12, 10, 12, 10, 12, 13])]

    signal = strategy.generate(candles)

    assert signal is None


def test_trend_filtered_ma_emits_sell_when_long_trend_is_lost():
    strategy = TrendFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16, 17, 12])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "trend_filtered_ma_sell"


def test_regime_filtered_ma_emits_buy_after_supported_reclaim():
    strategy = RegimeFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    prices = [
        100.0,
        100.6,
        101.2,
        101.8,
        102.4,
        103.0,
        103.6,
        104.2,
        104.8,
        105.4,
        106.0,
        106.6,
        107.2,
        107.8,
        108.4,
        109.0,
        109.6,
        110.2,
        109.7,
        108.7,
        107.7,
        113.7,
    ]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "regime_filtered_ma_buy"


def test_regime_filtered_ma_rejects_choppy_reclaim():
    strategy = RegimeFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    prices = [100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100, 104]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is None


def test_regime_filtered_ma_emits_sell_when_trend_floor_breaks():
    strategy = RegimeFilteredMovingAverageCrossStrategy(short_window=3, long_window=6)
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 112, 111, 110, 108]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "regime_filtered_ma_sell"


def test_defensive_trend_emits_buy_in_orderly_supported_uptrend():
    strategy = DefensiveTrendStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 14.5, 16, 17])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "defensive_trend_buy"


def test_defensive_trend_rejects_deep_pullback_despite_reclaim():
    strategy = DefensiveTrendStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 12, 14, 16, 18, 20, 15, 16, 17])]

    signal = strategy.generate(candles)

    assert signal is None


def test_defensive_trend_emits_sell_when_trend_floor_breaks():
    strategy = DefensiveTrendStrategy(short_window=3, long_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16, 17, 12])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "defensive_trend_sell"


def test_panic_rebound_emits_buy_after_washout_reclaim():
    strategy = PanicReboundStrategy(rebound_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 100, 98, 92, 96])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "panic_rebound_buy"


def test_panic_rebound_rejects_continuing_breakdown():
    strategy = PanicReboundStrategy(rebound_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 100, 98, 92, 89])]

    signal = strategy.generate(candles)

    assert signal is None or signal.side != "buy"


def test_panic_rebound_emits_sell_when_recovery_stalls():
    strategy = PanicReboundStrategy(rebound_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 100, 100, 100, 98, 92, 96, 93.5])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "panic_rebound_sell"


def test_regime_adaptive_long_buys_supported_uptrend_reclaim():
    strategy = RegimeAdaptiveLongStrategy(fast_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 14.5, 16, 17])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "regime_adaptive_long_buy"


def test_regime_adaptive_long_buys_choppy_lower_band_reclaim():
    strategy = RegimeAdaptiveLongStrategy(fast_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 99, 100, 101, 94, 96, 92, 95])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "regime_adaptive_long_buy"


def test_regime_adaptive_long_sells_when_context_breaks():
    strategy = RegimeAdaptiveLongStrategy(fast_window=3, context_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 102, 103, 104, 105, 103, 99, 96])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "regime_adaptive_long_sell"


def test_volatility_breakout_trend_buys_orderly_supported_breakout():
    strategy = VolatilityBreakoutTrendStrategy(breakout_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 102, 103, 104, 105, 106, 107, 106, 108, 110])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "volatility_breakout_trend_buy"


def test_volatility_breakout_trend_rejects_overextended_breakout():
    strategy = VolatilityBreakoutTrendStrategy(breakout_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 126])]

    signal = strategy.generate(candles)

    assert signal is None


def test_volatility_breakout_trend_rejects_marginal_breakout():
    strategy = VolatilityBreakoutTrendStrategy(breakout_window=3, trend_window=6)
    candles = [
        build_candle(i, price)
        for i, price in enumerate([100, 101, 102, 103, 104, 105, 105.4, 105.8, 105.6, 106.0, 106.08])
    ]

    signal = strategy.generate(candles)

    assert signal is None


def test_volatility_breakout_trend_sells_when_trend_floor_breaks():
    strategy = VolatilityBreakoutTrendStrategy(breakout_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 99])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "volatility_breakout_trend_sell"


def test_downtrend_breakdown_short_sells_breakdown_in_falling_regime():
    strategy = DowntrendBreakdownShortStrategy(breakdown_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 99, 98, 97, 96, 95, 94, 90])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "downtrend_breakdown_short_entry"


def test_downtrend_breakdown_short_buys_to_cover_recovery():
    strategy = DowntrendBreakdownShortStrategy(breakdown_window=3, trend_window=6)
    candles = [build_candle(i, price) for i, price in enumerate([100, 99, 98, 97, 96, 95, 94, 98])]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "downtrend_breakdown_short_exit"


def test_adaptive_range_reclaim_waits_for_enough_context():
    strategy = AdaptiveRangeReclaimStrategy(fast_window=3, context_window=6)

    assert strategy.generate([build_candle(i, 100 + i) for i in range(6)]) is None


def test_adaptive_range_reclaim_buys_after_range_reclaim():
    strategy = AdaptiveRangeReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 101, 100, 101, 100, 99, 97, 95, 96, 99]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "adaptive_range_reclaim_buy"


def test_adaptive_range_reclaim_sells_at_range_target():
    strategy = AdaptiveRangeReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 99, 98, 97, 96, 98, 100, 104, 108, 112]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "adaptive_range_reclaim_sell"


def test_factory_creates_adaptive_range_reclaim_as_research_only():
    strategy = create_strategy("adaptive_range_reclaim", short_window=3, long_window=6, symbol="BTCUSDT")

    assert isinstance(strategy, AdaptiveRangeReclaimStrategy)
    assert "adaptive_range_reclaim" in RESEARCH_ONLY_STRATEGIES


def test_volatility_regime_pullback_reclaim_waits_for_enough_context():
    strategy = VolatilityRegimePullbackReclaimStrategy(fast_window=3, context_window=6)

    assert strategy.generate([build_candle(i, 100 + i) for i in range(6)]) is None


def test_volatility_regime_pullback_reclaim_buys_quality_pullback_reclaim():
    strategy = VolatilityRegimePullbackReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 104, 108, 112, 108, 112, 115, 113, 114, 115]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "volatility_regime_pullback_reclaim_buy"


def test_volatility_regime_pullback_reclaim_buys_range_mid_reclaim():
    strategy = VolatilityRegimePullbackReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 102, 104, 106, 106, 108, 108, 106, 103, 108]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "buy"
    assert signal.reason == "volatility_regime_pullback_reclaim_buy"


def test_volatility_regime_pullback_reclaim_prioritizes_exit_over_new_entry():
    strategy = VolatilityRegimePullbackReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 102, 104, 106, 108, 110, 109, 107, 108, 111]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "volatility_regime_pullback_reclaim_sell"


def test_volatility_regime_pullback_reclaim_sells_when_fast_support_breaks():
    strategy = VolatilityRegimePullbackReclaimStrategy(fast_window=3, context_window=6)
    prices = [100, 102, 104, 106, 108, 110, 109, 107, 108, 104]
    candles = [build_candle(i, price) for i, price in enumerate(prices)]

    signal = strategy.generate(candles)

    assert signal is not None
    assert signal.side == "sell"
    assert signal.reason == "volatility_regime_pullback_reclaim_sell"


def test_factory_creates_volatility_regime_pullback_reclaim_as_research_only():
    strategy = create_strategy("volatility_regime_pullback_reclaim", short_window=3, long_window=6, symbol="BTCUSDT")

    assert isinstance(strategy, VolatilityRegimePullbackReclaimStrategy)
    assert "volatility_regime_pullback_reclaim" in RESEARCH_ONLY_STRATEGIES
