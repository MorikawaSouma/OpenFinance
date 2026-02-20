from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from openfinance.knowledge.evidence import EvidencePack
from openfinance.knowledge.service import KnowledgeService, build_default_knowledge_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@lru_cache(maxsize=1)
def _knowledge() -> KnowledgeService:
    return build_default_knowledge_service()


@router.get("/evidence/mock", response_model=EvidencePack)
def mock_evidence(query: str = Query(..., min_length=2), top_k: int = Query(default=5, ge=1, le=20)) -> EvidencePack:
    # Keep backward-compatible route path; now uses local corpus retriever + sqlite persistence.
    return _knowledge().retrieve(query=query, top_k=top_k)


@router.get("/evidence/packs")
def list_evidence_packs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return _knowledge().list_packs(limit=limit)


@router.get("/evidence/packs/{pack_id}", response_model=EvidencePack)
def get_evidence_pack(pack_id: str) -> EvidencePack:
    pack = _knowledge().get_pack(pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="evidence pack not found")
    return pack
