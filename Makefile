docker-install:
	# for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do sudo apt-get remove $pkg; done
	# Add Docker's official GPG key:
	sudo apt-get update
	sudo apt-get install ca-certificates curl
	sudo install -m 0755 -d /etc/apt/keyrings
	sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	sudo chmod a+r /etc/apt/keyrings/docker.asc

	# Add the repository to Apt sources:
	echo \
	  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
	  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
	  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
	sudo apt-get update
	sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
	sudo docker run hello-world

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
	echo "Building base image.."
	docker build -f docker_management/backend/dev.base.Dockerfile -t beiwe-server-dev-base .

dev-build:
	echo "Building images and running containers.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file ./.envs/.env.dev up --build $(args)

dev-migrate:
	echo "Migrating database.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file .envs/.env.dev exec -u 0 web python manage.py migrate --noinput

dev-collect-static:
	echo "Collecting static files.."
	docker compose -f docker_management/dev.docker-compose.yml --env-file .envs/.env.dev exec -u 0 web python manage.py collectstatic --no-input --clear

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
	echo "Building base image.."
	docker build -f docker_management/backend/prod.base.Dockerfile -t beiwe-server-prod-base .

prod-build:
	echo "Building images and running containers.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file ./.envs/.env.prod up --build $(args)

prod-migrate:
	echo "Migrating database.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file .envs/.env.prod exec -u 0 web python manage.py migrate --noinput

prod-collect-static:
	echo "Collecting static files.."
	docker compose -f docker_management/prod.docker-compose.yml --env-file .envs/.env.prod exec -u 0 web python manage.py collectstatic --no-input --clear