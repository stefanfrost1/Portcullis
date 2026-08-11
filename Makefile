# Manual/local fallback for building the images. GitHub Actions
# (.github/workflows/docker-build.yml) is the canonical builder and
# publishes to Docker Hub (simplitics1) on push.
REGISTRY ?= simplitics1
TAG      ?= latest

BACKEND_IMAGE  = $(REGISTRY)/portcullis:$(TAG)
FRONTEND_IMAGE = $(REGISTRY)/portcullis-frontend:$(TAG)

.PHONY: build build-backend build-frontend push push-backend push-frontend release

build: build-backend build-frontend

build-backend:
	docker build -t $(BACKEND_IMAGE) .

build-frontend:
	docker build -t $(FRONTEND_IMAGE) ./frontend

push: push-backend push-frontend

push-backend:
	docker push $(BACKEND_IMAGE)

push-frontend:
	docker push $(FRONTEND_IMAGE)

release: build push
