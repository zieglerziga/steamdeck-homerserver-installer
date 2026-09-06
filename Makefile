SHELL := /usr/bin/env bash
COMPOSE := sudo docker compose --env-file .env -f compose.yaml

.PHONY: help preflight prepare configure deploy verify stop backup restore upgrade

help:
	@printf '%s\n' 'preflight prepare configure deploy verify stop backup restore upgrade'

preflight:
	@./scripts/preflight.sh

prepare:
	@sudo ./scripts/prepare-host.sh

configure:
	@./scripts/configure.sh

deploy:
	@$(COMPOSE) up -d

verify:
	@./scripts/verify.sh

stop:
	@$(COMPOSE) stop

backup:
	@sudo ./scripts/backup.sh

restore:
	@test -n "$(ARCHIVE)" || { echo 'Usage: make restore ARCHIVE=/path/to/backup.tar.zst' >&2; exit 2; }
	@sudo ./scripts/restore.sh "$(ARCHIVE)"

upgrade:
	@./scripts/upgrade.sh

