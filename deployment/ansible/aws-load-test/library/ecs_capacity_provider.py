#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: ecs_capacity_provider
version_added: 1.0.0
short_description: Create or delete an ECS capacity provider
description:
  - Creates or deletes ECS capacity providers.
  - Capacity providers are used to manage the infrastructure for ECS tasks.
notes:
  - For details of the parameters and returns see U(https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_CreateCapacityProvider.html).
author:
  - "MCP Gateway Contributors"
options:
    state:
        description:
          - The desired state of the capacity provider.
        required: true
        choices: ["present", "absent"]
        type: str
    name:
        description:
          - The name of the capacity provider.
          - Up to 255 characters. Letters, numbers, underscores, and hyphens are allowed.
          - Cannot start with C(aws), C(ecs), or C(fargate).
        required: true
        type: str
    auto_scaling_group_provider:
        description:
          - The Auto Scaling group settings for the capacity provider.
        required: false
        type: dict
        suboptions:
            auto_scaling_group_arn:
                description:
                  - The Amazon Resource Name (ARN) or short name of the Auto Scaling group.
                type: str
                required: true
            managed_scaling:
                description:
                  - The managed scaling settings for the Auto Scaling group.
                type: dict
                suboptions:
                    status:
                        description:
                          - Whether managed scaling is enabled.
                        type: str
                        choices: ["ENABLED", "DISABLED"]
                    target_capacity:
                        description:
                          - The target capacity utilization percentage (1-100).
                        type: int
                    minimum_scaling_step_size:
                        description:
                          - Minimum number of instances to scale out at a time (1-10000).
                        type: int
                    maximum_scaling_step_size:
                        description:
                          - Maximum number of instances to scale out at a time (1-10000).
                        type: int
                    instance_warmup_period:
                        description:
                          - Seconds before a newly launched instance contributes to metrics (0-10000).
                        type: int
            managed_termination_protection:
                description:
                  - Whether managed termination protection is enabled.
                type: str
                choices: ["ENABLED", "DISABLED"]
            managed_draining:
                description:
                  - Whether managed draining is enabled for graceful EC2 instance draining.
                type: str
                choices: ["ENABLED", "DISABLED"]
    tags:
        description:
          - A dictionary of tags to add to the capacity provider.
        type: dict
        required: false
    wait:
        description:
          - Whether to wait for the capacity provider to reach ACTIVE state.
        type: bool
        default: true
    wait_timeout:
        description:
          - Maximum time in seconds to wait for the capacity provider to become active.
        type: int
        default: 300
extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""
# Create a capacity provider with managed scaling
- ecs_capacity_provider:
    state: present
    name: my-capacity-provider
    auto_scaling_group_provider:
      auto_scaling_group_arn: arn:aws:autoscaling:us-east-1:123456789012:autoScalingGroup:uuid:autoScalingGroupName/my-asg
      managed_scaling:
        status: ENABLED
        target_capacity: 100
        minimum_scaling_step_size: 1
        maximum_scaling_step_size: 10
      managed_termination_protection: DISABLED
      managed_draining: ENABLED

# Create a simple capacity provider
- ecs_capacity_provider:
    state: present
    name: simple-capacity-provider
    auto_scaling_group_provider:
      auto_scaling_group_arn: my-asg
      managed_scaling:
        status: ENABLED

# Delete a capacity provider
- ecs_capacity_provider:
    state: absent
    name: my-capacity-provider
"""

RETURN = r"""
capacity_provider:
    description: Details of the capacity provider.
    returned: when state is present
    type: complex
    contains:
        capacityProviderArn:
            description: The Amazon Resource Name (ARN) of the capacity provider.
            returned: always
            type: str
        name:
            description: The name of the capacity provider.
            returned: always
            type: str
        status:
            description: The status of the capacity provider.
            returned: always
            type: str
        autoScalingGroupProvider:
            description: The Auto Scaling group settings.
            returned: when applicable
            type: dict
        tags:
            description: The tags applied to the capacity provider.
            returned: when tags exist
            type: list
"""

import time

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import snake_dict_to_camel_dict

from ansible_collections.amazon.aws.plugins.module_utils.tagging import ansible_dict_to_boto3_tag_list
from ansible_collections.amazon.aws.plugins.module_utils.tagging import boto3_tag_list_to_ansible_dict

from ansible_collections.community.aws.plugins.module_utils.modules import AnsibleCommunityAWSModule as AnsibleAWSModule


class EcsCapacityProviderManager:
    """Handles ECS Capacity Providers"""

    def __init__(self, module):
        self.module = module
        self.ecs = module.client("ecs")

    def describe_capacity_provider(self, name):
        """Describe a capacity provider by name"""
        try:
            response = self.ecs.describe_capacity_providers(
                capacityProviders=[name],
                include=["TAGS"],
            )
            if response.get("capacityProviders"):
                return response["capacityProviders"][0]
            return None
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ClientException":
                return None
            raise

    def create_capacity_provider(self, name, auto_scaling_group_provider, tags):
        """Create a new capacity provider"""
        params = {
            "name": name,
        }

        if auto_scaling_group_provider:
            asg_provider = {}
            asg_provider["autoScalingGroupArn"] = auto_scaling_group_provider["auto_scaling_group_arn"]

            if auto_scaling_group_provider.get("managed_scaling"):
                managed_scaling = {}
                ms = auto_scaling_group_provider["managed_scaling"]
                if ms.get("status"):
                    managed_scaling["status"] = ms["status"]
                if ms.get("target_capacity") is not None:
                    managed_scaling["targetCapacity"] = ms["target_capacity"]
                if ms.get("minimum_scaling_step_size") is not None:
                    managed_scaling["minimumScalingStepSize"] = ms["minimum_scaling_step_size"]
                if ms.get("maximum_scaling_step_size") is not None:
                    managed_scaling["maximumScalingStepSize"] = ms["maximum_scaling_step_size"]
                if ms.get("instance_warmup_period") is not None:
                    managed_scaling["instanceWarmupPeriod"] = ms["instance_warmup_period"]
                asg_provider["managedScaling"] = managed_scaling

            if auto_scaling_group_provider.get("managed_termination_protection"):
                asg_provider["managedTerminationProtection"] = auto_scaling_group_provider["managed_termination_protection"]

            if auto_scaling_group_provider.get("managed_draining"):
                asg_provider["managedDraining"] = auto_scaling_group_provider["managed_draining"]

            params["autoScalingGroupProvider"] = asg_provider

        if tags:
            params["tags"] = ansible_dict_to_boto3_tag_list(tags, "key", "value")

        response = self.ecs.create_capacity_provider(**params)
        return response.get("capacityProvider")

    def delete_capacity_provider(self, name):
        """Delete a capacity provider"""
        response = self.ecs.delete_capacity_provider(capacityProvider=name)
        return response.get("capacityProvider")

    def wait_for_status(self, name, target_status, timeout):
        """Wait for capacity provider to reach target status"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            cp = self.describe_capacity_provider(name)
            if cp and cp.get("status") == target_status:
                return cp
            time.sleep(10)
        return None


def main():
    argument_spec = dict(
        state=dict(required=True, choices=["present", "absent"]),
        name=dict(required=True, type="str"),
        auto_scaling_group_provider=dict(
            required=False,
            type="dict",
            options=dict(
                auto_scaling_group_arn=dict(type="str", required=True),
                managed_scaling=dict(
                    type="dict",
                    options=dict(
                        status=dict(type="str", choices=["ENABLED", "DISABLED"]),
                        target_capacity=dict(type="int"),
                        minimum_scaling_step_size=dict(type="int"),
                        maximum_scaling_step_size=dict(type="int"),
                        instance_warmup_period=dict(type="int"),
                    ),
                ),
                managed_termination_protection=dict(type="str", choices=["ENABLED", "DISABLED"]),
                managed_draining=dict(type="str", choices=["ENABLED", "DISABLED"]),
            ),
        ),
        tags=dict(required=False, type="dict"),
        wait=dict(required=False, type="bool", default=True),
        wait_timeout=dict(required=False, type="int", default=300),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ("state", "present", ["auto_scaling_group_provider"]),
        ],
    )

    cp_manager = EcsCapacityProviderManager(module)
    results = dict(changed=False)

    name = module.params["name"]
    state = module.params["state"]

    try:
        existing = cp_manager.describe_capacity_provider(name)
    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
        module.fail_json_aws(e, msg=f"Failed to describe capacity provider '{name}'")

    if state == "present":
        # Treat INACTIVE capacity providers as non-existent (they were deleted)
        if existing and existing.get("status") == "INACTIVE":
            existing = None

        if existing:
            # Capacity provider already exists
            if existing.get("status") == "ACTIVE":
                results["capacity_provider"] = existing
                results["changed"] = False
            else:
                # Wait for it to become active if requested
                if module.params["wait"]:
                    cp = cp_manager.wait_for_status(name, "ACTIVE", module.params["wait_timeout"])
                    if cp:
                        results["capacity_provider"] = cp
                    else:
                        module.fail_json(msg=f"Timeout waiting for capacity provider '{name}' to become ACTIVE")
                else:
                    results["capacity_provider"] = existing
        else:
            # Create new capacity provider
            if not module.check_mode:
                try:
                    cp = cp_manager.create_capacity_provider(
                        name,
                        module.params["auto_scaling_group_provider"],
                        module.params["tags"],
                    )

                    if module.params["wait"]:
                        cp = cp_manager.wait_for_status(name, "ACTIVE", module.params["wait_timeout"])
                        if not cp:
                            module.fail_json(msg=f"Timeout waiting for capacity provider '{name}' to become ACTIVE")

                    results["capacity_provider"] = cp
                except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                    module.fail_json_aws(e, msg=f"Failed to create capacity provider '{name}'")

            results["changed"] = True

    elif state == "absent":
        if existing and existing.get("status") != "INACTIVE":
            if not module.check_mode:
                try:
                    cp_manager.delete_capacity_provider(name)
                except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
                    module.fail_json_aws(e, msg=f"Failed to delete capacity provider '{name}'")

            results["changed"] = True

    module.exit_json(**results)


if __name__ == "__main__":
    main()
