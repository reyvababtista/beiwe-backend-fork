dev-up-build-detach:
	$(MAKE) dev-base-build
	$(MAKE) dev-build args=-d
	$(MAKE) dev-migrate
	$(MAKE) dev-collect-static

dev-up-build:
	$(MAKE) dev-base-build
	$(MAKE) dev-build

dev-post-build:
	$(MAKE) dev-migrate
	$(MAKE) dev-collect-static

dev-base-build:
	@echo "\n\n\nBuilding base image.."
	docker build -f docker_management/backend/dev.base.Dockerfile -t beiwe-server-dev-base .

dev-build:
	@echo "\n\n\nBuilding images and running containers.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file docker_management/.envs/.env.dev up --build $(args)

dev-migrate:
	@echo "\n\n\nMigrating database.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file docker_management/.envs/.env.dev exec -u 0 web python manage.py migrate --noinput

dev-collect-static:
	@echo "\n\n\nCollecting static files.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file docker_management/.envs/.env.dev exec -u 0 web python manage.py collectstatic --no-input --clear

prod-up-build-detach:
	$(MAKE) prod-base-build
	$(MAKE) prod-build args=-d
	$(MAKE) prod-migrate
	$(MAKE) prod-collect-static

prod-up-build:
	$(MAKE) prod-base-build
	$(MAKE) prod-build

prod-post-build:
	$(MAKE) prod-migrate
	$(MAKE) prod-collect-static

prod-base-build:
	@echo "\n\n\nBuilding base image.."
	docker build -f docker_management/backend/prod.base.Dockerfile -t beiwe-server-prod-base .

prod-build:
	@echo "\n\n\nBuilding images and running containers.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file docker_management/.envs/.env.prod up --build $(args)

prod-migrate:
	@echo "\n\n\nMigrating database.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file docker_management/.envs/.env.prod exec -u 0 web python manage.py migrate --noinput

prod-collect-static:
	@echo "\n\n\nCollecting static files.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file docker_management/.envs/.env.prod exec -u 0 web python manage.py collectstatic --no-input --clear