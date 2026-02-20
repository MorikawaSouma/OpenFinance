PYTHON ?= python
PIP ?= $(PYTHON) -m pip

.PHONY: backend-install backend-dev backend-test frontend-install frontend-dev dev docs-check dev-reset docs-build docs-utf8-check

backend-install:
	cd backend && $(PIP) install -e ".[dev]"

backend-dev:
	cd backend && uvicorn openfinance.api.main:app --reload --port 8000

backend-test:
	cd backend && pytest

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

dev:
	$(PYTHON) infra/scripts/dev_runner.py

docs-build:
	$(PYTHON) scripts/render_figures/render_all.py
	$(PYTHON) scripts/build_docs.py

docs-utf8-check:
	$(PYTHON) scripts/check_utf8.py

docs-check:
	$(PYTHON) infra/scripts/docs_check.py

dev-reset:
	$(PYTHON) infra/scripts/dev_reset.py --yes
