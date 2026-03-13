# AGENTS.md

## Mission
This repository should produce a mechanism-first project explainer for OpenFinance, not a changelog, not a README rewrite, and not a file-by-file inventory.

The target output is an HTML article that helps a non-expert reader truly understand:
- how data is generated, stored, reused, and traced
- how multiple agents collaborate across tasks and stages
- how explainability is exposed without revealing private chain-of-thought
- how reasoning is represented operationally
- how plans, factors, strategies, backtests, reports, and approvals connect
- how the system behaves as a reproducible research-and-risk workbench rather than a demo chatbot

## Hard rules
- Do not write a file listing disguised as documentation.
- Do not paste code blocks unless a tiny snippet is essential to explain a mechanism.
- Do not narrate in chronological README style.
- Do not claim any mechanism that is not grounded in the repository.
- Distinguish clearly between:
  - user-visible behavior
  - backend orchestration
  - persisted artifacts
  - audit/explainability surfaces
- Prefer causal explanation over surface description.
- Every section should answer “how it works” or “why it is designed this way”.
- Write in Chinese.
- The final output should be HTML, readable as a standalone article.

## Writing standard
Assume the reader is intelligent but unfamiliar with the project.
The writing must be concrete, plain, and mechanism-driven.
Explain terms before using them.
Avoid empty academic phrases and marketing language.
Avoid “this module is responsible for...” repeated mechanically.

## Required workflow
1. Read the repository and infer the true execution loop of the system.
2. Build a concept map:
   user request -> task -> pipeline -> agent/tool/artifact events -> persisted registry -> report/evidence/risk outputs.
3. Extract the system’s data lineage and control flow separately.
4. Explain explainability surfaces separately from hidden reasoning.
5. Explain factor/strategy generation as a constrained process, not as magical LLM output.
6. Draft HTML.
7. Review for unsupported claims, repetition, and unreadable jargon.
8. Revise until the article reads like a serious internal architecture explainer.

## Output shape
Produce a single HTML document with:
- title
- abstract/overview
- section navigation
- diagrams described in words when images are unavailable
- conclusion
- appendix: terminology glossary