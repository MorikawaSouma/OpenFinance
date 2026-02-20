import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptimizerInput:
    scores: dict[str, float]
    volatilities: dict[str, float]
    gross_target: float = 1.0
    expected_returns: dict[str, float] = field(default_factory=dict)
    covariance: dict[str, dict[str, float]] = field(default_factory=dict)
    risk_budget: dict[str, float] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizerResult:
    weights: dict[str, float]
    diagnostics: dict[str, Any]


class PortfolioOptimizer(ABC):
    name: str = "base"

    @abstractmethod
    def optimize(self, inp: OptimizerInput) -> OptimizerResult:
        raise NotImplementedError


class ScoreBasedOptimizer(PortfolioOptimizer):
    name = "score_based"

    def optimize(self, inp: OptimizerInput) -> OptimizerResult:
        gross_target = max(0.0, float(inp.gross_target))
        keys = [key for key in inp.scores.keys() if key]
        if not keys or gross_target <= 0:
            return OptimizerResult(weights={key: 0.0 for key in keys}, diagnostics={"tiers": {}, "gross_target": gross_target})

        ranked = sorted(keys, key=lambda key: inp.scores.get(key, 0.0), reverse=True)
        tiers: dict[str, str] = {}
        raw: dict[str, float] = {}
        n = len(ranked)
        for idx, inst in enumerate(ranked):
            score = float(inp.scores.get(inst, 0.0))
            if n <= 1:
                bucket = "top"
                tier_mul = 1.0
            else:
                pct = 1.0 - (idx / max(1, n - 1))
                if pct >= 0.66:
                    bucket = "top"
                    tier_mul = 1.0
                elif pct >= 0.33:
                    bucket = "mid"
                    tier_mul = 0.6
                else:
                    bucket = "bottom"
                    tier_mul = 0.3
            tiers[inst] = bucket
            signed = 1.0 if score >= 0 else -1.0
            raw[inst] = signed * tier_mul * (abs(score) + 1e-9)

        denom = sum(abs(value) for value in raw.values())
        if denom <= 0:
            weights = {key: 0.0 for key in keys}
        else:
            weights = {key: (value / denom) * gross_target for key, value in raw.items()}
        return OptimizerResult(
            weights=weights,
            diagnostics={"tiers": tiers, "raw_weights": raw, "gross_target": gross_target},
        )


class RiskParityOptimizer(PortfolioOptimizer):
    name = "risk_parity"

    def optimize(self, inp: OptimizerInput) -> OptimizerResult:
        gross_target = max(0.0, float(inp.gross_target))
        keys = [key for key in inp.scores.keys() if key]
        if not keys or gross_target <= 0:
            return OptimizerResult(weights={key: 0.0 for key in keys}, diagnostics={"gross_target": gross_target})

        raw: dict[str, float] = {}
        for inst in keys:
            score = float(inp.scores.get(inst, 0.0))
            vol = max(1e-6, abs(float(inp.volatilities.get(inst, 0.02))))
            direction = 1.0 if score >= 0 else -1.0
            raw[inst] = direction * (1.0 / vol)
        denom = sum(abs(value) for value in raw.values())
        if denom <= 0:
            weights = {key: 0.0 for key in keys}
        else:
            weights = {key: (value / denom) * gross_target for key, value in raw.items()}
        return OptimizerResult(
            weights=weights,
            diagnostics={
                "method": "inverse_volatility",
                "raw_weights": raw,
                "gross_target": gross_target,
            },
        )


class RiskBudgetOptimizerV2(PortfolioOptimizer):
    name = "risk_budget_v2"

    def optimize(self, inp: OptimizerInput) -> OptimizerResult:
        assets = self._assets(inp)
        gross_target = max(0.0, float(inp.gross_target))
        if not assets or gross_target <= 0:
            return OptimizerResult(
                weights={asset: 0.0 for asset in assets},
                diagnostics={"gross_target": gross_target, "method": "covariance_risk_budget_v2"},
            )

        constraints = inp.constraints or {}
        max_iter = max(20, int(constraints.get("max_iter", 240) or 240))
        tol = max(1e-6, float(constraints.get("tol", 1e-4) or 1e-4))
        alpha_mu = max(0.0, min(0.5, float(constraints.get("alpha_mu", 0.08) or 0.08)))
        allow_short = bool(constraints.get("allow_short", False))
        max_position = constraints.get("max_position_weight")
        max_position = float(max_position) if isinstance(max_position, (int, float)) else None

        cov = self._cov_matrix(assets, inp)
        target_budget = self._target_budget(assets, inp.risk_budget)
        direction = self._asset_direction(assets, inp.scores, inp.expected_returns, allow_short=allow_short)
        mu_vec = self._mu_vector(assets, inp.expected_returns, inp.scores)

        abs_weights = [target_budget[idx] * gross_target for idx in range(len(assets))]
        loss = 0.0
        for _ in range(max_iter):
            signed = [abs_weights[idx] * direction[idx] for idx in range(len(assets))]
            rc_share = self._risk_contribution_share(signed, cov)
            loss = sum(abs(rc_share[idx] - target_budget[idx]) for idx in range(len(assets)))
            if loss <= tol:
                break
            updated: list[float] = []
            for idx in range(len(assets)):
                ratio = target_budget[idx] / max(1e-9, rc_share[idx])
                next_w = abs_weights[idx] * ratio
                if alpha_mu > 0:
                    next_w *= math.exp(alpha_mu * mu_vec[idx])
                updated.append(max(1e-9, next_w))
            abs_weights = self._renormalize(updated, gross_target=gross_target)
            if max_position is not None and max_position > 0:
                abs_weights = self._apply_abs_cap(abs_weights, cap=max_position, gross_target=gross_target)

        final_weights = {asset: (abs_weights[idx] * direction[idx]) for idx, asset in enumerate(assets)}
        final_rc_share = self._risk_contribution_share(
            [final_weights[asset] for asset in assets],
            cov,
        )
        achieved_budget = {assets[idx]: round(final_rc_share[idx], 6) for idx in range(len(assets))}
        target_budget_map = {assets[idx]: round(target_budget[idx], 6) for idx in range(len(assets))}
        deviation_l1 = round(sum(abs(final_rc_share[idx] - target_budget[idx]) for idx in range(len(assets))), 6)
        return OptimizerResult(
            weights=final_weights,
            diagnostics={
                "method": "covariance_risk_budget_v2",
                "gross_target": gross_target,
                "target_budget": target_budget_map,
                "achieved_budget": achieved_budget,
                "budget_deviation_l1": deviation_l1,
                "loss_final": round(loss, 8),
                "assets": assets,
                "covariance": {asset: {assets[j]: round(cov[i][j], 8) for j in range(len(assets))} for i, asset in enumerate(assets)},
                "direction": {assets[idx]: direction[idx] for idx in range(len(assets))},
            },
        )

    def _assets(self, inp: OptimizerInput) -> list[str]:
        ordered: list[str] = []
        for key in [*inp.scores.keys(), *inp.expected_returns.keys(), *inp.risk_budget.keys(), *inp.volatilities.keys()]:
            if key and key not in ordered:
                ordered.append(key)
        for row, cols in inp.covariance.items():
            if row and row not in ordered:
                ordered.append(row)
            for col in cols.keys():
                if col and col not in ordered:
                    ordered.append(col)
        return ordered

    def _target_budget(self, assets: list[str], risk_budget: dict[str, float]) -> list[float]:
        raw: list[float] = []
        for asset in assets:
            value = float(risk_budget.get(asset, 0.0))
            raw.append(max(0.0, value))
        if sum(raw) <= 0:
            return [1.0 / len(assets) for _ in assets]
        total = sum(raw)
        return [value / total for value in raw]

    def _asset_direction(
        self,
        assets: list[str],
        scores: dict[str, float],
        expected_returns: dict[str, float],
        *,
        allow_short: bool,
    ) -> list[float]:
        if allow_short:
            out: list[float] = []
            for asset in assets:
                mu = float(expected_returns.get(asset, scores.get(asset, 0.0)))
                out.append(1.0 if mu >= 0 else -1.0)
            return out
        agg = sum(float(scores.get(asset, 0.0)) for asset in assets)
        sign = 1.0 if agg >= 0 else -1.0
        return [sign for _ in assets]

    def _mu_vector(self, assets: list[str], expected_returns: dict[str, float], scores: dict[str, float]) -> list[float]:
        vals = [float(expected_returns.get(asset, scores.get(asset, 0.0))) for asset in assets]
        if not vals:
            return []
        mean = sum(vals) / len(vals)
        var = sum((value - mean) ** 2 for value in vals) / max(1, len(vals))
        std = math.sqrt(var)
        if std <= 1e-12:
            return [0.0 for _ in vals]
        return [(value - mean) / std for value in vals]

    def _cov_matrix(self, assets: list[str], inp: OptimizerInput) -> list[list[float]]:
        size = len(assets)
        mat = [[0.0 for _ in range(size)] for _ in range(size)]
        for i, row_asset in enumerate(assets):
            for j, col_asset in enumerate(assets):
                if row_asset in inp.covariance and col_asset in inp.covariance[row_asset]:
                    value = float(inp.covariance[row_asset][col_asset])
                elif col_asset in inp.covariance and row_asset in inp.covariance[col_asset]:
                    value = float(inp.covariance[col_asset][row_asset])
                elif i == j:
                    vol = max(1e-6, abs(float(inp.volatilities.get(row_asset, 0.02))))
                    value = vol * vol
                else:
                    value = 0.0
                mat[i][j] = value
        # Force symmetry and positive diagonal ridge.
        for i in range(size):
            for j in range(i + 1, size):
                mean = 0.5 * (mat[i][j] + mat[j][i])
                mat[i][j] = mean
                mat[j][i] = mean
            mat[i][i] = max(1e-8, mat[i][i])
        return mat

    def _risk_contribution_share(self, weights: list[float], cov: list[list[float]]) -> list[float]:
        n = len(weights)
        if n == 0:
            return []
        marginal = [0.0 for _ in range(n)]
        for i in range(n):
            total = 0.0
            for j in range(n):
                total += cov[i][j] * weights[j]
            marginal[i] = total
        portfolio_var = sum(weights[i] * marginal[i] for i in range(n))
        if portfolio_var <= 1e-12:
            return [1.0 / n for _ in range(n)]
        raw = [abs(weights[i] * marginal[i]) / math.sqrt(portfolio_var) for i in range(n)]
        denom = sum(raw)
        if denom <= 1e-12:
            return [1.0 / n for _ in range(n)]
        return [value / denom for value in raw]

    def _renormalize(self, values: list[float], *, gross_target: float) -> list[float]:
        total = sum(abs(value) for value in values)
        if total <= 1e-12:
            return [0.0 for _ in values]
        scale = gross_target / total
        return [value * scale for value in values]

    def _apply_abs_cap(self, values: list[float], *, cap: float, gross_target: float) -> list[float]:
        if cap <= 0:
            return [0.0 for _ in values]
        capped = [min(cap, max(0.0, value)) for value in values]
        total = sum(capped)
        if total <= 1e-12:
            return [0.0 for _ in values]
        if total < gross_target:
            deficit = gross_target - total
            room = [max(0.0, cap - value) for value in capped]
            room_total = sum(room)
            if room_total > 1e-12:
                for idx in range(len(capped)):
                    capped[idx] += deficit * (room[idx] / room_total)
        return self._renormalize(capped, gross_target=gross_target)


@dataclass(frozen=True)
class ConstraintInput:
    weights: dict[str, float]
    sectors: dict[str, str]
    max_position_weight: float
    max_gross_leverage: float
    sector_neutral: bool
    max_sector_exposure: float


@dataclass(frozen=True)
class ConstraintResult:
    weights: dict[str, float]
    adjusted: bool
    rejected: bool
    reason_code: str | None
    actions: list[dict[str, Any]]


class ConstraintSolver:
    def solve(self, inp: ConstraintInput) -> ConstraintResult:
        weights = {key: float(value) for key, value in inp.weights.items()}
        actions: list[dict[str, Any]] = []
        adjusted = False

        if inp.max_position_weight <= 0:
            return ConstraintResult(
                weights={key: 0.0 for key in weights},
                adjusted=True,
                rejected=True,
                reason_code="ex_ante_invalid_max_position_weight",
                actions=[{"action": "reject", "detail": "max_position_weight must be > 0"}],
            )
        if inp.max_gross_leverage <= 0:
            return ConstraintResult(
                weights={key: 0.0 for key in weights},
                adjusted=True,
                rejected=True,
                reason_code="ex_ante_invalid_max_gross_leverage",
                actions=[{"action": "reject", "detail": "max_gross_leverage must be > 0"}],
            )
        if inp.max_sector_exposure <= 0:
            return ConstraintResult(
                weights={key: 0.0 for key in weights},
                adjusted=True,
                rejected=True,
                reason_code="ex_ante_invalid_max_sector_exposure",
                actions=[{"action": "reject", "detail": "max_sector_exposure must be > 0"}],
            )

        # 1) Per-position cap.
        for inst, value in list(weights.items()):
            capped = max(-inp.max_position_weight, min(inp.max_position_weight, value))
            if not math.isclose(capped, value, rel_tol=0.0, abs_tol=1e-12):
                weights[inst] = capped
                adjusted = True
                actions.append(
                    {
                        "action": "max_position_weight_cap",
                        "instrument": inst,
                        "before": value,
                        "after": capped,
                    }
                )

        # 2) Sector exposure cap by gross absolute exposure.
        sector_groups: dict[str, list[str]] = {}
        for inst in weights.keys():
            sector = inp.sectors.get(inst, "Unknown")
            sector_groups.setdefault(sector, []).append(inst)
        for sector, members in sector_groups.items():
            gross = sum(abs(weights.get(inst, 0.0)) for inst in members)
            if gross > inp.max_sector_exposure and gross > 0:
                scale = inp.max_sector_exposure / gross
                for inst in members:
                    weights[inst] = weights.get(inst, 0.0) * scale
                adjusted = True
                actions.append(
                    {
                        "action": "max_sector_exposure_scale",
                        "sector": sector,
                        "before_gross": gross,
                        "after_gross": sum(abs(weights.get(inst, 0.0)) for inst in members),
                    }
                )

        # 3) Optional sector neutralization.
        if inp.sector_neutral:
            for sector, members in sector_groups.items():
                net = sum(weights.get(inst, 0.0) for inst in members)
                if abs(net) <= 1e-10:
                    continue
                adjusted = True
                if len(members) == 1:
                    inst = members[0]
                    before = weights.get(inst, 0.0)
                    weights[inst] = 0.0
                    actions.append(
                        {
                            "action": "sector_neutral_single_asset_zeroed",
                            "sector": sector,
                            "instrument": inst,
                            "before": before,
                            "after": 0.0,
                        }
                    )
                else:
                    shift = net / len(members)
                    for inst in members:
                        weights[inst] = weights.get(inst, 0.0) - shift
                    actions.append(
                        {
                            "action": "sector_neutral_shift",
                            "sector": sector,
                            "net_before": net,
                            "net_after": sum(weights.get(inst, 0.0) for inst in members),
                        }
                    )

        # 4) Gross leverage cap.
        gross_total = sum(abs(value) for value in weights.values())
        if gross_total > inp.max_gross_leverage and gross_total > 0:
            scale = inp.max_gross_leverage / gross_total
            for inst in list(weights.keys()):
                weights[inst] = weights[inst] * scale
            adjusted = True
            actions.append(
                {
                    "action": "max_gross_leverage_scale",
                    "before_gross": gross_total,
                    "after_gross": sum(abs(value) for value in weights.values()),
                }
            )

        return ConstraintResult(
            weights=weights,
            adjusted=adjusted,
            rejected=False,
            reason_code=None,
            actions=actions,
        )
