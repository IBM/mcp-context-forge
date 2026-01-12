#!/usr/bin/env bash
cd cyberfraud-mcp-management-service

echo "#############################"
echo "Running smoke tests"
echo "#############################"
python3 -m pip install --upgrade pip setuptools
python3 -m pip install uv --user
python3 -m uv run pytest tests/integration -v -s --setup-show
if [ $? != 0 ]; then
  echo "Integration test failed, exiting";
  exit 1;
fi
cd -
