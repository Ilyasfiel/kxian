from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_testnet_close_loop_runbook_stops_before_live():
    runbook = (ROOT / "docs" / "测试网闭环操作手册.md").read_text(encoding="utf-8")
    assert "Copy-Item .env.testnet.example .env" in runbook
    assert "KXIAN_MODE=testnet" in runbook
    assert "KXIAN_EXCHANGE=binance" in runbook
    assert "KXIAN_SYMBOL=BTCUSDT" in runbook
    assert "KXIAN_INTERVAL=4h" in runbook
    assert "kxian-bot launch-checklist --target testnet" in runbook
    assert "status=pass" in runbook
    assert "phase=testnet_observed_ready_for_live_review" in runbook
    assert "不要执行 `promote-profile-to-live`" in runbook
    assert "不要启动 live" in runbook
    assert "kxian-bot launch-checklist --target live" not in runbook


def test_change_log_records_testnet_candidate_scope():
    change_log = (ROOT / "变更记录.md").read_text(encoding="utf-8")
    assert "测试网闭环候选版本" in change_log
    assert "Binance testnet / BTCUSDT / 4h" in change_log
    assert "不执行 `promote-profile-to-live`" in change_log
    assert "不进行真实 live 下单" in change_log
