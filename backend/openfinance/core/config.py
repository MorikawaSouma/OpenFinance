from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_CURRENT_FILE = Path(__file__).resolve()
_BACKEND_DIR = _CURRENT_FILE.parents[2]
_REPO_ROOT = _CURRENT_FILE.parents[3]


class Settings(BaseSettings):
    app_name: str = "OpenFinance API"
    env: str = "dev"
    log_level: str = "INFO"
    enable_live_trading: bool = False
    data_root: str = ".openfinance/data"
    dataset_registry_file: str = ".openfinance/registry/datasets.jsonl"
    run_registry_file: str = ".openfinance/registry/runs.jsonl"
    plan_registry_file: str = ".openfinance/registry/plans.jsonl"
    evidence_db_file: str = ".openfinance/registry/evidence.sqlite3"
    factor_registry_db_file: str = ".openfinance/registry/factors.sqlite3"
    factor_artifact_root: str = ".openfinance/artifacts/factors"
    approval_db_file: str = ".openfinance/registry/approvals.sqlite3"
    risk_events_db_file: str = ".openfinance/registry/risk_events.sqlite3"
    chat_session_store_file: str = ".openfinance/registry/chat_sessions.json"
    task_registry_file: str = ".openfinance/registry/tasks.json"
    default_market: str = "US"
    knowledge_corpus_dir: str = "resources/corpus"
    audit_log_file: str = ".openfinance/registry/audit.jsonl"
    trading_mode: str = "research"
    kill_switch_enabled: bool = False
    risk_max_order_qty: float = 10000.0
    risk_max_account_drawdown: float = 0.05
    risk_abnormal_volatility_threshold: float = 0.03
    risk_volatility_window: int = 20
    risk_monitor_warn_ratio: float = 0.7
    risk_monitor_initial_equity: float = 1_000_000.0
    live_trading_unlock_required: bool = True
    llm_default_provider: str = "zhipu"
    zhipu_model: str = "glm-4.7"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    llm_force_stub: bool = True
    llm_require_remote: bool = False
    llm_remote_retries: int = 1
    agent_force_step_parse_error: bool = False
    task_force_error: bool = False
    pipeline_force_variant_error: bool = False
    credibility_seed: int = 42
    credibility_semantic_enabled: bool = True
    credibility_semantic_use_llm: bool = False
    credibility_weight_hard: float = 0.8
    credibility_weight_semantic: float = 0.2
    credibility_weight_source_type: float = 0.35
    credibility_weight_recency: float = 0.25
    credibility_weight_citation_density: float = 0.2
    credibility_weight_conflict: float = 0.2

    model_config = SettingsConfigDict(
        env_prefix="OPENFINANCE_",
        env_file=(str(_BACKEND_DIR / ".env"), str(_REPO_ROOT / ".env")),
        extra="ignore",
    )


settings = Settings()
