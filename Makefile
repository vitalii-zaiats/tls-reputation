# tls-reputation — build and publish linux/amd64 images to GHCR.
#
# The deploy targets are all pull-based: images are built here, pushed to
# ghcr.io, and Ansible only ever pulls them. Nothing is compiled on the
# servers.
#
#   make login          authenticate to ghcr.io
#   make build          build all three images for linux/amd64
#   make push           build and push all three
#   make push-backend   just one
#   make deploy         push, then run the Ansible playbook
#   make VERSION=0.2.0 push    publish an explicit version tag

REGISTRY    ?= ghcr.io
OWNER       ?= vitalii-zaiats
PROJECT     ?= tls-reputation
PLATFORM    ?= linux/amd64

# Default tag is the short commit SHA, so a deployed image is always traceable
# to a commit. `latest` moves with it. A dirty tree is marked, because an image
# built from uncommitted code should not be mistaken for a commit.
GIT_SHA     := $(shell git rev-parse --short HEAD 2>/dev/null || echo nogit)
GIT_DIRTY   := $(shell test -n "`git status --porcelain 2>/dev/null`" && echo -dirty)
VERSION     ?= $(GIT_SHA)$(GIT_DIRTY)

COMPONENTS  := backend frontend proxy
IMAGE_BASE  := $(REGISTRY)/$(OWNER)/$(PROJECT)

BUILDER     ?= tlsrep-builder

# Set by the push-* targets. Kept as plain conditionals rather than $(if ...)
# inside the recipe: a literal comma in an $(if) argument splits it, which
# silently mangles buildx flags.
ifdef PUSH
OUTPUT_FLAG := --push
CACHE_TO    := --cache-to type=registry,mode=max,ref=
else
OUTPUT_FLAG := --load
CACHE_TO    :=
endif

# A container-driver builder is what makes cross-platform builds work from an
# arm64 Mac; the default docker driver cannot emit linux/amd64 here.
define ensure_builder
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || \
		docker buildx create --name $(BUILDER) --driver docker-container --bootstrap >/dev/null
endef

define build_component
	$(call ensure_builder)
	docker buildx build \
		--builder $(BUILDER) \
		--platform $(PLATFORM) \
		--tag $(IMAGE_BASE)-$(1):$(VERSION) \
		--tag $(IMAGE_BASE)-$(1):latest \
		--label org.opencontainers.image.source=https://github.com/$(OWNER)/$(PROJECT) \
		--label org.opencontainers.image.revision=$(GIT_SHA) \
		--label org.opencontainers.image.licenses=Apache-2.0 \
		$(if $(CACHE_TO),$(CACHE_TO)$(IMAGE_BASE)-$(1):buildcache) \
		$(OUTPUT_FLAG) \
		./$(1)
endef

.PHONY: help
help:
	@sed -n 's/^#   //p' $(MAKEFILE_LIST) | head -20
	@echo
	@echo "current version tag: $(VERSION)"
	@echo "images:"
	@$(foreach c,$(COMPONENTS),echo "  $(IMAGE_BASE)-$(c):$(VERSION)";)

.PHONY: login
login:
	@echo "Needs a GitHub PAT with write:packages scope."
	@echo "  echo \$$GHCR_TOKEN | docker login ghcr.io -u $(OWNER) --password-stdin"
	@docker login $(REGISTRY)

# --- build (local, --load) --------------------------------------------------

.PHONY: build $(addprefix build-,$(COMPONENTS))
build: $(addprefix build-,$(COMPONENTS))

build-backend:  ; $(call build_component,backend)
build-frontend: ; $(call build_component,frontend)
build-proxy:    ; $(call build_component,proxy)

# --- push (build + --push) --------------------------------------------------

.PHONY: push $(addprefix push-,$(COMPONENTS))
push: $(addprefix push-,$(COMPONENTS))
	@echo
	@echo "pushed $(VERSION) — deploy with:"
	@echo "  make deploy VERSION=$(VERSION)"

push-backend:  ; @$(MAKE) build-backend  PUSH=1
push-frontend: ; @$(MAKE) build-frontend PUSH=1
push-proxy:    ; @$(MAKE) build-proxy    PUSH=1

# --- deploy -----------------------------------------------------------------

ANSIBLE_DIR   ?= ansible
ANSIBLE_FLAGS ?=

.PHONY: deploy deploy-backend deploy-frontend deploy-proxy
deploy: push
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml \
		-e tlsrep_image_tag=$(VERSION) $(ANSIBLE_FLAGS)

deploy-backend: push-backend
	cd $(ANSIBLE_DIR) && ansible-playbook backend.yml \
		-e tlsrep_image_tag=$(VERSION) $(ANSIBLE_FLAGS)

deploy-frontend: push-frontend
	cd $(ANSIBLE_DIR) && ansible-playbook frontend.yml \
		-e tlsrep_image_tag=$(VERSION) $(ANSIBLE_FLAGS)

deploy-proxy: push-proxy
	cd $(ANSIBLE_DIR) && ansible-playbook proxy.yml \
		-e tlsrep_image_tag=$(VERSION) $(ANSIBLE_FLAGS)

# --- local development ------------------------------------------------------

.PHONY: test lint dev-db
test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . ../proxy

dev-db:
	docker run -d --rm --name tlsrep-pg \
		-e POSTGRES_PASSWORD=tlsrep -e POSTGRES_USER=tlsrep -e POSTGRES_DB=tlsrep \
		-p 5432:5432 postgres:16-alpine

.PHONY: clean
clean:
	-docker buildx rm $(BUILDER)
