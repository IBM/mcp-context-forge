#!/bin/bash

export PATH=/root/.local/bin:$PATH
make test
make lint

echo "#############################"
echo "Preparing Evidence for Upload"
echo "#############################"

mkdir -p test/test_result_artifact_content
cp coverage.xml test/test_result_artifact_content/
cp coverage.xml test
