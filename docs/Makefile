# Author: Mihai Criveti

# Configuration section
HANDBOOK_NAME := mcpgateway-docs

# Do not change anything below this line
VENVS_DIR := $(HOME)/.venv
VENV_DIR := $(VENVS_DIR)/$(HANDBOOK_NAME)

# Setup to support M1 Macs - Linux will be empty; x86 Macs essentially NO-OP
BREW_SHELLENV := $(shell brew shellenv 2>/dev/null)

.PHONY: help
help:
	@grep "^# help\:" Makefile | grep -v grep | sed 's/\# help\: //' | sed 's/\# help\://'

# help: MAINTAIN
# help: venv                           - create a clean virtual environment for development
.PHONY: venv
venv:
	@test -d "$(VENVS_DIR)" || mkdir -p "$(VENVS_DIR)"
	@rm -Rf "$(VENV_DIR)"
	@eval '$(BREW_SHELLENV)' && python3 -m venv "$(VENV_DIR)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pip install --upgrade pip setuptools wheel && pip install markdown-blockdiag && pip install -r requirements.txt"
	@echo -e "Enter virtual environment using:\n. $(VENV_DIR)/bin/activate\n"


# help: venv-update                    - update a virtual environment for development
.PHONY: venv-update
venv-update:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pip install --upgrade pip setuptools wheel && pip install --upgrade markdown-blockdiag && pip install --upgrade -r requirements.txt"
	@echo -e "Enter virtual environment using:\n. $(VENV_DIR)/bin/activate\n"


# help: activate                       - enter existing venv
.PHONY: activate
activate:
	@echo -e "Enter virtual environment using:\n. $(VENV_DIR)/bin/activate\n"
	@. $(VENV_DIR)/bin/activate


# help: clean                          - clean all files
.PHONY: clean
clean:
	@rm -rf ./site


# help: git-clean                      - clean all files using .gitignore rules
.PHONY: git-clean
git-clean:
	@git clean -X -f -d


# help: git-scrub                      - clean all files, even untracked files
.PHONY: git-scrub
git-scrub:
	@git clean -x -f -d

# help:
# help: MKDOCS
# help: serve                          - serve project html documentation
.PHONY: serve
serve:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && mkdocs serve"

# help: build                          - serve project html documentation
.PHONY: build
build:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && mkdocs build > $(HANDBOOK_NAME).html"
	@/bin/bash -c "sed -i'' -e '1{/^Converting/d;}' $(HANDBOOK_NAME).html"
	@/bin/bash -c "sed -i'' -e 's#file://$(shell git rev-parse --show-toplevel)/##g' $(HANDBOOK_NAME).html"
	@/bin/bash -c "mkdir -p site/out"
	@/bin/bash -c "pandoc $(HANDBOOK_NAME).html -o $(HANDBOOK_NAME).docx"
	@/bin/bash -c "mv $(HANDBOOK_NAME).html site/out/"
	@/bin/bash -c "mv $(HANDBOOK_NAME).docx site/out/"

# help: package                        - package the sources for box deployment
.PHONY: package
package:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && mkdocs build && mkdir -p release && tar cvvf release/$(HANDBOOK_NAME)-Package-$$(date --iso).tar.gz --exclude='release' . "


# help: deploy                         - deploy project to github pages
.PHONY: deploy
deploy:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && mkdocs gh-deploy"

# help: combine                        - combine
.PHONY: combine
combine:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && mkdocscombine -o out/$(HANDBOOK_NAME)-combined.md"

# Keep these lines at the end of the file to retain output formatting.
# help:
