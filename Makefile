.PHONY: install run lint test audit docker-build docker-up docker-down

install:
	pip install -r requirements.txt

run:
	python main.py

lint:
	ruff check . --fix

test:
	@if [ -d tests ]; then \
	  pytest tests/ -v --tb=short; \
	else \
	  echo "No tests/ directory found."; \
	fi

# Vulnerability audit — requires pip-audit
audit:
	@which pip-audit > /dev/null 2>&1 || pip install pip-audit
	pip-audit -r requirements.txt

docker-build:
	docker build -t receipt-bot:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

# Check for any bare 'except Exception' in the codebase
check-bare-except:
	@grep -rn "except Exception:" --include="*.py" . | grep -v "test_" | grep -v ".pyc" \
	  && echo "WARNING: bare except Exception found (see above)" \
	  || echo "OK: no bare except Exception found"
