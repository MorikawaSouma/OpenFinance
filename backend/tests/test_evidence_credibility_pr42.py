from pathlib import Path

from openfinance.knowledge.rag import LocalCorpusRetriever


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pr42_credibility_distinguishes_promotional_vs_methodical(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write(
        corpus / "promo_note.txt",
        "\n".join(
            [
                "Promotional Alpha Report",
                "Guaranteed gains with no risk. Exclusive strategy. Buy now for amazing upside.",
                "This is the best ever product and limited time opportunity with guaranteed returns.",
            ]
        ),
    )
    _write(
        corpus / "method_note.txt",
        "\n".join(
            [
                "Methodical Factor Summary",
                "Methodology: regression on out-of-sample dataset with robustness checks.",
                "Sample size n=1200; source: exchange dataset; table 1 and figure 2 report confidence interval.",
            ]
        ),
    )
    retriever = LocalCorpusRetriever(corpus_dir=corpus)
    pack_1 = retriever.retrieve_evidence_pack("factor methodology robustness", top_k=4)
    pack_2 = retriever.retrieve_evidence_pack("factor methodology robustness", top_k=4)

    assert pack_1.credibility_breakdown
    assert isinstance(pack_1.credibility_breakdown.get("source_level"), list)
    assert (pack_1.credibility_breakdown.get("aggregate") or {}).get("final_score_mean") is not None

    score_by_title = {row.title: float(row.credibility_score) for row in pack_1.sources}
    assert "Promotional Alpha Report" in score_by_title
    assert "Methodical Factor Summary" in score_by_title
    assert score_by_title["Methodical Factor Summary"] > score_by_title["Promotional Alpha Report"]

    src_breakdowns = {row.title: row.credibility_breakdown for row in pack_1.sources}
    method_breakdown = src_breakdowns["Methodical Factor Summary"]
    promo_breakdown = src_breakdowns["Promotional Alpha Report"]
    for breakdown in [method_breakdown, promo_breakdown]:
        hard = breakdown.get("hard_signals", {})
        assert "source_type" in hard
        assert "recency" in hard
        assert "citation_density" in hard
        assert "conflict_score" in hard
        assert "semantic" in breakdown
        assert "weights" in breakdown

    assert "promotional_language" in ((promo_breakdown.get("semantic") or {}).get("tags") or [])
    assert "methods_disclosed" in ((method_breakdown.get("semantic") or {}).get("tags") or [])

    # Reproducibility: same input + same retriever(seed/anchor) -> same score and breakdown.
    score_by_title_2 = {row.title: float(row.credibility_score) for row in pack_2.sources}
    assert score_by_title == score_by_title_2
    assert pack_1.credibility_breakdown == pack_2.credibility_breakdown

