import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from openfinance.quant.factors.factor_spec import FactorSpec


class FactorRegistryEntry(BaseModel):
    factor_id: str
    version: str
    spec: dict
    dataset_schema_version: str
    inputs_signature: str
    availability_lag: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FactorRegistry:
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
                CREATE TABLE IF NOT EXISTS factors (
                    factor_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    spec TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    dataset_schema_version TEXT NOT NULL,
                    inputs_signature TEXT NOT NULL DEFAULT '',
                    availability_lag TEXT NOT NULL DEFAULT '0s',
                    PRIMARY KEY (factor_id, version)
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(factors)").fetchall()}
            if "inputs_signature" not in columns:
                conn.execute("ALTER TABLE factors ADD COLUMN inputs_signature TEXT NOT NULL DEFAULT ''")
            if "availability_lag" not in columns:
                conn.execute("ALTER TABLE factors ADD COLUMN availability_lag TEXT NOT NULL DEFAULT '0s'")
            conn.commit()

    def register(
        self,
        *,
        factor_id: str,
        version: str,
        spec: FactorSpec,
        dataset_schema_version: str,
    ) -> FactorRegistryEntry:
        existing = self.get(factor_id=factor_id, version=version)
        created_at = existing.created_at if existing is not None else datetime.now(UTC)
        payload = spec.model_dump(mode="json")
        inputs_signature = self._inputs_signature(spec)
        availability_lag = self._availability_lag(spec)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO factors
                (factor_id, version, spec, created_at, dataset_schema_version, inputs_signature, availability_lag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    factor_id,
                    version,
                    json.dumps(payload, ensure_ascii=False),
                    created_at.isoformat(),
                    dataset_schema_version,
                    inputs_signature,
                    availability_lag,
                ),
            )
            conn.commit()
        return FactorRegistryEntry(
            factor_id=factor_id,
            version=version,
            spec=payload,
            dataset_schema_version=dataset_schema_version,
            inputs_signature=inputs_signature,
            availability_lag=availability_lag,
            created_at=created_at,
        )

    def get(self, *, factor_id: str, version: str) -> FactorRegistryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT factor_id, version, spec, created_at, dataset_schema_version, inputs_signature, availability_lag
                FROM factors
                WHERE factor_id = ? AND version = ?
                """,
                (factor_id, version),
            ).fetchone()
        if row is None:
            return None
        return self._to_entry(row)

    def get_by_version(self, version: str) -> FactorRegistryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT factor_id, version, spec, created_at, dataset_schema_version, inputs_signature, availability_lag
                FROM factors
                WHERE version = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (version,),
            ).fetchone()
        if row is None:
            return None
        return self._to_entry(row)

    def list_entries(self, limit: int = 200) -> list[FactorRegistryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT factor_id, version, spec, created_at, dataset_schema_version, inputs_signature, availability_lag
                FROM factors
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._to_entry(row) for row in rows]

    def _to_entry(self, row: tuple) -> FactorRegistryEntry:
        spec = json.loads(row[2])
        return FactorRegistryEntry(
            factor_id=row[0],
            version=row[1],
            spec=spec,
            created_at=datetime.fromisoformat(row[3]),
            dataset_schema_version=row[4],
            inputs_signature=row[5] or self._inputs_signature(FactorSpec.model_validate(spec)),
            availability_lag=row[6] or self._availability_lag(FactorSpec.model_validate(spec)),
        )

    def _inputs_signature(self, spec: FactorSpec) -> str:
        parts = [f"{item.name}:{item.source}" for item in spec.inputs]
        if isinstance(spec.params.get("formula"), str):
            parts.append(f"formula:{spec.params.get('formula')}")
        return "|".join(parts)

    def _availability_lag(self, spec: FactorSpec) -> str:
        lags = sorted({item.availability_lag for item in spec.inputs if item.availability_lag})
        return ",".join(lags) if lags else "0s"
