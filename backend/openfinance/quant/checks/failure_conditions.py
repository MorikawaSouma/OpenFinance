from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, field_validator

FailureLevel = Literal["info", "warn", "block"]
FailureAppliesTo = Literal["factor", "strategy"]


class FailureConditionConfig(BaseModel):
    code: str
    description: str = ""
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)
    severity_thresholds: dict[str, float] = Field(default_factory=dict)
    applies_to: FailureAppliesTo = "factor"

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("failure condition code must not be empty")
        text = text.replace("-", "_").replace(" ", "_").upper()
        return text

    @field_validator("severity_thresholds")
    @classmethod
    def _normalize_thresholds(cls, value: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, raw in value.items():
            name = str(key).strip().lower()
            if name not in {"warn", "block"}:
                continue
            if isinstance(raw, (int, float)):
                out[name] = float(raw)
        return out


class FailureConditionCheckResult(BaseModel):
    code: str
    level: FailureLevel
    message: str
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


@dataclass(frozen=True)
class FailureConditionCheck:
    code: str
    description: str
    evaluate: Callable[[FailureConditionConfig, dict[str, Any]], FailureConditionCheckResult]


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(default)


def _resolve_threshold(
    config: FailureConditionConfig,
    *,
    name: str,
    default: float,
    param_aliases: tuple[str, ...],
) -> float:
    if name in config.severity_thresholds:
        return float(config.severity_thresholds[name])
    for alias in param_aliases:
        value = config.params.get(alias)
        if isinstance(value, (int, float)):
            return float(value)
    return float(default)


def _legacy_code(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "liquidity_dry_up": "LIQUIDITY_DROUGHT",
        "liquidity_drought": "LIQUIDITY_DROUGHT",
        "liquidity_crunch": "LIQUIDITY_DROUGHT",
        "high_volatility": "ABNORMAL_VOL_SPIKE",
        "vol_spike": "ABNORMAL_VOL_SPIKE",
        "abnormal_volatility": "ABNORMAL_VOL_SPIKE",
        "abnormal_vol_spike": "ABNORMAL_VOL_SPIKE",
        "crowding_spike": "CROWDING_PROXY",
        "crowding": "CROWDING_PROXY",
        "concentration_risk": "CROWDING_PROXY",
        "turnover_spike": "CROWDING_PROXY",
    }
    if text in aliases:
        return aliases[text]
    return text.upper()


def _default_config(code: str, *, applies_to: FailureAppliesTo) -> FailureConditionConfig:
    key = _legacy_code(code)
    if key == "LIQUIDITY_DROUGHT":
        return FailureConditionConfig(
            code=key,
            description="Liquidity drought: rolling volume deteriorates or spread widens.",
            params={
                "min_volume_ratio": 0.70,
                "max_spread_ratio": 1.60,
            },
            severity_thresholds={"warn": 0.05, "block": 0.25},
            applies_to=applies_to,
        )
    if key == "ABNORMAL_VOL_SPIKE":
        return FailureConditionConfig(
            code=key,
            description="Abnormal volatility spike relative to baseline.",
            params={
                "baseline_floor": 0.0005,
            },
            severity_thresholds={"warn": 1.80, "block": 2.40},
            applies_to=applies_to,
        )
    if key == "CROWDING_PROXY":
        return FailureConditionConfig(
            code=key,
            description="Crowding proxy: turnover and exposure concentration too high.",
            params={
                "turnover_cap": 0.35,
                "exposure_cap": 0.55,
            },
            severity_thresholds={"warn": 1.00, "block": 1.40},
            applies_to=applies_to,
        )
    return FailureConditionConfig(
        code=key,
        description=f"Legacy-mapped failure condition: {key}",
        params={},
        severity_thresholds={},
        applies_to=applies_to,
    )


def normalize_failure_conditions(
    value: Any,
    *,
    default_applies_to: FailureAppliesTo = "factor",
) -> list[FailureConditionConfig]:
    if value is None:
        return []
    if isinstance(value, FailureConditionConfig):
        return [value]
    if not isinstance(value, list):
        value = [value]

    rows: list[FailureConditionConfig] = []
    for item in value:
        if isinstance(item, FailureConditionConfig):
            rows.append(item)
            continue
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            rows.append(_default_config(text, applies_to=default_applies_to))
            continue
        if isinstance(item, dict):
            raw = dict(item)
            code = str(raw.get("code") or "").strip()
            if not code:
                continue
            merged = _default_config(code, applies_to=default_applies_to).model_dump(mode="json")
            for key in ("description", "params", "severity_thresholds", "applies_to"):
                if key in raw:
                    merged[key] = raw[key]
            rows.append(FailureConditionConfig.model_validate(merged))
            continue

    dedup: dict[tuple[str, str], FailureConditionConfig] = {}
    for row in rows:
        dedup[(row.code, row.applies_to)] = row
    return list(dedup.values())


def _liquidity_drought_check(
    config: FailureConditionConfig,
    context: dict[str, Any],
) -> FailureConditionCheckResult:
    rolling_volume = max(1e-9, _as_float(context.get("rolling_volume"), 0.0))
    rolling_volume_avg = max(1e-9, _as_float(context.get("rolling_volume_avg"), rolling_volume))
    spread_bps = max(0.0, _as_float(context.get("spread_bps"), 0.0))
    spread_bps_avg = max(1e-9, _as_float(context.get("rolling_spread_bps_avg"), max(1.0, spread_bps)))

    min_volume_ratio = max(0.01, _as_float(config.params.get("min_volume_ratio"), 0.7))
    max_spread_ratio = max(0.1, _as_float(config.params.get("max_spread_ratio"), 1.6))
    volume_ratio = rolling_volume / rolling_volume_avg
    spread_ratio = spread_bps / spread_bps_avg
    score = max(0.0, min_volume_ratio - volume_ratio) + max(0.0, spread_ratio - max_spread_ratio)

    warn_th = _resolve_threshold(
        config,
        name="warn",
        default=0.05,
        param_aliases=("warn_threshold", "warn_score"),
    )
    block_th = _resolve_threshold(
        config,
        name="block",
        default=0.25,
        param_aliases=("block_threshold", "block_score"),
    )
    level: FailureLevel = "info"
    if score >= block_th:
        level = "block"
    elif score >= warn_th:
        level = "warn"

    message = (
        f"LIQUIDITY_DROUGHT {level}: volume_ratio={volume_ratio:.3f}, "
        f"spread_ratio={spread_ratio:.3f}, score={score:.3f}"
    )
    return FailureConditionCheckResult(
        code="LIQUIDITY_DROUGHT",
        level=level,
        message=message,
        metrics={
            "score": round(score, 6),
            "volume_ratio": round(volume_ratio, 6),
            "spread_ratio": round(spread_ratio, 6),
            "rolling_volume": round(rolling_volume, 6),
            "rolling_volume_avg": round(rolling_volume_avg, 6),
            "spread_bps": round(spread_bps, 6),
            "rolling_spread_bps_avg": round(spread_bps_avg, 6),
        },
    )


def _abnormal_vol_spike_check(
    config: FailureConditionConfig,
    context: dict[str, Any],
) -> FailureConditionCheckResult:
    rolling_vol = max(0.0, _as_float(context.get("rolling_volatility"), 0.0))
    baseline_floor = max(1e-6, _as_float(config.params.get("baseline_floor"), 0.0005))
    baseline_vol = max(
        baseline_floor,
        _as_float(context.get("baseline_volatility"), rolling_vol),
    )
    vol_ratio = rolling_vol / baseline_vol if baseline_vol > 0 else 0.0

    warn_th = _resolve_threshold(
        config,
        name="warn",
        default=1.8,
        param_aliases=("warn_vol_ratio", "warn_threshold"),
    )
    block_th = _resolve_threshold(
        config,
        name="block",
        default=2.4,
        param_aliases=("block_vol_ratio", "block_threshold"),
    )
    level: FailureLevel = "info"
    if vol_ratio >= block_th:
        level = "block"
    elif vol_ratio >= warn_th:
        level = "warn"

    message = (
        f"ABNORMAL_VOL_SPIKE {level}: rolling_vol={rolling_vol:.6f}, "
        f"baseline_vol={baseline_vol:.6f}, ratio={vol_ratio:.3f}"
    )
    return FailureConditionCheckResult(
        code="ABNORMAL_VOL_SPIKE",
        level=level,
        message=message,
        metrics={
            "rolling_volatility": round(rolling_vol, 8),
            "baseline_volatility": round(baseline_vol, 8),
            "vol_ratio": round(vol_ratio, 6),
        },
    )


def _crowding_proxy_check(
    config: FailureConditionConfig,
    context: dict[str, Any],
) -> FailureConditionCheckResult:
    turnover = max(0.0, _as_float(context.get("turnover_proxy"), 0.0))
    exposure_concentration = max(0.0, _as_float(context.get("exposure_concentration"), 0.0))
    turnover_cap = max(1e-6, _as_float(config.params.get("turnover_cap"), 0.35))
    exposure_cap = max(1e-6, _as_float(config.params.get("exposure_cap"), 0.55))
    score = max(turnover / turnover_cap, exposure_concentration / exposure_cap)
    if not math.isfinite(score):
        score = 0.0

    warn_th = _resolve_threshold(
        config,
        name="warn",
        default=1.0,
        param_aliases=("warn_threshold", "warn_score"),
    )
    block_th = _resolve_threshold(
        config,
        name="block",
        default=1.4,
        param_aliases=("block_threshold", "block_score"),
    )
    level: FailureLevel = "info"
    if score >= block_th:
        level = "block"
    elif score >= warn_th:
        level = "warn"

    message = (
        f"CROWDING_PROXY {level}: turnover={turnover:.4f}, "
        f"exposure_concentration={exposure_concentration:.4f}, score={score:.3f}"
    )
    return FailureConditionCheckResult(
        code="CROWDING_PROXY",
        level=level,
        message=message,
        metrics={
            "score": round(score, 6),
            "turnover_proxy": round(turnover, 6),
            "exposure_concentration": round(exposure_concentration, 6),
            "turnover_cap": round(turnover_cap, 6),
            "exposure_cap": round(exposure_cap, 6),
        },
    )


class FailureConditionCheckRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, FailureConditionCheck] = {}

    def register(self, check: FailureConditionCheck) -> None:
        self._checks[check.code.strip().upper()] = check

    def evaluate(
        self,
        *,
        conditions: list[FailureConditionConfig],
        context: dict[str, Any],
    ) -> list[FailureConditionCheckResult]:
        rows: list[FailureConditionCheckResult] = []
        for condition in conditions:
            check = self._checks.get(condition.code.strip().upper())
            if check is None:
                rows.append(
                    FailureConditionCheckResult(
                        code=condition.code,
                        level="info",
                        message=f"Unsupported failure condition code: {condition.code}",
                        metrics={},
                    )
                )
                continue
            rows.append(check.evaluate(condition, context))
        return rows

    @classmethod
    def default_registry(cls) -> "FailureConditionCheckRegistry":
        registry = cls()
        registry.register(
            FailureConditionCheck(
                code="LIQUIDITY_DROUGHT",
                description="Rolling volume drought and spread widening detector.",
                evaluate=_liquidity_drought_check,
            )
        )
        registry.register(
            FailureConditionCheck(
                code="ABNORMAL_VOL_SPIKE",
                description="Rolling volatility spike detector.",
                evaluate=_abnormal_vol_spike_check,
            )
        )
        registry.register(
            FailureConditionCheck(
                code="CROWDING_PROXY",
                description="Turnover/exposure concentration crowding detector.",
                evaluate=_crowding_proxy_check,
            )
        )
        return registry
