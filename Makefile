PYTHON ?= python
PIP ?= $(PYTHON) -m pip

.PHONY: backend-install backend-dev backend-test frontend-install frontend-dev dev dev-reset

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

dev-reset:
	$(PYTHON) infra/scripts/dev_reset.py --yes
