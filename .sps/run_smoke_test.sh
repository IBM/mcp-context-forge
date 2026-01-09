#!/usr/bin/env bash
cd cyberfraud-mcp-management-service

echo "#############################"
echo "Running smoke tests"
echo "#############################"
pip3 install --upgrade pip
pip3 install uv --user
uv run pytest tests/integration -v -s --setup-show
if [ $? != 0 ]; then
  echo "Integration test failed, exiting";
  exit 1;
fi
cd -
