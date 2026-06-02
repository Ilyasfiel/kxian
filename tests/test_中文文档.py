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

def test_bitget_gray_runbook_covers_manual_confirmation_and_single_canary():
    runbook = (ROOT / "docs" / "Bitget实盘灰度手册.md").read_text(encoding="utf-8")
    assert "KXIAN_EXCHANGE=bitget" in runbook
    assert "KXIAN_USE_TESTNET=false" in runbook
    assert "KXIAN_MAX_LIVE_ORDER_USDT=5" in runbook
    assert "KXIAN_LIVE_CONFIRMATION=LIVE:bitget:BTCUSDT:4h" in runbook
    assert "KXIAN_BITGET_API_PASSPHRASE" in runbook
    assert "提现" in runbook
    assert "IP 白名单" in runbook
    assert "approve-bitget-live-gray" in runbook
    assert "trade-loop --max-iterations 1 --sleep-seconds 0" in runbook
    assert "order-status --order-id" in runbook
    assert "cancel-order --order-id" in runbook
    assert "sync-fills" in runbook
    assert "launch-checklist --target live" in runbook
    assert "status=pass" in runbook
    assert "bitget-live-readiness" in runbook
    assert "will_submit_orders=false" in runbook
    assert "--include-account" in runbook
    assert "--sync-fills" in runbook
    assert "strategy_gate" in runbook
    assert "sample_validation_gate" in runbook
    assert "stress_gate" in runbook
    assert "walk_forward_gate" in runbook
    assert "不得执行 `approve-bitget-live-gray`" in runbook
    assert "没有 open/submitted/partial/unknown 真实订单" in runbook


def test_bitget_strategy_evidence_report_keeps_live_blocked():
    report = (ROOT / "docs" / "Bitget策略证据研究报告.md").read_text(encoding="utf-8")
    assert "blocked_before_bitget_live_canary" in report
    assert "策略证据不足" in report
    assert "prefilter_pass_count=0" in report
    assert "volatility_regime_pullback_reclaim" in report
    assert "adaptive_range_reclaim" in report
    assert "不得执行 `approve-bitget-live-gray`" in report
    assert "`trade-loop`" in report
    assert "`run-once`" in report
    assert "`test-order`" in report
    assert "`promote-profile-to-live`" in report
    assert "`cancel-order`" in report
    assert "open/submitted/partial/unknown" in report
    assert "不得把 `screen-samples` 的失败预筛结果包装成上线证据" in report
    assert "如果没有新的未触碰样本外窗口，不允许生成 live profile" in report
