from pathlib import Path


def test_gitignore_protects_runtime_secrets_and_evidence_artifacts():
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in gitignore
    assert "data/" in gitignore
    assert "*.sqlite3" in gitignore
    assert "artifacts/" in gitignore


def test_ci_runs_tests_compile_and_offline_smoke():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m playwright install --with-deps chromium" in workflow
    assert "python -m pytest -v" in workflow
    assert "python -m compileall src/kxian_bot" in workflow
    assert "paper-dry-run --input-file sample_data/ohlcv_smoke.csv" in workflow
    assert "- name: Secret scan" in workflow
    assert "git ls-files | grep -E" in workflow
    assert "git grep -IEn" in workflow
    assert "PRIVATE KEY" in workflow
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
    assert "测试网闭环" in runbook
    assert "--evidence-out" in runbook
    assert "进入 bounded `--execute-loop` 下单观察前" in runbook
    assert "kxian-bot launch-checklist --target live" not in runbook
    assert "不执行 `promote-profile-to-live`" in runbook
    for block in runbook.split("```powershell")[1:]:
        commands = block.split("```", 1)[0]
        assert "launch-checklist --target live" not in commands
        assert "promote-profile-to-live" not in commands


def test_chinese_release_notes_and_evidence_spec_record_boundaries():
    release_notes = Path("docs/测试网闭环版本发布说明.md").read_text(encoding="utf-8")
    evidence_spec = Path("docs/测试网证据包规范.md").read_text(encoding="utf-8")

    assert "v0.1.0-testnet" in release_notes
    assert "0c97babc2a2448e9f49dfc0108f83bbd4f81add6" in release_notes
    assert "GitHub CI" in release_notes
    assert "Success" in release_notes
    assert "不表示实盘可直接启动" in release_notes
    assert "不读取、回显或提交 `.env`" in release_notes
    assert "kxian.testnet.evidence.v1" in evidence_spec
    assert "live_ready=false" in evidence_spec
    assert "credentials.present" in evidence_spec
    assert "`audit` 用于复核证据生成环境和契约状态" in evidence_spec
    assert "content_sha256" in evidence_spec
    assert "testnet_evidence_contract_failures" in evidence_spec
    assert "X-MBX-APIKEY" in evidence_spec
    assert "signature" in evidence_spec
