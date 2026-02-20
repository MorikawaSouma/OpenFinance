from openfinance.quant.portfolio import (
    ConstraintInput,
    ConstraintSolver,
    OptimizerInput,
    RiskParityOptimizer,
    ScoreBasedOptimizer,
)


def test_risk_parity_optimizer_inverse_vol_sign_and_ratio() -> None:
    optimizer = RiskParityOptimizer()
    result = optimizer.optimize(
        OptimizerInput(
            scores={"A": 1.0, "B": -1.0},
            volatilities={"A": 0.1, "B": 0.2},
            gross_target=1.0,
        )
    )
    assert result.weights["A"] > 0
    assert result.weights["B"] < 0
    ratio = abs(result.weights["A"]) / max(1e-9, abs(result.weights["B"]))
    assert ratio > 1.9
    assert ratio < 2.1


def test_constraint_solver_enforces_sector_cap_and_can_reject_invalid_params() -> None:
    score_optimizer = ScoreBasedOptimizer()
    optimized = score_optimizer.optimize(
        OptimizerInput(
            scores={"AAPL": 1.0, "MSFT": 0.8},
            volatilities={"AAPL": 0.2, "MSFT": 0.2},
            gross_target=1.0,
        )
    )

    solver = ConstraintSolver()
    constrained = solver.solve(
        ConstraintInput(
            weights=optimized.weights,
            sectors={"AAPL": "Tech", "MSFT": "Tech"},
            max_position_weight=0.8,
            max_gross_leverage=1.0,
            sector_neutral=False,
            max_sector_exposure=0.2,
        )
    )
    assert constrained.rejected is False
    assert constrained.adjusted is True
    assert sum(abs(value) for value in constrained.weights.values()) <= 0.200001
    assert any(action.get("action") == "max_sector_exposure_scale" for action in constrained.actions)

    invalid = solver.solve(
        ConstraintInput(
            weights={"AAPL": 0.3},
            sectors={"AAPL": "Tech"},
            max_position_weight=0.8,
            max_gross_leverage=1.0,
            sector_neutral=False,
            max_sector_exposure=0.0,
        )
    )
    assert invalid.rejected is True
    assert invalid.reason_code == "ex_ante_invalid_max_sector_exposure"
