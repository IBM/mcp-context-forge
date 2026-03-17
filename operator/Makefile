IMG ?= contextforge-operator:latest

.PHONY: build
build: ## Build the operator binary
	go build -o bin/manager ./cmd/main.go

.PHONY: test
test: ## Run tests
	go test ./... -coverprofile cover.out

.PHONY: fmt
fmt: ## Run go fmt
	go fmt ./...

.PHONY: vet
vet: ## Run go vet
	go vet ./...

.PHONY: docker-build
docker-build: ## Build the container image
	docker build -f Containerfile -t $(IMG) .

.PHONY: docker-push
docker-push: ## Push the container image
	docker push $(IMG)

.PHONY: install-crd
install-crd: ## Install CRD into the cluster
	oc apply -f config/crd/bases/

.PHONY: install-rbac
install-rbac: ## Install RBAC into the cluster
	oc apply -f config/rbac/

.PHONY: deploy
deploy: install-crd install-rbac ## Deploy the operator
	oc apply -f config/manager/deployment.yaml

.PHONY: undeploy
undeploy: ## Remove the operator
	oc delete -f config/manager/deployment.yaml --ignore-not-found
	oc delete -f config/rbac/ --ignore-not-found
	oc delete -f config/crd/bases/ --ignore-not-found

.PHONY: sample
sample: ## Create a sample ContextForge instance
	oc apply -f config/samples/contextforge_v1alpha1_contextforge.yaml

.PHONY: run
run: ## Run the operator locally (outside cluster)
	go run ./cmd/main.go

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
