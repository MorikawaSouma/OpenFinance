from pathlib import Path

from openfinance.core.config import settings
from openfinance.external_adapters import MacroProviderBase, NewsProviderBase
from openfinance.knowledge.evidence import EvidencePack
from openfinance.knowledge.rag import HybridRetriever, LocalCorpusRetriever, RAGRetriever
from openfinance.knowledge.store import EvidencePackStore


def _resolve_backend_relative(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / p).resolve()


class KnowledgeService:
    def __init__(self, retriever: RAGRetriever, store: EvidencePackStore) -> None:
        self.retriever = retriever
        self.store = store

    def retrieve(self, query: str, top_k: int = 5) -> EvidencePack:
        pack = self.retriever.retrieve_evidence_pack(query=query, top_k=top_k)
        self.store.save(pack)
        return pack

    def get_pack(self, pack_id: str) -> EvidencePack | None:
        return self.store.get(pack_id)

    def list_packs(self, limit: int = 100) -> list[dict]:
        return self.store.list(limit=limit)


def build_default_knowledge_service(
    *,
    news_provider: NewsProviderBase | None = None,
    macro_provider: MacroProviderBase | None = None,
) -> KnowledgeService:
    corpus_dir = _resolve_backend_relative(settings.knowledge_corpus_dir)
    local = LocalCorpusRetriever(corpus_dir=corpus_dir)
    retriever: RAGRetriever = HybridRetriever(
        local_retriever=local,
        news_provider=news_provider,
        macro_provider=macro_provider,
    )
    store = EvidencePackStore(db_path=settings.evidence_db_file)
    return KnowledgeService(retriever=retriever, store=store)
