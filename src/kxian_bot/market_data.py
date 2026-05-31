from __future__ import annotations

import csv
import io
import json
import re
import time
from typing import Any, Protocol
import zipfile

import requests

from kxian_bot.models import Candle, Exchange
from kxian_bot.storage import SQLiteStorage


class MarketDataError(RuntimeError):
    pass


class MarketDataClient(Protocol):
    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        ...

    def fetch_historical_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit_per_request: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> list[Candle]:
        ...

    @staticmethod
    def load_klines_from_file(path: str) -> list[Candle]:
        ...


_INTERVAL_PATTERN = re.compile(r"^(\d+)([smhHdDwW])(?:utc)?$")
_CSV_FIELD_ALIASES = {
    "open_time": ("open_time", "opentime", "open timestamp", "open_timestamp", "timestamp", "time", "date", "datetime"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
    "close_time": ("close_time", "closetime", "close timestamp", "close_timestamp"),
}


def interval_to_milliseconds(interval: str) -> int:
    match = _INTERVAL_PATTERN.match(interval.strip())
    if match is None:
        raise MarketDataError(f"Unsupported fixed interval: {interval}")

    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        "s": 1_000,
        "m": 60_000,
        "h": 3_600_000,
        "H": 3_600_000,
        "d": 86_400_000,
        "D": 86_400_000,
        "w": 604_800_000,
        "W": 604_800_000,
    }
    return amount * multipliers[unit]


def _validate_time_range(start_time: int, end_time: int) -> None:
    if start_time < 0 or end_time < 0:
        raise MarketDataError("Historical time range must use non-negative millisecond timestamps")
    if start_time >= end_time:
        raise MarketDataError("Historical start time must be earlier than end time")


def _clamp_limit(limit_per_request: int | None, maximum: int) -> int:
    if limit_per_request is None:
        return maximum
    if limit_per_request <= 0:
        raise MarketDataError("limit_per_request must be greater than zero")
    return min(limit_per_request, maximum)


def _clean_candles(candles: list[Candle], start_time: int, end_time: int) -> list[Candle]:
    by_open_time: dict[int, Candle] = {}
    for candle in candles:
        if candle.open_time < start_time or candle.open_time > end_time:
            continue
        if candle.close_time < candle.open_time:
            continue
        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            continue
        if candle.high < candle.low or candle.volume < 0:
            continue
        by_open_time[candle.open_time] = candle
    return [by_open_time[key] for key in sorted(by_open_time)]


def load_klines_from_file(path: str) -> list[Candle]:
    lower_path = path.lower()
    if lower_path.endswith(".zip"):
        return parse_zip_klines(path)
    if lower_path.endswith(".csv"):
        return parse_csv_klines(path)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "data" in payload:
        return OkxMarketDataClient.parse_klines(payload)
    if isinstance(payload, list):
        return BinanceMarketDataClient.parse_klines(payload)
    raise MarketDataError("Unsupported kline file format. Expected Binance JSON, OKX JSON, OHLCV CSV, or Binance Vision ZIP.")


def aggregate_candles(candles: list[Candle], interval: str) -> list[Candle]:
    if not candles:
        return []
    interval_ms = interval_to_milliseconds(interval)
    if interval_ms <= 0:
        raise MarketDataError("Aggregation interval must be positive")

    sorted_candles = sorted(candles, key=lambda candle: candle.open_time)
    buckets: dict[int, list[Candle]] = {}
    for candle in sorted_candles:
        bucket_open_time = (candle.open_time // interval_ms) * interval_ms
        buckets.setdefault(bucket_open_time, []).append(candle)

    output: list[Candle] = []
    for bucket_open_time in sorted(buckets):
        bucket = buckets[bucket_open_time]
        output.append(
            Candle(
                open_time=bucket_open_time,
                open=bucket[0].open,
                high=max(candle.high for candle in bucket),
                low=min(candle.low for candle in bucket),
                close=bucket[-1].close,
                volume=sum(candle.volume for candle in bucket),
                close_time=max(candle.close_time for candle in bucket),
            )
        )
    return output


def latest_contiguous_candles(candles: list[Candle], interval: str) -> list[Candle]:
    if not candles:
        return []

    interval_ms = interval_to_milliseconds(interval)
    if interval_ms <= 0:
        raise MarketDataError("Contiguous candle interval must be positive")

    covered = [candles[-1]]
    max_gap = interval_ms * 3
    previous_open = candles[-1].open_time
    for candle in reversed(candles[:-1]):
        gap = previous_open - candle.open_time
        if gap <= 0 or gap > max_gap:
            break
        covered.append(candle)
        previous_open = candle.open_time
    covered.reverse()
    return covered


def parse_zip_klines(path: str) -> list[Candle]:
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith(".csv") and not name.endswith("/"))
        if not names:
            raise MarketDataError("ZIP kline file must contain a CSV file")
        with archive.open(names[0]) as raw:
            handle = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            return _parse_csv_klines_from_handle(handle)


def parse_csv_klines(path: str) -> list[Candle]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return _parse_csv_klines_from_handle(handle)


def _parse_csv_klines_from_handle(handle) -> list[Candle]:
    reader = csv.reader(handle)
    rows = [row for row in reader if any((value or "").strip() for value in row)]
    if not rows:
        raise MarketDataError("CSV kline file must include at least one data row")

    if _looks_like_binance_vision_row(rows[0]):
        candles = [_parse_binance_vision_csv_row(row) for row in rows]
    else:
        field_map = _csv_field_map(rows[0])
        candles = [_parse_header_csv_row(row, rows[0], field_map) for row in rows[1:]]
    return sorted(candles, key=lambda candle: candle.open_time)


def _parse_header_csv_row(row: list[str], fieldnames: list[str], field_map: dict[str, str]) -> Candle:
    record = {field: row[index] if index < len(row) else "" for index, field in enumerate(fieldnames)}
    return Candle(
        open_time=_parse_timestamp(record[field_map["open_time"]]),
        open=float(record[field_map["open"]]),
        high=float(record[field_map["high"]]),
        low=float(record[field_map["low"]]),
        close=float(record[field_map["close"]]),
        volume=float(record[field_map["volume"]]),
        close_time=(
            _parse_timestamp(record[field_map["close_time"]])
            if field_map.get("close_time")
            else _parse_timestamp(record[field_map["open_time"]])
        ),
    )


def _looks_like_binance_vision_row(row: list[str]) -> bool:
    if len(row) < 7:
        return False
    try:
        _parse_timestamp(row[0])
        float(row[1])
        float(row[2])
        float(row[3])
        float(row[4])
        float(row[5])
        _parse_timestamp(row[6])
    except (MarketDataError, ValueError):
        return False
    return True


def _parse_binance_vision_csv_row(row: list[str]) -> Candle:
    if len(row) < 7:
        raise MarketDataError("Binance Vision CSV rows must contain at least 7 columns")
    return Candle(
        open_time=_parse_timestamp(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=_parse_timestamp(row[6]),
    )


def _csv_field_map(fieldnames: list[str]) -> dict[str, str]:
    normalized = {_normalize_field_name(name): name for name in fieldnames}
    output: dict[str, str] = {}
    for canonical, aliases in _CSV_FIELD_ALIASES.items():
        for alias in aliases:
            key = _normalize_field_name(alias)
            if key in normalized:
                output[canonical] = normalized[key]
                break
        if canonical != "close_time" and canonical not in output:
            raise MarketDataError(f"CSV kline file is missing required column: {canonical}")
    return output


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _parse_timestamp(value: str) -> int:
    text = str(value).strip()
    if not text:
        raise MarketDataError("CSV kline timestamp cannot be empty")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        if "." not in text:
            return _normalize_epoch_timestamp(int(text))
        return _normalize_epoch_timestamp(float(text))
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError as exc:
        raise MarketDataError(f"Unsupported CSV timestamp: {value}") from exc


def _normalize_epoch_timestamp(value: int | float) -> int:
    if value >= 10_000_000_000_000_000:
        return int(value / 1_000_000)
    if value >= 10_000_000_000_000:
        return int(value / 1_000)
    if value > 10_000_000_000:
        return int(value)
    return int(value * 1000)


class BinanceMarketDataClient:
    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"
    MAX_HISTORICAL_LIMIT = 1000

    def __init__(self, use_testnet: bool = False) -> None:
        self.base_url = self.TESTNET_URL if use_testnet else self.BASE_URL

    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        return self._request_klines(symbol, interval, limit=limit)

    def fetch_historical_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit_per_request: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> list[Candle]:
        _validate_time_range(start_time, end_time)
        interval_ms = interval_to_milliseconds(interval)
        limit = _clamp_limit(limit_per_request, self.MAX_HISTORICAL_LIMIT)
        cursor = start_time
        candles_by_open_time: dict[int, Candle] = {}

        while cursor <= end_time:
            page = self._request_klines(
                symbol,
                interval,
                limit=limit,
                start_time=cursor,
                end_time=end_time,
            )
            page = _clean_candles(page, start_time, end_time)
            if not page:
                break

            for candle in page:
                candles_by_open_time[candle.open_time] = candle

            last_open_time = page[-1].open_time
            if last_open_time >= end_time:
                break

            next_cursor = last_open_time + interval_ms
            cursor = next_cursor if next_cursor > cursor else cursor + interval_ms

            if len(page) < limit:
                break
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        return [candles_by_open_time[key] for key in sorted(candles_by_open_time)]

    def _request_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        try:
            response = requests.get(
                f"{self.base_url}/api/v3/klines",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MarketDataError(f"Failed to fetch klines from Binance: {exc}") from exc
        return self.parse_klines(response.json())

    @staticmethod
    def load_klines_from_file(path: str) -> list[Candle]:
        return load_klines_from_file(path)

    @staticmethod
    def parse_klines(payload: list[list[Any]]) -> list[Candle]:
        candles: list[Candle] = []
        for item in payload:
            candles.append(
                Candle(
                    open_time=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time=int(item[6]),
                )
            )
        return candles


def format_okx_symbol(symbol: str) -> str:
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT"
    return symbol


class OkxMarketDataClient:
    BASE_URL = "https://www.okx.com"
    MAX_HISTORICAL_LIMIT = 300

    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        try:
            response = requests.get(
                f"{self.BASE_URL}/api/v5/market/candles",
                params={"instId": format_okx_symbol(symbol), "bar": interval, "limit": limit},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MarketDataError(f"Failed to fetch klines from OKX: {exc}") from exc
        payload = response.json()
        self._raise_for_okx_error(payload)
        return self.parse_klines(payload)

    def fetch_historical_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit_per_request: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> list[Candle]:
        _validate_time_range(start_time, end_time)
        interval_ms = interval_to_milliseconds(interval)
        limit = _clamp_limit(limit_per_request, self.MAX_HISTORICAL_LIMIT)
        after = end_time + interval_ms
        candles_by_open_time: dict[int, Candle] = {}

        while after > start_time:
            page = self._request_history_klines(symbol, interval, limit=limit, after=after)
            page = _clean_candles(page, start_time, end_time)
            if not page:
                break

            for candle in page:
                candles_by_open_time[candle.open_time] = candle

            earliest_open_time = page[0].open_time
            if earliest_open_time <= start_time:
                break
            after = earliest_open_time

            if len(page) < limit:
                break
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        return [candles_by_open_time[key] for key in sorted(candles_by_open_time)]

    def _request_history_klines(self, symbol: str, interval: str, limit: int, after: int) -> list[Candle]:
        try:
            response = requests.get(
                f"{self.BASE_URL}/api/v5/market/history-candles",
                params={
                    "instId": format_okx_symbol(symbol),
                    "bar": interval,
                    "limit": limit,
                    "after": str(after),
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MarketDataError(f"Failed to fetch historical klines from OKX: {exc}") from exc
        payload = response.json()
        self._raise_for_okx_error(payload)
        return self.parse_klines(payload, confirmed_only=True)

    @staticmethod
    def load_klines_from_file(path: str) -> list[Candle]:
        return load_klines_from_file(path)

    @staticmethod
    def parse_klines(payload: dict[str, Any], confirmed_only: bool = False) -> list[Candle]:
        candles: list[Candle] = []
        for item in payload.get("data", []):
            if confirmed_only and len(item) > 8 and item[8] != "1":
                continue
            timestamp = int(item[0])
            candles.append(
                Candle(
                    open_time=timestamp,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time=timestamp,
                )
            )
        return sorted(candles, key=lambda candle: candle.open_time)

    @staticmethod
    def _raise_for_okx_error(payload: dict[str, Any]) -> None:
        if str(payload.get("code", "0")) != "0":
            raise MarketDataError(f"OKX returned error: {payload.get('msg', 'unknown_error')}")


class SQLiteReplayMarketDataClient:
    def __init__(self, storage: SQLiteStorage, exchange: Exchange) -> None:
        self.storage = storage
        self.exchange = exchange
        self._cursor_by_market: dict[tuple[str, str], int] = {}

    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        candles = latest_contiguous_candles(self.storage.load_candles(self.exchange, symbol, interval), interval)
        if not candles:
            raise MarketDataError(
                f"No local candles for {self.exchange} {symbol} {interval}. "
                "Run download-history first or import sample data."
            )
        key = (symbol, interval)
        cursor = self._cursor_by_market.get(key, min(max(limit, 1), len(candles)))
        if cursor > len(candles):
            return []
        window = candles[max(0, cursor - max(limit, 1)) : cursor]
        self._cursor_by_market[key] = cursor + 1
        return window

    def fetch_historical_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit_per_request: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> list[Candle]:
        _validate_time_range(start_time, end_time)
        return self.storage.load_candles(self.exchange, symbol, interval, start_time=start_time, end_time=end_time)

    @staticmethod
    def load_klines_from_file(path: str) -> list[Candle]:
        return load_klines_from_file(path)


def create_market_data_client(exchange: Exchange, use_testnet: bool = False) -> MarketDataClient:
    if exchange == "binance":
        return BinanceMarketDataClient(use_testnet=use_testnet)
    if exchange == "okx":
        return OkxMarketDataClient()
    raise MarketDataError(f"Unsupported exchange: {exchange}")


def create_sqlite_replay_market_data_client(storage: SQLiteStorage, exchange: Exchange) -> MarketDataClient:
    return SQLiteReplayMarketDataClient(storage, exchange)
