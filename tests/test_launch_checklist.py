from kxian_bot.config import RuntimeConfig
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.models import BacktestRunSummary, Candle, LoopEvent, StressBacktestRunSummary, WalkForwardRunSummary
from kxian_bot.storage import SQLiteStorage


SAMPLE_VALIDATION_EVIDENCE = {
    "status": "pass",
    "reason": "all_samples_passed",
    "sample_count": 2,
    "passed_samples": 2,
    "failed_samples": 0,
    "summary": {
        "total_trade_count": 70,
        "min_return_pct": 1.0,
        "worst_drawdown_pct": 7.0,
        "min_profit_factor": 1.3,
        "min_stress_pass_rate": 100.0,
        "min_walk_forward_pass_rate": 75.0,
    },
    "samples": [],
}


def test_launch_checklist_blocks_testnet_when_credentials_are_missing(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    config = RuntimeConfig(
        mode="paper",
        db_path=str(db_path),
        interval="4h",
        binance_api_key="",
        binance_api_secret="",
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["target_mode"] == "testnet"
    assert result["phase"] == "blocked_before_testnet"
    assert any("sandbox API credentials" in step for step in result["next_steps"])


def test_launch_checklist_passes_testnet_and_points_to_observation(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_testnet_dry_run"
    assert result["checks"][0]["name"] == "testnet_closed_loop_scope"
    assert result["checks"][1]["name"] == "readiness"
    assert result["checks"][2]["name"] == "testnet_profile"
    assert result["checks"][3]["name"] == "testnet_bounded_autotrade"
    assert result["checks"][3]["status"] == "pass"
    assert result["checks"][4]["name"] == "testnet_observation"
    assert result["checks"][5]["name"] == "testnet_order_observation"
    assert any("testnet-observe" in step for step in result["next_steps"])


def test_launch_checklist_allows_early_testnet_review_with_autotrade_off(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")
    check_status = {check["name"]: check["status"] for check in result["checks"]}

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_testnet_dry_run"
    assert check_status["testnet_closed_loop_scope"] == "pass"
    assert check_status["readiness"] == "pass"
    assert check_status["testnet_bounded_autotrade"] == "fail"
    assert any("KXIAN_ENABLE_TESTNET_AUTOTRADE=true" in step for step in result["next_steps"])


def test_launch_checklist_does_not_mark_final_phase_when_autotrade_is_off(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False)
    _record_observation(storage, execute_loop=True)
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")
    autotrade_check = next(check for check in result["checks"] if check["name"] == "testnet_bounded_autotrade")

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_bounded_testnet_order_observation"
    assert autotrade_check["details"]["failures"] == ["testnet_autotrade_disabled"]
    assert not any("ready_for_live_review" in step for step in result["next_steps"])


def test_launch_checklist_passes_final_testnet_review_after_both_observations(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False)
    _record_observation(storage, execute_loop=True)
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "pass"
    assert result["phase"] == "testnet_observed_ready_for_live_review"
    assert result["target_mode"] == "testnet"
    assert result["testnet_observation"]["non_ordering"]["cycles_completed"] == 6
    assert result["testnet_observation"]["bounded_order"]["cycles_completed"] == 6
    assert all(check["status"] == "pass" for check in result["checks"])
    assert any("do not promote to live" in step for step in result["next_steps"])


def test_launch_checklist_blocks_live_until_both_testnet_observations_and_live_profile_exist(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False)
    config = RuntimeConfig(
        mode="live",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_launch_checklist(config, storage, target_mode="live")
    check_status = {check["name"]: check["status"] for check in result["checks"]}

    assert result["status"] == "blocked"
    assert result["phase"] == "blocked_before_live"
    assert check_status["testnet_observation"] == "pass"
    assert check_status["testnet_order_observation"] == "fail"
    assert check_status["live_profile"] == "fail"
    assert any("--execute-loop" in step for step in result["next_steps"])


def test_launch_checklist_passes_live_after_profile_and_observations_exist(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False)
    _record_observation(storage, execute_loop=True)
    storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        updated_by="test",
    )
    config = RuntimeConfig(
        mode="live",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_launch_checklist(config, storage, target_mode="live")

    assert result["status"] == "pass"
    assert result["phase"] == "ready_for_bounded_live_loop"
    assert result["testnet_observation"]["bounded_order"]["execute_loop"] is True
    assert "KXIAN_LIVE_CONFIRMATION=LIVE:binance:BTCUSDT:4h" in result["next_steps"][0]


def test_launch_checklist_does_not_complete_testnet_when_order_observation_has_open_orders(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False)
    storage.record_loop_event(
        LoopEvent(
            loop_id="observe-open-order",
            iteration=1,
            status="idle",
            mode="testnet",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            message="testnet_observe_passed",
            payload={
                "kind": "testnet_observe",
                "observation_id": "open-order",
                "cycle": 1,
                "status": "pass",
                "reason": "",
                "duration_seconds": 0.1,
                "execute_loop": True,
                "order_lifecycle": {
                    "state": "open_orders",
                    "acceptable": False,
                    "open_order_count": 1,
                },
            },
        )
    )
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["reason"] == "testnet_launch_blocked"
    assert result["phase"] == "ready_for_bounded_testnet_order_observation"
    assert result["testnet_observation"]["bounded_order"]["status"] == "fail"
    assert result["testnet_observation"]["bounded_order"]["order_lifecycle"]["state"] == "open_orders"
    assert any("order-status" in step for step in result["next_steps"])
    assert any("cancel-order" in step for step in result["next_steps"])
    assert any("sync-fills" in step for step in result["next_steps"])
    assert any("preflight" in step for step in result["next_steps"])


def test_launch_checklist_requires_six_testnet_observation_cycles(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False, cycles=1)
    _record_observation(storage, execute_loop=True, cycles=1)
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_testnet_dry_run"
    assert result["testnet_observation"]["non_ordering"]["cycles_completed"] == 1
    assert any("testnet-observe --cycles 6" in step for step in result["next_steps"])


def test_launch_checklist_requires_order_lifecycle_for_bounded_observation(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False, cycles=6)
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id="observe-legacy-order",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": "legacy-order",
                    "cycle": cycle,
                    "status": "pass",
                    "reason": "",
                    "duration_seconds": 0.1,
                    "execute_loop": True,
                },
            )
        )
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_bounded_testnet_order_observation"
    assert result["testnet_observation"]["bounded_order"]["status"] == "pass"
    assert result["testnet_observation"]["bounded_order"]["order_lifecycle"] is None


def test_launch_checklist_final_phase_requires_non_ordering_observation(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=True, cycles=6)
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    assert result["phase"] == "ready_for_testnet_dry_run"
    assert any("testnet-observe --cycles 6" in step for step in result["next_steps"])


def test_launch_checklist_blocks_live_when_bounded_observation_lacks_lifecycle(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_ready_evidence(storage, mode="testnet")
    _record_observation(storage, execute_loop=False, cycles=6)
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id="observe-legacy-order",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": "legacy-order",
                    "cycle": cycle,
                    "status": "pass",
                    "reason": "",
                    "duration_seconds": 0.1,
                    "execute_loop": True,
                },
            )
        )
    config = RuntimeConfig(
        mode="live",
        db_path=str(db_path),
        market_data_source="sqlite",
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_launch_checklist(config, storage, target_mode="live")
    order_check = next(check for check in result["checks"] if check["name"] == "testnet_order_observation")

    assert result["status"] == "blocked"
    assert "missing_order_lifecycle" in order_check["details"]["failures"]


def test_launch_checklist_blocks_out_of_scope_testnet_target(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        exchange="okx",
        symbol="ETHUSDT",
        interval="1m",
        okx_api_key="key",
        okx_api_secret="secret",
        okx_api_passphrase="pass",
        enable_testnet_autotrade=True,
    )

    result = run_launch_checklist(config, storage, target_mode="testnet")

    assert result["status"] == "blocked"
    scope_check = next(check for check in result["checks"] if check["name"] == "testnet_closed_loop_scope")
    assert scope_check["details"]["failures"] == [
        "binance_exchange_required",
        "btcusdt_symbol_required",
        "4h_interval_required",
    ]


def _record_ready_evidence(storage: SQLiteStorage, mode: str) -> None:
    storage.upsert_candles(
        [
            Candle(open_time=i, open=10 + i, high=10 + i, low=10 + i, close=10 + i, volume=1, close_time=i + 1)
            for i in range(40)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    evidence = {"sample_validation": SAMPLE_VALIDATION_EVIDENCE}
    if mode == "testnet":
        evidence["promotion"] = {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"}
    if mode == "live":
        evidence["promotion"] = {"source_profile_key": "testnet:binance:BTCUSDT:4h", "target_mode": "live"}
        evidence["testnet_observation"] = {"non_ordering": {"status": "pass"}, "bounded_order": {"status": "pass"}}
    storage.upsert_strategy_profile(
        mode=mode,
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
        evidence=evidence,
        updated_by="test",
    )


def _record_backtest(storage: SQLiteStorage) -> None:
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="run-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            initial_equity=1000,
            final_equity=1020,
            return_pct=2.0,
            max_drawdown_pct=5.0,
            win_rate=50,
            profit_factor=1.5,
            trade_count=35,
            fees_paid=1,
            slippage_paid=0.5,
        )
    )


def _record_stress(storage: SQLiteStorage) -> None:
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="stress-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            scenario_count=5,
            passed_scenarios=5,
            failed_scenarios=0,
            pass_rate=100,
            worst_return_pct=1.0,
            worst_drawdown_pct=7.0,
            worst_profit_factor=1.3,
            min_trade_count=35,
            scenarios=[],
        )
    )


def _record_walk_forward(storage: SQLiteStorage) -> None:
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="walk-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            segment_count=3,
            passed_segments=2,
            failed_segments=1,
            pass_rate=75,
            total_trade_count=35,
            min_segment_trade_count=5,
            worst_return_pct=0.5,
            worst_drawdown_pct=5.0,
            worst_profit_factor=1.2,
            segments=[],
        )
    )


def _record_observation(storage: SQLiteStorage, execute_loop: bool, cycles: int = 6) -> None:
    observation_id = "order" if execute_loop else "check"
    for cycle in range(1, cycles + 1):
        storage.record_loop_event(
            LoopEvent(
                loop_id=f"observe-{observation_id}",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": observation_id,
                    "cycle": cycle,
                    "status": "pass",
                    "reason": "",
                    "duration_seconds": 0.1,
                    "execute_loop": execute_loop,
                    "order_lifecycle": {
                        "state": "healthy_idle" if execute_loop else "not_attempted",
                        "acceptable": True,
                        "open_order_count": 0,
                    },
                },
            )
        )
