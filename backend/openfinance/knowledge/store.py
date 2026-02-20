import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openfinance.knowledge.evidence import EvidencePack, EvidenceSource


class EvidencePackStore:
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
                CREATE TABLE IF NOT EXISTS evidence_packs (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    credibility_score REAL NOT NULL,
                    time_relevance REAL NOT NULL DEFAULT 0.5,
                    credibility_breakdown TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(evidence_packs)").fetchall()
                if isinstance(row, tuple) and len(row) > 1
            }
            if "time_relevance" not in cols:
                conn.execute("ALTER TABLE evidence_packs ADD COLUMN time_relevance REAL NOT NULL DEFAULT 0.5")
            if "credibility_breakdown" not in cols:
                conn.execute("ALTER TABLE evidence_packs ADD COLUMN credibility_breakdown TEXT NOT NULL DEFAULT '{}'")
            conn.commit()

    def save(self, pack: EvidencePack) -> None:
        sources_payload = []
        for source in pack.sources:
            row = source.model_dump(mode="json")
            ts = source.published_at or source.timestamp
            if ts is not None:
                row["ts"] = ts.isoformat()
            else:
                row["ts"] = None
            row["uri"] = source.uri or source.url
            row["full_text_ref"] = source.full_text_ref
            row["source_type"] = source.source_type
            row["credibility_breakdown"] = source.credibility_breakdown
            sources_payload.append(row)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence_packs (
                    id, query, sources, credibility_score, time_relevance, credibility_breakdown, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(pack.evidence_pack_id),
                    pack.query,
                    json.dumps(sources_payload, ensure_ascii=False),
                    float(pack.credibility_score),
                    float(pack.time_relevance),
                    json.dumps(pack.credibility_breakdown or {}, ensure_ascii=False),
                    pack.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, pack_id: str) -> EvidencePack | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, query, sources, credibility_score, time_relevance, credibility_breakdown, created_at
                FROM evidence_packs
                WHERE id = ?
                """,
                (pack_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_pack(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, query, sources, credibility_score, time_relevance, credibility_breakdown, created_at
                FROM evidence_packs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            pack = self._row_to_pack(row)
            out.append(
                {
                    "id": str(pack.evidence_pack_id),
                    "query": pack.query,
                    "created_at": pack.created_at.isoformat(),
                    "credibility_score": pack.credibility_score,
                    "time_relevance": pack.time_relevance,
                    "source_count": len(pack.sources),
                    "sources": [source.model_dump(mode="json") for source in pack.sources],
                    "credibility_breakdown": pack.credibility_breakdown,
                }
            )
        return out

    def _row_to_pack(self, row: tuple[Any, ...]) -> EvidencePack:
        raw_sources = json.loads(row[2] or "[]")
        sources: list[EvidenceSource] = []
        for raw in raw_sources:
            source = dict(raw)
            if "ts" in source and source.get("published_at") is None:
                source["published_at"] = source.get("ts")
            if "ts" in source and source.get("timestamp") is None:
                source["timestamp"] = source.get("ts")
            if "uri" in source and source.get("url") is None:
                source["url"] = source.get("uri")
            if "url" in source and source.get("uri") is None:
                source["uri"] = source.get("url")
            if "source_type" not in source:
                source["source_type"] = "unknown"
            if "credibility_breakdown" not in source:
                source["credibility_breakdown"] = {}
            sources.append(EvidenceSource.model_validate(source))
        raw_breakdown = row[5] if len(row) > 5 else "{}"
        parsed_breakdown = json.loads(raw_breakdown or "{}") if isinstance(raw_breakdown, str) else {}
        if len(row) > 6:
            time_relevance = row[4]
            created_at = row[6]
        elif len(row) == 5:
            time_relevance = 0.5
            created_at = row[4]
        else:
            time_relevance = 0.5
            created_at = datetime.now(UTC).isoformat()
        return EvidencePack.model_validate(
            {
                "evidence_pack_id": row[0],
                "query": row[1],
                "sources": [source.model_dump(mode="json") for source in sources],
                "credibility_score": row[3],
                "time_relevance": time_relevance,
                "credibility_breakdown": parsed_breakdown if isinstance(parsed_breakdown, dict) else {},
                "created_at": created_at,
                "key_points": [f"Loaded {len(sources)} source(s) from persistent store."],
            }
        )
