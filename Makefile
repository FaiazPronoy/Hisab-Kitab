DC = docker compose
RUN = $(DC) run --rm api

up:
	$(DC) up -d --build

down:
	$(DC) down

seed:
	$(DC) exec api python -m scripts.seed_demo

test:
	$(RUN) pytest -q --junitxml=test-results/junit.xml --cov=app --cov-report=term --cov-report=xml:test-results/coverage.xml

eval:
	$(RUN) python -m eval.runner

bigpdf:
	$(RUN) python -m scripts.make_big_pdf

lint:
	$(RUN) ruff check app tests
