#!/bin/bash
set -e

# Base structure
mkdir -p docs/{overview,development,deployment,manage,using/clients,using/agents}

# Root index
touch docs/index.md

# --- .pages files and index.md for each top-level section ---

# Overview
cat > docs/overview/.pages <<EOF
title: Overview
nav:
  - index.md
  - features.md
  - ui.md
EOF
touch docs/overview/{index.md,features.md,ui.md}

# Development
cat > docs/development/.pages <<EOF
title: Development
nav:
  - index.md
  - building.md
  - packaging.md
EOF
touch docs/development/{index.md,building.md,packaging.md}

# Deployment
cat > docs/deployment/.pages <<EOF
title: Deployment
nav:
  - index.md
  - local.md
  - container.md
  - kubernetes.md
  - ibm-code-engine.md
  - aws.md
  - azure.md
EOF
touch docs/deployment/{index.md,local.md,container.md,kubernetes.md,ibm-code-engine.md,aws.md,azure.md}

# Manage
cat > docs/manage/.pages <<EOF
title: Management
nav:
  - index.md
  - backup.md
  - logging.md
EOF
touch docs/manage/{index.md,backup.md,logging.md}

# Using
cat > docs/using/.pages <<EOF
title: Usage
nav:
  - index.md
  - mcpgateway-wrapper.md
  - Clients: clients/index.md
  - Agents: agents/index.md
EOF
touch docs/using/{index.md,mcpgateway-wrapper.md}

# Clients
cat > docs/using/clients/.pages <<EOF
title: Clients
nav:
  - index.md
  - mcp-inspector.md
  - claude-desktop.md
  - cline.md
  - continue.md
EOF
touch docs/using/clients/{index.md,mcp-inspector.md,claude-desktop.md,cline.md,continue.md}

# Agents
cat > docs/using/agents/.pages <<EOF
title: Agents
nav:
  - index.md
  - langchain.md
  - langgraph.md
  - crewai.md
  - bee.md
EOF
touch docs/using/agents/{index.md,langchain.md,langgraph.md,crewai.md,bee.md}
