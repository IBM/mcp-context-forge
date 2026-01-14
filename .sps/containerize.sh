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

source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/go_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/github_utils.sh
source $WORKSPACE/$PIPELINE_CONFIG_REPO_PATH/scripts/utilities/logger.sh

IMAGE_NAME="$(get_env app-name)"
# If it's CI build then the image tag eg: Dev_<COMMIT>_<DATE>
# If it's PR build then the image tag eg: Ft_<COMMIT>_<DATE>
BUILD_DATE="$(date +%Y%m%d%H%M%S)"
IMAGE_TAG="${IMAGE_PREFIX}_$(cat /config/git-commit)_${BUILD_DATE}"
IMAGE_TAG=${IMAGE_TAG////_}
IMAGE_BASE="${REGISTRY_URL}/${IMAGE_NAME}"
IMAGE="${IMAGE_BASE}:${IMAGE_TAG}"

IMAGE_BASE="mcpgateway/mcpgateway"
BASE_IMAGE_TAG="${IMAGE_TAG}_base"
DOCKER_REGISTRY=$(get_env artifactory-docker-full-url "docker-na.artifactory.swg-devops.com/sec-isc-team-isc-icp-docker-local")


MULTI_ARCH_BUILD=$(get_env multi-arch-build "1")
if [ $MULTI_ARCH_BUILD == "1" ]; then
   echo "Building multi architecture image"
   BASE_IMAGE_REPO="${DOCKER_REGISTRY}/${IMAGE_BASE}:${BASE_IMAGE_TAG}"
   sed -i "s%BASE_IMAGE_REPO%${BASE_IMAGE_REPO}%g" Containerfile.cyberfraud
   make REGISTRY="${DOCKER_REGISTRY}" IMAGE_BASE="$IMAGE_BASE" IMAGE_TAG="$BASE_IMAGE_TAG" CONTAINER_RUNTIME=docker CONTAINER_FILE=./Containerfile.lite  container-build-multi && \
   make REGISTRY="${DOCKER_REGISTRY}" IMAGE_BASE="${IMAGE_NAME}" IMAGE_TAG="${IMAGE_TAG}" CONTAINER_RUNTIME=docker CONTAINER_FILE=./Containerfile.cyberfraud  container-build-multi;
else
   echo "Building single architecture image"
   BASE_IMAGE_REPO="${IMAGE_BASE}:${BASE_IMAGE_TAG}"
   sed -i "s%BASE_IMAGE_REPO%${BASE_IMAGE_REPO}%g" Containerfile.cyberfraud
   make IMAGE_BASE="$IMAGE_BASE" IMAGE_TAG="$BASE_IMAGE_TAG" docker-prod && \
   make IMAGE_BASE="$IMAGE_NAME" IMAGE_TAG="${IMAGE_TAG}" CONTAINER_RUNTIME=docker CONTAINER_FILE=./Containerfile.cyberfraud container-build && \
   docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE}" && \
   docker push "${IMAGE}"
fi


MCP_GATEWAY_IMAGE_TAG="${IMAGE_TAG}"
RUN_SMOKE_TESTS=$(get_env run-smoke-tests "1")
if [ $RUN_SMOKE_TESTS == "1" ]; then
   source ./.sps/run_smoke_test.sh
else
   echo "run-smoke-tests set to 0; Skipping smoke tests"
fi

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
