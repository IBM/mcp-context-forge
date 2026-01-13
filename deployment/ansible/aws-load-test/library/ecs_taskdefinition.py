#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# Modified from community.aws.ecs_taskdefinition to add 'deleted' state
# for permanent task definition deletion using delete_task_definitions API

DOCUMENTATION = r"""
---
module: ecs_taskdefinition
version_added: 1.0.0
short_description: register a task definition in ecs
description:
    - Registers, deregisters, or deletes task definitions in the Amazon Web Services (AWS) EC2 Container Service (ECS).
author:
    - Mark Chance (@Java1Guy)
    - Alina Buzachis (@alinabuzachis)
options:
    state:
        description:
            - State whether the task definition should exist, be deregistered, or be permanently deleted.
            - C(present) - Register or update the task definition.
            - C(inactive) - Deregister the task definition (marks as INACTIVE but retains in AWS).
            - C(absent) - Permanently delete the task definition from AWS.
        required: true
        choices: ['present', 'inactive', 'absent']
        type: str
    arn:
        description:
            - The ARN of the task description to delete.
        required: false
        type: str
    family:
        description:
            - A Name that would be given to the task definition.
        required: false
        type: str
    revision:
        description:
            - A revision number for the task definition.
            - When I(state=absent) and no revision is provided (only family), ALL revisions in the family will be deleted.
        required: False
        type: int
    force_create:
        description:
            - Always create new task definition.
        required: False
        type: bool
        default: false
    containers:
        description:
            - A list of containers definitions.
            - See U(https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html) for a complete list of parameters.
        required: False
        type: list
        elements: dict
        suboptions:
            name:
                description: The name of a container.
                required: False
                type: str
            image:
                description: The image used to start a container.
                required: False
                type: str
            repositoryCredentials:
                description: The private repository authentication credentials to use.
                required: False
                type: dict
                suboptions:
                    credentialsParameter:
                        description:
                            - The Amazon Resource Name (ARN) of the secret containing the private repository credentials.
                        required: True
                        type: str
            cpu:
                description: The number of cpu units reserved for the container.
                required: False
                type: int
            memory:
                description: The amount (in MiB) of memory to present to the container.
                required: False
                type: int
            memoryReservation:
                description: The soft limit (in MiB) of memory to reserve for the container.
                required: False
                type: int
            links:
                description:
                    - Allows containers to communicate with each other without the need for port mappings.
                    - This parameter is only supported if I(network_mode=bridge).
                required: False
                type: list
                elements: str
            portMappings:
                description: The list of port mappings for the container.
                required: False
                type: list
                elements: dict
                suboptions:
                    containerPort:
                        description: The port number on the container that is bound to the user-specified or automatically assigned host port.
                        required: False
                        type: int
                    hostPort:
                        description: The port number on the container instance to reserve for your container.
                        required: False
                        type: int
                    protocol:
                        description: The protocol used for the port mapping.
                        required: False
                        type: str
                        default: tcp
                        choices: ['tcp', 'udp']
            essential:
                description:
                    - If I(essential=True), and the container fails or stops for any reason, all other containers that are part of the task are stopped.
                required: False
                type: bool
            entryPoint:
                description: The entry point that is passed to the container.
                required: False
                type: str
            command:
                description: The command that is passed to the container. If there are multiple arguments, each argument is a separated string in the array.
                required: False
                type: list
                elements: str
            environment:
                description: The environment variables to pass to a container.
                required: False
                type: list
                elements: dict
                suboptions:
                    name:
                        description: The name of the key-value pair.
                        required: False
                        type: str
                    value:
                        description: The value of the key-value pair.
                        required: False
                        type: str
            environmentFiles:
                description: A list of files containing the environment variables to pass to a container.
                required: False
                type: list
                elements: dict
                suboptions:
                    value:
                        description: The Amazon Resource Name (ARN) of the Amazon S3 object containing the environment variable file.
                        required: False
                        type: str
                    type:
                        description: The file type to use. The only supported value is C(s3).
                        required: False
                        type: str
            mountPoints:
                description: The mount points for data volumes in your container.
                required: False
                type: list
                elements: dict
                suboptions:
                    sourceVolume:
                        description: The name of the volume to mount.
                        required: False
                        type: str
                    containerPath:
                        description: The path on the container to mount the host volume at.
                        required: False
                        type: str
                    readOnly:
                        description:
                            - If this value is C(True), the container has read-only access to the volume.
                            - If this value is C(False), then the container can write to the volume.
                        required: False
                        default: False
                        type: bool
            volumesFrom:
                description: Data volumes to mount from another container.
                required: False
                type: list
                elements: dict
                suboptions:
                    sourceContainer:
                        description:
                            - The name of another container within the same task definition from which to mount volumes.
                        required: False
                        type: str
                    readOnly:
                        description:
                            - If this value is C(True), the container has read-only access to the volume.
                            - If this value is C(False), then the container can write to the volume.
                        required: False
                        default: False
                        type: bool
            linuxParameters:
                description: Linux-specific modifications that are applied to the container, such as Linux kernel capabilities.
                required: False
                type: dict
            secrets:
                description: The secrets to pass to the container.
                required: False
                type: list
                elements: dict
            dependsOn:
                description:
                    - The dependencies defined for container startup and shutdown.
                    - When a dependency is defined for container startup, for container shutdown it is reversed.
                required: False
                type: list
                elements: dict
            startTimeout:
                description: Time duration (in seconds) to wait before giving up on resolving dependencies for a container.
                required: False
                type: int
            stopTimeout:
                description: Time duration (in seconds) to wait before the container is forcefully killed if it doesn't exit normally on its own.
                required: False
                type: int
            hostname:
                description:
                    - The hostname to use for your container.
                    - This parameter is not supported if I(network_mode=awsvpc).
                required: False
                type: str
            user:
                description:
                    - The user to use inside the container.
                    - This parameter is not supported for Windows containers.
                required: False
                type: str
            workingDirectory:
                description: The working directory in which to run commands inside the container.
                required: False
                type: str
            disableNetworking:
                description: When this parameter is C(True), networking is disabled within the container.
                required: False
                type: bool
            privileged:
                description: When this parameter is C(True), the container is given elevated privileges on the host container instance.
                required: False
                type: bool
            readonlyRootFilesystem:
                description: When this parameter is C(True), the container is given read-only access to its root file system.
                required: false
                type: bool
            dnsServers:
                description:
                    - A list of DNS servers that are presented to the container.
                    - This parameter is not supported for Windows containers.
                required: False
                type: list
                elements: str
            dnsSearchDomains:
                description:
                    - A list of DNS search domains that are presented to the container.
                    - This parameter is not supported for Windows containers.
                required: False
                type: list
                elements: str
            extraHosts:
                description:
                    - A list of hostnames and IP address mappings to append to the /etc/hosts file on the container.
                    - This parameter is not supported for Windows containers or tasks that use I(network_mode=awsvpc).
                required: False
                type: list
                elements: dict
            dockerSecurityOptions:
                description:
                    - A list of strings to provide custom labels for SELinux and AppArmor multi-level security systems.
                    - This parameter is not supported for Windows containers.
                required: False
                type: list
                elements: str
            interactive:
                description:
                    - When I(interactive=True), it allows to deploy containerized applications that require stdin or a tty to be allocated.
                required: False
                type: bool
            pseudoTerminal:
                description: When this parameter is C(True), a TTY is allocated.
                required: False
                type: bool
            dockerLabels:
                description: A key/value map of labels to add to the container.
                required: False
                type: dict
            ulimits:
                description:
                    - A list of ulimits to set in the container.
                    - This parameter is not supported for Windows containers.
                required: False
                type: list
                elements: dict
            logConfiguration:
                description: The log configuration specification for the container.
                required: False
                type: dict
            healthCheck:
                description: The health check command and associated configuration parameters for the container.
                required: False
                type: dict
            systemControls:
                description: A list of namespaced kernel parameters to set in the container.
                required: False
                type: list
                elements: dict
            resourceRequirements:
                description:
                    - The type and amount of a resource to assign to a container.
                    - The only supported resources are C(GPU) and C(InferenceAccelerator).
                required: False
                type: list
                elements: dict
            firelensConfiguration:
                description:
                    - The FireLens configuration for the container.
                    - This is used to specify and configure a log router for container logs.
                required: False
                type: dict
    network_mode:
        description:
            - The Docker networking mode to use for the containers in the task.
            - Windows containers must use I(network_mode=default), which will utilize docker NAT networking.
            - Setting I(network_mode=default) for a Linux container will use C(bridge) mode.
        required: false
        default: bridge
        choices: [ 'default', 'bridge', 'host', 'none', 'awsvpc' ]
        type: str
    task_role_arn:
        description:
            - The Amazon Resource Name (ARN) of the IAM role that containers in this task can assume. All containers in this task are granted
              the permissions that are specified in this role.
        required: false
        type: str
        default: ''
    execution_role_arn:
        description:
            - The Amazon Resource Name (ARN) of the task execution role that the Amazon ECS container agent and the Docker daemon can assume.
        required: false
        type: str
        default: ''
    volumes:
        description:
            - A list of names of volumes to be attached.
        required: False
        type: list
        elements: dict
        suboptions:
            name:
                type: str
                description: The name of the volume.
                required: true
    launch_type:
        description:
            - The launch type on which to run your task.
        required: false
        type: str
        choices: ["EC2", "FARGATE"]
    cpu:
        description:
            - The number of cpu units used by the task. If I(launch_type=EC2), this field is optional and any value can be used.
            - If I(launch_type=FARGATE), this field is required and you must use one of C(256), C(512), C(1024), C(2048), C(4096).
        required: false
        type: str
    memory:
        description:
            - The amount (in MiB) of memory used by the task. If I(launch_type=EC2), this field is optional and any value can be used.
            - If I(launch_type=FARGATE), this field is required and is limited by the CPU.
        required: false
        type: str
    placement_constraints:
        version_added: 2.1.0
        description:
            - Placement constraint objects to use for the task.
            - You can specify a maximum of 10 constraints per task.
            - Task placement constraints are not supported for tasks run on Fargate.
        required: false
        type: list
        elements: dict
        suboptions:
            type:
                description: The type of constraint.
                type: str
            expression:
                description: A cluster query language expression to apply to the constraint.
                type: str
    runtime_platform:
        version_added: 6.4.0
        description:
            - runtime platform configuration for the task
        required: false
        type: dict
        default: {
                    "operatingSystemFamily": "LINUX",
                    "cpuArchitecture": "X86_64"
                }
        suboptions:
            cpuArchitecture:
                description: The CPU Architecture type to be used by the task
                type: str
                required: false
                choices: ['X86_64', 'ARM64']
            operatingSystemFamily:
                description: OS type to be used by the task
                type: str
                required: false
                choices: ['LINUX', 'WINDOWS_SERVER_2019_FULL', 'WINDOWS_SERVER_2019_CORE', 'WINDOWS_SERVER_2022_FULL', 'WINDOWS_SERVER_2022_CORE']
extends_documentation_fragment:
    - amazon.aws.common.modules
    - amazon.aws.region.modules
    - amazon.aws.boto3
"""

EXAMPLES = r"""
- name: Create task definition
  ecs_taskdefinition:
    family: nginx
    containers:
      - name: nginx
        essential: true
        image: "nginx"
        portMappings:
          - containerPort: 8080
            hostPort: 8080
    state: present

- name: Deregister task definition (marks as INACTIVE)
  ecs_taskdefinition:
    arn: "arn:aws:ecs:us-west-2:123456789:task-definition/my-task:1"
    state: inactive

- name: Permanently delete task definition
  ecs_taskdefinition:
    arn: "arn:aws:ecs:us-west-2:123456789:task-definition/my-task:1"
    state: absent

- name: Permanently delete ALL revisions in a task definition family
  ecs_taskdefinition:
    family: my-task
    state: absent
"""

RETURN = r"""
taskdefinition:
    description: a reflection of the input parameters
    type: dict
    returned: always
"""

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible_collections.amazon.aws.plugins.module_utils.retries import AWSRetry

from ansible_collections.community.aws.plugins.module_utils.modules import AnsibleCommunityAWSModule as AnsibleAWSModule


class EcsTaskManager:
    """Handles ECS Tasks"""

    def __init__(self, module):
        self.module = module

        self.ecs = module.client("ecs", AWSRetry.jittered_backoff())

    def describe_task(self, task_name):
        try:
            response = self.ecs.describe_task_definition(aws_retry=True, taskDefinition=task_name)
            return response["taskDefinition"]
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError):
            return None

    def register_task(
        self,
        family,
        task_role_arn,
        execution_role_arn,
        network_mode,
        container_definitions,
        volumes,
        launch_type,
        cpu,
        memory,
        placement_constraints,
        runtime_platform,
    ):
        validated_containers = []

        # Ensures the number parameters are int as required by the AWS SDK
        for container in container_definitions:
            for param in ("memory", "cpu", "memoryReservation", "startTimeout", "stopTimeout"):
                if param in container:
                    container[param] = int(container[param])

            if "portMappings" in container:
                for port_mapping in container["portMappings"]:
                    for port in ("hostPort", "containerPort"):
                        if port in port_mapping:
                            port_mapping[port] = int(port_mapping[port])
                    if network_mode == "awsvpc" and "hostPort" in port_mapping:
                        if port_mapping["hostPort"] != port_mapping.get("containerPort"):
                            self.module.fail_json(msg=("In awsvpc network mode, host port must be set to the same as " "container port or not be set"))

            if "linuxParameters" in container:
                for linux_param in container.get("linuxParameters"):
                    if linux_param == "tmpfs":
                        for tmpfs_param in container["linuxParameters"]["tmpfs"]:
                            if "size" in tmpfs_param:
                                tmpfs_param["size"] = int(tmpfs_param["size"])

                    for param in ("maxSwap", "swappiness", "sharedMemorySize"):
                        if param in linux_param:
                            container["linuxParameters"][param] = int(container["linuxParameters"][param])

            if "ulimits" in container:
                for limits_mapping in container["ulimits"]:
                    for limit in ("softLimit", "hardLimit"):
                        if limit in limits_mapping:
                            limits_mapping[limit] = int(limits_mapping[limit])

            validated_containers.append(container)

        params = dict(
            family=family,
            taskRoleArn=task_role_arn,
            containerDefinitions=container_definitions,
            volumes=volumes,
        )
        if network_mode != "default":
            params["networkMode"] = network_mode
        if cpu:
            params["cpu"] = cpu
        if memory:
            params["memory"] = memory
        if launch_type:
            params["requiresCompatibilities"] = [launch_type]
        if execution_role_arn:
            params["executionRoleArn"] = execution_role_arn
        if placement_constraints:
            params["placementConstraints"] = placement_constraints
        if runtime_platform:
            params["runtimePlatform"] = runtime_platform

        try:
            response = self.ecs.register_task_definition(aws_retry=True, **params)
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Failed to register task")

        return response["taskDefinition"]

    def describe_task_definitions(self, family):
        data = {"taskDefinitionArns": [], "nextToken": None}

        def fetch():
            # Boto3 is weird about params passed, so only pass nextToken if we have a value
            params = {"familyPrefix": family}

            if data["nextToken"]:
                params["nextToken"] = data["nextToken"]

            result = self.ecs.list_task_definitions(aws_retry=True, **params)
            data["taskDefinitionArns"] += result["taskDefinitionArns"]
            data["nextToken"] = result.get("nextToken", None)
            return data["nextToken"] is not None

        # Fetch all the arns, possibly across multiple pages
        while fetch():
            pass

        # Return the full descriptions of the task definitions, sorted ascending by revision
        return list(
            sorted(
                [self.ecs.describe_task_definition(aws_retry=True, taskDefinition=arn)["taskDefinition"] for arn in data["taskDefinitionArns"]],
                key=lambda td: td["revision"],
            )
        )

    def deregister_task(self, taskArn):
        response = self.ecs.deregister_task_definition(aws_retry=True, taskDefinition=taskArn)
        return response["taskDefinition"]

    def delete_task(self, taskArn):
        """Permanently delete a task definition using delete_task_definitions API."""
        try:
            response = self.ecs.delete_task_definitions(aws_retry=True, taskDefinitions=[taskArn])
            if response.get("failures"):
                failure = response["failures"][0]
                self.module.fail_json(msg=f"Failed to delete task definition: {failure.get('reason', 'Unknown error')}")
            if response.get("taskDefinitions"):
                return response["taskDefinitions"][0]
            return None
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Failed to delete task definition")


def main():
    argument_spec = dict(
        state=dict(required=True, choices=["present", "inactive", "absent"]),
        arn=dict(required=False, type="str"),
        family=dict(required=False, type="str"),
        revision=dict(required=False, type="int"),
        force_create=dict(required=False, default=False, type="bool"),
        containers=dict(required=False, type="list", elements="dict"),
        network_mode=dict(required=False, default="bridge", choices=["default", "bridge", "host", "none", "awsvpc"], type="str"),
        task_role_arn=dict(required=False, default="", type="str"),
        execution_role_arn=dict(required=False, default="", type="str"),
        volumes=dict(required=False, type="list", elements="dict"),
        launch_type=dict(required=False, choices=["EC2", "FARGATE"]),
        cpu=dict(),
        memory=dict(required=False, type="str"),
        placement_constraints=dict(
            required=False,
            type="list",
            elements="dict",
            options=dict(type=dict(type="str"), expression=dict(type="str")),
        ),
        runtime_platform=dict(
            required=False,
            default={"operatingSystemFamily": "LINUX", "cpuArchitecture": "X86_64"},
            type="dict",
            options=dict(
                cpuArchitecture=dict(required=False, choices=["X86_64", "ARM64"]),
                operatingSystemFamily=dict(
                    required=False,
                    choices=[
                        "LINUX",
                        "WINDOWS_SERVER_2019_FULL",
                        "WINDOWS_SERVER_2019_CORE",
                        "WINDOWS_SERVER_2022_FULL",
                        "WINDOWS_SERVER_2022_CORE",
                    ],
                ),
            ),
        ),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("launch_type", "FARGATE", ["cpu", "memory"])],
    )

    task_to_describe = None
    task_mgr = EcsTaskManager(module)
    results = dict(changed=False)

    if module.params["state"] == "present":
        if "containers" not in module.params or not module.params["containers"]:
            module.fail_json(msg="To use task definitions, a list of containers must be specified")

        if "family" not in module.params or not module.params["family"]:
            module.fail_json(msg="To use task definitions, a family must be specified")

        network_mode = module.params["network_mode"]
        launch_type = module.params["launch_type"]
        placement_constraints = module.params["placement_constraints"]
        if launch_type == "FARGATE":
            if network_mode != "awsvpc":
                module.fail_json(msg="To use FARGATE launch type, network_mode must be awsvpc")
            if placement_constraints:
                module.fail_json(msg="Task placement constraints are not supported for tasks run on Fargate")

        for container in module.params["containers"]:
            if container.get("links") and network_mode == "awsvpc":
                module.fail_json(msg="links parameter is not supported if network mode is awsvpc.")

            for environment in container.get("environment", []):
                environment["value"] = environment["value"]

            for environment_file in container.get("environmentFiles", []):
                if environment_file["type"] != "s3":
                    module.fail_json(msg="The only supported value for environmentFiles is s3.")

            for linux_param in container.get("linuxParameters", {}):
                if linux_param == "maxSwap" and launch_type == "FARGATE":
                    module.fail_json(msg="devices parameter is not supported with the FARGATE launch type.")

                if linux_param == "maxSwap" and launch_type == "FARGATE":
                    module.fail_json(msg="maxSwap parameter is not supported with the FARGATE launch type.")
                elif linux_param == "maxSwap" and int(container["linuxParameters"]["maxSwap"]) < 0:
                    module.fail_json(msg="Accepted values for maxSwap are 0 or any positive integer.")

                if linux_param == "swappiness" and (int(container["linuxParameters"]["swappiness"]) < 0 or int(container["linuxParameters"]["swappiness"]) > 100):
                    module.fail_json(msg="Accepted values for swappiness are whole numbers between 0 and 100.")

                if linux_param == "sharedMemorySize" and launch_type == "FARGATE":
                    module.fail_json(msg="sharedMemorySize parameter is not supported with the FARGATE launch type.")

                if linux_param == "tmpfs" and launch_type == "FARGATE":
                    module.fail_json(msg="tmpfs parameter is not supported with the FARGATE launch type.")

            if container.get("hostname") and network_mode == "awsvpc":
                module.fail_json(msg="hostname parameter is not supported when the awsvpc network mode is used.")

            if container.get("extraHosts") and network_mode == "awsvpc":
                module.fail_json(msg="extraHosts parameter is not supported when the awsvpc network mode is used.")

        family = module.params["family"]
        existing_definitions_in_family = task_mgr.describe_task_definitions(module.params["family"])

        if "revision" in module.params and module.params["revision"]:
            # The definition specifies revision. We must guarantee that an active revision of that number will result from this.
            revision = int(module.params["revision"])

            # A revision has been explicitly specified. Attempt to locate a matching revision
            tasks_defs_for_revision = [td for td in existing_definitions_in_family if td["revision"] == revision]
            existing = tasks_defs_for_revision[0] if len(tasks_defs_for_revision) > 0 else None

            if existing and existing["status"] != "ACTIVE":
                # We cannot reactivate an inactive revision
                module.fail_json(msg=f"A task in family '{family}' already exists for revision {int(revision)}, but it is inactive")
            elif not existing:
                if not existing_definitions_in_family and revision != 1:
                    module.fail_json(msg=f"You have specified a revision of {int(revision)} but a created revision would be 1")
                elif existing_definitions_in_family and existing_definitions_in_family[-1]["revision"] + 1 != revision:
                    module.fail_json(msg=(f"You have specified a revision of {int(revision)} but a created revision would be" f" {int(existing_definitions_in_family[-1]['revision'] + 1)}"))
        else:
            existing = None

            def _right_has_values_of_left(left, right):
                # Make sure the values are equivalent for everything left has
                for k, v in left.items():
                    if not ((not v and (k not in right or not right[k])) or (k in right and v == right[k])):
                        # We don't care about list ordering because ECS can change things
                        if isinstance(v, list) and k in right:
                            left_list = v
                            right_list = right[k] or []

                            if len(left_list) != len(right_list):
                                return False

                            for list_val in left_list:
                                if list_val not in right_list:
                                    # if list_val is the port mapping, the key 'protocol' may be absent (but defaults to 'tcp')
                                    # fill in that default if absent and see if it is in right_list then
                                    if isinstance(list_val, dict) and not list_val.get("protocol"):
                                        modified_list_val = dict(list_val)
                                        modified_list_val.update(protocol="tcp")
                                        if modified_list_val in right_list:
                                            continue
                        else:
                            return False

                # Make sure right doesn't have anything that left doesn't
                for k, v in right.items():
                    if v and k not in left:
                        # 'essential' defaults to True when not specified
                        if k == "essential" and v is True:
                            pass
                        else:
                            return False

                return True

            def _task_definition_matches(
                requested_volumes,
                requested_containers,
                requested_task_role_arn,
                requested_launch_type,
                existing_task_definition,
            ):
                if td["status"] != "ACTIVE":
                    return None

                if requested_task_role_arn != td.get("taskRoleArn", ""):
                    return None

                if requested_launch_type is not None and requested_launch_type not in td.get("requiresCompatibilities", []):
                    return None

                existing_volumes = td.get("volumes", []) or []

                if len(requested_volumes) != len(existing_volumes):
                    # Nope.
                    return None

                if len(requested_volumes) > 0:
                    for requested_vol in requested_volumes:
                        found = False

                        for actual_vol in existing_volumes:
                            if _right_has_values_of_left(requested_vol, actual_vol):
                                found = True
                                break

                        if not found:
                            return None

                existing_containers = td.get("containerDefinitions", []) or []

                if len(requested_containers) != len(existing_containers):
                    # Nope.
                    return None

                for requested_container in requested_containers:
                    found = False

                    for actual_container in existing_containers:
                        if _right_has_values_of_left(requested_container, actual_container):
                            found = True
                            break

                    if not found:
                        return None

                return existing_task_definition

            # No revision explicitly specified. Attempt to find an active, matching revision that has all the properties requested
            for td in existing_definitions_in_family:
                requested_volumes = module.params["volumes"] or []
                requested_containers = module.params["containers"] or []
                requested_task_role_arn = module.params["task_role_arn"]
                requested_launch_type = module.params["launch_type"]
                existing = _task_definition_matches(requested_volumes, requested_containers, requested_task_role_arn, requested_launch_type, td)

                if existing:
                    break

        if existing and not module.params.get("force_create"):
            # Awesome. Have an existing one. Nothing to do.
            results["taskdefinition"] = existing
        else:
            if not module.check_mode:
                # Doesn't exist. create it.
                volumes = module.params.get("volumes", []) or []
                results["taskdefinition"] = task_mgr.register_task(
                    module.params["family"],
                    module.params["task_role_arn"],
                    module.params["execution_role_arn"],
                    module.params["network_mode"],
                    module.params["containers"],
                    volumes,
                    module.params["launch_type"],
                    module.params["cpu"],
                    module.params["memory"],
                    module.params["placement_constraints"],
                    module.params["runtime_platform"],
                )
            results["changed"] = True

    elif module.params["state"] in ("inactive", "absent"):
        # When de-registering or deleting a task definition, we can specify the ARN OR the family and revision.
        # For state=absent, we can also specify just the family to delete ALL revisions.
        if "arn" in module.params and module.params["arn"] is not None:
            task_to_describe = module.params["arn"]
        elif "family" in module.params and module.params["family"] is not None and "revision" in module.params and module.params["revision"] is not None:
            task_to_describe = module.params["family"] + ":" + str(module.params["revision"])
        elif module.params["state"] == "absent" and "family" in module.params and module.params["family"] is not None:
            # Delete ALL revisions in the family
            task_to_describe = None
            family = module.params["family"]
            existing_definitions = task_mgr.describe_task_definitions(family)

            if not existing_definitions:
                # No task definitions in this family, nothing to do
                results["taskdefinitions"] = []
            else:
                deleted_definitions = []
                for td in existing_definitions:
                    if td.get("status") == "DELETE_IN_PROGRESS":
                        continue
                    if not module.check_mode:
                        # Must deregister (make INACTIVE) before deleting
                        if td.get("status") == "ACTIVE":
                            task_mgr.deregister_task(td["taskDefinitionArn"])
                        deleted_td = task_mgr.delete_task(td["taskDefinitionArn"])
                        if deleted_td:
                            deleted_definitions.append(deleted_td)
                    else:
                        deleted_definitions.append(td)
                    results["changed"] = True

                results["taskdefinitions"] = deleted_definitions

            module.exit_json(**results)
        else:
            module.fail_json(msg="To delete task definitions, an arn, family and revision, or family alone (for state=absent) must be specified")

        existing = task_mgr.describe_task(task_to_describe)

        if not existing:
            # Task definition doesn't exist, nothing to do
            pass
        else:
            results["taskdefinition"] = existing

            if module.params["state"] == "inactive":
                # Deregister only (marks as INACTIVE)
                if "status" in existing and existing["status"] == "INACTIVE":
                    results["changed"] = False
                else:
                    if not module.check_mode:
                        task_mgr.deregister_task(task_to_describe)
                    results["changed"] = True

            elif module.params["state"] == "absent":
                # Permanently delete the task definition
                if "status" in existing and existing["status"] == "DELETE_IN_PROGRESS":
                    results["changed"] = False
                else:
                    if not module.check_mode:
                        # Must deregister (make INACTIVE) before deleting
                        if existing.get("status") == "ACTIVE":
                            task_mgr.deregister_task(task_to_describe)
                        deleted_td = task_mgr.delete_task(task_to_describe)
                        if deleted_td:
                            results["taskdefinition"] = deleted_td
                    results["changed"] = True

    module.exit_json(**results)


if __name__ == "__main__":
    main()
