# Canonical commands. Every number quoted in the README or the docs is
# produced by one of these, so a claim can always be re-checked rather than
# taken on trust.
#
# `make verify` is the gate: contract, tests, latency. Run it before pushing.

.PHONY: help verify test contract latency cost demo demo-live index extract ingest web clean-derived

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

verify: test latency ## the full gate: tests then latency against contract targets

test: ## whole suite (contract gate included)
	python3 -m pytest tests/ -q

contract: ## contract gate only: invented vocabulary, non-verbatim quotes, stale TS mirror
	python3 -m pytest tests/test_contract.py -q

latency: ## measure the model-free stages against contracts/contract.json targets
	python3 -m engine.retrieval.latency_bench

cost: ## what has actually been spent, from the append-only ledger
	python3 -m engine.llm.report

demo: ## walk the engine end to end on four questions; no model calls, free
	python3 scripts/demo.py

demo-live: ## same, plus the Sonnet answer writer (costs money)
	python3 scripts/demo.py --write-answers

ingest: ## harvest + build the graph from the Federal Register (long; resumable)
	python3 -m engine.ingest.build --since 2021-01-01

index: ## rebuild the hybrid retrieval index over data/build/paragraphs.jsonl
	python3 -m engine.retrieval.index --build

extract: ## extract applicability rules and actions (metered; set a cap)
	python3 -m engine.rules.cli extract --cap 4.0

web: ## the UI against the live backend
	cd web && pnpm install && pnpm dev

# Derived artifacts only. Never touches data/raw, which is the downloaded
# corpus and expensive to refetch.
clean-derived:
	rm -f data/build/*.jsonl data/build/retrieval.db data/build/*.npy
	@echo "removed derived artifacts; data/raw is untouched"
	@echo "rebuild in dependency order: make ingest && make extract && make index"
