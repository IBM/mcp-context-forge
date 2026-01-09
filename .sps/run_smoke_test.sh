#!/usr/bin/env bash
pushd
cd cyberfraud-mcp-management-service

echo "#############################"
echo "Running smoke tests"
echo "#############################"
uv run pytest tests/integration -v -s --setup-show
if [ $? != 0 ]; then
  echo "Integration test failed, exiting";
  exit 1;
fi
popd
