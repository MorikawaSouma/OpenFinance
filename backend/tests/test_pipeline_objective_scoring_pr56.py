from openfinance.research.pipeline import ResearchPipelineEngine


def test_pr56_zero_trade_variant_does_not_beat_active_variant() -> None:
    engine = ResearchPipelineEngine.__new__(ResearchPipelineEngine)
    objectives = ["低回撤", "高夏普"]

    zero_trade_score = engine._score_objective(
        {
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "turnover": 0.0,
            "trade_count": 0,
            "order_count": 10,
            "reject_count": 10,
        },
        objectives,
    )
    active_score = engine._score_objective(
        {
            "sharpe": 0.156905,
            "max_drawdown": 0.125235,
            "total_return": 0.006312,
            "turnover": 0.912453,
            "trade_count": 5,
            "order_count": 5,
            "reject_count": 0,
        },
        objectives,
    )

    assert active_score > zero_trade_score
