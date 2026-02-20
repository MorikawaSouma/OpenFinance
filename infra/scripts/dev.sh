#!/usr/bin/env sh
set -eu

echo "Start backend: cd backend && uvicorn openfinance.api.main:app --reload --port 8000"
echo "Start frontend: cd frontend && npm run dev"
