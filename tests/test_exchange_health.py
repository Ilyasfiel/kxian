import requests

from kxian_bot.config import RuntimeConfig
from kxian_bot.exchange_health import run_exchange_health_check


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._payload


def test_exchange_health_passes_for_reachable_binance(monkeypatch):
    urls = []

    def fake_get(url, params, timeout):
        urls.append((url, params, timeout))
        if url.endswith("/api/v3/klines"):
            return FakeResponse([[1, "1", "1", "1", "1", "1", 2]])
        return FakeResponse({"serverTime": 123})

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(mode="testnet", exchange="binance", symbol="BTCUSDT", interval="1m")

    result = run_exchange_health_check(config, timeout_seconds=2)

    assert result["status"] == "pass"
    assert [check["status"] for check in result["checks"]] == ["pass", "pass"]
    assert urls[0][1] == {"symbol": "BTCUSDT", "interval": "1m", "limit": 1}
    assert urls[0][0] == "https://testnet.binance.vision/api/v3/klines"
    assert urls[1][0] == "https://testnet.binance.vision/api/v3/time"
    assert result["next_steps"] == ["exchange endpoints are reachable for the current configuration"]


def test_exchange_health_uses_binance_production_market_data_for_paper(monkeypatch):
    urls = []

    def fake_get(url, params, timeout):
        urls.append(url)
        return FakeResponse([[1, "1", "1", "1", "1", "1", 2]])

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")

    result = run_exchange_health_check(config, timeout_seconds=2)

    assert result["status"] == "pass"
    assert urls == ["https://api.binance.com/api/v3/klines"]


def test_exchange_health_reports_timeout_without_secret_values(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ConnectTimeout("timed out with no secrets")

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        binance_api_key="secret-key",
        binance_api_secret="secret-value",
    )

    result = run_exchange_health_check(config, timeout_seconds=1)

    assert result["status"] == "fail"
    assert {check["details"]["reason"] for check in result["checks"]} == {"exchange_timeout"}
    assert "verify this machine" in result["next_steps"][0]
    assert "secret-key" not in str(result)
    assert "secret-value" not in str(result)


def test_exchange_health_skips_public_market_data_for_sqlite(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(url)
        return FakeResponse({"serverTime": 123})

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(
        mode="paper",
        exchange="binance",
        market_data_source="sqlite",
    )

    result = run_exchange_health_check(config)

    checks = {check["name"]: check for check in result["checks"]}
    assert result["status"] == "pass"
    assert checks["public_market_data"]["details"]["required"] is False
    assert checks["trading_endpoint"]["details"]["required"] is False
    assert calls == []


def test_exchange_health_uses_okx_symbol_format(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return FakeResponse({"code": "0", "data": [["1"]]})

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(mode="testnet", exchange="okx", symbol="BTCUSDT", interval="1m")

    result = run_exchange_health_check(config)

    assert result["status"] == "pass"
    assert calls[0][1]["instId"] == "BTC-USDT"
    assert calls[1][0] == "https://www.okx.com/api/v5/public/time"


def test_exchange_health_uses_bitget_public_and_trading_endpoints(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        if url.endswith("/api/v2/spot/market/candles"):
            return FakeResponse({"code": "00000", "data": [["1", "1", "1", "1", "1", "1", "1", "1"]]})
        return FakeResponse({"code": "00000", "data": {"serverTime": "1700000000000"}})

    monkeypatch.setattr("kxian_bot.exchange_health.requests.get", fake_get)
    config = RuntimeConfig(mode="live", exchange="bitget", symbol="BTCUSDT", interval="4h")

    result = run_exchange_health_check(config)

    assert result["status"] == "pass"
    assert calls[0][0] == "https://api.bitget.com/api/v2/spot/market/candles"
    assert calls[0][1] == {"symbol": "BTCUSDT", "granularity": "4h", "limit": 1}
    assert calls[1][0] == "https://api.bitget.com/api/v2/public/time"
