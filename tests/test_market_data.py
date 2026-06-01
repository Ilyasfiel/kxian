import pytest
import zipfile

from kxian_bot.market_data import (
    BitgetMarketDataClient,
    BinanceMarketDataClient,
    MarketDataError,
    OkxMarketDataClient,
    SQLiteReplayMarketDataClient,
    aggregate_candles,
    create_market_data_client,
    fetch_bitget_trading_rule,
    format_okx_symbol,
    interval_to_milliseconds,
    latest_contiguous_candles,
    load_klines_from_file,
)
from kxian_bot.models import Candle
from kxian_bot.storage import SQLiteStorage


def test_binance_kline_parser():
    candles = BinanceMarketDataClient.parse_klines(
        [[1, "10", "11", "9", "10.5", "100", 2]]
    )

    assert candles[0].open_time == 1
    assert candles[0].open == 10
    assert candles[0].close == 10.5
    assert candles[0].close_time == 2


def test_load_klines_from_binance_json_file(tmp_path):
    path = tmp_path / "binance.json"
    path.write_text('[[1, "10", "11", "9", "10.5", "100", 2]]', encoding="utf-8")

    candles = load_klines_from_file(str(path))

    assert candles[0].open_time == 1
    assert candles[0].close == 10.5


def test_load_klines_from_okx_json_file(tmp_path):
    path = tmp_path / "okx.json"
    path.write_text(
        '{"code":"0","data":[["3","12","13","11","12.5","100","1200","1200","1"],["1","10","11","9","10.5","90","945","945","1"]]}',
        encoding="utf-8",
    )

    candles = load_klines_from_file(str(path))

    assert [candle.open_time for candle in candles] == [1, 3]
    assert candles[1].close == 12.5


def test_load_klines_from_csv_file(tmp_path):
    path = tmp_path / "ohlcv.csv"
    path.write_text(
        "\n".join(
            [
                "timestamp,open,high,low,close,volume,close_time",
                "2024-01-01T00:00:00Z,10,11,9,10.5,100,2024-01-01T00:00:59Z",
                "1704067260,10.5,12,10,11.5,120,1704067319",
            ]
        ),
        encoding="utf-8",
    )

    candles = load_klines_from_file(str(path))

    assert [candle.open_time for candle in candles] == [1704067200000, 1704067260000]
    assert candles[0].close_time == 1704067259000
    assert candles[1].high == 12


def test_load_klines_from_binance_vision_csv_without_header(tmp_path):
    path = tmp_path / "BTCUSDT-1m-2024-01.csv"
    path.write_text(
        "\n".join(
            [
                "1704067200000,42283.58,42283.59,42250.00,42261.10,12.5,1704067259999,528242.0,123,6.0,253556.0,0",
                "1704067260000,42261.11,42295.00,42260.00,42290.00,10.0,1704067319999,422900.0,95,5.0,211450.0,0",
            ]
        ),
        encoding="utf-8",
    )

    candles = load_klines_from_file(str(path))

    assert [candle.open_time for candle in candles] == [1704067200000, 1704067260000]
    assert candles[0].close_time == 1704067259999
    assert candles[1].close == 42290.00


def test_load_klines_from_binance_vision_zip(tmp_path):
    path = tmp_path / "BTCUSDT-1m-2024-01.zip"
    csv_payload = "1704067200000,42283.58,42283.59,42250.00,42261.10,12.5,1704067259999,528242.0,123,6.0,253556.0,0\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BTCUSDT-1m-2024-01.csv", csv_payload)

    candles = load_klines_from_file(str(path))

    assert len(candles) == 1
    assert candles[0].open_time == 1704067200000
    assert candles[0].volume == 12.5


def test_load_klines_from_binance_vision_zip_normalizes_microsecond_timestamps(tmp_path):
    path = tmp_path / "BTCUSDT-1m-2025-01.zip"
    csv_payload = "1735689600000000,93425.99,93426.00,93400.00,93410.00,3.5,1735689659999000,326935.0,45,1.5,140115.0,0\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BTCUSDT-1m-2025-01.csv", csv_payload)

    candles = load_klines_from_file(str(path))

    assert len(candles) == 1
    assert candles[0].open_time == 1735689600000
    assert candles[0].close_time == 1735689659999


def test_load_klines_from_csv_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,open,close\n1,10,11\n", encoding="utf-8")

    try:
        load_klines_from_file(str(path))
    except MarketDataError as exc:
        assert "missing required column" in str(exc)
    else:
        raise AssertionError("Expected MarketDataError")


def test_okx_kline_parser_sorts_ascending():
    payload = {
        "data": [
            ["3", "12", "13", "11", "12.5", "100", "1200", "1200", "1"],
            ["1", "10", "11", "9", "10.5", "90", "945", "945", "1"],
        ]
    }

    candles = OkxMarketDataClient.parse_klines(payload)

    assert [candle.open_time for candle in candles] == [1, 3]
    assert candles[0].close == 10.5
    assert candles[1].volume == 100


def test_okx_symbol_formatter():
    assert format_okx_symbol("BTCUSDT") == "BTC-USDT"
    assert format_okx_symbol("ETH-USDT") == "ETH-USDT"


def test_market_data_factory_selects_okx():
    client = create_market_data_client("okx")

    assert isinstance(client, OkxMarketDataClient)


def test_market_data_factory_selects_bitget():
    client = create_market_data_client("bitget")

    assert isinstance(client, BitgetMarketDataClient)


def test_binance_market_data_factory_can_select_testnet_endpoint(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(url)
        return FakeResponse([[1, "10", "11", "9", "10.5", "100", 2]])

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)
    client = create_market_data_client("binance", use_testnet=True)

    candles = client.fetch_klines("BTCUSDT", "1m", limit=1)

    assert candles[0].close == 10.5
    assert calls == ["https://testnet.binance.vision/api/v3/klines"]


def test_bitget_kline_parser_sorts_ascending():
    payload = {
        "code": "00000",
        "data": [
            ["120000", "12", "13", "11", "12", "100", "1200", "1200"],
            ["60000", "11", "12", "10", "11", "90", "990", "990"],
        ],
    }

    candles = BitgetMarketDataClient.parse_klines(payload)

    assert [candle.open_time for candle in candles] == [60000, 120000]
    assert candles[0].close == 11
    assert candles[1].volume == 100


def test_bitget_fetch_historical_klines_walks_backwards_and_returns_ascending(monkeypatch):
    calls = []
    pages = [
        {
            "code": "00000",
            "data": [
                ["120000", "12", "13", "11", "12", "100", "1200", "1200"],
                ["60000", "11", "12", "10", "11", "90", "990", "990"],
            ],
        },
        {
            "code": "00000",
            "data": [["0", "10", "11", "9", "10", "80", "800", "800"]],
        },
    ]

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    candles = BitgetMarketDataClient().fetch_historical_klines(
        "BTCUSDT",
        "1m",
        start_time=0,
        end_time=120_000,
        limit_per_request=2,
    )

    assert [candle.open_time for candle in candles] == [0, 60_000, 120_000]
    assert calls[0][0] == "https://api.bitget.com/api/v2/spot/market/history-candles"
    assert calls[0][1]["granularity"] == "1min"
    assert calls[0][1]["endTime"] == "180000"
    assert calls[1][1]["endTime"] == "60000"


def test_bitget_fetch_klines_uses_explicit_4h_granularity(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return FakeResponse({"code": "00000", "data": [["0", "10", "11", "9", "10", "1"]]})

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    candles = BitgetMarketDataClient().fetch_klines("BTCUSDT", "4h", limit=1)

    assert candles[0].open_time == 0
    assert calls[0][1]["granularity"] == "4h"


def test_fetch_bitget_trading_rule_parses_required_fields(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "pricePrecision": "2",
                        "quantityPrecision": "6",
                        "minTradeAmount": "0.00001",
                        "minTradeUSDT": "5",
                    }
                ],
            }
        )

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    rule = fetch_bitget_trading_rule("BTCUSDT")

    assert rule["price_step"] == 0.01
    assert rule["quantity_step"] == 0.000001
    assert rule["min_quantity"] == 0.00001
    assert rule["min_notional"] == 5


def test_fetch_bitget_trading_rule_fails_closed_when_required_field_missing(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "pricePrecision": "2",
                        "quantityPrecision": "6",
                        "minTradeAmount": "0.00001",
                    }
                ],
            }
        )

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    with pytest.raises(MarketDataError, match="minTradeUSDT"):
        fetch_bitget_trading_rule("BTCUSDT")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_interval_to_milliseconds():
    assert interval_to_milliseconds("1m") == 60_000
    assert interval_to_milliseconds("4H") == 14_400_000


def test_aggregate_candles_to_larger_interval():
    candles = [
        Candle(open_time=0, open=10, high=12, low=9, close=11, volume=1, close_time=59_999),
        Candle(open_time=60_000, open=11, high=13, low=10, close=12, volume=2, close_time=119_999),
        Candle(open_time=300_000, open=12, high=15, low=11, close=14, volume=3, close_time=359_999),
    ]

    aggregated = aggregate_candles(candles, "5m")

    assert len(aggregated) == 2
    assert aggregated[0].open_time == 0
    assert aggregated[0].open == 10
    assert aggregated[0].high == 13
    assert aggregated[0].low == 9
    assert aggregated[0].close == 12
    assert aggregated[0].volume == 3
    assert aggregated[0].close_time == 119_999
    assert aggregated[1].open_time == 300_000


def test_binance_fetch_historical_klines_paginates_and_deduplicates(monkeypatch):
    calls = []
    pages = [
        [[0, "10", "11", "9", "10", "100", 59_999], [60_000, "11", "12", "10", "11", "100", 119_999]],
        [[60_000, "11", "12", "10", "11", "100", 119_999], [120_000, "12", "13", "11", "12", "100", 179_999]],
    ]

    def fake_get(url, params, timeout):
        calls.append(params)
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    candles = BinanceMarketDataClient().fetch_historical_klines(
        "BTCUSDT",
        "1m",
        start_time=0,
        end_time=120_000,
        limit_per_request=2,
    )

    assert [candle.open_time for candle in candles] == [0, 60_000, 120_000]
    assert calls[0]["startTime"] == 0
    assert calls[1]["startTime"] == 120_000


def test_okx_fetch_historical_klines_walks_backwards_and_returns_ascending(monkeypatch):
    calls = []
    pages = [
        {
            "code": "0",
            "data": [
                ["120000", "12", "13", "11", "12", "100", "1200", "1200", "1"],
                ["60000", "11", "12", "10", "11", "100", "1100", "1100", "1"],
            ],
        },
        {
            "code": "0",
            "data": [["0", "10", "11", "9", "10", "100", "1000", "1000", "1"]],
        },
    ]

    def fake_get(url, params, timeout):
        calls.append(params)
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("kxian_bot.market_data.requests.get", fake_get)

    candles = OkxMarketDataClient().fetch_historical_klines(
        "BTCUSDT",
        "1m",
        start_time=0,
        end_time=120_000,
        limit_per_request=2,
    )

    assert [candle.open_time for candle in candles] == [0, 60_000, 120_000]
    assert calls[0]["after"] == "180000"
    assert calls[1]["after"] == "60000"


def test_historical_klines_reject_invalid_time_range():
    try:
        BinanceMarketDataClient().fetch_historical_klines("BTCUSDT", "1m", start_time=2, end_time=1)
    except MarketDataError as exc:
        assert "start time" in str(exc)
    else:
        raise AssertionError("Expected MarketDataError")


def test_sqlite_replay_market_data_advances_cursor(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate([10, 9, 8, 9, 10, 11])
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    client = SQLiteReplayMarketDataClient(storage, "binance")

    first = client.fetch_klines("BTCUSDT", "1m", limit=3)
    second = client.fetch_klines("BTCUSDT", "1m", limit=3)
    exhausted = [client.fetch_klines("BTCUSDT", "1m", limit=3) for _ in range(3)]

    assert [candle.open_time for candle in first] == [0, 1, 2]
    assert [candle.open_time for candle in second] == [1, 2, 3]
    assert exhausted[-1] == []


def test_sqlite_replay_market_data_uses_latest_contiguous_candles(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_candles(
        [
            Candle(open_time=0, open=1, high=1, low=1, close=1, volume=1, close_time=59_999),
            Candle(open_time=1_704_067_200_000, open=10, high=10, low=10, close=10, volume=1, close_time=1_704_067_259_999),
            Candle(open_time=1_704_067_260_000, open=11, high=11, low=11, close=11, volume=1, close_time=1_704_067_319_999),
            Candle(open_time=1_704_067_320_000, open=12, high=12, low=12, close=12, volume=1, close_time=1_704_067_379_999),
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    client = SQLiteReplayMarketDataClient(storage, "binance")

    candles = client.fetch_klines("BTCUSDT", "1m", limit=3)

    assert [candle.open_time for candle in candles] == [1_704_067_200_000, 1_704_067_260_000, 1_704_067_320_000]


def test_latest_contiguous_candles_ignores_stale_outliers():
    candles = [
        Candle(open_time=0, open=1, high=1, low=1, close=1, volume=1, close_time=59_999),
        Candle(open_time=1_704_067_200_000, open=10, high=10, low=10, close=10, volume=1, close_time=1_704_067_259_999),
        Candle(open_time=1_704_067_260_000, open=11, high=11, low=11, close=11, volume=1, close_time=1_704_067_319_999),
    ]

    covered = latest_contiguous_candles(candles, "1m")

    assert [candle.open_time for candle in covered] == [1_704_067_200_000, 1_704_067_260_000]


def test_sqlite_replay_market_data_errors_when_empty(tmp_path):
    client = SQLiteReplayMarketDataClient(SQLiteStorage(tmp_path / "kxian.sqlite3"), "binance")

    try:
        client.fetch_klines("BTCUSDT", "1m")
    except MarketDataError as exc:
        assert "No local candles" in str(exc)
    else:
        raise AssertionError("Expected MarketDataError")
