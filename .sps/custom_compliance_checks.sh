#!/bin/bash

export PATH=/root/.local/bin:$PATH
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/go_utils.sh
install_python3 3.11
cp mcp-servers/go/system-monitor-server/go.* .
install_go
pip3.11 install --upgrade pip 
mkdir -p app
echo "############# Python Version #################"
python3 -V
