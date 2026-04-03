import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from openfinance.research.strategy_spec import StrategySpec


class StrategyRegistryEntry(BaseModel):
    strategy_id: str
    version: str
    spec: StrategySpec
    market: str
    strategy_family: str
    plan_id: str | None = None
    experiment_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StrategyRegistry:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    spec TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    market TEXT NOT NULL DEFAULT 'US',
                    strategy_family TEXT NOT NULL DEFAULT '',
                    plan_id TEXT,
                    experiment_id TEXT,
                    PRIMARY KEY (strategy_id, version)
                )
                """
            )
            conn.commit()

    def register(self, *, spec: StrategySpec) -> StrategyRegistryEntry:
        existing = self.get(strategy_id=spec.strategy_id, version=spec.strategy_version)
        created_at = existing.created_at if existing is not None else datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO strategies
                (strategy_id, version, spec, created_at, market, strategy_family, plan_id, experiment_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.strategy_id,
                    spec.strategy_version,
                    json.dumps(spec.model_dump(mode="json"), ensure_ascii=False),
                    created_at.isoformat(),
                    spec.market,
                    spec.strategy_family,
                    spec.plan_id,
                    spec.experiment_id,
                ),
            )
            conn.commit()
        return StrategyRegistryEntry(
            strategy_id=spec.strategy_id,
            version=spec.strategy_version,
            spec=spec,
            market=spec.market,
            strategy_family=spec.strategy_family,
            plan_id=spec.plan_id,
            experiment_id=spec.experiment_id,
            created_at=created_at,
        )

    def get(self, *, strategy_id: str, version: str) -> StrategyRegistryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT strategy_id, version, spec, created_at, market, strategy_family, plan_id, experiment_id
                FROM strategies
                WHERE strategy_id = ? AND version = ?
                """,
                (strategy_id, version),
            ).fetchone()
        if row is None:
            return None
        return self._to_entry(row)

    def get_by_version(self, version: str) -> StrategyRegistryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT strategy_id, version, spec, created_at, market, strategy_family, plan_id, experiment_id
                FROM strategies
                WHERE version = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (version,),
            ).fetchone()
        if row is None:
            return None
        return self._to_entry(row)

    def list_entries(self, limit: int = 200) -> list[StrategyRegistryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT strategy_id, version, spec, created_at, market, strategy_family, plan_id, experiment_id
                FROM strategies
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._to_entry(row) for row in rows]

    def _to_entry(self, row: tuple) -> StrategyRegistryEntry:
        spec = StrategySpec.model_validate(json.loads(row[2]))
        return StrategyRegistryEntry(
            strategy_id=row[0],
            version=row[1],
            spec=spec,
            created_at=datetime.fromisoformat(row[3]),
            market=row[4],
            strategy_family=row[5],
            plan_id=row[6],
            experiment_id=row[7],
        )
