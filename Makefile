PY ?= python3
PORT ?= 8000

.PHONY: help run deps batch serve test lint clean docker docker-down demo

help:            ## Buyruqlar ro'yxati
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

run: clean deps batch serve   ## Toza bazadan: bog'liqliklar -> batch -> server

deps:            ## Bog'liqliklarni o'rnatish
	$(PY) -m pip install -q -r requirements.txt

batch:           ## Skorkartani o'rgatib natija/kredit_qarorlari.csv ni yozadi
	$(PY) -m app.pipeline --evaluate

serve:           ## API + frontend (http://localhost:$(PORT))
	$(PY) -m uvicorn app.api:app --host 0.0.0.0 --port $(PORT)

test:            ## Avtomatik testlar
	$(PY) -m pytest tests/ -q

demo:            ## Toza baza bilan to'liq demo (batch -> server)
	rm -f kredit.db*
	$(MAKE) batch
	$(MAKE) serve

docker:          ## docker compose up --build
	docker compose up --build

docker-down:     ## Konteynerlarni to'xtatish
	docker compose down -v

clean:           ## Vaqtinchalik fayllarni tozalash
	rm -f kredit.db*
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
