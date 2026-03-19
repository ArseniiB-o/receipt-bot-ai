.PHONY: install run lint test

install:
	pip install -r requirements.txt

run:
	python main.py

lint:
	ruff check . --fix

test:
	@if [ -d tests ]; then pytest tests/; else echo "No tests/ directory found."; fi
