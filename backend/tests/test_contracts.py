from openfinance.agents.schemas import AgentOutput
from openfinance.data.contracts.instruments import Instrument, TradingHours, TradingSession
from openfinance.quant.backtest.report import BacktestReport, BacktestRequest
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.report import DecayPoint, FactorReport
from openfinance.trading.domain import Order


def test_instrument_contract() -> None:
    instrument = Instrument(
        instrument_id="us_eq_aapl",
        symbol="AAPL",
        asset_class="equity",
        venue="NASDAQ",
        currency="USD",
        tick_size=0.01,
        lot_size=1,
        trading_hours=TradingHours(
            timezone="America/New_York",
            sessions=[TradingSession(start="09:30", end="16:00")],
        ),
    )
    assert instrument.symbol == "AAPL"


def test_factor_spec_contract() -> None:
    spec = FactorSpec(
        factor_id="value_basic",
        factor_version="0.1.0",
        description="Simple value factor",
        inputs=[FactorInput(name="pe_ratio", source="fundamentals")],
        validation_plan=ValidationPlan(
            in_sample_start="2020-01-01",
            in_sample_end="2022-12-31",
            out_sample_start="2023-01-01",
            out_sample_end="2024-12-31",
        ),
    )
    assert spec.inputs[0].availability_lag == "0s"


def test_backtest_report_contract() -> None:
    request = BacktestRequest(
        dataset_version="ds_v1",
        strategy_id="mean_reversion",
        strategy_version="0.1.0",
        market="US",
        start="2020-01-01",
        end="2024-01-01",
    )
    report = BacktestReport(
        dataset_version=request.dataset_version,
        strategy_version=request.strategy_version,
    )
    assert report.dataset_version == "ds_v1"
    assert isinstance(report.factor_versions, list)


def test_agent_output_contract() -> None:
    output = AgentOutput(summary="ok", confidence=0.8)
    assert output.summary == "ok"


def test_factor_report_contract() -> None:
    report = FactorReport(
        factor_id="momentum_1d",
        factor_version="0.1.0",
        dataset_version="ds_v1",
        market="US",
        observation_count=120,
        ic_mean=0.02,
        ic_std=0.11,
        rank_ic_mean=0.03,
        rank_ic_std=0.09,
        t_stat=2.1,
        decay_curve=[DecayPoint(lag=1, ic=0.02), DecayPoint(lag=2, ic=0.01)],
    )
    assert report.factor_id == "momentum_1d"


def test_trading_domain_contract() -> None:
    order = Order(
        instrument_id="us_eq_aapl",
        side="buy",
        quantity=100,
        order_type="market",
    )
    assert order.status == "new"
