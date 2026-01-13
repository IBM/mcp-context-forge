AWS_REGION ?= eu-west-1
ANSIBLE_EXTRA_VARS ?= ''
ANSIBLE_PLAYBOOK := ansible-playbook -i inventories/${AWS_REGION}/aws_ec2.yaml -i inventories/${AWS_REGION}/localhost.yaml -e ${ANSIBLE_EXTRA_VARS}

.PHONY: help up down playbook venv ssh exec

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ''
	@echo 'Set ANSIBLE_VERBOSITY=N to change debug level (N=0-5)'

up: venv ## Bring up infrastructure
	${ANSIBLE_PLAYBOOK} up.yaml

down: venv ## Tear down infrastructure
	ANSIBLE_COW_SELECTION=skeleton ${ANSIBLE_PLAYBOOK} down.yaml

playbook: venv ## Run a playbook from playbooks/ directory (usage: make playbook PLAYBOOK=foo)
ifndef PLAYBOOK
	@echo 'Error: PLAYBOOK variable is required'
	@echo 'Usage: make playbook PLAYBOOK=<playbook-name>'
	@echo 'Example: make playbook PLAYBOOK=ecs-up'
	@exit 1
endif
	${ANSIBLE_PLAYBOOK} playbooks/${PLAYBOOK}.yaml

venv: ## Initiailze or update the virtual environment
	[ -d ./.venv ] || uv venv --seed
	uv pip install --upgrade -r requirements.txt

ssh: ## SSH to the bastion server (requires AWS_SSH_KEY env var)
ifndef AWS_SSH_KEY
	@echo 'Error: AWS_SSH_KEY environment variable is required'
	@echo 'Usage: AWS_SSH_KEY=/path/to/key.pem make ssh'
	@exit 1
endif
	@echo 'Finding bastion server IP address...'
	@BASTION_IP=$$(aws ec2 describe-instances \
		--region ${AWS_REGION} \
		--filters "Name=tag:Role,Values=bastion" "Name=instance-state-name,Values=running" \
		--query "Reservations[0].Instances[0].PublicIpAddress" \
		--output text); \
	if [ "$$BASTION_IP" = "None" ] || [ -z "$$BASTION_IP" ]; then \
		echo 'Error: Could not find running bastion server in region ${AWS_REGION}'; \
		exit 1; \
	fi; \
	echo "Connecting to bastion at $$BASTION_IP..."; \
	ssh -i ${AWS_SSH_KEY} ubuntu@$$BASTION_IP

exec: ## Execute shell in ECS container (usage: make exec TARGET=gateway)
ifndef TARGET
	@echo 'Error: TARGET variable is required'
	@echo 'Usage: make exec TARGET=<container-name>'
	@echo 'Example: make exec TARGET=gateway'
	@exit 1
endif
	@CLUSTER=$$(aws ecs list-clusters --region ${AWS_REGION} --query "clusterArns[0]" --output text); \
	if [ "$$CLUSTER" = "None" ] || [ -z "$$CLUSTER" ]; then \
		echo 'Error: Could not find ECS cluster in region ${AWS_REGION}'; \
		exit 1; \
	fi; \
	TASK=$$(aws ecs list-tasks --region ${AWS_REGION} --cluster "$$CLUSTER" --service-name mcf-$${AWS_REGION}-dev-${TARGET}-svc --query "taskArns[0]" --output text); \
	if [ "$$TASK" = "None" ] || [ -z "$$TASK" ]; then \
		echo 'Error: Could not find running task for service ${TARGET}'; \
		exit 1; \
	fi; \
	echo "Connecting to ${TARGET} container in cluster $$CLUSTER..."; \
	aws ecs execute-command --region ${AWS_REGION} --cluster "$$CLUSTER" --task "$$TASK" --container ${TARGET} --interactive --command "/bin/sh"
