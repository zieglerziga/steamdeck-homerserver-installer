SHELL := /usr/bin/env bash
COMPOSE := sudo docker compose --env-file .env -f compose.yaml

.PHONY: help dependencies preflight prepare configure deploy verify guard-reset stop backup restore upgrade

help:
	@printf '%s\n' 'dependencies preflight prepare configure deploy verify guard-reset stop backup restore upgrade'

dependencies:
	@./scripts/install-dependencies.sh

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

guard-reset:
	@sudo --preserve-env=LAN_IP ./scripts/disk_guard.py reset

stop:
	@$(COMPOSE) stop

backup:
	@sudo ./scripts/backup.sh

restore:
	@test -n "$(ARCHIVE)" || { echo 'Usage: make restore ARCHIVE=/path/to/backup.tar.zst' >&2; exit 2; }
	@sudo ./scripts/restore.sh "$(ARCHIVE)"

upgrade:
	@./scripts/upgrade.sh
