#!/bin/bash

source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
install_python3 3.11
pip3.11 install --upgrade pip 
mkdir -p app
echo "############# Python Version #################"
python3 -V
