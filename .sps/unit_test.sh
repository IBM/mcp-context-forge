#!/bin/bash

export PATH=/root/.local/bin:$PATH
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/python_utils.sh
install_python3 3.11
pip3.11 install --upgrade pip pytest pytest-cov sqlalchemy
mkdir -p app
echo "############# Python Version #################"
python3 -V
dnf install -y  postgresql-devel

echo "############# Running Install ################"
 make venv install install-dev
echo "############# Running Linting ##################"
make ruff autoflake isort black
echo "############# Running Install dependencies ################"
. $HOME/.venv/mcpgateway/bin/activate && \
    python3 -m uv pip install 'psycopg[c]' && \
    python3 -m uv pip install 'psycopg2' && \
    python3 -m uv pip install 'openpyxl' && \
    python3 -m uv pip install 'copier' && \
    deactivate
echo "############# Running Install DB ################"
make install-db
echo "############# Running Tests and Coverage ##################"
source $HOME/.venv/mcpgateway/bin/activate && \
		export DATABASE_URL='sqlite:///:memory:' && \
		export TEST_DATABASE_URL='sqlite:///:memory:' && \
		uv run --active pytest -p pytest_cov -n auto --maxfail=0 -v --ignore=tests/fuzz --cov=mcpgateway
coverage xml
coverage report


echo "#############################"
echo "Preparing Evidence for Upload"
echo "#############################"

mkdir -p test/test_result_artifact_content
cp coverage.xml test/test_result_artifact_content/
cp coverage.xml test
