#!/usr/bin/env bash

#!/bin/bash
#===================================================================================
#
# FILE: Copied from containerize_operand.sh
#
# USAGE: bash $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/containerize.sh
#
# GLOBALS:
#  REGISTRY_USER: artifactory user
#  REGISTRY_URL: artifactory URL
#  REGISTRY_TOKEN: artifactory token
#
# DESCRIPTION: provides functionality to containerize a microservice operand image.
# It is assumed that the repository contains a 'Dockerfile' at the root of the repository.
# The built artifact is pushed to the QRadar Suite Artifactory instance
#     set in Secrets Manager with key=taas-artifactory-url.
#==================================================================================

set -euo pipefail

echo "pipeline_namespace: $(get_env pipeline_namespace)"

# Retrive pipeline name and set the image tag prefix
if [[ "$(get_env pipeline_namespace)" == *"pr"* ]]; then
  IMAGE_PREFIX="Ft"
else
  IMAGE_PREFIX="Dev"
fi

IMAGE_NAME="$(get_env app-name)"
# If it's CI build then the image tag eg: Dev_<COMMIT>_<DATE>
# If it's PR build then the image tag eg: Ft_<COMMIT>_<DATE>
BUILD_DATE="$(date +%Y%m%d%H%M%S)"
IMAGE_TAG="${IMAGE_PREFIX}_$(cat /config/git-commit)_${BUILD_DATE}"
IMAGE_TAG=${IMAGE_TAG////_}
IMAGE_BASE="${REGISTRY_URL}/${IMAGE_NAME}"
IMAGE="${IMAGE_BASE}:${IMAGE_TAG}"

CONTAINER_FILE="./Containerfile"
make container-build

source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/go_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/github_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/logger.sh

docker tag mcpgateway/mcpgateway:latest "${IMAGE}"
docker push "${IMAGE}"

DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE}" | awk -F@ '{print $2}')"

save_artifact "${IMAGE_NAME}" \
    type=image \
    "name=${IMAGE}" \
    "digest=${DIGEST}" \
    "tags=${IMAGE_TAG}" \
    "build_date=${BUILD_DATE}"
url="$(load_repo app-repo url)"
sha="$(load_repo app-repo commit)"

save_artifact "${IMAGE_NAME}" \
    "source=${url}.git#${sha}"

# save IMAGE_TAG to file
echo $IMAGE_TAG > $WORKSPACE/operand_tag.txt

# Log image name and tags
log_info "Image Name: ${IMAGE_NAME}"
log_info "Tags: ${IMAGE_TAG}"
