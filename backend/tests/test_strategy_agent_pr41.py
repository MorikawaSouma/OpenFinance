from openfinance.llm.provider import LLMProviderRegistry, ZhipuGLM47Provider
from openfinance.research.strategy_agent import StrategyAgent


def _agent() -> StrategyAgent:
    registry = LLMProviderRegistry()
    registry.register(ZhipuGLM47Provider(), is_default=True)
    return StrategyAgent(registry)


def test_pr41_strategy_agent_outputs_market_dependent_tradeoff() -> None:
    agent = _agent()
    common_kwargs = {
        "question": "Build a low-drawdown momentum strategy with clear trade-offs.",
        "research_plan": {"objectives": ["high_sharpe", "low_drawdown"]},
        "factor_health_report": {
            "oos_gap": 0.01,
            "turnover_proxy": 0.12,
            "coverage": 0.92,
            "in_sample_ic_mean": 0.03,
            "out_sample_ic_mean": 0.025,
        },
        "constraints": {"max_drawdown_target": 0.12},
        "risk_budget": "vol_target_10pct",
        "variant": {
            "strategy_family": "trend",
            "rebalance": "intraday",
            "lookback_days": 20,
            "signal_threshold": 0.02,
            "position_sizing": "risk_budget",
            "risk_budget": "vol_target_10pct",
            "max_position": 0.12,
        },
    }

    us = agent.decide(
        market="US",
        market_rules={
            "market": "US",
            "t_plus_one": False,
            "lot_size": 1.0,
            "supports_fractional_qty": True,
            "min_notional": 0.0,
            "is_24x7": False,
        },
        **common_kwargs,
    )
    cn = agent.decide(
        market="CN",
        market_rules={
            "market": "CN",
            "t_plus_one": True,
            "lot_size": 100.0,
            "supports_fractional_qty": False,
            "min_notional": 0.0,
            "is_24x7": False,
        },
        **common_kwargs,
    )

    assert len(us.candidates) >= 2
    assert len(cn.candidates) >= 2
    assert us.selected.name in {"RiskBudgetAllocator", "EqualWeightAllocator"}
    assert cn.selected.name in {"RiskBudgetAllocator", "EqualWeightAllocator"}
    assert "market=US" in us.selected.tradeoff_summary
    assert "market=CN" in cn.selected.tradeoff_summary
    assert cn.selected.name != us.selected.name

