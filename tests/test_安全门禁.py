from pathlib import Path


def test_gitignore_protects_runtime_secrets_and_evidence_artifacts():
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in gitignore
    assert "data/" in gitignore
    assert "*.sqlite3" in gitignore
    assert "artifacts/" in gitignore


def test_ci_runs_tests_compile_and_offline_smoke():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m pytest -v" in workflow
    assert "python -m compileall src/kxian_bot" in workflow
    assert "paper-dry-run --input-file sample_data/ohlcv_smoke.csv" in workflow
    assert "KXIAN_MODE: paper" in workflow
    assert "KXIAN_ALLOW_LIVE: \"false\"" in workflow
    assert "KXIAN_ENABLE_LIVE_AUTOTRADE: \"false\"" in workflow
    assert workflow.index("env:") < workflow.index("- name: Checkout")


def test_chinese_docs_record_testnet_acceptance_without_live_steps():
    record = Path("docs/测试网闭环验收记录.md").read_text(encoding="utf-8")
    runbook = Path("docs/测试网闭环操作手册.md").read_text(encoding="utf-8")

    assert "88878706-3996-4c69-876a-2275612d4f2d" in record
    assert "332ce95c-dcc2-4e8b-9f87-b335f72db2db" in record
    assert "exchange_order_id=9311985" in record
    assert "phase=testnet_observed_ready_for_live_review" in record
    assert "testnet-close-loop" in runbook
    assert "--evidence-out" in runbook
    assert "进入 bounded `--execute-loop` 下单观察前" in runbook
    assert "kxian-bot launch-checklist --target live" not in runbook
    assert "不要执行 `promote-profile-to-live`" in runbook
    for block in runbook.split("```powershell")[1:]:
        commands = block.split("```", 1)[0]
        assert "launch-checklist --target live" not in commands
        assert "promote-profile-to-live" not in commands
