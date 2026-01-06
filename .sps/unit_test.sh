#!/bin/bash

export PATH=/root/.local/bin:$PATH
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
install_python3 3.11
pip3.11 install --upgrade pip pytest pytest-cov sqlalchemy

echo "############# Python Version #################"
python3 -V
echo "############# Running Install ################"
make install-dev
echo "############# Running Install psycogpg################"
source $HOME/.venv/mcpgateway/bin/activate && python3 -m uv pip install 'psycopg2'
echo "############# Running Install DB ################"
make install-db
echo "############# Running Linting ################"
make lint
echo "############# Running Tests ##################"
make test
echo "############# Running Coverage ###############"
make coverage


echo "#############################"
echo "Preparing Evidence for Upload"
echo "#############################"

mkdir -p test/test_result_artifact_content
cp coverage.xml test/test_result_artifact_content/
cp coverage.xml test
