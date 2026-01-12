#!/usr/bin/env bash
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
install_python3 3.11

cd cyberfraud-mcp-management-service

echo "#############################"
echo "Running smoke tests"
echo "#############################"
python3 -m pip install --upgrade pip setuptools
python3 -m pip install uv --user
alias uv="python3 -m uv"
python3 -m uv run pytest tests/integration -v -s --setup-show
if [ $? != 0 ]; then
  echo "Integration test failed, exiting";
  exit 1;
fi
cd -
