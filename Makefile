.PHONY: help dev prod down logs ps seed seed-reset build pull config clean

COMPOSE_DEV  = docker compose -f compose.yml -f compose.dev.yml --profile local-db
COMPOSE_PROD = docker compose -f compose.yml -f compose.prod.yml

help:  ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

dev:  ## Start the full dev stack (backend, frontend, scraper, n8n, mongo)
	$(COMPOSE_DEV) up --build

dev-d:  ## Same as dev, detached
	$(COMPOSE_DEV) up --build -d

prod:  ## Start the production stack (detached)
	$(COMPOSE_PROD) up -d

down:  ## Stop dev stack
	$(COMPOSE_DEV) down

down-prod:  ## Stop prod stack
	$(COMPOSE_PROD) down

logs:  ## Tail logs (dev)
	$(COMPOSE_DEV) logs -f --tail=100

ps:  ## Show running services (dev)
	$(COMPOSE_DEV) ps

seed:  ## Run DB seed inside the backend container
	$(COMPOSE_DEV) exec backend npm run seed

seed-reset:  ## DROP users/projects/competitors then reseed
	$(COMPOSE_DEV) exec backend npm run seed:reset

build:  ## Build all images (no cache-busting)
	$(COMPOSE_DEV) build

pull:  ## Pull latest third-party images (n8n, mongo, redis)
	$(COMPOSE_DEV) pull

config:  ## Validate compose files & resolved env
	$(COMPOSE_DEV) config > /dev/null && echo "dev  OK"
	$(COMPOSE_PROD) config > /dev/null && echo "prod OK"

clean:  ## Remove volumes (⚠ destroys local DB + n8n workflows)
	$(COMPOSE_DEV) down -v
