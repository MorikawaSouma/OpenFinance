import time

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 60.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_submit_pipeline_run_returns_task_and_completes() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        resp = client.post(
            "/run/submit",
            json={
                "question": "Build a low-drawdown JP strategy and run backtest.",
                "market": "JP",
                "run_paper_trade": False,
                "experiments": 3,
                "session_id": "submit-pipeline-session",
            },
        )
        assert resp.status_code == 200
        task = resp.json()
        task_id = str(task.get("task_id") or "")
        assert task_id
        assert task.get("task_type") == "pipeline_run"

        done = _wait_task(client, task_id, timeout_s=120.0)
        assert done["status"] == "done"
        run_id = str((done.get("result_ref") or {}).get("run_id") or "")
        assert run_id
        pipeline_response = ((done.get("result") or {}).get("pipeline_response") or {})
        assert pipeline_response.get("strategy_validation", {}).get("schema_version") == "strategy_validation.v1"
        assert pipeline_response.get("strategy_compilation", {}).get("schema_version") == "strategy_compilation.v1"
        assert pipeline_response.get("strategy_compilation", {}).get("compilation_profile", {}).get("schema_version") == "strategy_compilation_profile.v1"
        assert pipeline_response.get("strategy_compilation", {}).get("compilation_policy", {}).get("schema_version") == "strategy_compilation_policy.v1"
        first_experiment = ((pipeline_response.get("experiments") or [{}])[0]) if isinstance(pipeline_response, dict) else {}
        assert ((first_experiment.get("backtest_request") or {}).get("evaluation_plan") or {}).get("schema_version") == "backtest_evaluation_plan.v1"
        assert ((first_experiment.get("backtest_request") or {}).get("evaluation_plan") or {}).get("request_input_profile", {}).get("schema_version") == "strategy_backtest_request_input_profile.v1"
    finally:
        settings.llm_force_stub = previous_force_stub


def test_submit_multi_market_compare_returns_task_and_diff_table() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/multi-market/compare/submit",
        json={
            "markets": ["US", "JP"],
            "strategy_id": "submit_mm",
            "strategy_version": "submit-mm-v1",
            "session_id": "submit-mm-session",
        },
    )
    assert resp.status_code == 200
    task = resp.json()
    task_id = str(task.get("task_id") or "")
    assert task_id
    assert task.get("task_type") == "multi_market.compare"

    done = _wait_task(client, task_id, timeout_s=120.0)
    assert done["status"] == "done"
    result = done.get("result") or {}
    assert isinstance(result.get("diff_table"), list)
    assert len(result.get("diff_table")) >= 2
    assert (result.get("strategy_validation") or {}).get("schema_version") == "strategy_validation.v1"
    assert (result.get("strategy_compilation") or {}).get("schema_version") == "strategy_compilation.v1"
    assert (result.get("strategy_compilation") or {}).get("compilation_profile", {}).get("schema_version") == "strategy_compilation_profile.v1"
    assert (result.get("strategy_compilation") or {}).get("compilation_policy", {}).get("schema_version") == "strategy_compilation_policy.v1"
    assert (result.get("outcome_summary") or {}).get("schema_version") == "strategy_compare_outcome_summary.v1"
    assert len(((result.get("outcome_summary") or {}).get("rows") or [])) >= 2
    assert (result.get("result_details") or {}).get("schema_version") == "strategy_compare_result_details.v1"
    assert len(((result.get("result_details") or {}).get("diff_rows") or [])) >= 2
    assert (((result.get("rows") or [])[0]).get("action_regime_details") or {}).get("schema_version") == "strategy_runtime_action_regime.v1"
    assert (((result.get("rows") or [])[0]).get("attribution_execution_details") or {}).get("schema_version") == "strategy_runtime_attribution_execution.v1"
    assert (((result.get("rows") or [])[0]).get("control_optimizer_details") or {}).get("schema_version") == "strategy_runtime_control_optimizer.v1"
    assert (((result.get("rows") or [])[0]).get("control_action_deep_details") or {}).get("schema_version") == "strategy_runtime_control_action_deep.v1"


def test_submit_robustness_returns_task_and_report_summary() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/robustness/run/submit",
        json={
            "market": "US",
            "strategy_id": "submit_rb",
            "strategy_version": "submit-rb-v1",
            "session_id": "submit-rb-session",
            "max_variants": 8,
        },
    )
    assert resp.status_code == 200
    task = resp.json()
    task_id = str(task.get("task_id") or "")
    assert task_id
    assert task.get("task_type") == "robustness.run"

    done = _wait_task(client, task_id, timeout_s=180.0)
    assert done["status"] == "done"
    result = done.get("result") or {}
    summary = (result.get("summary") or {}) if isinstance(result, dict) else {}
    assert str(result.get("robustness_id") or "").strip()
    assert isinstance(summary.get("variant_count"), int)
    assert (result.get("outcome_summary") or {}).get("schema_version") == "strategy_robustness_outcome_summary.v1"
    report = (result.get("report") or {}) if isinstance(result, dict) else {}
    assert (report.get("base_strategy_validation") or {}).get("schema_version") == "strategy_validation.v1"
    assert (report.get("base_strategy_compilation") or {}).get("schema_version") == "strategy_compilation.v1"
    assert (report.get("base_strategy_compilation") or {}).get("compilation_profile", {}).get("schema_version") == "strategy_compilation_profile.v1"
    assert (report.get("base_strategy_compilation") or {}).get("compilation_policy", {}).get("schema_version") == "strategy_compilation_policy.v1"
    assert (report.get("base_backtest_request") or {}).get("evaluation_plan", {}).get("schema_version") == "backtest_evaluation_plan.v1"
    assert (report.get("base_backtest_request") or {}).get("evaluation_plan", {}).get("request_input_profile", {}).get("schema_version") == "strategy_backtest_request_input_profile.v1"
    assert (report.get("outcome_summary") or {}).get("schema_version") == "strategy_robustness_outcome_summary.v1"
    assert (report.get("result_details") or {}).get("schema_version") == "strategy_robustness_result_details.v1"
    assert ((((report.get("variants") or [])[0]).get("action_regime_details")) or {}).get("schema_version") == "strategy_runtime_action_regime.v1"
    assert ((((report.get("variants") or [])[0]).get("attribution_execution_details")) or {}).get("schema_version") == "strategy_runtime_attribution_execution.v1"
    assert ((((report.get("variants") or [])[0]).get("control_optimizer_details")) or {}).get("schema_version") == "strategy_runtime_control_optimizer.v1"
    assert ((((report.get("variants") or [])[0]).get("control_action_deep_details")) or {}).get("schema_version") == "strategy_runtime_control_action_deep.v1"


def test_submit_orchestrator_returns_task_and_response() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        resp = client.post(
            "/orchestrator/run/submit",
            json={
                "question": "How should I think about downside risk in JP equities?",
                "active_agents": ["Strategy", "RiskManager"],
                "session_id": "submit-orch-session",
            },
        )
        assert resp.status_code == 200
        task = resp.json()
        task_id = str(task.get("task_id") or "")
        assert task_id
        assert task.get("task_type") == "orchestrator_run"

        done = _wait_task(client, task_id, timeout_s=60.0)
        assert done["status"] == "done"
        result = done.get("result") or {}
        assert str(result.get("trace_id") or "").strip()
        assert isinstance(result.get("summary"), str)
    finally:
        settings.llm_force_stub = previous_force_stub


def test_submit_factor_run_returns_task_and_report() -> None:
    client = TestClient(app)
    ds_resp = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "submit_factor_ds",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-03-31",
            "seed": 11,
        },
    )
    assert ds_resp.status_code == 200
    ds_task = ds_resp.json()
    ds_done = _wait_task(client, str(ds_task.get("task_id") or ""), timeout_s=90.0)
    assert ds_done["status"] == "done"
    dataset_version = str((ds_done.get("result") or {}).get("dataset_version") or "")
    assert dataset_version

    resp = client.post(
        "/workbench/factors/run/submit",
        json={
            "dataset_version": dataset_version,
            "factor_id": "submit_factor",
            "factor_version": "submit-factor-v1",
            "formula": "Rank(Ts_Mean(close, 20))",
            "inputs": ["close", "open"],
            "availability_lag": "0s",
            "failure_conditions": ["high_volatility", "range_bound_market"],
            "cost_sensitivity_level": "medium",
            "cost_sensitivity_rationale": "Moderate turnover expected.",
            "expected_horizon": "swing",
            "session_id": "submit-factor-session",
        },
    )
    assert resp.status_code == 200
    task = resp.json()
    task_id = str(task.get("task_id") or "")
    assert task_id
    assert task.get("task_type") == "factor.run"

    done = _wait_task(client, task_id, timeout_s=90.0)
    assert done["status"] == "done"
    result = done.get("result") or {}
    assert str(result.get("factor_version") or "").strip()
    assert isinstance(result.get("report"), dict)


def test_submit_factor_multi_market_compare_returns_task_and_rows() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/factor/multi_market_compare/submit",
        json={
            "factor_spec": {
                "factor_id": "submit_factor_mmc",
                "factor_version": "submit-factor-mmc-v1",
                "description": "submit compare factor",
                "inputs": [{"name": "close", "source": "market", "availability_lag": "0s"}],
                "params": {
                    "formula": "Rank(Ts_Mean(close, 20))",
                    "lookback_days": 20,
                    "decay_lags": 6,
                    "universe": ["AAA", "BBB", "CCC"],
                },
                "validation_plan": {
                    "in_sample_start": "2023-01-01",
                    "in_sample_end": "2023-12-31",
                    "out_sample_start": "2024-01-01",
                    "out_sample_end": "2024-12-31",
                },
                "failure_conditions": ["high_volatility"],
                "cost_sensitivity": {
                    "level": "medium",
                    "rationale": "Moderate turnover profile.",
                },
                "expected_horizon": "swing",
            },
            "markets": ["US", "JP"],
            "start": "2023-01-01",
            "end": "2024-12-31",
            "seed": 19,
            "session_id": "submit-factor-mmc-session",
        },
    )
    assert resp.status_code == 200
    task = resp.json()
    task_id = str(task.get("task_id") or "")
    assert task_id
    assert task.get("task_type") == "factor.multi_market_compare"

    done = _wait_task(client, task_id, timeout_s=120.0)
    assert done["status"] == "done"
    result = done.get("result") or {}
    rows = result.get("per_market_metrics") or []
    assert isinstance(rows, list)
    assert len(rows) >= 2
