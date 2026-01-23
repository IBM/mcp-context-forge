#!/bin/bash

export PATH=/root/.local/bin:$PATH
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/go_utils.sh
install_python3 3.11
# Go causing mend failure
rm -rf  mcp-servers/go
pip3.11 install --upgrade pip 
mkdir -p app
echo "############# Python Version #################"
python3 -V
