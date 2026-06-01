import pytest

from kxian_bot.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def isolate_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


def test_defaults_to_paper_mode(monkeypatch):
    monkeypatch.delenv("KXIAN_MODE", raising=False)
    monkeypatch.delenv("KXIAN_ALLOW_LIVE", raising=False)
    monkeypatch.delenv("KXIAN_EXCHANGE", raising=False)
    monkeypatch.delenv("KXIAN_STOP_LOSS_PCT", raising=False)
    monkeypatch.delenv("KXIAN_TAKE_PROFIT_PCT", raising=False)
    monkeypatch.delenv("KXIAN_TRAILING_STOP_PCT", raising=False)

    config = load_config()

    assert config.mode == "paper"
    assert config.allow_live is False
    assert config.exchange == "binance"
    assert config.market_data_source == "exchange"
    assert config.strategy == "moving_average_cross"
    assert config.enable_testnet_autotrade is False
    assert config.enable_live_autotrade is False
    assert config.live_confirmation == ""
    assert config.live_credentials_confirmed is False
    assert config.max_live_order_usdt == 50
    assert config.require_strategy_gate is True
    assert config.require_sample_validation_gate is True
    assert config.min_gate_trades == 30
    assert config.loop_lock_stale_seconds == 120
    assert config.max_consecutive_loop_errors == 3
    assert config.fee_rate == 0.001
    assert config.slippage_rate == 0.0005
    assert config.stop_loss_pct == 2.0
    assert config.take_profit_pct == 4.0
    assert config.trailing_stop_pct == 2.0


def test_config_tests_ignore_outer_kxian_environment(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "paper")
    monkeypatch.setenv("KXIAN_ENABLE_TESTNET_AUTOTRADE", "true")

    config = load_config()

    assert config.mode == "paper"
    assert config.enable_testnet_autotrade is True


def test_live_mode_requires_explicit_allow(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "false")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_ALLOW_LIVE" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for live mode without allow flag")


def test_live_execution_requires_explicit_autotrade_when_dry_run_disabled(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_LIVE_DRY_RUN", "false")
    monkeypatch.setenv("KXIAN_USE_TESTNET", "false")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("KXIAN_INTERVAL", "4h")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_ENABLE_LIVE_AUTOTRADE" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for disabled live autotrade")


def test_live_execution_requires_confirmation_phrase(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_LIVE_DRY_RUN", "false")
    monkeypatch.setenv("KXIAN_ENABLE_LIVE_AUTOTRADE", "true")
    monkeypatch.setenv("KXIAN_USE_TESTNET", "false")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("KXIAN_INTERVAL", "4h")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_LIVE_CONFIRMATION=LIVE:binance:BTCUSDT:4h" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for missing live confirmation")


def test_live_execution_loads_when_all_live_confirmations_are_present(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_LIVE_DRY_RUN", "false")
    monkeypatch.setenv("KXIAN_ENABLE_LIVE_AUTOTRADE", "true")
    monkeypatch.setenv("KXIAN_USE_TESTNET", "false")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("KXIAN_INTERVAL", "4h")
    monkeypatch.setenv("KXIAN_LIVE_CONFIRMATION", "LIVE:binance:BTCUSDT:4h")
    monkeypatch.setenv("KXIAN_LIVE_CREDENTIALS_CONFIRMED", "true")
    monkeypatch.setenv("KXIAN_MAX_LIVE_ORDER_USDT", "25")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    config = load_config()

    assert config.mode == "live"
    assert config.live_dry_run is False
    assert config.enable_live_autotrade is True
    assert config.use_testnet is False
    assert config.live_confirmation == "LIVE:binance:BTCUSDT:4h"
    assert config.live_credentials_confirmed is True
    assert config.max_live_order_usdt == 25


def test_live_execution_requires_production_credential_confirmation(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_LIVE_DRY_RUN", "false")
    monkeypatch.setenv("KXIAN_ENABLE_LIVE_AUTOTRADE", "true")
    monkeypatch.setenv("KXIAN_USE_TESTNET", "false")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("KXIAN_INTERVAL", "4h")
    monkeypatch.setenv("KXIAN_LIVE_CONFIRMATION", "LIVE:binance:BTCUSDT:4h")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_LIVE_CREDENTIALS_CONFIRMED=true" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for unconfirmed production credentials")


def test_testnet_mode_requires_credentials_but_not_live_allow(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "testnet")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "false")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    config = load_config()

    assert config.mode == "testnet"
    assert config.allow_live is False
    assert config.use_testnet is True
    assert config.enable_testnet_autotrade is False


def test_testnet_autotrade_requires_explicit_flag(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "testnet")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")
    monkeypatch.setenv("KXIAN_ENABLE_TESTNET_AUTOTRADE", "true")

    config = load_config()

    assert config.enable_testnet_autotrade is True


def test_strategy_gate_thresholds_are_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_REQUIRE_STRATEGY_GATE", "false")
    monkeypatch.setenv("KXIAN_REQUIRE_SAMPLE_VALIDATION_GATE", "false")
    monkeypatch.setenv("KXIAN_MIN_GATE_TRADES", "100")
    monkeypatch.setenv("KXIAN_MIN_GATE_RETURN_PCT", "2.5")
    monkeypatch.setenv("KXIAN_MAX_GATE_DRAWDOWN_PCT", "8")
    monkeypatch.setenv("KXIAN_MIN_GATE_PROFIT_FACTOR", "1.3")

    config = load_config()

    assert config.require_strategy_gate is False
    assert config.require_sample_validation_gate is False
    assert config.min_gate_trades == 100
    assert config.min_gate_return_pct == 2.5
    assert config.max_gate_drawdown_pct == 8
    assert config.min_gate_profit_factor == 1.3


def test_strategy_name_is_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_STRATEGY", "regime_breakout")

    config = load_config()

    assert config.strategy == "regime_breakout"


def test_research_only_short_strategy_name_is_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_STRATEGY", "downtrend_breakdown_short")

    config = load_config()

    assert config.strategy == "downtrend_breakdown_short"


def test_volatility_breakout_trend_strategy_name_is_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_STRATEGY", "volatility_breakout_trend")

    config = load_config()

    assert config.strategy == "volatility_breakout_trend"


def test_regime_filtered_ma_cross_strategy_name_is_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_STRATEGY", "regime_filtered_ma_cross")

    config = load_config()

    assert config.strategy == "regime_filtered_ma_cross"


def test_invalid_strategy_name_is_rejected(monkeypatch):
    monkeypatch.setenv("KXIAN_STRATEGY", "coin_flip")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_STRATEGY" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for unsupported strategy")


def test_loop_lock_stale_seconds_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_LOOP_LOCK_STALE_SECONDS", "45")

    config = load_config()

    assert config.loop_lock_stale_seconds == 45


def test_loop_circuit_breaker_threshold_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_MAX_CONSECUTIVE_LOOP_ERRORS", "5")

    config = load_config()

    assert config.max_consecutive_loop_errors == 5


def test_protective_exit_thresholds_are_configurable(monkeypatch):
    monkeypatch.setenv("KXIAN_STOP_LOSS_PCT", "3.5")
    monkeypatch.setenv("KXIAN_TAKE_PROFIT_PCT", "7.25")
    monkeypatch.setenv("KXIAN_TRAILING_STOP_PCT", "4.5")

    config = load_config()

    assert config.stop_loss_pct == 3.5
    assert config.take_profit_pct == 7.25
    assert config.trailing_stop_pct == 4.5


def test_binance_testnet_mode_requires_testnet_endpoint(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "testnet")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.setenv("KXIAN_USE_TESTNET", "false")
    monkeypatch.setenv("KXIAN_BINANCE_API_KEY", "key")
    monkeypatch.setenv("KXIAN_BINANCE_API_SECRET", "secret")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_USE_TESTNET" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for Binance testnet without testnet endpoint")


def test_loads_values_from_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KXIAN_SYMBOL=ETHUSDT\nKXIAN_EXCHANGE=okx\nKXIAN_FEE_RATE=0.002\nKXIAN_SLIPPAGE_RATE=0.001\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KXIAN_SYMBOL", raising=False)
    monkeypatch.delenv("KXIAN_EXCHANGE", raising=False)
    monkeypatch.delenv("KXIAN_MODE", raising=False)
    monkeypatch.delenv("KXIAN_ALLOW_LIVE", raising=False)

    config = load_config()

    assert config.symbol == "ETHUSDT"
    assert config.exchange == "okx"
    assert config.fee_rate == 0.002
    assert config.slippage_rate == 0.001


def test_invalid_exchange_rejected(monkeypatch):
    monkeypatch.setenv("KXIAN_EXCHANGE", "coinbase")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_EXCHANGE" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for unsupported exchange")


def test_sqlite_market_data_source_config(monkeypatch):
    monkeypatch.setenv("KXIAN_MARKET_DATA_SOURCE", "sqlite")

    config = load_config()

    assert config.market_data_source == "sqlite"


def test_invalid_market_data_source_rejected(monkeypatch):
    monkeypatch.setenv("KXIAN_MARKET_DATA_SOURCE", "websocket")

    try:
        load_config()
    except ConfigError as exc:
        assert "KXIAN_MARKET_DATA_SOURCE" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for unsupported market data source")


def test_live_binance_requires_credentials(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_EXCHANGE", "binance")
    monkeypatch.delenv("KXIAN_BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("KXIAN_BINANCE_API_SECRET", raising=False)

    try:
        load_config()
    except ConfigError as exc:
        assert "Binance credentials" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for missing Binance credentials")


def test_live_okx_requires_passphrase(monkeypatch):
    monkeypatch.setenv("KXIAN_MODE", "live")
    monkeypatch.setenv("KXIAN_ALLOW_LIVE", "true")
    monkeypatch.setenv("KXIAN_EXCHANGE", "okx")
    monkeypatch.setenv("KXIAN_OKX_API_KEY", "key")
    monkeypatch.setenv("KXIAN_OKX_API_SECRET", "secret")
    monkeypatch.delenv("KXIAN_OKX_API_PASSPHRASE", raising=False)

    try:
        load_config()
    except ConfigError as exc:
        assert "OKX credentials" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for missing OKX passphrase")
