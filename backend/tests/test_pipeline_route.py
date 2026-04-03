from fastapi.testclient import TestClient

from openfinance.agents.catalog import build_default_agents
from openfinance.api.main import app


def test_expert_agents_present() -> None:
    agents = build_default_agents()
    for name in ["Buffett", "Soros", "Simons", "Dalio", "Kahneman", "Factor"]:
        assert name in agents


def test_plan_route_generates_structured_plan() -> None:
    client = TestClient(app)
    r = client.post(
        "/plan",
        json={
            "question": "请给我一个趋势策略，目标高夏普低回撤",
            "market": "JP",
        },
    )
    assert r.status_code == 200
    payload = r.json()
    plan = payload["plan"]
    assert payload["plan_id"].startswith("plan_")
    assert len(plan["candidate_factors"]) >= 3
    assert len(plan["experiment_matrix"]) >= 3
    assert "objectives" in plan and len(plan["objectives"]) >= 1
    for section in ["value", "macro", "stats", "behavior"]:
        assert section in plan
        assert isinstance(plan[section], dict)
        assert len(plan[section].get("hypotheses", [])) >= 1
        for key in ["evidence_queries", "evaluation_actions", "risks"]:
            assert isinstance(plan[section].get(key), list)


def test_plans_diverge_for_different_questions() -> None:
    client = TestClient(app)
    questions = [
        ("趋势策略，偏高夏普", "US"),
        ("价值策略，低换手", "US"),
        ("风险平价股债配置，低回撤", "JP"),
    ]
    plans = []
    for question, market in questions:
        resp = client.post("/plan", json={"question": question, "market": market})
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        for section in ["value", "macro", "stats", "behavior"]:
            assert len((plan.get(section) or {}).get("hypotheses", [])) >= 1
        plans.append(plan)

    first_factors = {plan["candidate_factors"][0]["factor_id"] for plan in plans}
    first_variants = {plan["experiment_matrix"][0]["variant_id"] for plan in plans}
    assert len(first_factors) >= 3
    assert len(first_variants) >= 3


def test_run_from_plan_multi_experiments_and_reproducible_metrics() -> None:
    client = TestClient(app)
    plan_resp = client.post(
        "/plan",
        json={"question": "请设计趋势策略并比较三组实验参数", "market": "JP"},
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["plan_id"]

    r1 = client.post("/run", json={"plan_id": plan_id, "run_paper_trade": False})
    r2 = client.post("/run", json={"plan_id": plan_id, "run_paper_trade": False})
    assert r1.status_code == 200
    assert r2.status_code == 200
    p1 = r1.json()
    p2 = r2.json()

    assert len(p1["experiments"]) >= 3
    assert len(p1["comparison_table"]) >= 3
    assert p1["dataset_version"] == p2["dataset_version"]
    assert p1["plan_id"] == plan_id == p2["plan_id"]
    assert "factor_report" in p1
    assert "ic_mean" in p1["factor_report"]
    assert p1["factor_artifact_path"]
    assert p1["strategy_spec"]["schema_version"] == "strategy_spec.v1"
    assert p1["strategy_spec"]["simulation_only"] is True
    assert p1["strategy_validation"]["schema_version"] == "strategy_validation.v1"
    assert p1["strategy_validation"]["next_output"] == "BacktestRequest"
    assert p1["strategy_validation"]["compile_ready"] is True
    assert p1["strategy_compilation"]["schema_version"] == "strategy_compilation.v1"
    assert p1["strategy_compilation"]["executable_object"] == "BacktestRequest"
    assert p1["strategy_compilation"]["compilation_profile"]["schema_version"] == "strategy_compilation_profile.v1"
    assert p1["strategy_compilation"]["compilation_policy"]["schema_version"] == "strategy_compilation_policy.v1"
    assert p1["strategy_compilation"]["compilation_policy"]["rule_surface_id"] == "strategy_compilation.backtest.v1"
    assert any("rule_id" in row for row in p1["strategy_compilation"]["compilation_policy"]["checks"])

    m1 = {row["variant_id"]: row["metrics"] for row in p1["experiments"]}
    m2 = {row["variant_id"]: row["metrics"] for row in p2["experiments"]}
    assert m1 == m2
    f1 = {row["variant_id"]: row["factor_report"] for row in p1["experiments"]}
    f2 = {row["variant_id"]: row["factor_report"] for row in p2["experiments"]}
    assert f1 == f2

    lookbacks = {row["strategy_spec"]["lookback_days"] for row in p1["experiments"]}
    families = {row["strategy_family"] for row in p1["experiments"]}
    assert len(lookbacks) >= 2
    assert len(families) >= 2
    assert all("decay_curve" in row["factor_report"] for row in p1["experiments"])
    assert all("circuit_breaker" in row["strategy_spec"] for row in p1["experiments"])
    assert all("failure_regimes" in row["strategy_spec"] for row in p1["experiments"])
    assert all("execution_model" in row["backtest_request"] for row in p1["experiments"])
    assert all(
        ((row["backtest_request"].get("evaluation_plan") or {}).get("schema_version"))
        == "backtest_evaluation_plan.v1"
        for row in p1["experiments"]
    )
    assert all(
        ((row["backtest_request"].get("evaluation_plan") or {}).get("request_input_profile") or {}).get("schema_version")
        == "strategy_backtest_request_input_profile.v1"
        for row in p1["experiments"]
    )
    assert all("strategy_decision" in row for row in p1["experiments"])
    assert all((row.get("strategy_decision") or {}).get("schema_version") == "strategy_decision.v1" for row in p1["experiments"])
    assert all((row.get("strategy_decision") or {}).get("selected") for row in p1["experiments"])
    assert all((row.get("strategy_validation") or {}).get("schema_version") == "strategy_validation.v1" for row in p1["experiments"])
    assert all((row.get("strategy_validation") or {}).get("compile_ready") is True for row in p1["experiments"])
    assert all((row.get("strategy_compilation") or {}).get("schema_version") == "strategy_compilation.v1" for row in p1["experiments"])
    assert all(
        ((row.get("strategy_compilation") or {}).get("compilation_profile") or {}).get("schema_version") == "strategy_compilation_profile.v1"
        for row in p1["experiments"]
    )
    assert all(
        ((row.get("strategy_compilation") or {}).get("compilation_policy") or {}).get("schema_version") == "strategy_compilation_policy.v1"
        for row in p1["experiments"]
    )

    step_names = [s["name"] for s in p1["steps"]]
    for name in ["plan.compose", "evidence.pack", "factor.define", "strategy.compose", "backtest.run", "risk.explain"]:
        assert name in step_names


def test_pipeline_run_chain_compat() -> None:
    client = TestClient(app)
    r = client.post(
        "/pipeline/run",
        json={
            "question": "为什么最近日经波动变大？给我低回撤配置建议",
            "market": "JP",
            "max_drawdown_target": 0.1,
            "run_paper_trade": True,
            "experiments": 3,
        },
    )
    assert r.status_code == 200
    payload = r.json()
    for k in ["trace_id", "plan_id", "evidence_pack_id", "factor_version", "strategy_version", "dataset_version", "run_id"]:
        assert k in payload and payload[k]
    assert payload["strategy_spec"]["schema_version"] == "strategy_spec.v1"
    assert payload.get("strategy_decision")
    assert payload["strategy_decision"]["schema_version"] == "strategy_decision.v1"
    assert (payload.get("strategy_decision") or {}).get("selected")
    assert payload["strategy_validation"]["schema_version"] == "strategy_validation.v1"
    assert payload["strategy_validation"]["compile_ready"] is True
    assert payload["strategy_compilation"]["schema_version"] == "strategy_compilation.v1"
    assert payload["strategy_compilation"]["executable_object"] == "BacktestRequest"
    assert payload["strategy_compilation"]["compilation_profile"]["schema_version"] == "strategy_compilation_profile.v1"
    assert payload["strategy_compilation"]["compilation_policy"]["schema_version"] == "strategy_compilation_policy.v1"
    assert payload["strategy_compilation"]["compilation_policy"]["rule_surface_id"] == "strategy_compilation.backtest.v1"
    assert len(payload["experiments"]) >= 3
    report = client.get(f"/workbench/runs/{payload['run_id']}")
    assert report.status_code == 200
    factor_versions = report.json().get("factor_versions", [])
    assert isinstance(factor_versions, list)
    assert len(factor_versions) >= 1
    strategy_decision = report.json().get("strategy_decision", {})
    assert isinstance(strategy_decision, dict)
    assert strategy_decision.get("schema_version") == "strategy_decision.v1"
    assert strategy_decision.get("selected")
    strategy_validation = report.json().get("strategy_validation", {})
    assert isinstance(strategy_validation, dict)
    assert strategy_validation.get("schema_version") == "strategy_validation.v1"
    assert strategy_validation.get("compile_ready") is True
    strategy_compilation = report.json().get("strategy_compilation", {})
    assert isinstance(strategy_compilation, dict)
    assert strategy_compilation.get("schema_version") == "strategy_compilation.v1"
    assert (strategy_compilation.get("compilation_profile") or {}).get("schema_version") == "strategy_compilation_profile.v1"
    assert (strategy_compilation.get("compilation_policy") or {}).get("schema_version") == "strategy_compilation_policy.v1"
    assert (strategy_compilation.get("compilation_policy") or {}).get("rule_surface_id") == "strategy_compilation.backtest.v1"
    strategy_trace = report.json().get("strategy_trace", {})
    assert isinstance(strategy_trace, dict)
    assert strategy_trace.get("schema_version") == "strategy_trace_artifact.v1"
    assert strategy_trace.get("trace_object") == "BacktestReport"
    assert (strategy_trace.get("evaluation_plan") or {}).get("schema_version") == "backtest_evaluation_plan.v1"
    assert len(((strategy_trace.get("factor_lineage") or {}).get("factor_versions") or [])) >= 1
    runtime_summary = report.json().get("runtime_summary", {})
    assert isinstance(runtime_summary, dict)
    assert runtime_summary.get("schema_version") == "strategy_runtime_outcome_summary.v1"
    assert runtime_summary.get("summary_object") == "BacktestReport"
    assert runtime_summary.get("market") == payload["market"]
    assert runtime_summary.get("factor_lineage_count", 0) >= 1
    runtime_diagnostics = report.json().get("runtime_diagnostics", {})
    assert isinstance(runtime_diagnostics, dict)
    assert runtime_diagnostics.get("schema_version") == "strategy_runtime_diagnostics.v1"
    assert runtime_diagnostics.get("diagnostics_object") == "BacktestReport"
    action_regime_details = report.json().get("action_regime_details", {})
    assert isinstance(action_regime_details, dict)
    assert action_regime_details.get("schema_version") == "strategy_runtime_action_regime.v1"
    assert action_regime_details.get("detail_object") == "BacktestReport"
    attribution_execution_details = report.json().get("attribution_execution_details", {})
    assert isinstance(attribution_execution_details, dict)
    assert attribution_execution_details.get("schema_version") == "strategy_runtime_attribution_execution.v1"
    assert attribution_execution_details.get("detail_object") == "BacktestReport"
    control_optimizer_details = report.json().get("control_optimizer_details", {})
    assert isinstance(control_optimizer_details, dict)
    assert control_optimizer_details.get("schema_version") == "strategy_runtime_control_optimizer.v1"
    assert control_optimizer_details.get("detail_object") == "BacktestReport"
    control_action_deep_details = report.json().get("control_action_deep_details", {})
    assert isinstance(control_action_deep_details, dict)
    assert control_action_deep_details.get("schema_version") == "strategy_runtime_control_action_deep.v1"
    assert control_action_deep_details.get("detail_object") == "BacktestReport"
    evidence_refs = report.json().get("evidence_refs", [])
    assert any(str(ref).startswith("evidence_pack:") for ref in evidence_refs)
    assert any(str(ref).startswith("evidence_source:") for ref in evidence_refs)
