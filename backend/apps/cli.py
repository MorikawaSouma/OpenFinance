import argparse
import json
from datetime import date

from openfinance.core.config import settings
from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def cmd_generate_mock(args: argparse.Namespace) -> None:
    config = MockDatasetConfig(
        dataset_id=args.dataset_id,
        market=args.market,
        symbol=args.symbol,
        start_date=_parse_date(args.start),
        end_date=_parse_date(args.end),
        seed=args.seed,
        base_price=args.base_price,
        missing_rate_target=args.missing_rate,
        delayed_rate_target=args.delayed_rate,
        backfill_rate_target=args.backfill_rate,
        outlier_rate_target=args.outlier_rate,
        include_survivorship_bias=args.include_survivorship_bias,
    )
    factory = MockDataFactory()
    dataset = factory.generate(config)
    registry = DatasetRegistry(
        registry_file=settings.dataset_registry_file,
        data_root=settings.data_root,
    )
    entry = registry.register(dataset)
    print(
        json.dumps(
            {
                "dataset_id": entry.dataset_id,
                "dataset_version": entry.dataset_version,
                "artifact_path": entry.artifact_path,
                "quality_report": entry.quality_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_list_datasets(_: argparse.Namespace) -> None:
    registry = DatasetRegistry(
        registry_file=settings.dataset_registry_file,
        data_root=settings.data_root,
    )
    rows = [
        {
            "dataset_version": entry.dataset_version,
            "dataset_id": entry.dataset_id,
            "seed": entry.seed,
            "artifact_path": entry.artifact_path,
        }
        for entry in registry.list_entries()
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_run_backtest(args: argparse.Namespace) -> None:
    dataset_registry = DatasetRegistry(
        registry_file=settings.dataset_registry_file,
        data_root=settings.data_root,
    )
    run_registry = RunRegistry(settings.run_registry_file)
    audit_store = FileAuditStore(settings.audit_log_file)
    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=run_registry,
        audit_store=audit_store,
        report_root=settings.data_root,
    )
    request = BacktestRequest(
        dataset_version=args.dataset_version,
        strategy_id=args.strategy_id,
        strategy_version=args.strategy_version,
        market=args.market,
        start=args.start,
        end=args.end,
    )
    report = runner.run(request)
    print(
        json.dumps(
            {
                "run_id": str(report.run_id),
                "dataset_version": report.dataset_version,
                "strategy_version": report.strategy_version,
                "audit_trace_id": str(report.audit_trace_id),
                "metrics": report.metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_list_runs(_: argparse.Namespace) -> None:
    registry = RunRegistry(settings.run_registry_file)
    rows = [entry.model_dump(mode="json") for entry in registry.list_entries()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenFinance CLI")
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser("generate-mock", help="Generate and register a mock dataset")
    generate.add_argument("--dataset-id", default="mock_us_equity")
    generate.add_argument("--market", default="US")
    generate.add_argument("--symbol", default="AAPL")
    generate.add_argument("--start", required=True, help="YYYY-MM-DD")
    generate.add_argument("--end", required=True, help="YYYY-MM-DD")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--base-price", type=float, default=100.0)
    generate.add_argument("--missing-rate", type=float, default=0.01)
    generate.add_argument("--delayed-rate", type=float, default=0.02)
    generate.add_argument("--backfill-rate", type=float, default=0.01)
    generate.add_argument("--outlier-rate", type=float, default=0.005)
    generate.add_argument("--include-survivorship-bias", action="store_true")
    generate.set_defaults(func=cmd_generate_mock)

    list_datasets = subparsers.add_parser("list-datasets", help="List dataset registry entries")
    list_datasets.set_defaults(func=cmd_list_datasets)

    run_backtest = subparsers.add_parser("run-backtest", help="Run a minimal backtest")
    run_backtest.add_argument("--dataset-version", required=True)
    run_backtest.add_argument("--strategy-id", default="placeholder_strategy")
    run_backtest.add_argument("--strategy-version", default="0.1.0")
    run_backtest.add_argument("--market", default="US")
    run_backtest.add_argument("--start", required=True, help="YYYY-MM-DD")
    run_backtest.add_argument("--end", required=True, help="YYYY-MM-DD")
    run_backtest.set_defaults(func=cmd_run_backtest)

    list_runs = subparsers.add_parser("list-runs", help="List backtest runs")
    list_runs.set_defaults(func=cmd_list_runs)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        print(
            f"OpenFinance CLI | env={settings.env} | live_trading={settings.enable_live_trading}"
        )
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
