from openfinance.markets.plugins import CNMarketRules, JPMarketRules
from openfinance.quant.backtest.migration import MigrationChecker


def test_migration_checker_flags_cn_t_plus_one_for_high_frequency() -> None:
    checker = MigrationChecker()
    warnings = checker.check(
        {
            "strategy_family": "trend",
            "rebalance": "daily",
            "lookback_days": 2,
            "auto_round_lot": False,
            "max_position": 0.12,
            "leverage_limit": 1.0,
        },
        "CN",
        CNMarketRules(),
    )
    assert any(item.code == "cn_t_plus_one_high_frequency" for item in warnings)


def test_migration_checker_flags_session_coverage_gap_for_jp_default_utc_close() -> None:
    checker = MigrationChecker()
    warnings = checker.check(
        {
            "strategy_family": "trend",
            "rebalance": "weekly",
            "lookback_days": 20,
            "run_time_utc": "16:00",
        },
        "JP",
        JPMarketRules(),
    )
    assert any(item.code == "trading_session_coverage_gap" for item in warnings)
