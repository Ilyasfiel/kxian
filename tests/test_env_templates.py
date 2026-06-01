from pathlib import Path


def test_testnet_env_template_contains_no_secrets_and_keeps_live_disabled():
    template = Path(".env.testnet.example").read_text(encoding="utf-8")

    assert "KXIAN_MODE=testnet" in template
    assert "KXIAN_USE_TESTNET=true" in template
    assert "KXIAN_BINANCE_API_KEY=\n" in template
    assert "KXIAN_BINANCE_API_SECRET=\n" in template
    assert "KXIAN_ENABLE_TESTNET_AUTOTRADE=false" in template
    assert "KXIAN_ALLOW_LIVE=false" in template
    assert "KXIAN_ENABLE_LIVE_AUTOTRADE=false" in template
    assert "KXIAN_LIVE_CREDENTIALS_CONFIRMED=false" in template
    assert "your_testnet_key" not in template
    assert "your_testnet_secret" not in template
