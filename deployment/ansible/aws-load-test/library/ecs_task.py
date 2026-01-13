#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: ecs_task
version_added: 1.0.0
short_description: Run, start or stop a task in ECS
description:
    - Creates or deletes instances of task definitions.
author:
    - Mark Chance (@Java1Guy)
options:
    operation:
        description:
            - Which task operation to execute.
            - When I(operation=run) I(task_definition) must be set.
            - When I(operation=start) both I(task_definition) and I(container_instances) must be set.
            - When I(operation=stop) both I(task_definition) and I(task) must be set.
        required: True
        choices: ['run', 'start', 'stop']
        type: str
    cluster:
        description:
            - The name of the cluster to run the task on.
            - If not specified, the cluster name will be C(default).
        required: False
        type: str
        default: 'default'
    task_definition:
        description:
            - The task definition to start, run or stop.
        required: False
        type: str
    overrides:
        description:
            - A dictionary of values to pass to the new instances.
        required: False
        type: dict
    count:
        description:
            - How many new instances to start.
        required: False
        type: int
    task:
        description:
            - The ARN of the task to stop.
        required: False
        type: str
    container_instances:
        description:
            - The list of container instances on which to deploy the task.
        required: False
        type: list
        elements: str
    started_by:
        description:
            - A value showing who or what started the task (for informational purposes).
        required: False
        type: str
    network_configuration:
        description:
          - Network configuration of the service. Only applicable for task definitions created with I(network_mode=awsvpc).
        type: dict
        suboptions:
            assign_public_ip:
                description: Whether the task's elastic network interface receives a public IP address.
                type: bool
                version_added: 1.5.0
            subnets:
                description: A list of subnet IDs to which the task is attached.
                type: list
                elements: str
            security_groups:
                description: A list of group names or group IDs for the task.
                type: list
                elements: str
    launch_type:
        description:
          - The launch type on which to run your service.
        required: false
        choices: ["EC2", "FARGATE"]
        type: str
    tags:
        type: dict
        description:
          - Tags that will be added to ecs tasks on start and run
        required: false
        aliases: ['resource_tags']
    wait:
        description:
          - Whether or not to wait for the desired state.
        type: bool
        default: false
        version_added: 4.1.0
    wait_complete:
        description:
          - Whether to wait for the task to complete execution and capture container exit codes.
          - When enabled, waits for all containers in the task to finish and includes exit codes in results.
          - Only applicable for I(operation=run) and I(operation=start).
          - Implies I(wait=true) to ensure task starts before waiting for completion.
        type: bool
        default: false
        version_added: 4.1.0
extends_documentation_fragment:
    - amazon.aws.common.modules
    - amazon.aws.region.modules
    - amazon.aws.boto3
"""

EXAMPLES = r"""
# Simple example of run task
- name: Run task
  community.aws.ecs_task:
    operation: run
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    count: 1
    started_by: ansible_user
  register: task_output

# Simple example of start task

- name: Start a task
  community.aws.ecs_task:
    operation: start
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    task: "arn:aws:ecs:us-west-2:123456789012:task/3f8353d1-29a8-4689-bbf6-ad79937ffe8a"
    tags:
      resourceName: a_task_for_ansible_to_run
      type: long_running_task
      network: internal
      version: 1.4
    container_instances:
      - arn:aws:ecs:us-west-2:123456789012:container-instance/79c23f22-876c-438a-bddf-55c98a3538a8
    started_by: ansible_user
    network_configuration:
      subnets:
        - subnet-abcd1234
      security_groups:
        - sg-aaaa1111
        - my_security_group
  register: task_output

- name: RUN a task on Fargate
  community.aws.ecs_task:
    operation: run
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    task: "arn:aws:ecs:us-west-2:123456789012:task/3f8353d1-29a8-4689-bbf6-ad79937ffe8a"
    started_by: ansible_user
    launch_type: FARGATE
    network_configuration:
      subnets:
        - subnet-abcd1234
      security_groups:
        - sg-aaaa1111
        - my_security_group
  register: task_output

- name: RUN a task on Fargate with public ip assigned
  community.aws.ecs_task:
    operation: run
    count: 2
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    task: "arn:aws:ecs:us-west-2:123456789012:task/3f8353d1-29a8-4689-bbf6-ad79937ffe8a"
    started_by: ansible_user
    launch_type: FARGATE
    network_configuration:
      assign_public_ip: true
      subnets:
        - subnet-abcd1234
  register: task_output

- name: Stop a task
  community.aws.ecs_task:
    operation: stop
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    task: "arn:aws:ecs:us-west-2:123456789012:task/3f8353d1-29a8-4689-bbf6-ad79937ffe8a"

- name: Run a task and wait for it to complete
  community.aws.ecs_task:
    operation: run
    cluster: console-sample-app-static-cluster
    task_definition: console-sample-app-static-taskdef
    count: 1
    started_by: ansible_user
    launch_type: FARGATE
    network_configuration:
      subnets:
        - subnet-abcd1234
      security_groups:
        - sg-aaaa1111
    wait_complete: true
  register: task_output

# Access task completion details:
# - task_output.task[0].stopCode (e.g., "EssentialContainerExited", "TaskFailedToStart")
# - task_output.task[0].stoppedReason (human-readable explanation)
# - task_output.task[0].containers[0].exitCode (container exit code)
"""

RETURN = r"""
task:
    description: details about the task that was started
    returned: success
    type: complex
    contains:
        taskArn:
            description: The Amazon Resource Name (ARN) that identifies the task.
            returned: always
            type: str
        clusterArn:
            description: The Amazon Resource Name (ARN) of the of the cluster that hosts the task.
            returned: only when details is true
            type: str
        taskDefinitionArn:
            description: The Amazon Resource Name (ARN) of the task definition.
            returned: only when details is true
            type: str
        containerInstanceArn:
            description: The Amazon Resource Name (ARN) of the container running the task.
            returned: only when details is true
            type: str
        overrides:
            description: The container overrides set for this task.
            returned: only when details is true
            type: list
            elements: dict
        lastStatus:
            description: The last recorded status of the task.
            returned: only when details is true
            type: str
        desiredStatus:
            description: The desired status of the task.
            returned: only when details is true
            type: str
        containers:
            description: The container details.
            returned: only when details is true
            type: list
            elements: dict
        startedBy:
            description: The used who started the task.
            returned: only when details is true
            type: str
        stoppedReason:
            description: The reason why the task was stopped.
            returned: only when details is true
            type: str
        createdAt:
            description: The timestamp of when the task was created.
            returned: only when details is true
            type: str
        startedAt:
            description: The timestamp of when the task was started.
            returned: only when details is true
            type: str
        stoppedAt:
            description: The timestamp of when the task was stopped.
            returned: only when details is true
            type: str
        launchType:
            description: The launch type on which to run your task.
            returned: always
            type: str
        stopCode:
            description: The stop code indicating why the task was stopped.
            returned: when wait_complete is true and task has stopped
            type: str
        containers:
            description: Details about containers in the task, including exitCode for each container.
            returned: when wait_complete is true and task has stopped
            type: list
            elements: dict
"""

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible_collections.amazon.aws.plugins.module_utils.ec2 import get_ec2_security_group_ids_from_names
from ansible_collections.amazon.aws.plugins.module_utils.tagging import ansible_dict_to_boto3_tag_list

from ansible_collections.community.aws.plugins.module_utils.modules import AnsibleCommunityAWSModule as AnsibleAWSModule


class EcsExecManager:
    """Handles ECS Tasks"""

    def __init__(self, module):
        self.module = module
        self.ecs = module.client("ecs")
        self.ec2 = module.client("ec2")

    def format_network_configuration(self, network_config):
        result = dict()
        if "subnets" in network_config:
            result["subnets"] = network_config["subnets"]
        else:
            self.module.fail_json(msg="Network configuration must include subnets")
        if "security_groups" in network_config:
            groups = network_config["security_groups"]
            if any(not sg.startswith("sg-") for sg in groups):
                try:
                    vpc_id = self.ec2.describe_subnets(SubnetIds=[result["subnets"][0]])["Subnets"][0]["VpcId"]
                    groups = get_ec2_security_group_ids_from_names(groups, self.ec2, vpc_id)
                except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
                    self.module.fail_json_aws(e, msg="Couldn't look up security groups")
            result["securityGroups"] = groups
        if "assign_public_ip" in network_config:
            if network_config["assign_public_ip"] is True:
                result["assignPublicIp"] = "ENABLED"
            else:
                result["assignPublicIp"] = "DISABLED"

        return dict(awsvpcConfiguration=result)

    def list_tasks(self, cluster_name, service_name, status):
        response = self.ecs.list_tasks(
            cluster=cluster_name,
            family=service_name,
            desiredStatus=status,
        )
        if len(response["taskArns"]) > 0:
            for c in response["taskArns"]:
                if c.endswith(service_name):
                    return c
        return None

    def run_task(self, cluster, task_definition, overrides, count, startedBy, launch_type, tags):
        if overrides is None:
            overrides = dict()
        params = dict(cluster=cluster, taskDefinition=task_definition, overrides=overrides, count=count, startedBy=startedBy)
        if self.module.params["network_configuration"]:
            params["networkConfiguration"] = self.format_network_configuration(self.module.params["network_configuration"])
        if launch_type:
            params["launchType"] = launch_type
        if tags:
            params["tags"] = ansible_dict_to_boto3_tag_list(tags, "key", "value")

            # TODO: need to check if long arn format enabled.
        try:
            response = self.ecs.run_task(**params)
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Couldn't run task")
        # include tasks and failures
        return response["tasks"]

    def start_task(self, cluster, task_definition, overrides, container_instances, startedBy, tags):
        args = dict()
        if cluster:
            args["cluster"] = cluster
        if task_definition:
            args["taskDefinition"] = task_definition
        if overrides:
            args["overrides"] = overrides
        if container_instances:
            args["containerInstances"] = container_instances
        if startedBy:
            args["startedBy"] = startedBy
        if self.module.params["network_configuration"]:
            args["networkConfiguration"] = self.format_network_configuration(self.module.params["network_configuration"])
        if tags:
            args["tags"] = ansible_dict_to_boto3_tag_list(tags, "key", "value")
        try:
            response = self.ecs.start_task(**args)
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Couldn't start task")
        # include tasks and failures
        return response["tasks"]

    def stop_task(self, cluster, task):
        response = self.ecs.stop_task(cluster=cluster, task=task)
        return response["task"]

    def ecs_task_long_format_enabled(self):
        account_support = self.ecs.list_account_settings(name="taskLongArnFormat", effectiveSettings=True)
        return account_support["settings"][0]["value"] == "enabled"

    def wait_for_task_completion(self, cluster, task_arns):
        """
        Wait for tasks to complete and return detailed information.

        Args:
            cluster: The cluster name
            task_arns: List of task ARNs to wait for

        Returns:
            List of task details including AWS's native stopCode, stoppedReason,
            and container exitCode fields
        """
        # Wait for tasks to stop
        waiter = self.ecs.get_waiter("tasks_stopped")
        try:
            waiter.wait(
                tasks=task_arns,
                cluster=cluster,
            )
        except botocore.exceptions.WaiterError as e:
            self.module.fail_json_aws(e, "Timeout waiting for tasks to complete")

        # Describe tasks to get complete details including exit codes
        try:
            response = self.ecs.describe_tasks(
                cluster=cluster,
                tasks=task_arns,
            )
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
            self.module.fail_json_aws(e, "Failed to describe completed tasks")

        return response["tasks"]


def main():
    argument_spec = dict(
        operation=dict(required=True, choices=["run", "start", "stop"]),
        cluster=dict(required=False, type="str", default="default"),  # R S P
        task_definition=dict(required=False, type="str"),  # R* S*
        overrides=dict(required=False, type="dict"),  # R S
        count=dict(required=False, type="int"),  # R
        task=dict(required=False, type="str"),  # P*
        container_instances=dict(required=False, type="list", elements="str"),  # S*
        started_by=dict(required=False, type="str"),  # R S
        network_configuration=dict(required=False, type="dict"),
        launch_type=dict(required=False, choices=["EC2", "FARGATE"]),
        tags=dict(required=False, type="dict", aliases=["resource_tags"]),
        wait=dict(required=False, default=False, type="bool"),
        wait_complete=dict(required=False, default=False, type="bool"),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ("launch_type", "FARGATE", ["network_configuration"]),
            ("operation", "run", ["task_definition"]),
            ("operation", "start", ["task_definition", "container_instances"]),
            ("operation", "stop", ["task_definition", "task"]),
        ],
    )

    # Validate Inputs
    if module.params["operation"] == "run":
        task_to_list = module.params["task_definition"]
        status_type = "RUNNING"

    if module.params["operation"] == "start":
        task_to_list = module.params["task"]
        status_type = "RUNNING"

    if module.params["operation"] == "stop":
        task_to_list = module.params["task_definition"]
        status_type = "STOPPED"

    service_mgr = EcsExecManager(module)

    if module.params["tags"]:
        if not service_mgr.ecs_task_long_format_enabled():
            module.fail_json(msg="Cannot set task tags: long format task arns are required to set tags")

    existing = service_mgr.list_tasks(module.params["cluster"], task_to_list, status_type)

    results = dict(changed=False)
    if module.params["operation"] == "run":
        if existing:
            # TBD - validate the rest of the details
            results["task"] = existing
        else:
            if not module.check_mode:
                # run_task returns a list of tasks created
                tasks = service_mgr.run_task(
                    module.params["cluster"],
                    module.params["task_definition"],
                    module.params["overrides"],
                    module.params["count"],
                    module.params["started_by"],
                    module.params["launch_type"],
                    module.params["tags"],
                )

                # Wait for task(s) to be running prior to exiting
                if module.params["wait"] or module.params["wait_complete"]:
                    waiter = service_mgr.ecs.get_waiter("tasks_running")
                    try:
                        waiter.wait(
                            tasks=[task["taskArn"] for task in tasks],
                            cluster=module.params["cluster"],
                        )
                    except botocore.exceptions.WaiterError as e:
                        module.fail_json_aws(e, "Timeout waiting for tasks to run")

                # Wait for task(s) to complete and capture exit codes
                if module.params["wait_complete"]:
                    tasks = service_mgr.wait_for_task_completion(
                        module.params["cluster"],
                        [task["taskArn"] for task in tasks],
                    )

                results["task"] = tasks

            results["changed"] = True

    elif module.params["operation"] == "start":
        if existing:
            # TBD - validate the rest of the details
            results["task"] = existing
        else:
            if not module.check_mode:
                tasks = service_mgr.start_task(
                    module.params["cluster"],
                    module.params["task_definition"],
                    module.params["overrides"],
                    module.params["container_instances"],
                    module.params["started_by"],
                    module.params["tags"],
                )

                # Wait for task(s) to complete and capture exit codes
                if module.params["wait_complete"]:
                    # First wait for tasks to be running
                    waiter = service_mgr.ecs.get_waiter("tasks_running")
                    try:
                        waiter.wait(
                            tasks=[task["taskArn"] for task in tasks],
                            cluster=module.params["cluster"],
                        )
                    except botocore.exceptions.WaiterError as e:
                        module.fail_json_aws(e, "Timeout waiting for tasks to run")

                    # Then wait for completion
                    tasks = service_mgr.wait_for_task_completion(
                        module.params["cluster"],
                        [task["taskArn"] for task in tasks],
                    )

                results["task"] = tasks

            results["changed"] = True

    elif module.params["operation"] == "stop":
        if existing:
            results["task"] = existing
        else:
            if not module.check_mode:
                # it exists, so we should delete it and mark changed.
                # return info about the cluster deleted
                results["task"] = service_mgr.stop_task(module.params["cluster"], module.params["task"])

                # Wait for task to be stopped prior to exiting
                if module.params["wait"]:
                    waiter = service_mgr.ecs.get_waiter("tasks_stopped")
                    try:
                        waiter.wait(
                            tasks=[module.params["task"]],
                            cluster=module.params["cluster"],
                        )
                    except botocore.exceptions.WaiterError as e:
                        module.fail_json_aws(e, "Timeout waiting for task to stop")

            results["changed"] = True

    module.exit_json(**results)


if __name__ == "__main__":
    main()
