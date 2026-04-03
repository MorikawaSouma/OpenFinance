"use client";

import Link from "next/link";
import { useMemo } from "react";
import { CheckCircle2, Circle, Download, Play } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import {
  usePipelineWorkspaceActions,
  usePipelineWorkspaceState,
} from "@/components/providers/pipeline-workspace-provider";
import { useWorkbenchShellActions, useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";

const stepOrder = [
  "plan.compose",
  "evidence.pack",
  "factor.define",
  "strategy.compose",
  "dataset.prepare",
  "backtest.run",
  "paper.trade",
  "risk.explain",
];

function validationBadgeVariant(status: string) {
  if (status === "invalid") return "destructive" as const;
  if (status === "warn") return "warning" as const;
  return "success" as const;
}

function compilePolicyBadgeVariant(status: string) {
  if (status === "blocked") return "destructive" as const;
  if (status === "allowed_with_warning") return "warning" as const;
  return "success" as const;
}

function formatCompilePolicyToken(value: string) {
  return value.replace(/_/g, " ");
}

function formatCompileValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value == null) return "null";
  try {
    const text = JSON.stringify(value);
    return text.length > 120 ? `${text.slice(0, 117)}...` : text;
  } catch {
    return "[unserializable]";
  }
}

export default function PipelinePage() {
  const { mode } = useWorkbenchShellState();
  const { pushToast } = useWorkbenchShellActions();
  const {
    question,
    market,
    highTurnoverMode,
    autoAdjustForRules,
    confirmMigrationRisk,
    running,
    preflightWarnings,
    displayPipeline,
    pipelineInProgress,
  } = usePipelineWorkspaceState();
  const {
    setQuestion,
    setMarket,
    setHighTurnoverMode,
    setAutoAdjustForRules,
    setConfirmMigrationRisk,
    runPipeline,
  } = usePipelineWorkspaceActions();

  const frameworkSections = useMemo(() => {
    const plan = displayPipeline?.research_plan;
    if (!plan) return [];
    return [
      { key: "value", label: "Value", payload: plan.value },
      { key: "macro", label: "Macro", payload: plan.macro },
      { key: "stats", label: "Stats", payload: plan.stats },
      { key: "behavior", label: "Behavior", payload: plan.behavior },
    ];
  }, [displayPipeline]);

  async function onRun() {
    await runPipeline();
  }

  async function exportAuditBundle() {
    if (!displayPipeline) return;
    try {
      const logs = await api.getAudit(mode === "developer" ? displayPipeline.trace_id : undefined);
      const blob = new Blob([JSON.stringify({ pipeline: displayPipeline, logs }, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_bundle_${displayPipeline.run_id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast("Export failed", err instanceof Error ? err.message : "Unknown error", "error");
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>Pipeline Timeline</CardTitle>
            <CardDescription>Plan to evidence to factors to strategy to multi-run backtest.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={exportAuditBundle} disabled={!displayPipeline}>
              <Download className="mr-1 h-4 w-4" />
              Export Audit Bundle
            </Button>
            <Button onClick={onRun} disabled={running}>
              <Play className="mr-1 h-4 w-4" />
              {running ? "Running..." : "Run End-to-End"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter a research question. The system generates a plan and runs migration preflight."
              className="min-w-[260px] flex-1"
            />
            <select
              value={market}
              onChange={(e) => setMarket(e.target.value)}
              className="h-10 rounded-md border bg-background px-2 text-sm"
            >
              {["US", "CN", "JP", "CRYPTO"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <Badge variant={mode === "developer" ? "warning" : "success"}>
              {mode === "developer" ? "Developer Mode" : "User Mode"}
            </Badge>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={highTurnoverMode} onChange={(e) => setHighTurnoverMode(e.target.checked)} />
              High-frequency / intraday profile
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={autoAdjustForRules} onChange={(e) => setAutoAdjustForRules(e.target.checked)} />
              Auto-adjust to market rules
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={confirmMigrationRisk} onChange={(e) => setConfirmMigrationRisk(e.target.checked)} />
              Confirm migration risk and continue
            </label>
          </div>
        </CardContent>
      </Card>

      {preflightWarnings.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Migration Preflight</CardTitle>
            <CardDescription>
              Pre-run market structure warnings for T+1, lot size, and trading session differences.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {preflightWarnings.map((row, idx) => (
              <div key={`${row.code}-${row.variant_id ?? "global"}-${idx}`} className="rounded-md border p-2">
                <div className="flex items-center gap-2">
                  <Badge variant={row.severity === "block" ? "destructive" : "warning"}>{row.severity}</Badge>
                  <p className="font-semibold">
                    [{row.market}] {row.title}
                  </p>
                </div>
                <p className="mt-1 text-muted-foreground">{row.explanation}</p>
                {row.suggestion ? <p className="mt-1 text-foreground">Suggestion: {row.suggestion}</p> : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {pipelineInProgress ? (
        <Card>
          <CardHeader>
            <CardTitle>Executing...</CardTitle>
            <CardDescription>Preparing full timeline and report assets.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {stepOrder.map((step) => (
              <Skeleton key={step} className="h-12 w-full" />
            ))}
          </CardContent>
        </Card>
      ) : null}

      {!displayPipeline ? (
        <EmptyState title="No pipeline run yet" description="Run once to generate plan and experiment comparison." />
      ) : (
        <>
          <Card>
            <CardHeader className="md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Stepper</CardTitle>
                <CardDescription>Each step card expands input/output summary.</CardDescription>
              </div>
              <Button asChild variant="secondary">
                <Link href={`/reports/${displayPipeline.run_id}`}>Open Run Report</Link>
              </Button>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3">
                {displayPipeline.steps.map((step, idx) => {
                  const done = step.status === "done";
                  return (
                    <li key={`${step.name}-${idx}`} className="rounded-lg border p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          {done ? <CheckCircle2 className="h-4 w-4 text-success" /> : <Circle className="h-4 w-4 text-muted-foreground" />}
                          <p className="text-sm font-semibold">{step.name}</p>
                        </div>
                        <Badge variant={done ? "success" : "warning"}>{step.status}</Badge>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Plan Snapshot</CardTitle>
              <CardDescription>Question-specific objectives and four-lens framework.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2 text-xs text-muted-foreground">
              <p>plan_id: {displayPipeline.plan_id}</p>
              <p>objectives: {displayPipeline.research_plan.objectives.join(", ")}</p>
              <p>families: {displayPipeline.research_plan.candidate_strategy_families.join(", ")}</p>
              {frameworkSections.length > 0 ? (
                <Tabs defaultValue="value">
                  <TabsList>
                    {frameworkSections.map((section) => (
                      <TabsTrigger key={`framework-tab-${section.key}`} value={section.key}>
                        {section.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {frameworkSections.map((section) => (
                    <TabsContent key={`framework-content-${section.key}`} value={section.key}>
                      <p>{(section.payload?.hypotheses ?? []).join(" | ") || "-"}</p>
                    </TabsContent>
                  ))}
                </Tabs>
              ) : null}
            </CardContent>
          </Card>

          {displayPipeline.strategy_spec ? (
            <Card>
              <CardHeader>
                <CardTitle>Selected Strategy Spec</CardTitle>
                <CardDescription>
                  Product-facing strategy semantics. The executable backtest request remains an internal runtime object.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 text-sm md:grid-cols-2">
                <p>strategy_id: <span className="font-medium">{displayPipeline.strategy_spec.strategy_id}</span></p>
                <p>strategy_version: <span className="font-medium">{displayPipeline.strategy_spec.strategy_version}</span></p>
                <p>strategy_family: <span className="font-medium">{displayPipeline.strategy_spec.strategy_family}</span></p>
                <p>market: <span className="font-medium">{displayPipeline.strategy_spec.market}</span></p>
                <p>rebalance: <span className="font-medium">{displayPipeline.strategy_spec.rebalance}</span></p>
                <p>lookback_days: <span className="font-medium">{displayPipeline.strategy_spec.lookback_days}</span></p>
                <p>position_sizing: <span className="font-medium">{displayPipeline.strategy_spec.position_sizing}</span></p>
                <p>risk_budget: <span className="font-medium">{displayPipeline.strategy_spec.risk_budget}</span></p>
                <p>max_position: <span className="font-medium">{displayPipeline.strategy_spec.max_position}</span></p>
                <p>leverage_limit: <span className="font-medium">{displayPipeline.strategy_spec.leverage_limit}</span></p>
                <p>simulation_only: <span className="font-medium">{displayPipeline.strategy_spec.simulation_only ? "true" : "false"}</span></p>
                <p>signal_threshold: <span className="font-medium">{displayPipeline.strategy_spec.signal_threshold}</span></p>
                <div className="md:col-span-2">
                  <p className="font-medium">Rationale</p>
                  <p className="mt-1 text-xs text-muted-foreground">{displayPipeline.strategy_spec.rationale}</p>
                </div>
                <div className="md:col-span-2">
                  <p className="font-medium">Failure Regimes</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {displayPipeline.strategy_spec.failure_regimes.length > 0 ? (
                      displayPipeline.strategy_spec.failure_regimes.map((item) => (
                        <Badge key={item} variant="muted">
                          {item}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-xs text-muted-foreground">No failure regimes recorded.</span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {displayPipeline.strategy_validation ? (
            <Card>
              <CardHeader>
                <CardTitle>Strategy Validation</CardTitle>
                <CardDescription>
                  Validation artifact between the durable `StrategySpec` and the internal `BacktestRequest`.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={validationBadgeVariant(displayPipeline.strategy_validation.status)}>
                    {displayPipeline.strategy_validation.status}
                  </Badge>
                  <Badge variant="muted">
                    decision={displayPipeline.strategy_validation.decision_status}
                  </Badge>
                  <Badge variant="muted">
                    next={displayPipeline.strategy_validation.next_output}
                  </Badge>
                </div>
                <p className="text-muted-foreground">{displayPipeline.strategy_validation.summary}</p>
                <div className="grid gap-2 rounded-lg border border-dashed p-3 text-xs md:grid-cols-2">
                  <p>compile_ready: <span className="font-medium">{displayPipeline.strategy_validation.compile_ready ? "true" : "false"}</span></p>
                  <p>selected_candidate: <span className="font-medium">{displayPipeline.strategy_validation.selected_candidate ?? "n/a"}</span></p>
                  <p>validated_object: <span className="font-medium">{displayPipeline.strategy_validation.validated_object}</span></p>
                  <p>evidence_refs: <span className="font-medium">{displayPipeline.strategy_validation.evidence_refs.length}</span></p>
                </div>
                <div className="space-y-2">
                  {displayPipeline.strategy_validation.checks.map((check) => (
                    <div key={check.check_id} className="rounded-lg border p-3 text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        <Badge variant={validationBadgeVariant(check.status)}>{check.status}</Badge>
                        <span className="font-medium text-foreground">{check.check_id}</span>
                      </div>
                      <p className="mt-2">{check.detail}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {displayPipeline.strategy_compilation ? (
            <Card>
              <CardHeader>
                <CardTitle>Strategy Compilation</CardTitle>
                <CardDescription>
                  Typed compile mapping from validated `StrategySpec` into the internal `BacktestRequest`.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={validationBadgeVariant(displayPipeline.strategy_compilation.validation_status)}>
                    {displayPipeline.strategy_compilation.validation_status}
                  </Badge>
                  <Badge variant="muted">
                    target={displayPipeline.strategy_compilation.executable_object}
                  </Badge>
                  <Badge variant="muted">
                    decision={displayPipeline.strategy_compilation.decision_status}
                  </Badge>
                  {displayPipeline.strategy_compilation.compilation_policy ? (
                    <Badge variant={compilePolicyBadgeVariant(displayPipeline.strategy_compilation.compilation_policy.status)}>
                      policy={displayPipeline.strategy_compilation.compilation_policy.status}
                    </Badge>
                  ) : null}
                </div>
                <p className="text-muted-foreground">{displayPipeline.strategy_compilation.summary}</p>
                <div className="grid gap-2 rounded-lg border border-dashed p-3 text-xs md:grid-cols-2">
                  <p>compile_ready: <span className="font-medium">{displayPipeline.strategy_compilation.compile_ready ? "true" : "false"}</span></p>
                  <p>selected_candidate: <span className="font-medium">{displayPipeline.strategy_compilation.selected_candidate ?? "n/a"}</span></p>
                  <p>bindings: <span className="font-medium">{displayPipeline.strategy_compilation.bindings.length}</span></p>
                  <p>overlays: <span className="font-medium">{displayPipeline.strategy_compilation.overlays.length}</span></p>
                </div>
                {displayPipeline.strategy_compilation.compilation_profile ? (
                  <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                    <p className="font-medium uppercase tracking-wide text-foreground">Compile Profile</p>
                    <p className="mt-2">{displayPipeline.strategy_compilation.compilation_profile.summary}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(["user_configurable", "environment_bound", "runtime_derived", "validation_required_override"] as const).map((kind) => {
                        const count = displayPipeline.strategy_compilation?.compilation_profile?.input_policies.filter((row) => row.classification === kind).length ?? 0;
                        return (
                          <Badge key={kind} variant="muted">
                            {formatCompilePolicyToken(kind)}={count}
                          </Badge>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                {displayPipeline.strategy_compilation.compilation_policy ? (
                  <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                    <p className="font-medium uppercase tracking-wide text-foreground">Compile Policy</p>
                    <p className="mt-2">{displayPipeline.strategy_compilation.compilation_policy.summary}</p>
                    <p className="mt-2">
                      rule_surface={displayPipeline.strategy_compilation.compilation_policy.rule_surface_id}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge variant={compilePolicyBadgeVariant(displayPipeline.strategy_compilation.compilation_policy.status)}>
                        {displayPipeline.strategy_compilation.compilation_policy.status}
                      </Badge>
                      <Badge variant="muted">
                        allowed={Math.max(
                          0,
                          displayPipeline.strategy_compilation.compilation_policy.checks.length
                            - displayPipeline.strategy_compilation.compilation_policy.warning_count
                            - displayPipeline.strategy_compilation.compilation_policy.blocked_count,
                        )}
                      </Badge>
                      <Badge variant="muted">
                        warning={displayPipeline.strategy_compilation.compilation_policy.warning_count}
                      </Badge>
                      <Badge variant="muted">
                        blocked={displayPipeline.strategy_compilation.compilation_policy.blocked_count}
                      </Badge>
                    </div>
                  </div>
                ) : null}
                <div className="grid gap-3 xl:grid-cols-2">
                  {displayPipeline.strategy_compilation.compilation_profile ? (
                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Configuration Boundary</p>
                      {displayPipeline.strategy_compilation.compilation_profile.input_policies.slice(0, 8).map((row) => (
                        <div key={`${row.output_path}-${row.source_path}-policy`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                          <p className="font-medium text-foreground">{row.output_path}</p>
                          <p className="mt-1">
                            class={formatCompilePolicyToken(row.classification)} / configured_by={formatCompilePolicyToken(row.configured_by)}
                          </p>
                          <p className="mt-1">
                            validated_by={formatCompilePolicyToken(row.validated_by)} / source={row.source_kind ?? "n/a"}:{row.source_path}
                          </p>
                          <p className="mt-1">{row.rationale}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <div className="space-y-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source Map</p>
                    {displayPipeline.strategy_compilation.bindings.slice(0, 10).map((row) => (
                      <div key={`${row.output_path}-${row.source_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                        <p className="font-medium text-foreground">{row.output_path}</p>
                        <p className="mt-1">source={row.source_kind} / {row.source_path}</p>
                        <p className="mt-1 break-all">{formatCompileValue(row.value)}</p>
                        {row.note ? <p className="mt-1">{row.note}</p> : null}
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Overlays</p>
                    {displayPipeline.strategy_compilation.overlays.length > 0 ? (
                      displayPipeline.strategy_compilation.overlays.map((row) => (
                        <div key={`${row.output_path}-${row.source_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                          <p className="font-medium text-foreground">{row.output_path}</p>
                          <p className="mt-1">final={formatCompileValue(row.final_value)}</p>
                          <p className="mt-1">source={row.source_kind} / {row.source_path}</p>
                          {row.overridden_source_path ? (
                            <p className="mt-1">
                              overrides={row.overridden_source_kind} / {row.overridden_source_path} ({formatCompileValue(row.overridden_value)})
                            </p>
                          ) : null}
                          <p className="mt-1">{row.rationale}</p>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                        No compile-time overlays were recorded for this pipeline result.
                      </div>
                    )}
                    {displayPipeline.strategy_compilation.compilation_profile?.override_policies.length ? (
                      <div className="space-y-2 pt-2">
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Override Policy</p>
                        {displayPipeline.strategy_compilation.compilation_profile.override_policies.map((row) => (
                          <div key={`${row.output_path}-${row.source_path}-override-policy`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                            <p className="font-medium text-foreground">{row.output_path}</p>
                            <p className="mt-1">
                              class={formatCompilePolicyToken(row.classification)} / configured_by={formatCompilePolicyToken(row.configured_by)}
                            </p>
                            <p className="mt-1">
                              source={row.source_kind}:{row.source_path} / requires_validation={row.requires_additional_validation ? "true" : "false"}
                            </p>
                            <p className="mt-1">{row.rationale}</p>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  {displayPipeline.strategy_compilation.compilation_policy ? (
                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Policy Checks</p>
                      {(displayPipeline.strategy_compilation.compilation_policy.checks.some((row) => row.outcome !== "allowed")
                        ? displayPipeline.strategy_compilation.compilation_policy.checks.filter((row) => row.outcome !== "allowed")
                        : displayPipeline.strategy_compilation.compilation_policy.checks.slice(0, 4)
                      ).map((row) => (
                        <div key={`${row.code}-${row.output_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={compilePolicyBadgeVariant(row.outcome)}>{row.outcome}</Badge>
                            <span className="font-medium text-foreground">{row.output_path}</span>
                          </div>
                          <p className="mt-1">
                            rule={row.rule_id} / code={row.code}
                          </p>
                          <p className="mt-1">
                            fact={formatCompilePolicyToken(row.fact_source)} / checked_by={formatCompilePolicyToken(row.checked_by)}
                          </p>
                          <p className="mt-1">
                            class={formatCompilePolicyToken(row.classification)} / configured_by={formatCompilePolicyToken(row.configured_by)}
                          </p>
                          <p className="mt-1">
                            requires_validation={row.requires_additional_validation ? "true" : "false"}
                          </p>
                          <p className="mt-1">{row.detail}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}
