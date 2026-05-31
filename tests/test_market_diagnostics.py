from kxian_bot.market_diagnostics import diagnose_market
from kxian_bot.models import Candle


def test_diagnose_market_reports_benchmark_drawdown_and_cost_pressure():
    candles = [
        Candle(open_time=index, open=price, high=price, low=price, close=price, volume=1, close_time=index + 1)
        for index, price in enumerate([100, 110, 105, 120])
    ]

    result = diagnose_market(candles, segments=2, fee_rate=0.001, slippage_rate=0.0005)

    assert result["candle_count"] == 4
    assert result["buy_hold_return_pct"] == 20.0
    assert result["buy_hold_max_drawdown_pct"] == 4.5455
    assert result["round_trip_friction_pct"] == 0.3
    assert result["classification"]["regime"] == "uptrend"
    assert result["segment_count"] == 2
    assert len(result["segments"]) == 2
    assert result["segments"][0]["return_pct"] == 10.0
    assert result["segments"][1]["return_pct"] == 14.2857


def test_diagnose_market_handles_empty_sample():
    result = diagnose_market([], segments=3)

    assert result["candle_count"] == 0
    assert result["buy_hold_return_pct"] == 0.0
    assert result["segments"] == []
    assert result["classification"]["cost_pressure"] == "unknown"
