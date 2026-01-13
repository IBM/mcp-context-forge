#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: ecs_service
version_added: 1.0.0
short_description: Create, terminate, start or stop a service in ECS
description:
  - Creates or terminates ECS services.
notes:
  - The service role specified must be assumable. (i.e. have a trust relationship for the ecs service, ecs.amazonaws.com)
  - For details of the parameters and returns see U(https://boto3.readthedocs.io/en/latest/reference/services/ecs.html).
  - An IAM role must have been previously created.
author:
  - "Mark Chance (@Java1Guy)"
  - "Darek Kaczynski (@kaczynskid)"
  - "Stephane Maarek (@simplesteph)"
  - "Zac Blazic (@zacblazic)"
options:
    state:
        description:
          - The desired state of the service.
        required: true
        choices: ["present", "absent", "deleting"]
        type: str
    name:
        description:
          - The name of the service.
        required: true
        type: str
        aliases: ['service']
    cluster:
        description:
          - The name of the cluster in which the service exists.
          - If not specified, the cluster name will be C(default).
        required: false
        type: str
        default: 'default'
    task_definition:
        description:
          - The task definition the service will run.
          - This parameter is required when I(state=present) unless I(force_new_deployment=True).
          - This parameter is ignored when updating a service with a C(CODE_DEPLOY) deployment controller in which case
            the task definition is managed by Code Pipeline and cannot be updated.
        required: false
        type: str
    load_balancers:
        description:
          - The list of ELBs defined for this service.
          - Load balancers for an existing service cannot be updated, and it is an error to do so.
          - When the deployment controller is CODE_DEPLOY changes to this value are simply ignored, and do not cause an error.
        required: false
        type: list
        elements: dict
        default: []
    desired_count:
        description:
          - The count of how many instances of the service.
          - This parameter is required when I(state=present).
        required: false
        type: int
    client_token:
        description:
          - Unique, case-sensitive identifier you provide to ensure the idempotency of the request. Up to 32 ASCII characters are allowed.
        required: false
        type: str
        default: ''
    role:
        description:
          - The name or full Amazon Resource Name (ARN) of the IAM role that allows your Amazon ECS container agent to make calls to your load balancer
            on your behalf.
          - This parameter is only required if you are using a load balancer with your service in a network mode other than C(awsvpc).
        required: false
        type: str
        default: ''
    delay:
        description:
          - The time to wait before checking that the service is available.
        required: false
        default: 10
        type: int
    repeat:
        description:
          - The number of times to check that the service is available.
        required: false
        default: 10
        type: int
    force_new_deployment:
        description:
          - Force deployment of service even if there are no changes.
        required: false
        type: bool
        default: false
    deployment_controller:
        description:
          - The deployment controller to use for the service. If no deploymenet controller is specified, the ECS controller is used.
        required: false
        version_added: 4.1.0
        type: dict
        default: {}
        suboptions:
          type:
            type: str
            choices: ["ECS", "CODE_DEPLOY", "EXTERNAL"]
            description: The deployment controller type to use.
    deployment_configuration:
        description:
          - Optional parameters that control the deployment_configuration.
          - Format is '{"maximum_percent":<integer>, "minimum_healthy_percent":<integer>}
        required: false
        type: dict
        default: {}
        suboptions:
          maximum_percent:
            type: int
            description: Upper limit on the number of tasks in a service that are allowed in the RUNNING or PENDING state during a deployment.
          minimum_healthy_percent:
            type: int
            description: A lower limit on the number of tasks in a service that must remain in the RUNNING state during a deployment.
          deployment_circuit_breaker:
            type: dict
            description: The deployment circuit breaker determines whether a service deployment will fail if the service can't reach a steady state.
            suboptions:
              enable:
                type: bool
                description: If enabled, a service deployment will transition to a failed state and stop launching new tasks.
              rollback:
                type: bool
                description: If enabled, ECS will roll back your service to the last completed deployment after a failure.
    enable_execute_command:
        description:
          - Whether or not to enable the execute command functionality for the containers in the ECS task.
          - If I(enable_execute_command=true) execute command functionality is enabled on all containers in the ECS task.
        required: false
        type: bool
        version_added: 5.4.0
    placement_constraints:
        description:
          - The placement constraints for the tasks in the service.
          - See U(https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_PlacementConstraint.html) for more details.
        required: false
        type: list
        elements: dict
        default: []
        suboptions:
          type:
            description: The type of constraint.
            type: str
          expression:
            description: A cluster query language expression to apply to the constraint.
            required: false
            type: str
    purge_placement_constraints:
        version_added: 5.3.0
        description:
            - Toggle overwriting of existing placement constraints. This is needed for backwards compatibility.
            - By default I(purge_placement_constraints=false). In release 9.0.0 this will be changed to I(purge_placement_constraints=true).
        required: false
        type: bool
        default: false
    placement_strategy:
        description:
          - The placement strategy objects to use for tasks in your service. You can specify a maximum of 5 strategy rules per service.
        required: false
        type: list
        elements: dict
        default: []
        suboptions:
          type:
            description: The type of placement strategy.
            type: str
          field:
            description: The field to apply the placement strategy against.
            type: str
    purge_placement_strategy:
        version_added: 5.3.0
        description:
            - Toggle overwriting of existing placement strategy. This is needed for backwards compatibility.
            - By default I(purge_placement_strategy=false). In release 9.0.0 this will be changed to I(purge_placement_strategy=true).
        required: false
        type: bool
        default: false
    force_deletion:
        description:
          - Forcibly delete the service. Required when deleting a service with >0 scale, or no target group.
        default: False
        type: bool
        version_added: 2.1.0
    network_configuration:
        description:
          - Network configuration of the service. Only applicable for task definitions created with I(network_mode=awsvpc).
        type: dict
        suboptions:
          subnets:
            description:
              - A list of subnet IDs to associate with the task.
            type: list
            elements: str
          security_groups:
            description:
              - A list of security group names or group IDs to associate with the task.
            type: list
            elements: str
          assign_public_ip:
            description:
              - Whether the task's elastic network interface receives a public IP address.
            type: bool
    launch_type:
        description:
          - The launch type on which to run your service.
        required: false
        choices: ["EC2", "FARGATE"]
        type: str
    capacity_provider_strategy:
        version_added: 4.0.0
        description:
          - The capacity provider strategy to use with your service. You can specify a maximum of 6 providers per strategy.
        required: false
        type: list
        elements: dict
        default: []
        suboptions:
            capacity_provider:
                description:
                  - Name of capacity provider.
                type: str
            weight:
                description:
                  - The relative percentage of the total number of launched tasks that should use the specified provider.
                type: int
            base:
                description:
                  - How many tasks, at a minimum, should use the specified provider.
                type: int
    platform_version:
        type: str
        description:
          - Numeric part of platform version or LATEST
          - See U(https://docs.aws.amazon.com/AmazonECS/latest/developerguide/platform_versions.html) for more details.
        required: false
        version_added: 1.5.0
    health_check_grace_period_seconds:
        description:
          - Seconds to wait before health checking the freshly added/updated services.
        required: false
        type: int
    service_registries:
        description:
          - Describes service discovery registries this service will register with.
        type: list
        elements: dict
        default: []
        required: false
        suboptions:
            container_name:
                description:
                  - Container name for service discovery registration.
                type: str
            container_port:
                description:
                  - Container port for service discovery registration.
                type: int
            arn:
                description:
                  - Service discovery registry ARN.
                type: str
    service_connect_configuration:
        description:
          - The configuration for this service to discover and connect to services, and be discovered by, and connected from, other services within a namespace.
          - See U(https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ServiceConnectConfiguration.html) for more details.
        type: dict
        required: false
        version_added: 7.2.0
        suboptions:
            enabled:
                description:
                  - Specifies whether to use Service Connect with this service.
                type: bool
                required: true
            namespace:
                description:
                  - The namespace name or full Amazon Resource Name (ARN) of the AWS Cloud Map namespace for use with Service Connect.
                type: str
            services:
                description:
                  - The list of Service Connect service objects.
                type: list
                elements: dict
            log_configuration:
                description:
                  - The log configuration for the container.
                type: dict
            access_log_configuration:
                description:
                  - The access log configuration for Service Connect.
                type: dict
    scheduling_strategy:
        description:
          - The scheduling strategy.
          - Defaults to C(REPLICA) if not given to preserve previous behavior.
        required: false
        choices: ["DAEMON", "REPLICA"]
        type: str
    wait:
        description:
          - Whether or not to wait for the service to reach the desired state.
          - When I(state=present), waits for the service to be stable with tasks in the RUNNING state.
          - When I(state=absent), waits for the service to be inactive.
        type: bool
        default: false
        version_added: 4.1.0
    propagate_tags:
        description:
          - Propagate tags from ECS task defintition or ECS service to ECS task.
        required: false
        choices: ["TASK_DEFINITION", "SERVICE"]
        type: str
        version_added: 4.1.0
    tags:
        description:
          - A dictionary of tags to add or remove from the resource.
        type: dict
        required: false
        version_added: 4.1.0
extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""
# Note: These examples do not set authentication details, see the AWS Guide for details.
# Basic provisioning example
- community.aws.ecs_service:
    state: present
    name: console-test-service
    cluster: new_cluster
    task_definition: 'new_cluster-task:1'
    desired_count: 0

- name: create ECS service on VPC network
  community.aws.ecs_service:
    state: present
    name: console-test-service
    cluster: new_cluster
    task_definition: 'new_cluster-task:1'
    desired_count: 0
    network_configuration:
      subnets:
        - subnet-abcd1234
      security_groups:
        - sg-aaaa1111
        - my_security_group

# Simple example to delete
- community.aws.ecs_service:
    name: default
    state: absent
    cluster: new_cluster

# With custom deployment configuration (added in version 2.3), placement constraints and strategy (added in version 2.4)
- community.aws.ecs_service:
    state: present
    name: test-service
    cluster: test-cluster
    task_definition: test-task-definition
    desired_count: 3
    deployment_configuration:
      minimum_healthy_percent: 75
      maximum_percent: 150
    placement_constraints:
      - type: memberOf
        expression: 'attribute:flavor==test'
    placement_strategy:
      - type: binpack
        field: memory

# With deployment circuit breaker (added in version 4.0)
- community.aws.ecs_service:
    state: present
    name: test-service
    cluster: test-cluster
    task_definition: test-task-definition
    desired_count: 3
    deployment_configuration:
      deployment_circuit_breaker:
        enable: true
        rollback: true

# With capacity_provider_strategy (added in version 4.0)
- community.aws.ecs_service:
    state: present
    name: test-service
    cluster: test-cluster
    task_definition: test-task-definition
    desired_count: 1
    capacity_provider_strategy:
      - capacity_provider: test-capacity-provider-1
        weight: 1
        base: 0

# With tags and tag propagation
- community.aws.ecs_service:
    state: present
    name: tags-test-service
    cluster: new_cluster
    task_definition: 'new_cluster-task:1'
    desired_count: 1
    tags:
      Firstname: jane
      lastName: doe
    propagate_tags: SERVICE

# With Service Connect configuration
- community.aws.ecs_service:
    state: present
    name: service-connect-test
    cluster: my_cluster
    task_definition: 'my-task:1'
    desired_count: 1
    service_connect_configuration:
      enabled: true
      namespace: my-cloudmap-namespace
      services:
        - port_name: http
          client_aliases:
            - port: 80

# Create service and wait for tasks to be running
- community.aws.ecs_service:
    state: present
    name: my-service
    cluster: my_cluster
    task_definition: 'my-task:1'
    desired_count: 2
    wait: true
    delay: 10
    repeat: 30
"""

RETURN = r"""
service:
    description: Details of created service.
    returned: when creating a service
    type: complex
    contains:
        capacityProviderStrategy:
            version_added: 4.0.0
            description: The capacity provider strategy to use with your service.
            returned: always
            type: complex
            contains:
                base:
                    description: How many tasks, at a minimum, should use the specified provider.
                    returned: always
                    type: int
                capacityProvider:
                    description: Name of capacity provider.
                    returned: always
                    type: str
                weight:
                    description: The relative percentage of the total number of launched tasks that should use the specified provider.
                    returned: always
                    type: int
        clusterArn:
            description: The Amazon Resource Name (ARN) of the of the cluster that hosts the service.
            returned: always
            type: str
        desiredCount:
            description: The desired number of instantiations of the task definition to keep running on the service.
            returned: always
            type: int
        loadBalancers:
            description:
                - A list of load balancer objects
            returned: always
            type: complex
            contains:
                loadBalancerName:
                    description: the name
                    returned: always
                    type: str
                containerName:
                    description: The name of the container to associate with the load balancer.
                    returned: always
                    type: str
                containerPort:
                    description: The port on the container to associate with the load balancer.
                    returned: always
                    type: int
        pendingCount:
            description: The number of tasks in the cluster that are in the PENDING state.
            returned: always
            type: int
        runningCount:
            description: The number of tasks in the cluster that are in the RUNNING state.
            returned: always
            type: int
        serviceArn:
            description:
                - The Amazon Resource Name (ARN) that identifies the service. The ARN contains the C(arn:aws:ecs) namespace, followed by
                  the region of the service, the AWS account ID of the service owner, the service namespace, and then the service name.
            sample: 'arn:aws:ecs:us-east-1:123456789012:service/my-service'
            returned: always
            type: str
        serviceName:
            description: A user-generated string used to identify the service
            returned: always
            type: str
        status:
            description: The valid values are ACTIVE, DRAINING, or INACTIVE.
            returned: always
            type: str
        tags:
            description: The tags applied to this resource.
            returned: success
            type: dict
        taskDefinition:
            description: The ARN of a task definition to use for tasks in the service.
            returned: always
            type: str
        deployments:
            description: list of service deployments
            returned: always
            type: list
            elements: dict
        deploymentConfiguration:
            description: dictionary of deploymentConfiguration
            returned: always
            type: complex
            contains:
                maximumPercent:
                    description: maximumPercent param
                    returned: always
                    type: int
                minimumHealthyPercent:
                    description: minimumHealthyPercent param
                    returned: always
                    type: int
                deploymentCircuitBreaker:
                    description: dictionary of deploymentCircuitBreaker
                    returned: always
                    type: complex
                    contains:
                        enable:
                            description: The state of the circuit breaker feature.
                            returned: always
                            type: bool
                        rollback:
                            description: The state of the rollback feature of the circuit breaker.
                            returned: always
                            type: bool
        events:
            description: list of service events
            returned: always
            type: list
            elements: dict
        placementConstraints:
            description: List of placement constraints objects
            returned: always
            type: list
            elements: dict
            contains:
                type:
                    description: The type of constraint. Valid values are distinctInstance and memberOf.
                    returned: always
                    type: str
                expression:
                    description: A cluster query language expression to apply to the constraint. Note you cannot specify an expression if the constraint type is
                                 distinctInstance.
                    returned: always
                    type: str
        placementStrategy:
            description: List of placement strategy objects
            returned: always
            type: list
            elements: dict
            contains:
                type:
                    description: The type of placement strategy. Valid values are random, spread and binpack.
                    returned: always
                    type: str
                field:
                    description: The field to apply the placement strategy against. For the spread placement strategy, valid values are instanceId
                                 (or host, which has the same effect), or any platform or custom attribute that is applied to a container instance,
                                 such as attribute:ecs.availability-zone. For the binpack placement strategy, valid values are CPU and MEMORY.
                    returned: always
                    type: str
        propagateTags:
            description: The type of tag propagation applied to the resource.
            returned: always
            type: str
ansible_facts:
    description: Facts about deleted service.
    returned: when deleting a service
    type: complex
    contains:
        service:
            description: Details of deleted service.
            returned: when service existed and was deleted
            type: complex
            contains:
                clusterArn:
                    description: The Amazon Resource Name (ARN) of the of the cluster that hosts the service.
                    returned: always
                    type: str
                desiredCount:
                    description: The desired number of instantiations of the task definition to keep running on the service.
                    returned: always
                    type: int
                loadBalancers:
                    description: A list of load balancer objects
                    returned: always
                    type: complex
                    contains:
                        loadBalancerName:
                            description: the name
                            returned: always
                            type: str
                        containerName:
                            description: The name of the container to associate with the load balancer.
                            returned: always
                            type: str
                        containerPort:
                            description: The port on the container to associate with the load balancer.
                            returned: always
                            type: int
                pendingCount:
                    description: The number of tasks in the cluster that are in the PENDING state.
                    returned: always
                    type: int
                runningCount:
                    description: The number of tasks in the cluster that are in the RUNNING state.
                    returned: always
                    type: int
                serviceArn:
                    description:
                        - The Amazon Resource Name (ARN) that identifies the service. The ARN contains the arn:aws:ecs namespace, followed by the region
                          of the service, the AWS account ID of the service owner, the service namespace, and then the service name.
                    sample: 'arn:aws:ecs:us-east-1:123456789012:service/my-service'
                    returned: always
                    type: str
                serviceName:
                    description: A user-generated string used to identify the service
                    returned: always
                    type: str
                status:
                    description: The valid values are ACTIVE, DRAINING, or INACTIVE.
                    returned: always
                    type: str
                tags:
                    description: The tags applied to this resource.
                    returned: when tags found
                    type: list
                    elements: dict
                taskDefinition:
                    description: The ARN of a task definition to use for tasks in the service.
                    returned: always
                    type: str
                deployments:
                    description: list of service deployments
                    returned: always
                    type: list
                    elements: dict
                deploymentConfiguration:
                    description: dictionary of deploymentConfiguration
                    returned: always
                    type: complex
                    contains:
                        maximumPercent:
                            description: maximumPercent param
                            returned: always
                            type: int
                        minimumHealthyPercent:
                            description: minimumHealthyPercent param
                            returned: always
                            type: int
                        deploymentCircuitBreaker:
                            description: dictionary of deploymentCircuitBreaker
                            returned: always
                            type: complex
                            contains:
                                enable:
                                    description: The state of the circuit breaker feature.
                                    returned: always
                                    type: bool
                                rollback:
                                    description: The state of the rollback feature of the circuit breaker.
                                    returned: always
                                    type: bool
                events:
                    description: list of service events
                    returned: always
                    type: list
                    elements: dict
                placementConstraints:
                    description: List of placement constraints objects
                    returned: always
                    type: list
                    elements: dict
                    contains:
                        type:
                            description: The type of constraint. Valid values are distinctInstance and memberOf.
                            returned: always
                            type: str
                        expression:
                            description: A cluster query language expression to apply to the constraint. Note you cannot specify an expression if
                                         the constraint type is distinctInstance.
                            returned: always
                            type: str
                placementStrategy:
                    description: List of placement strategy objects
                    returned: always
                    type: list
                    elements: dict
                    contains:
                        type:
                            description: The type of placement strategy. Valid values are random, spread and binpack.
                            returned: always
                            type: str
                        field:
                            description: The field to apply the placement strategy against. For the spread placement strategy, valid values are instanceId
                                         (or host, which has the same effect), or any platform or custom attribute that is applied to a container instance,
                                         such as attribute:ecs.availability-zone. For the binpack placement strategy, valid values are CPU and MEMORY.
                            returned: always
                            type: str
                propagateTags:
                    description: The type of tag propagation applied to the resource
                    returned: always
                    type: str

"""

import time

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import snake_dict_to_camel_dict

from ansible_collections.amazon.aws.plugins.module_utils.ec2 import get_ec2_security_group_ids_from_names
from ansible_collections.amazon.aws.plugins.module_utils.tagging import ansible_dict_to_boto3_tag_list
from ansible_collections.amazon.aws.plugins.module_utils.tagging import boto3_tag_list_to_ansible_dict
from ansible_collections.amazon.aws.plugins.module_utils.transformation import map_complex_type

from ansible_collections.community.aws.plugins.module_utils.modules import AnsibleCommunityAWSModule as AnsibleAWSModule

DEPLOYMENT_CONTROLLER_TYPE_MAP = {
    "type": "str",
}

DEPLOYMENT_CONFIGURATION_TYPE_MAP = {
    "maximum_percent": "int",
    "minimum_healthy_percent": "int",
    "deployment_circuit_breaker": "dict",
}


class EcsServiceManager:
    """Handles ECS Services"""

    def __init__(self, module):
        self.module = module
        self.ecs = module.client("ecs")
        self.ec2 = module.client("ec2")

    def format_network_configuration(self, network_config):
        result = dict()
        if network_config["subnets"] is not None:
            result["subnets"] = network_config["subnets"]
        else:
            self.module.fail_json(msg="Network configuration must include subnets")
        if network_config["security_groups"] is not None:
            groups = network_config["security_groups"]
            if any(not sg.startswith("sg-") for sg in groups):
                try:
                    vpc_id = self.ec2.describe_subnets(SubnetIds=[result["subnets"][0]])["Subnets"][0]["VpcId"]
                    groups = get_ec2_security_group_ids_from_names(groups, self.ec2, vpc_id)
                except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
                    self.module.fail_json_aws(e, msg="Couldn't look up security groups")
            result["securityGroups"] = groups
        if network_config["assign_public_ip"] is not None:
            if network_config["assign_public_ip"] is True:
                result["assignPublicIp"] = "ENABLED"
            else:
                result["assignPublicIp"] = "DISABLED"
        return dict(awsvpcConfiguration=result)

    def find_in_array(self, array_of_services, service_name, field_name="serviceArn"):
        for c in array_of_services:
            if c[field_name].endswith(service_name):
                return c
        return None

    def describe_service(self, cluster_name, service_name):
        response = self.ecs.describe_services(
            cluster=cluster_name,
            services=[service_name],
            include=["TAGS"],
        )
        msg = ""

        if len(response["failures"]) > 0:
            c = self.find_in_array(response["failures"], service_name, "arn")
            msg += ", failure reason is " + c["reason"]
            if c and c["reason"] == "MISSING":
                return None
            # fall thru and look through found ones
        if len(response["services"]) > 0:
            c = self.find_in_array(response["services"], service_name)
            if c:
                return c
        raise Exception(f"Unknown problem describing service {service_name}.")

    def is_matching_service(self, expected, existing):
        # aws returns the arn of the task definition
        #   arn:aws:ecs:eu-central-1:123456789:task-definition/ansible-fargate-nginx:3
        # but the user is just entering
        #   ansible-fargate-nginx:3
        if expected["task_definition"] != existing["taskDefinition"].split("/")[-1]:
            if existing.get("deploymentController", {}).get("type", None) != "CODE_DEPLOY":
                return False

        if expected.get("health_check_grace_period_seconds"):
            if expected.get("health_check_grace_period_seconds") != existing.get("healthCheckGracePeriodSeconds"):
                return False

        if (expected["load_balancers"] or []) != existing["loadBalancers"]:
            return False

        if (expected["propagate_tags"] or "NONE") != existing["propagateTags"]:
            return False

        if boto3_tag_list_to_ansible_dict(existing.get("tags", [])) != (expected["tags"] or {}):
            return False

        if (expected["enable_execute_command"] or False) != existing.get("enableExecuteCommand", False):
            return False

        # Compare service connect configuration
        expected_service_connect = snake_dict_to_camel_dict(expected["service_connect_configuration"]) if expected.get("service_connect_configuration") else {}
        if expected_service_connect != existing.get("serviceConnectConfiguration", {}):
            return False

        # expected is params. DAEMON scheduling strategy returns desired count equal to
        # number of instances running; don't check desired count if scheduling strat is daemon
        if expected["scheduling_strategy"] != "DAEMON":
            if (expected["desired_count"] or 0) != existing["desiredCount"]:
                return False

        return True

    def create_service(
        self,
        service_name,
        cluster_name,
        task_definition,
        load_balancers,
        desired_count,
        client_token,
        role,
        deployment_controller,
        deployment_configuration,
        placement_constraints,
        placement_strategy,
        health_check_grace_period_seconds,
        network_configuration,
        service_registries,
        launch_type,
        platform_version,
        scheduling_strategy,
        capacity_provider_strategy,
        tags,
        propagate_tags,
        enable_execute_command,
        service_connect_configuration,
    ):
        params = dict(
            cluster=cluster_name,
            serviceName=service_name,
            taskDefinition=task_definition,
            loadBalancers=load_balancers,
            clientToken=client_token,
            role=role,
            deploymentConfiguration=deployment_configuration,
            placementStrategy=placement_strategy,
        )
        if network_configuration:
            params["networkConfiguration"] = network_configuration
        if deployment_controller:
            params["deploymentController"] = deployment_controller
        if launch_type:
            params["launchType"] = launch_type
        if platform_version:
            params["platformVersion"] = platform_version
        if self.health_check_setable(params) and health_check_grace_period_seconds is not None:
            params["healthCheckGracePeriodSeconds"] = health_check_grace_period_seconds
        if service_registries:
            params["serviceRegistries"] = service_registries
        if service_connect_configuration:
            params["serviceConnectConfiguration"] = service_connect_configuration

        # filter placement_constraint and left only those where value is not None
        # use-case: `distinctInstance` type should never contain `expression`, but None will fail `str` type validation
        if placement_constraints:
            params["placementConstraints"] = [{key: value for key, value in constraint.items() if value is not None} for constraint in placement_constraints]

        # desired count is not required if scheduling strategy is daemon
        if desired_count is not None:
            params["desiredCount"] = desired_count
        if capacity_provider_strategy:
            params["capacityProviderStrategy"] = capacity_provider_strategy
        if propagate_tags:
            params["propagateTags"] = propagate_tags
        # desired count is not required if scheduling strategy is daemon
        if desired_count is not None:
            params["desiredCount"] = desired_count
        if tags:
            params["tags"] = ansible_dict_to_boto3_tag_list(tags, "key", "value")

        if scheduling_strategy:
            params["schedulingStrategy"] = scheduling_strategy
        if enable_execute_command:
            params["enableExecuteCommand"] = enable_execute_command

        response = self.ecs.create_service(**params)
        return self.jsonize(response["service"])

    def update_service(
        self,
        service_name,
        cluster_name,
        task_definition,
        desired_count,
        deployment_configuration,
        placement_constraints,
        placement_strategy,
        network_configuration,
        health_check_grace_period_seconds,
        force_new_deployment,
        capacity_provider_strategy,
        load_balancers,
        purge_placement_constraints,
        purge_placement_strategy,
        enable_execute_command,
        service_connect_configuration,
    ):
        params = dict(
            cluster=cluster_name,
            service=service_name,
            taskDefinition=task_definition,
            deploymentConfiguration=deployment_configuration,
        )
        # filter placement_constraint and left only those where value is not None
        # use-case: `distinctInstance` type should never contain `expression`, but None will fail `str` type validation
        if placement_constraints:
            params["placementConstraints"] = [{key: value for key, value in constraint.items() if value is not None} for constraint in placement_constraints]

        if purge_placement_constraints and not placement_constraints:
            params["placementConstraints"] = []

        if placement_strategy:
            params["placementStrategy"] = placement_strategy

        if purge_placement_strategy and not placement_strategy:
            params["placementStrategy"] = []

        if network_configuration:
            params["networkConfiguration"] = network_configuration
        if force_new_deployment:
            params["forceNewDeployment"] = force_new_deployment
        if capacity_provider_strategy:
            params["capacityProviderStrategy"] = capacity_provider_strategy
        if health_check_grace_period_seconds is not None:
            params["healthCheckGracePeriodSeconds"] = health_check_grace_period_seconds
        # desired count is not required if scheduling strategy is daemon
        if desired_count is not None:
            params["desiredCount"] = desired_count
        if enable_execute_command is not None:
            params["enableExecuteCommand"] = enable_execute_command
        if service_connect_configuration:
            params["serviceConnectConfiguration"] = service_connect_configuration

        if load_balancers:
            params["loadBalancers"] = load_balancers

        response = self.ecs.update_service(**params)

        return self.jsonize(response["service"])

    def jsonize(self, service):
        # some fields are datetime which is not JSON serializable
        # make them strings
        if "createdAt" in service:
            service["createdAt"] = str(service["createdAt"])
        if "deployments" in service:
            for d in service["deployments"]:
                if "createdAt" in d:
                    d["createdAt"] = str(d["createdAt"])
                if "updatedAt" in d:
                    d["updatedAt"] = str(d["updatedAt"])
        if "events" in service:
            for e in service["events"]:
                if "createdAt" in e:
                    e["createdAt"] = str(e["createdAt"])
        return service

    def delete_service(self, service, cluster=None, force=False):
        return self.ecs.delete_service(cluster=cluster, service=service, force=force)

    def health_check_setable(self, params):
        load_balancers = params.get("loadBalancers", [])
        return len(load_balancers) > 0


def main():
    argument_spec = dict(
        state=dict(required=True, choices=["present", "absent", "deleting"]),
        name=dict(required=True, type="str", aliases=["service"]),
        cluster=dict(required=False, type="str", default="default"),
        task_definition=dict(required=False, type="str"),
        load_balancers=dict(required=False, default=[], type="list", elements="dict"),
        desired_count=dict(required=False, type="int"),
        client_token=dict(required=False, default="", type="str", no_log=False),
        role=dict(required=False, default="", type="str"),
        delay=dict(required=False, type="int", default=10),
        repeat=dict(required=False, type="int", default=10),
        force_new_deployment=dict(required=False, default=False, type="bool"),
        force_deletion=dict(required=False, default=False, type="bool"),
        deployment_controller=dict(required=False, default={}, type="dict"),
        deployment_configuration=dict(required=False, default={}, type="dict"),
        wait=dict(required=False, default=False, type="bool"),
        placement_constraints=dict(
            required=False,
            default=[],
            type="list",
            elements="dict",
            options=dict(type=dict(type="str"), expression=dict(required=False, type="str")),
        ),
        purge_placement_constraints=dict(required=False, default=False, type="bool"),
        placement_strategy=dict(
            required=False,
            default=[],
            type="list",
            elements="dict",
            options=dict(
                type=dict(type="str"),
                field=dict(type="str"),
            ),
        ),
        purge_placement_strategy=dict(required=False, default=False, type="bool"),
        health_check_grace_period_seconds=dict(required=False, type="int"),
        network_configuration=dict(
            required=False,
            type="dict",
            options=dict(
                subnets=dict(type="list", elements="str"),
                security_groups=dict(type="list", elements="str"),
                assign_public_ip=dict(type="bool"),
            ),
        ),
        launch_type=dict(required=False, choices=["EC2", "FARGATE"]),
        platform_version=dict(required=False, type="str"),
        service_registries=dict(required=False, type="list", default=[], elements="dict"),
        service_connect_configuration=dict(required=False, type="dict"),
        scheduling_strategy=dict(required=False, choices=["DAEMON", "REPLICA"]),
        capacity_provider_strategy=dict(
            required=False,
            type="list",
            default=[],
            elements="dict",
            options=dict(
                capacity_provider=dict(type="str"),
                weight=dict(type="int"),
                base=dict(type="int"),
            ),
        ),
        propagate_tags=dict(required=False, choices=["TASK_DEFINITION", "SERVICE"]),
        tags=dict(required=False, type="dict"),
        enable_execute_command=dict(required=False, type="bool"),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("launch_type", "FARGATE", ["network_configuration"])],
        required_together=[["load_balancers", "role"]],
        mutually_exclusive=[["launch_type", "capacity_provider_strategy"]],
    )

    if module.params["state"] == "present":
        if module.params["scheduling_strategy"] == "REPLICA" and module.params["desired_count"] is None:
            module.fail_json(msg="state is present, scheduling_strategy is REPLICA; missing desired_count")
        if module.params["task_definition"] is None and not module.params["force_new_deployment"]:
            module.fail_json(msg="Either task_definition or force_new_deployment is required when status is present.")

    if len(module.params["capacity_provider_strategy"]) > 6:
        module.fail_json(msg="AWS allows a maximum of six capacity providers in the strategy.")

    service_mgr = EcsServiceManager(module)
    if module.params["network_configuration"]:
        network_configuration = service_mgr.format_network_configuration(module.params["network_configuration"])
    else:
        network_configuration = None

    deployment_controller = map_complex_type(module.params["deployment_controller"], DEPLOYMENT_CONTROLLER_TYPE_MAP)

    deploymentController = snake_dict_to_camel_dict(deployment_controller)

    deployment_configuration = map_complex_type(module.params["deployment_configuration"], DEPLOYMENT_CONFIGURATION_TYPE_MAP)

    deploymentConfiguration = snake_dict_to_camel_dict(deployment_configuration)
    serviceRegistries = list(map(snake_dict_to_camel_dict, module.params["service_registries"]))
    serviceConnectConfiguration = snake_dict_to_camel_dict(module.params["service_connect_configuration"]) if module.params["service_connect_configuration"] else None
    capacityProviders = list(map(snake_dict_to_camel_dict, module.params["capacity_provider_strategy"]))

    try:
        existing = service_mgr.describe_service(module.params["cluster"], module.params["name"])
    except Exception as e:
        module.fail_json_aws(
            e,
            msg=f"Exception describing service '{module.params['name']}' in cluster '{module.params['cluster']}'",
        )

    results = dict(changed=False)

    if module.params["state"] == "present":
        matching = False
        update = False

        if existing and "status" in existing and existing["status"] == "ACTIVE":
            if module.params["force_new_deployment"]:
                update = True
            elif service_mgr.is_matching_service(module.params, existing):
                matching = True
                results["service"] = existing
            else:
                update = True

        if not matching:
            if not module.check_mode:
                role = module.params["role"]
                clientToken = module.params["client_token"]

                loadBalancers = []
                for loadBalancer in module.params["load_balancers"]:
                    if "containerPort" in loadBalancer:
                        loadBalancer["containerPort"] = int(loadBalancer["containerPort"])
                    loadBalancers.append(loadBalancer)

                for loadBalancer in loadBalancers:
                    if "containerPort" in loadBalancer:
                        loadBalancer["containerPort"] = int(loadBalancer["containerPort"])

                if update:
                    # check various parameters and AWS SDK versions and give a helpful error if the SDK is not new enough for feature

                    if module.params["scheduling_strategy"]:
                        if (existing["schedulingStrategy"]) != module.params["scheduling_strategy"]:
                            module.fail_json(msg="It is not possible to update the scheduling strategy of an existing service")

                    if module.params["service_registries"]:
                        if (existing["serviceRegistries"] or []) != serviceRegistries:
                            module.fail_json(msg="It is not possible to update the service registries of an existing service")
                    if module.params["capacity_provider_strategy"]:
                        if "launchType" in existing.keys():
                            module.fail_json(msg="It is not possible to change an existing service from launch_type to capacity_provider_strategy.")
                    if module.params["launch_type"]:
                        if "capacityProviderStrategy" in existing.keys():
                            module.fail_json(msg="It is not possible to change an existing service from capacity_provider_strategy to launch_type.")
                    if (existing["loadBalancers"] or []) != loadBalancers:
                        # fails if deployment type is not CODE_DEPLOY or ECS
                        if existing["deploymentController"]["type"] not in ["CODE_DEPLOY", "ECS"]:
                            module.fail_json(msg="It is not possible to update the load balancers of an existing service")

                    if existing.get("deploymentController", {}).get("type", None) == "CODE_DEPLOY":
                        task_definition = ""
                        network_configuration = []
                    else:
                        task_definition = module.params["task_definition"]

                    if module.params["propagate_tags"] and module.params["propagate_tags"] != existing["propagateTags"]:
                        module.fail_json(msg="It is not currently supported to enable propagation tags of an existing service")

                    if module.params["tags"] and boto3_tag_list_to_ansible_dict(existing["tags"]) != module.params["tags"]:
                        module.fail_json(msg="It is not currently supported to change tags of an existing service")

                    updatedLoadBalancers = loadBalancers if existing["deploymentController"]["type"] == "ECS" else []

                    if task_definition is None and module.params["force_new_deployment"]:
                        task_definition = existing["taskDefinition"]

                    try:
                        # update required
                        response = service_mgr.update_service(
                            module.params["name"],
                            module.params["cluster"],
                            task_definition,
                            module.params["desired_count"],
                            deploymentConfiguration,
                            module.params["placement_constraints"],
                            module.params["placement_strategy"],
                            network_configuration,
                            module.params["health_check_grace_period_seconds"],
                            module.params["force_new_deployment"],
                            capacityProviders,
                            updatedLoadBalancers,
                            module.params["purge_placement_constraints"],
                            module.params["purge_placement_strategy"],
                            module.params["enable_execute_command"],
                            serviceConnectConfiguration,
                        )
                    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                        module.fail_json_aws(e, msg="Couldn't create service")

                else:
                    try:
                        response = service_mgr.create_service(
                            module.params["name"],
                            module.params["cluster"],
                            module.params["task_definition"],
                            loadBalancers,
                            module.params["desired_count"],
                            clientToken,
                            role,
                            deploymentController,
                            deploymentConfiguration,
                            module.params["placement_constraints"],
                            module.params["placement_strategy"],
                            module.params["health_check_grace_period_seconds"],
                            network_configuration,
                            serviceRegistries,
                            module.params["launch_type"],
                            module.params["platform_version"],
                            module.params["scheduling_strategy"],
                            capacityProviders,
                            module.params["tags"],
                            module.params["propagate_tags"],
                            module.params["enable_execute_command"],
                            serviceConnectConfiguration,
                        )
                    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                        module.fail_json_aws(e, msg="Couldn't create service")

                if response.get("tags", None):
                    response["tags"] = boto3_tag_list_to_ansible_dict(response["tags"])
                results["service"] = response

                # Wait for service to be stable with tasks running if wait=True
                if module.params["wait"]:
                    waiter = service_mgr.ecs.get_waiter("services_stable")
                    try:
                        waiter.wait(
                            services=[module.params["name"]],
                            cluster=module.params["cluster"],
                            WaiterConfig={
                                "Delay": module.params["delay"],
                                "MaxAttempts": module.params["repeat"],
                            },
                        )
                    except botocore.exceptions.WaiterError as e:
                        module.fail_json_aws(e, "Timeout waiting for service to become stable with tasks running")

            results["changed"] = True

    elif module.params["state"] == "absent":
        if not existing:
            pass
        else:
            # it exists, so we should delete it and mark changed.
            # return info about the cluster deleted
            del existing["deployments"]
            del existing["events"]
            results["ansible_facts"] = existing
            if "status" in existing and existing["status"] == "INACTIVE":
                results["changed"] = False
            else:
                if not module.check_mode:
                    try:
                        service_mgr.delete_service(
                            module.params["name"],
                            module.params["cluster"],
                            module.params["force_deletion"],
                        )

                        # Wait for service to be INACTIVE prior to exiting
                        if module.params["wait"]:
                            waiter = service_mgr.ecs.get_waiter("services_inactive")
                            try:
                                waiter.wait(
                                    services=[module.params["name"]],
                                    cluster=module.params["cluster"],
                                    WaiterConfig={
                                        "Delay": module.params["delay"],
                                        "MaxAttempts": module.params["repeat"],
                                    },
                                )
                            except botocore.exceptions.WaiterError as e:
                                module.fail_json_aws(e, "Timeout waiting for service removal")
                    except botocore.exceptions.ClientError as e:
                        module.fail_json_aws(e, msg="Couldn't delete service")

                results["changed"] = True

    elif module.params["state"] == "deleting":
        if not existing:
            module.fail_json(msg="Service '" + module.params["name"] + " not found.")

        # it exists, so we should delete it and mark changed.
        # return info about the cluster deleted
        delay = module.params["delay"]
        repeat = module.params["repeat"]
        time.sleep(delay)
        for i in range(repeat):
            existing = service_mgr.describe_service(module.params["cluster"], module.params["name"])
            status = existing["status"]
            if status == "INACTIVE":
                results["changed"] = True
                break
            time.sleep(delay)
        if i is repeat - 1:
            module.fail_json(msg=f"Service still not deleted after {repeat} tries of {delay} seconds each.")

    module.exit_json(**results)


if __name__ == "__main__":
    main()
