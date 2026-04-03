from typing import Any, Literal

from pydantic import BaseModel, Field

from openfinance.markets.plugins import build_market_rules_provider
from openfinance.quant.backtest.migration import MigrationChecker, MigrationWarning
from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_spec import StrategySpec
from openfinance.research.strategy_validation import StrategyValidationResult


CompilationSourceKind = Literal[
    "strategy_spec",
    "strategy_spec.constraints",
    "strategy_decision.selected",
    "strategy_validation",
    "runtime_request",
    "default",
]

CompilationInputClassification = Literal[
    "user_configurable",
    "environment_bound",
    "runtime_derived",
    "validation_required_override",
]

CompilationConfiguredBy = Literal[
    "strategy_spec",
    "strategy_decision",
    "user_request",
    "prepared_dataset",
    "system_environment",
    "runtime_pipeline",
    "validation_artifact",
]

CompilationValidatedBy = Literal[
    "strategy_validation",
    "compilation_profile",
    "not_applicable",
]

CompilationPolicyOutcome = Literal["allowed", "allowed_with_warning", "blocked"]
CompilationPolicyCheckedBy = Literal["compilation_profile", "migration_checker", "backtest_runtime"]
CompilationPolicyFactSource = Literal[
    "compilation_profile.override_policies",
    "backtest_runner.supported_execution_models",
    "market_rules_provider",
    "migration_checker.warning_codes",
]
StrategyCompileProvenanceMode = Literal[
    "pipeline_managed",
    "user_requested",
    "runtime_variant",
]


class StrategyCompileRuntimeContext(BaseModel):
    provenance_mode: StrategyCompileProvenanceMode = "pipeline_managed"
    dataset_version: str
    start: str
    end: str
    execution_model: str = "next_open"
    run_time_utc: str = "16:00"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    auto_round_lot: bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    dataset_version_classification: CompilationInputClassification = "runtime_derived"
    dataset_version_configured_by: CompilationConfiguredBy = "prepared_dataset"
    window_classification: CompilationInputClassification = "runtime_derived"
    window_configured_by: CompilationConfiguredBy = "runtime_pipeline"
    execution_model_classification: CompilationInputClassification = "environment_bound"
    execution_model_configured_by: CompilationConfiguredBy = "system_environment"
    run_time_utc_classification: CompilationInputClassification = "environment_bound"
    run_time_utc_configured_by: CompilationConfiguredBy = "system_environment"
    cost_model_classification: CompilationInputClassification = "runtime_derived"
    cost_model_configured_by: CompilationConfiguredBy = "runtime_pipeline"
    auto_round_lot_classification: CompilationInputClassification = "validation_required_override"
    auto_round_lot_configured_by: CompilationConfiguredBy = "runtime_pipeline"


class StrategyCompileRuntimeProvenancePreset(BaseModel):
    mode: StrategyCompileProvenanceMode
    dataset_version_classification: CompilationInputClassification = "runtime_derived"
    dataset_version_configured_by: CompilationConfiguredBy = "prepared_dataset"
    window_classification: CompilationInputClassification
    window_configured_by: CompilationConfiguredBy
    execution_model_classification: CompilationInputClassification = "environment_bound"
    execution_model_configured_by: CompilationConfiguredBy = "system_environment"
    run_time_utc_classification: CompilationInputClassification = "environment_bound"
    run_time_utc_configured_by: CompilationConfiguredBy = "system_environment"
    cost_model_classification: CompilationInputClassification
    cost_model_configured_by: CompilationConfiguredBy
    auto_round_lot_classification: CompilationInputClassification = "validation_required_override"
    auto_round_lot_configured_by: CompilationConfiguredBy


class StrategyCompilationBinding(BaseModel):
    output_path: str
    value: Any = None
    source_kind: CompilationSourceKind
    source_path: str
    note: str = ""


class StrategyCompilationOverlay(BaseModel):
    output_path: str
    final_value: Any = None
    source_kind: CompilationSourceKind
    source_path: str
    overridden_source_kind: CompilationSourceKind | None = None
    overridden_source_path: str | None = None
    overridden_value: Any = None
    rationale: str


class StrategyCompilationInputPolicy(BaseModel):
    output_path: str
    classification: CompilationInputClassification
    configured_by: CompilationConfiguredBy
    validated_by: CompilationValidatedBy
    source_kind: CompilationSourceKind | None = None
    source_path: str
    rationale: str


class CompilationOverridePolicy(BaseModel):
    output_path: str
    classification: CompilationInputClassification
    configured_by: CompilationConfiguredBy
    source_kind: CompilationSourceKind
    source_path: str
    requires_additional_validation: bool = False
    rationale: str


class StrategyCompilationProfile(BaseModel):
    schema_version: str = "strategy_compilation_profile.v1"
    profile_id: str = "backtest_request.simulation.v1"
    executable_object: Literal["BacktestRequest"] = "BacktestRequest"
    summary: str = ""
    input_policies: list[StrategyCompilationInputPolicy] = Field(default_factory=list)
    override_policies: list[CompilationOverridePolicy] = Field(default_factory=list)


class StrategyCompilationPolicyRule(BaseModel):
    rule_id: str
    applies_to: str
    severity: CompilationPolicyOutcome
    fact_source: CompilationPolicyFactSource
    checked_by: CompilationPolicyCheckedBy
    description: str
    markets: list[str] = Field(default_factory=list)
    environments: list[Literal["backtest"]] = Field(default_factory=lambda: ["backtest"])


class StrategyCompilationPolicyRuleSurface(BaseModel):
    schema_version: str = "strategy_compilation_policy_rules.v1"
    rule_surface_id: str = "strategy_compilation.backtest.v1"
    rules: list[StrategyCompilationPolicyRule] = Field(default_factory=list)


class StrategyCompilationPolicyCheck(BaseModel):
    rule_id: str
    code: str
    output_path: str
    classification: CompilationInputClassification
    configured_by: CompilationConfiguredBy
    outcome: CompilationPolicyOutcome
    checked_by: CompilationPolicyCheckedBy
    fact_source: CompilationPolicyFactSource
    requires_additional_validation: bool = False
    detail: str


class StrategyCompilationPolicyResult(BaseModel):
    schema_version: str = "strategy_compilation_policy.v1"
    checked_object: Literal["strategy_compilation_profile"] = "strategy_compilation_profile"
    rule_surface_schema_version: str = "strategy_compilation_policy_rules.v1"
    rule_surface_id: str = "strategy_compilation.backtest.v1"
    market: str
    environment: Literal["backtest"] = "backtest"
    status: CompilationPolicyOutcome
    compile_ready: bool
    summary: str
    warning_count: int = 0
    blocked_count: int = 0
    checks: list[StrategyCompilationPolicyCheck] = Field(default_factory=list)


class StrategyCompilationPlan(BaseModel):
    schema_version: str = "strategy_compilation.v1"
    strategy_id: str
    strategy_version: str
    market: str
    executable_object: Literal["BacktestRequest"] = "BacktestRequest"
    compile_ready: bool
    validation_status: str
    decision_status: str
    selected_candidate: str | None = None
    summary: str
    bindings: list[StrategyCompilationBinding] = Field(default_factory=list)
    overlays: list[StrategyCompilationOverlay] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    compilation_profile: StrategyCompilationProfile = Field(default_factory=StrategyCompilationProfile)
    compilation_policy: StrategyCompilationPolicyResult | None = None


_ALLOWED_EXECUTION_MODELS = {"next_open", "next_close"}
_MARKET_RULES = build_market_rules_provider()

_ALLOWED_POLICY_RULES = [
    StrategyCompilationPolicyRule(
        rule_id="runtime.execution_model_supported",
        applies_to="request.execution_model",
        severity="allowed",
        fact_source="backtest_runner.supported_execution_models",
        checked_by="backtest_runtime",
        description="The requested execution model is explicitly supported by BacktestRunner.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.dataset_version.runtime_binding",
        applies_to="request.dataset_version",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Dataset version is allowed to bind at compile time from prepared runtime context.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.start.runtime_window",
        applies_to="request.start",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Backtest start date is allowed to bind from runtime/request window selection.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.end.runtime_window",
        applies_to="request.end",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Backtest end date is allowed to bind from runtime/request window selection.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.execution_model.environment_binding",
        applies_to="request.execution_model",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Execution model remains an environment-owned compile input rather than durable strategy semantics.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.cost_model.commission_bps.runtime_binding",
        applies_to="request.cost_model.commission_bps",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Commission settings are allowed compile-time runtime inputs.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.request.cost_model.slippage_bps.runtime_binding",
        applies_to="request.cost_model.slippage_bps",
        severity="allowed",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Slippage settings are allowed compile-time runtime inputs.",
    ),
]

_WARNING_POLICY_RULES = [
    StrategyCompilationPolicyRule(
        rule_id="override.constraints.auto_round_lot.requires_review",
        applies_to="constraints.auto_round_lot",
        severity="allowed_with_warning",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Lot-rounding overrides stay reviewable because they can materially change executable quantity behavior.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.constraints.leverage_limit.compile_overlay",
        applies_to="constraints.leverage_limit",
        severity="allowed_with_warning",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Compile-time leverage overlays remain distinct from decision-owned semantics and require review.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="migration.lot_size_rounding_impact",
        applies_to="constraints.auto_round_lot",
        severity="allowed_with_warning",
        fact_source="migration_checker.warning_codes",
        checked_by="migration_checker",
        description="Market lot-size rounding can alter exposure even when the request remains executable.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="migration.trading_session_coverage_gap",
        applies_to="environment.run_time_utc",
        severity="allowed_with_warning",
        fact_source="migration_checker.warning_codes",
        checked_by="migration_checker",
        description="Configured execution time may sit outside a tradable local session and should be reviewed.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="override.unmapped_compile_override_review_required",
        applies_to="*",
        severity="allowed_with_warning",
        fact_source="compilation_profile.override_policies",
        checked_by="compilation_profile",
        description="Unmapped compile-time overrides default to warning until a dedicated rule is added.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="migration.unmapped_warning_review_required",
        applies_to="*",
        severity="allowed_with_warning",
        fact_source="migration_checker.warning_codes",
        checked_by="migration_checker",
        description="Unmapped migration warnings default to warning until a dedicated policy rule is added.",
    ),
]

_BLOCKED_POLICY_RULES = [
    StrategyCompilationPolicyRule(
        rule_id="runtime.execution_model_unsupported",
        applies_to="request.execution_model",
        severity="blocked",
        fact_source="backtest_runner.supported_execution_models",
        checked_by="backtest_runtime",
        description="Unsupported execution models are blocked because BacktestRunner would otherwise silently coerce them.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="runtime.market_rules_registered",
        applies_to="request.market",
        severity="blocked",
        fact_source="market_rules_provider",
        checked_by="migration_checker",
        description="Compilation is blocked when no market-rule provider is registered for the target market.",
    ),
    StrategyCompilationPolicyRule(
        rule_id="migration.cn_t_plus_one_high_frequency",
        applies_to="constraints.rebalance",
        severity="blocked",
        fact_source="migration_checker.warning_codes",
        checked_by="migration_checker",
        description="High-frequency setups that violate T+1 market structure are blocked at compile-policy time.",
        markets=["CN"],
    ),
    StrategyCompilationPolicyRule(
        rule_id="migration.lot_size_precision_mismatch",
        applies_to="constraints.auto_round_lot",
        severity="blocked",
        fact_source="migration_checker.warning_codes",
        checked_by="migration_checker",
        description="Compile-time quantity precision that violates lot-size rules without rounding is blocked.",
    ),
]

_STRATEGY_COMPILATION_POLICY_RULE_SURFACE = StrategyCompilationPolicyRuleSurface(
    rules=[*_ALLOWED_POLICY_RULES, *_WARNING_POLICY_RULES, *_BLOCKED_POLICY_RULES]
)
_POLICY_RULES_BY_ID = {
    rule.rule_id: rule for rule in _STRATEGY_COMPILATION_POLICY_RULE_SURFACE.rules
}
_OVERRIDE_RULE_IDS_BY_OUTPUT_PATH = {
    "request.dataset_version": "override.request.dataset_version.runtime_binding",
    "request.start": "override.request.start.runtime_window",
    "request.end": "override.request.end.runtime_window",
    "request.execution_model": "override.request.execution_model.environment_binding",
    "request.cost_model.commission_bps": "override.request.cost_model.commission_bps.runtime_binding",
    "request.cost_model.slippage_bps": "override.request.cost_model.slippage_bps.runtime_binding",
    "constraints.auto_round_lot": "override.constraints.auto_round_lot.requires_review",
    "constraints.leverage_limit": "override.constraints.leverage_limit.compile_overlay",
}
_MIGRATION_RULE_IDS_BY_CODE = {
    "cn_t_plus_one_high_frequency": "migration.cn_t_plus_one_high_frequency",
    "lot_size_precision_mismatch": "migration.lot_size_precision_mismatch",
    "lot_size_rounding_impact": "migration.lot_size_rounding_impact",
    "trading_session_coverage_gap": "migration.trading_session_coverage_gap",
}
_RUNTIME_PROVENANCE_PRESETS = {
    "pipeline_managed": StrategyCompileRuntimeProvenancePreset(
        mode="pipeline_managed",
        window_classification="runtime_derived",
        window_configured_by="runtime_pipeline",
        cost_model_classification="runtime_derived",
        cost_model_configured_by="runtime_pipeline",
        auto_round_lot_configured_by="runtime_pipeline",
    ),
    "user_requested": StrategyCompileRuntimeProvenancePreset(
        mode="user_requested",
        window_classification="user_configurable",
        window_configured_by="user_request",
        cost_model_classification="user_configurable",
        cost_model_configured_by="user_request",
        auto_round_lot_configured_by="user_request",
    ),
    "runtime_variant": StrategyCompileRuntimeProvenancePreset(
        mode="runtime_variant",
        window_classification="user_configurable",
        window_configured_by="user_request",
        cost_model_classification="runtime_derived",
        cost_model_configured_by="runtime_pipeline",
        auto_round_lot_configured_by="runtime_pipeline",
    ),
}


def _rollup_policy_outcome(outcomes: list[CompilationPolicyOutcome]) -> CompilationPolicyOutcome:
    if "blocked" in outcomes:
        return "blocked"
    if "allowed_with_warning" in outcomes:
        return "allowed_with_warning"
    return "allowed"


def get_strategy_compilation_policy_rule_surface() -> StrategyCompilationPolicyRuleSurface:
    return _STRATEGY_COMPILATION_POLICY_RULE_SURFACE.model_copy(deep=True)


def _policy_rule(rule_id: str) -> StrategyCompilationPolicyRule:
    return _POLICY_RULES_BY_ID[rule_id]


def _override_rule_id(output_path: str) -> str:
    return _OVERRIDE_RULE_IDS_BY_OUTPUT_PATH.get(
        output_path,
        "override.unmapped_compile_override_review_required",
    )


def _migration_rule_id(code: str) -> str:
    return _MIGRATION_RULE_IDS_BY_CODE.get(
        str(code or "").strip(),
        "migration.unmapped_warning_review_required",
    )


def get_strategy_compile_runtime_provenance_preset(
    mode: StrategyCompileProvenanceMode,
) -> StrategyCompileRuntimeProvenancePreset:
    return _RUNTIME_PROVENANCE_PRESETS[mode].model_copy(deep=True)


def build_strategy_compile_runtime_context(
    *,
    dataset_version: str,
    start: str,
    end: str,
    execution_model: str = "next_open",
    run_time_utc: str = "16:00",
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    auto_round_lot: bool | None = None,
    evidence_refs: list[str] | None = None,
    provenance_mode: StrategyCompileProvenanceMode = "pipeline_managed",
) -> StrategyCompileRuntimeContext:
    preset = get_strategy_compile_runtime_provenance_preset(provenance_mode)
    return StrategyCompileRuntimeContext(
        provenance_mode=preset.mode,
        dataset_version=dataset_version,
        start=start,
        end=end,
        execution_model=execution_model,
        run_time_utc=run_time_utc,
        commission_bps=float(commission_bps),
        slippage_bps=float(slippage_bps),
        auto_round_lot=auto_round_lot,
        evidence_refs=list(evidence_refs or []),
        dataset_version_classification=preset.dataset_version_classification,
        dataset_version_configured_by=preset.dataset_version_configured_by,
        window_classification=preset.window_classification,
        window_configured_by=preset.window_configured_by,
        execution_model_classification=preset.execution_model_classification,
        execution_model_configured_by=preset.execution_model_configured_by,
        run_time_utc_classification=preset.run_time_utc_classification,
        run_time_utc_configured_by=preset.run_time_utc_configured_by,
        cost_model_classification=preset.cost_model_classification,
        cost_model_configured_by=preset.cost_model_configured_by,
        auto_round_lot_classification=preset.auto_round_lot_classification,
        auto_round_lot_configured_by=preset.auto_round_lot_configured_by,
    )


class StrategyCompilationPolicyChecker:
    def __init__(self) -> None:
        self.migration_checker = MigrationChecker()

    def _add_rule_check(
        self,
        checks: list[StrategyCompilationPolicyCheck],
        *,
        rule_id: str,
        code: str,
        output_path: str,
        classification: CompilationInputClassification,
        configured_by: CompilationConfiguredBy,
        requires_additional_validation: bool,
        detail: str,
    ) -> None:
        rule = _policy_rule(rule_id)
        checks.append(
            StrategyCompilationPolicyCheck(
                rule_id=rule.rule_id,
                code=code,
                output_path=output_path,
                classification=classification,
                configured_by=configured_by,
                outcome=rule.severity,
                checked_by=rule.checked_by,
                fact_source=rule.fact_source,
                requires_additional_validation=requires_additional_validation,
                detail=detail,
            )
        )

    def validate(
        self,
        spec: StrategySpec,
        validation: StrategyValidationResult,
        profile: StrategyCompilationProfile,
        *,
        runtime_context: StrategyCompileRuntimeContext,
        decision: StrategyDecision | None = None,
    ) -> StrategyCompilationPolicyResult:
        checks: list[StrategyCompilationPolicyCheck] = []

        execution_model = str(runtime_context.execution_model or "").strip().lower()
        if execution_model in _ALLOWED_EXECUTION_MODELS:
            self._add_rule_check(
                checks,
                rule_id="runtime.execution_model_supported",
                code="execution_model_supported",
                output_path="request.execution_model",
                classification=runtime_context.execution_model_classification,
                configured_by=runtime_context.execution_model_configured_by,
                requires_additional_validation=False,
                detail=f"Execution model {execution_model} is supported by the current BacktestRunner.",
            )
        else:
            self._add_rule_check(
                checks,
                rule_id="runtime.execution_model_unsupported",
                code="execution_model_supported",
                output_path="request.execution_model",
                classification=runtime_context.execution_model_classification,
                configured_by=runtime_context.execution_model_configured_by,
                requires_additional_validation=True,
                detail=(
                    f"Execution model {runtime_context.execution_model!r} is not supported. "
                    "BacktestRunner would silently coerce it to next_open, so compilation is blocked until normalized."
                ),
            )

        for row in profile.override_policies:
            rule_id = _override_rule_id(row.output_path)
            rule = _policy_rule(rule_id)
            detail = row.rationale
            if rule.severity == "allowed_with_warning":
                detail += " Additional compile-policy review is required before this override should be treated as fully compile-ready."
            self._add_rule_check(
                checks,
                rule_id=rule_id,
                code=f"override_policy.{row.output_path.replace('.', '_')}",
                output_path=row.output_path,
                classification=row.classification,
                configured_by=row.configured_by,
                requires_additional_validation=row.requires_additional_validation,
                detail=detail,
            )

        market_key = str(spec.market or "").upper()
        try:
            rules = _MARKET_RULES.get(market_key)
        except KeyError:
            self._add_rule_check(
                checks,
                rule_id="runtime.market_rules_registered",
                code="unsupported_market_rules",
                output_path="request.market",
                classification="environment_bound",
                configured_by="system_environment",
                requires_additional_validation=True,
                detail=f"No market-rule provider is registered for market={market_key}.",
            )
            rules = None

        if rules is not None:
            migration_payload = spec.model_dump(mode="json")
            if runtime_context.auto_round_lot is not None:
                migration_payload["auto_round_lot"] = bool(runtime_context.auto_round_lot)
            migration_payload["run_time_utc"] = str(runtime_context.run_time_utc or "16:00")
            migration_warnings = self.migration_checker.check(migration_payload, market_key, rules)
            for warning in migration_warnings:
                rule_id = _migration_rule_id(warning.code)
                if warning.code in {"lot_size_precision_mismatch", "lot_size_rounding_impact"}:
                    output_path = "constraints.auto_round_lot"
                    classification = runtime_context.auto_round_lot_classification
                    configured_by = runtime_context.auto_round_lot_configured_by
                elif warning.code == "trading_session_coverage_gap":
                    output_path = "environment.run_time_utc"
                    classification = runtime_context.run_time_utc_classification
                    configured_by = runtime_context.run_time_utc_configured_by
                else:
                    output_path = "constraints.rebalance"
                    classification = "user_configurable"
                    configured_by = "strategy_spec"
                self._add_rule_check(
                    checks,
                    rule_id=rule_id,
                    code=warning.code,
                    output_path=output_path,
                    classification=classification,
                    configured_by=configured_by,
                    requires_additional_validation=_policy_rule(rule_id).severity != "allowed",
                    detail=warning.explanation,
                )

        outcomes = [check.outcome for check in checks]
        status = _rollup_policy_outcome(outcomes)
        blocked_count = sum(1 for check in checks if check.outcome == "blocked")
        warning_count = sum(1 for check in checks if check.outcome == "allowed_with_warning")
        summary = (
            f"{sum(1 for check in checks if check.outcome == 'allowed')} allowed, "
            f"{warning_count} warning, and {blocked_count} blocked compile-policy check(s) "
            f"for market={market_key or 'UNKNOWN'} environment=backtest using rule_surface={_STRATEGY_COMPILATION_POLICY_RULE_SURFACE.rule_surface_id}."
        )
        if decision is not None and validation.decision_status == "aligned":
            summary += " Decision-selected semantics remain separate from compile-time environment and override rules."
        if blocked_count > 0:
            summary += " Resolve blocked compile-policy checks before treating BacktestRequest as compile-ready."
        return StrategyCompilationPolicyResult(
            rule_surface_schema_version=_STRATEGY_COMPILATION_POLICY_RULE_SURFACE.schema_version,
            rule_surface_id=_STRATEGY_COMPILATION_POLICY_RULE_SURFACE.rule_surface_id,
            market=market_key or "UNKNOWN",
            status=status,
            compile_ready=blocked_count == 0,
            summary=summary,
            warning_count=warning_count,
            blocked_count=blocked_count,
            checks=checks,
        )


_COMPILATION_POLICY_CHECKER = StrategyCompilationPolicyChecker()


def parse_strategy_compilation_plan(raw: Any) -> StrategyCompilationPlan | None:
    if isinstance(raw, StrategyCompilationPlan):
        return raw
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return StrategyCompilationPlan.model_validate(raw)
    except ValueError:
        return None


def build_strategy_compilation_plan(
    spec: StrategySpec,
    validation: StrategyValidationResult,
    *,
    runtime_context: StrategyCompileRuntimeContext,
    decision: StrategyDecision | None = None,
) -> StrategyCompilationPlan:
    bindings: list[StrategyCompilationBinding] = []
    overlays: list[StrategyCompilationOverlay] = []

    def bind(
        output_path: str,
        value: Any,
        *,
        source_kind: CompilationSourceKind,
        source_path: str,
        note: str = "",
    ) -> None:
        bindings.append(
            StrategyCompilationBinding(
                output_path=output_path,
                value=value,
                source_kind=source_kind,
                source_path=source_path,
                note=note,
            )
        )

    def overlay(
        output_path: str,
        final_value: Any,
        *,
        source_kind: CompilationSourceKind,
        source_path: str,
        rationale: str,
        overridden_source_kind: CompilationSourceKind | None = None,
        overridden_source_path: str | None = None,
        overridden_value: Any = None,
    ) -> None:
        overlays.append(
            StrategyCompilationOverlay(
                output_path=output_path,
                final_value=final_value,
                source_kind=source_kind,
                source_path=source_path,
                overridden_source_kind=overridden_source_kind,
                overridden_source_path=overridden_source_path,
                overridden_value=overridden_value,
                rationale=rationale,
            )
        )

    bind("request.dataset_version", runtime_context.dataset_version, source_kind="runtime_request", source_path="dataset_version")
    bind("request.strategy_id", spec.strategy_id, source_kind="strategy_spec", source_path="strategy_id")
    bind("request.strategy_version", spec.strategy_version, source_kind="strategy_spec", source_path="strategy_version")
    bind("request.market", str(spec.market or "").upper(), source_kind="strategy_spec", source_path="market")
    bind("request.start", runtime_context.start, source_kind="runtime_request", source_path="start")
    bind("request.end", runtime_context.end, source_kind="runtime_request", source_path="end")
    bind(
        "request.execution_model",
        runtime_context.execution_model,
        source_kind="runtime_request",
        source_path="execution_model",
        note="Execution model remains runtime-owned, not strategy-owned.",
    )
    bind(
        "request.cost_model.commission_bps",
        float(runtime_context.commission_bps),
        source_kind="runtime_request",
        source_path="commission_bps",
    )
    bind(
        "request.cost_model.slippage_bps",
        float(runtime_context.slippage_bps),
        source_kind="runtime_request",
        source_path="slippage_bps",
    )
    if runtime_context.auto_round_lot is not None:
        bind(
            "constraints.auto_round_lot",
            bool(runtime_context.auto_round_lot),
            source_kind="runtime_request",
            source_path="auto_round_lot",
            note="Lot-rounding remains an executable/runtime overlay.",
        )

    bind("constraints.strategy_family", spec.strategy_family, source_kind="strategy_spec", source_path="strategy_family")
    bind("constraints.rebalance", spec.rebalance, source_kind="strategy_spec", source_path="rebalance")
    bind("constraints.lookback_days", int(spec.lookback_days), source_kind="strategy_spec", source_path="lookback_days")
    bind(
        "constraints.signal_threshold",
        float(spec.signal_threshold),
        source_kind="strategy_spec",
        source_path="signal_threshold",
    )
    bind(
        "constraints.position_sizing",
        spec.position_sizing,
        source_kind="strategy_spec",
        source_path="position_sizing",
    )
    bind("constraints.risk_budget", spec.risk_budget, source_kind="strategy_spec", source_path="risk_budget")
    bind("constraints.max_position", float(spec.max_position), source_kind="strategy_spec", source_path="max_position")
    bind("constraints.stop_loss", float(spec.stop_loss), source_kind="strategy_spec", source_path="stop_loss")

    leverage_source_kind: CompilationSourceKind = "strategy_spec"
    leverage_source_path = "leverage_limit"
    leverage_note = ""
    if isinstance(spec.constraints, dict) and "leverage_limit" in spec.constraints:
        leverage_source_kind = "strategy_spec.constraints"
        leverage_source_path = "constraints.leverage_limit"
        leverage_note = "Compile-time leverage overlay is preserved from strategy constraints."
    bind(
        "constraints.leverage_limit",
        float(spec.leverage_limit),
        source_kind=leverage_source_kind,
        source_path=leverage_source_path,
        note=leverage_note,
    )

    bind(
        "constraints.circuit_breaker",
        spec.circuit_breaker.model_dump(mode="json"),
        source_kind="strategy_spec",
        source_path="circuit_breaker",
    )
    bind(
        "constraints.failure_regimes",
        list(spec.failure_regimes),
        source_kind="strategy_spec",
        source_path="failure_regimes",
    )
    if spec.circuit_breaker.rule.type == "drawdown":
        bind(
            "constraints.max_drawdown_target",
            float(spec.circuit_breaker.rule.threshold),
            source_kind="strategy_spec",
            source_path="circuit_breaker.rule.threshold",
            note="Derived from drawdown circuit-breaker semantics.",
        )

    bind(
        "evaluation_plan.strategy_validation",
        validation.model_dump(mode="json"),
        source_kind="strategy_validation",
        source_path="strategy_validation",
    )
    if decision is not None:
        bind(
            "evaluation_plan.strategy_decision",
            decision.model_dump(mode="json"),
            source_kind="strategy_decision.selected",
            source_path="selected",
        )
    if runtime_context.evidence_refs:
        bind(
            "evaluation_plan.evidence_refs",
            list(runtime_context.evidence_refs),
            source_kind="runtime_request",
            source_path="evidence_refs",
            note="Evidence linkage is carried into the executable request context.",
        )

    overlay(
        "request.dataset_version",
        runtime_context.dataset_version,
        source_kind="runtime_request",
        source_path="dataset_version",
        rationale="Dataset selection is runtime-owned and remains outside durable strategy semantics.",
    )
    overlay(
        "request.start",
        runtime_context.start,
        source_kind="runtime_request",
        source_path="start",
        rationale="Simulation window start is runtime-owned and not part of StrategySpec.",
    )
    overlay(
        "request.end",
        runtime_context.end,
        source_kind="runtime_request",
        source_path="end",
        rationale="Simulation window end is runtime-owned and not part of StrategySpec.",
    )
    overlay(
        "request.execution_model",
        runtime_context.execution_model,
        source_kind="runtime_request",
        source_path="execution_model",
        rationale="Execution model remains an internal executable concern.",
    )
    overlay(
        "request.cost_model.commission_bps",
        float(runtime_context.commission_bps),
        source_kind="runtime_request",
        source_path="commission_bps",
        rationale="Commission settings remain runtime-only cost overlays.",
    )
    overlay(
        "request.cost_model.slippage_bps",
        float(runtime_context.slippage_bps),
        source_kind="runtime_request",
        source_path="slippage_bps",
        rationale="Slippage settings remain runtime-only cost overlays.",
    )
    if runtime_context.auto_round_lot is not None:
        overlay(
            "constraints.auto_round_lot",
            bool(runtime_context.auto_round_lot),
            source_kind="runtime_request",
            source_path="auto_round_lot",
            rationale="Lot rounding belongs to executable request behavior, not durable strategy semantics.",
        )

    if decision is not None:
        selected_spec = decision.selected.spec
        if round(float(selected_spec.leverage_limit), 6) != round(float(spec.leverage_limit), 6):
            overlay(
                "constraints.leverage_limit",
                float(spec.leverage_limit),
                source_kind=leverage_source_kind,
                source_path=leverage_source_path,
                overridden_source_kind="strategy_decision.selected",
                overridden_source_path="selected.spec.leverage_limit",
                overridden_value=float(selected_spec.leverage_limit),
                rationale=(
                    "Leverage limit is compiled as an executable overlay and must not be mistaken for a "
                    "decision-owned semantic field."
                ),
            )

    runtime_overlay_count = sum(1 for row in overlays if row.source_kind == "runtime_request")
    decision_override_count = sum(1 for row in overlays if row.overridden_source_kind == "strategy_decision.selected")

    compilation_profile = build_strategy_compilation_profile(
        spec,
        validation,
        runtime_context=runtime_context,
        decision=decision,
        overlays=overlays,
    )
    compilation_policy = _COMPILATION_POLICY_CHECKER.validate(
        spec,
        validation,
        compilation_profile,
        runtime_context=runtime_context,
        decision=decision,
    )
    compile_ready = bool(validation.compile_ready) and bool(compilation_policy.compile_ready)

    if not validation.compile_ready:
        summary = (
            "Compilation plan documents the current StrategySpec-to-BacktestRequest mapping, "
            "but validation has not marked the strategy as compile-ready."
        )
    elif compilation_policy.status == "blocked":
        summary = (
            "Compilation plan documents the current StrategySpec-to-BacktestRequest mapping, "
            "but compile-policy checks have blocked one or more runtime/environment inputs."
        )
    elif overlays:
        summary = (
            f"Compilation plan maps validated strategy semantics into BacktestRequest with "
            f"{runtime_overlay_count} runtime overlay(s), {decision_override_count} decision override(s), "
            f"and compile-policy status={compilation_policy.status}."
        )
    else:
        summary = (
            "Compilation plan maps validated strategy semantics directly into BacktestRequest without overlays "
            f"and with compile-policy status={compilation_policy.status}."
        )

    return StrategyCompilationPlan(
        strategy_id=spec.strategy_id,
        strategy_version=spec.strategy_version,
        market=str(spec.market or "").upper(),
        compile_ready=compile_ready,
        validation_status=str(validation.status),
        decision_status=str(validation.decision_status),
        selected_candidate=validation.selected_candidate,
        summary=summary,
        bindings=bindings,
        overlays=overlays,
        evidence_refs=[str(ref).strip() for ref in spec.evidence_refs if str(ref).strip()],
        compilation_profile=compilation_profile,
        compilation_policy=compilation_policy,
    )


def build_strategy_compilation_profile(
    spec: StrategySpec,
    validation: StrategyValidationResult,
    *,
    runtime_context: StrategyCompileRuntimeContext,
    decision: StrategyDecision | None = None,
    overlays: list[StrategyCompilationOverlay] | None = None,
) -> StrategyCompilationProfile:
    input_policies: list[StrategyCompilationInputPolicy] = []
    override_policies: list[CompilationOverridePolicy] = []
    overlay_rows = overlays or []

    def add_policy(
        output_path: str,
        classification: CompilationInputClassification,
        configured_by: CompilationConfiguredBy,
        validated_by: CompilationValidatedBy,
        *,
        source_kind: CompilationSourceKind | None,
        source_path: str,
        rationale: str,
    ) -> None:
        input_policies.append(
            StrategyCompilationInputPolicy(
                output_path=output_path,
                classification=classification,
                configured_by=configured_by,
                validated_by=validated_by,
                source_kind=source_kind,
                source_path=source_path,
                rationale=rationale,
            )
        )

    def add_override_policy(
        output_path: str,
        classification: CompilationInputClassification,
        configured_by: CompilationConfiguredBy,
        *,
        source_kind: CompilationSourceKind,
        source_path: str,
        requires_additional_validation: bool,
        rationale: str,
    ) -> None:
        override_policies.append(
            CompilationOverridePolicy(
                output_path=output_path,
                classification=classification,
                configured_by=configured_by,
                source_kind=source_kind,
                source_path=source_path,
                requires_additional_validation=requires_additional_validation,
                rationale=rationale,
            )
        )

    add_policy(
        "request.dataset_version",
        runtime_context.dataset_version_classification,
        runtime_context.dataset_version_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="dataset_version",
        rationale="Dataset selection comes from the prepared dataset/runtime environment, not durable strategy semantics.",
    )
    add_policy(
        "request.start",
        runtime_context.window_classification,
        runtime_context.window_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="start",
        rationale="Simulation window start is chosen outside StrategySpec and enters at compile time.",
    )
    add_policy(
        "request.end",
        runtime_context.window_classification,
        runtime_context.window_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="end",
        rationale="Simulation window end is chosen outside StrategySpec and enters at compile time.",
    )
    add_policy(
        "request.execution_model",
        runtime_context.execution_model_classification,
        runtime_context.execution_model_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="execution_model",
        rationale="Execution model remains an executable/runtime concern, not a durable strategy semantic.",
    )
    add_policy(
        "environment.run_time_utc",
        runtime_context.run_time_utc_classification,
        runtime_context.run_time_utc_configured_by,
        "compilation_profile",
        source_kind="runtime_request",
        source_path="run_time_utc",
        rationale="Execution time remains an environment-bound compile input and is reviewed against market session rules.",
    )
    add_policy(
        "request.cost_model.commission_bps",
        runtime_context.cost_model_classification,
        runtime_context.cost_model_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="commission_bps",
        rationale="Commission settings are compile-time runtime inputs and should not be mistaken for strategy semantics.",
    )
    add_policy(
        "request.cost_model.slippage_bps",
        runtime_context.cost_model_classification,
        runtime_context.cost_model_configured_by,
        "not_applicable",
        source_kind="runtime_request",
        source_path="slippage_bps",
        rationale="Slippage settings are compile-time runtime inputs and should not be mistaken for strategy semantics.",
    )
    if runtime_context.auto_round_lot is not None:
        add_policy(
            "constraints.auto_round_lot",
            runtime_context.auto_round_lot_classification,
            runtime_context.auto_round_lot_configured_by,
            "compilation_profile",
            source_kind="runtime_request",
            source_path="auto_round_lot",
            rationale="Lot-rounding enters compilation as an executable override and needs explicit ownership.",
        )

    spec_policies: list[tuple[str, str, str]] = [
        ("constraints.strategy_family", "strategy_family", "User-facing strategy family is durable strategy semantics."),
        ("constraints.rebalance", "rebalance", "Rebalance cadence is a durable strategy semantic."),
        ("constraints.lookback_days", "lookback_days", "Lookback horizon remains user-configurable strategy semantics."),
        ("constraints.signal_threshold", "signal_threshold", "Signal threshold remains user-configurable strategy semantics."),
        ("constraints.position_sizing", "position_sizing", "Position sizing model remains part of the durable strategy object."),
        ("constraints.risk_budget", "risk_budget", "Risk budget remains part of the durable strategy object."),
        ("constraints.max_position", "max_position", "Max position remains part of the durable strategy object."),
        ("constraints.stop_loss", "stop_loss", "Stop-loss semantics stay product-facing until compilation into executable constraints."),
        ("constraints.circuit_breaker", "circuit_breaker", "Circuit breaker configuration remains durable strategy semantics."),
        ("constraints.failure_regimes", "failure_regimes", "Failure regime expectations remain durable strategy semantics."),
        ("constraints.max_drawdown_target", "circuit_breaker.rule.threshold", "Max drawdown target is derived from durable circuit-breaker semantics."),
    ]
    for output_path, source_path, rationale in spec_policies:
        add_policy(
            output_path,
            "user_configurable",
            "strategy_spec",
            "strategy_validation",
            source_kind="strategy_spec",
            source_path=source_path,
            rationale=rationale,
        )

    leverage_classification: CompilationInputClassification = "user_configurable"
    leverage_validated_by: CompilationValidatedBy = "strategy_validation"
    leverage_rationale = "Leverage limit remains part of the durable strategy object when no compile-time override is applied."
    if any(row.output_path == "constraints.leverage_limit" for row in overlay_rows):
        leverage_classification = "validation_required_override"
        leverage_validated_by = "compilation_profile"
        leverage_rationale = (
            "Leverage limit crosses the compile boundary as an override-sensitive field and must not be mistaken for a "
            "purely decision-owned semantic."
        )
    add_policy(
        "constraints.leverage_limit",
        leverage_classification,
        "strategy_spec",
        leverage_validated_by,
        source_kind="strategy_spec.constraints" if isinstance(spec.constraints, dict) and "leverage_limit" in spec.constraints else "strategy_spec",
        source_path="constraints.leverage_limit" if isinstance(spec.constraints, dict) and "leverage_limit" in spec.constraints else "leverage_limit",
        rationale=leverage_rationale,
    )

    for row in overlay_rows:
        if row.output_path == "request.dataset_version":
            add_override_policy(
                row.output_path,
                runtime_context.dataset_version_classification,
                runtime_context.dataset_version_configured_by,
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=False,
                rationale="Dataset binding is environment/runtime-selected at compile time.",
            )
        elif row.output_path in {"request.start", "request.end"}:
            add_override_policy(
                row.output_path,
                runtime_context.window_classification,
                runtime_context.window_configured_by,
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=False,
                rationale="Window bounds enter compilation from flow-specific runtime/request context.",
            )
        elif row.output_path == "request.execution_model":
            add_override_policy(
                row.output_path,
                runtime_context.execution_model_classification,
                runtime_context.execution_model_configured_by,
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=False,
                rationale="Execution model is environment-owned and stays outside durable strategy semantics.",
            )
        elif row.output_path in {"request.cost_model.commission_bps", "request.cost_model.slippage_bps"}:
            add_override_policy(
                row.output_path,
                runtime_context.cost_model_classification,
                runtime_context.cost_model_configured_by,
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=False,
                rationale="Cost settings are compile-time runtime inputs rather than durable strategy semantics.",
            )
        elif row.output_path == "constraints.auto_round_lot":
            add_override_policy(
                row.output_path,
                runtime_context.auto_round_lot_classification,
                runtime_context.auto_round_lot_configured_by,
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=runtime_context.auto_round_lot_classification == "validation_required_override",
                rationale="Lot-rounding is an executable override that should stay explicit at compile time.",
            )
        elif row.output_path == "constraints.leverage_limit":
            add_override_policy(
                row.output_path,
                "validation_required_override",
                "strategy_spec",
                source_kind=row.source_kind,
                source_path=row.source_path,
                requires_additional_validation=True,
                rationale=(
                    "Leverage limit can differ from decision-selected semantics after compile-time overlays, so this "
                    "path stays under explicit override policy."
                ),
            )

    counts = {
        "user_configurable": sum(1 for row in input_policies if row.classification == "user_configurable"),
        "environment_bound": sum(1 for row in input_policies if row.classification == "environment_bound"),
        "runtime_derived": sum(1 for row in input_policies if row.classification == "runtime_derived"),
        "validation_required_override": sum(
            1 for row in input_policies if row.classification == "validation_required_override"
        ),
    }
    summary = (
        f"{counts['user_configurable']} user-configurable path(s), "
        f"{counts['environment_bound']} environment-bound path(s), "
        f"{counts['runtime_derived']} runtime-derived path(s), and "
        f"{counts['validation_required_override']} validation-required override path(s) feed this BacktestRequest."
    )
    if decision is not None and validation.decision_status == "aligned":
        summary += " Decision-selected semantics remain separate from compile-time executable overlays."

    return StrategyCompilationProfile(
        summary=summary,
        input_policies=input_policies,
        override_policies=override_policies,
    )
