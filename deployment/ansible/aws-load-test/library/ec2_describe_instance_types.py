#!/usr/bin/python
# -*- coding: utf-8 -*-
# ruff: noqa: E402

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: ec2_describe_instance_types
version_added: 1.0.0
short_description: Retrieve information about EC2 instance types
description:
  - Retrieves detailed information about EC2 instance types.
  - By default, all instance types for the current region are described.
  - Can filter results using instance type names or filters.
  - Does not implement DryRun or pagination features.
author:
  - "Jonathan Springer <jps@s390x.com>"
options:
    instance_types:
        description:
          - List of instance types to describe.
          - Must be exact instance type names (e.g., C(t3.micro), C(m5.large)).
          - For wildcard matching, use the I(filters) option with C(instance-type) filter instead.
          - Maximum of 100 instance types.
          - If not provided, all instance types are returned.
        required: false
        type: list
        elements: str
        default: []
    filters:
        description:
          - A list of filters to apply.
          - Each filter is a dict with I(name) and I(values) keys.
          - Filter values support wildcards (e.g., C(t3.*) to match all t3 instance types).
          - See U(https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html)
            for possible filters.
          - Filter names and values are case sensitive.
        required: false
        type: list
        elements: dict
        default: []
        suboptions:
            name:
                description: The name of the filter.
                type: str
                required: true
            values:
                description: The filter values. Can be a single value or list of values.
                type: list
                elements: str
                required: true
extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""
# Get information about all instance types
- ec2_describe_instance_types:
  register: all_instance_types

# Get information about specific instance types
- ec2_describe_instance_types:
    instance_types:
      - t3.micro
      - t3.small
      - t3.medium
  register: t3_types

# Get all c5 instance types using wildcard filter
- ec2_describe_instance_types:
    filters:
      - name: instance-type
        values:
          - "c5.*"
  register: c5_types

# Filter for current generation instance types with GPU
- ec2_describe_instance_types:
    filters:
      - name: current-generation
        values:
          - "true"
      - name: instance-type
        values:
          - "p3*"
  register: gpu_types

# Filter for bare metal instance types
- ec2_describe_instance_types:
    filters:
      - name: bare-metal
        values:
          - "true"
  register: bare_metal_types

# Filter by processor architecture
- ec2_describe_instance_types:
    filters:
      - name: processor-info.supported-architecture
        values:
          - arm64
  register: arm_types

# Filter for free tier eligible instances
- ec2_describe_instance_types:
    filters:
      - name: free-tier-eligible
        values:
          - "true"
  register: free_tier_types

# Combine multiple filters (m5 family with 4 vCPUs)
- ec2_describe_instance_types:
    filters:
      - name: instance-type
        values:
          - "m5.*"
      - name: vcpu-info.default-vcpus
        values:
          - "4"
  register: m5_4vcpu_types

# Filter with multiple values
- ec2_describe_instance_types:
    filters:
      - name: processor-info.supported-architecture
        values:
          - arm64
          - x86_64
  register: multi_arch_types

# Combine specific instance types with filters
- ec2_describe_instance_types:
    instance_types:
      - t3.micro
      - t3.small
      - t3.medium
    filters:
      - name: processor-info.supported-architecture
        values:
          - x86_64
  register: filtered_t3_types
"""

RETURN = r"""
instance_types:
    description: List of instance type information objects.
    returned: always
    type: list
    elements: dict
    contains:
        instance_type:
            description: The instance type identifier.
            returned: always
            type: str
            sample: "t3.micro"
        current_generation:
            description: Whether the instance type is current generation.
            returned: always
            type: bool
        free_tier_eligible:
            description: Whether the instance type is eligible for the free tier.
            returned: always
            type: bool
        supported_usage_classes:
            description: Usage classes supported (on-demand, spot, capacity-block).
            returned: always
            type: list
            elements: str
        supported_root_device_types:
            description: Supported root device types (ebs, instance-store).
            returned: always
            type: list
            elements: str
        supported_virtualization_types:
            description: Supported virtualization types (hvm, paravirtual).
            returned: always
            type: list
            elements: str
        bare_metal:
            description: Whether this is a bare metal instance type.
            returned: always
            type: bool
        hypervisor:
            description: The hypervisor type (nitro, xen).
            returned: when available
            type: str
        processor_info:
            description: Processor information.
            returned: always
            type: dict
            contains:
                supported_architectures:
                    description: Supported CPU architectures.
                    type: list
                    elements: str
                sustained_clock_speed_in_ghz:
                    description: Sustained clock speed in GHz.
                    type: float
        v_cpu_info:
            description: vCPU information.
            returned: always
            type: dict
            contains:
                default_v_cpus:
                    description: Default number of vCPUs.
                    type: int
                default_cores:
                    description: Default number of cores.
                    type: int
                default_threads_per_core:
                    description: Default threads per core.
                    type: int
                valid_cores:
                    description: List of valid core counts.
                    type: list
                    elements: int
                valid_threads_per_core:
                    description: List of valid thread per core counts.
                    type: list
                    elements: int
        memory_info:
            description: Memory information.
            returned: always
            type: dict
            contains:
                size_in_mi_b:
                    description: Memory size in MiB.
                    type: int
        instance_storage_supported:
            description: Whether instance storage is supported.
            returned: always
            type: bool
        instance_storage_info:
            description: Instance storage information.
            returned: when instance_storage_supported is true
            type: dict
            contains:
                total_size_in_g_b:
                    description: Total instance storage size in GB.
                    type: int
                disks:
                    description: List of instance storage disks.
                    type: list
                    elements: dict
                nvme_support:
                    description: NVMe support status.
                    type: str
                encryption_support:
                    description: Encryption support status.
                    type: str
        ebs_info:
            description: EBS information.
            returned: always
            type: dict
            contains:
                ebs_optimized_support:
                    description: EBS optimized support status.
                    type: str
                encryption_support:
                    description: EBS encryption support status.
                    type: str
                ebs_optimized_info:
                    description: EBS optimized performance info.
                    type: dict
                nvme_support:
                    description: NVMe support status.
                    type: str
        network_info:
            description: Network information.
            returned: always
            type: dict
            contains:
                network_performance:
                    description: Network performance description.
                    type: str
                maximum_network_interfaces:
                    description: Maximum number of network interfaces.
                    type: int
                maximum_network_cards:
                    description: Maximum number of network cards.
                    type: int
                ipv4_addresses_per_interface:
                    description: Maximum IPv4 addresses per interface.
                    type: int
                ipv6_addresses_per_interface:
                    description: Maximum IPv6 addresses per interface.
                    type: int
                ipv6_supported:
                    description: Whether IPv6 is supported.
                    type: bool
                ena_support:
                    description: ENA support status.
                    type: str
                efa_supported:
                    description: Whether EFA is supported.
                    type: bool
                encryption_in_transit_supported:
                    description: Whether encryption in transit is supported.
                    type: bool
        gpu_info:
            description: GPU information.
            returned: when GPU is available
            type: dict
            contains:
                gpus:
                    description: List of GPU devices.
                    type: list
                    elements: dict
                total_gpu_memory_in_mi_b:
                    description: Total GPU memory in MiB.
                    type: int
        fpga_info:
            description: FPGA information.
            returned: when FPGA is available
            type: dict
        inference_accelerator_info:
            description: Inference accelerator information.
            returned: when inference accelerators are available
            type: dict
        placement_group_info:
            description: Placement group information.
            returned: always
            type: dict
            contains:
                supported_strategies:
                    description: Supported placement strategies.
                    type: list
                    elements: str
        hibernation_supported:
            description: Whether hibernation is supported.
            returned: always
            type: bool
        burstable_performance_supported:
            description: Whether burstable performance is supported.
            returned: always
            type: bool
        dedicated_hosts_supported:
            description: Whether dedicated hosts are supported.
            returned: always
            type: bool
        auto_recovery_supported:
            description: Whether auto recovery is supported.
            returned: always
            type: bool
        supported_boot_modes:
            description: Supported boot modes (legacy-bios, uefi).
            returned: always
            type: list
            elements: str
        nitro_enclaves_support:
            description: Nitro Enclaves support status.
            returned: when available
            type: str
        nitro_tpm_support:
            description: NitroTPM support status.
            returned: when available
            type: str
        nitro_tpm_info:
            description: NitroTPM information.
            returned: when NitroTPM is supported
            type: dict
"""

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import camel_dict_to_snake_dict

from ansible_collections.community.aws.plugins.module_utils.modules import (
    AnsibleCommunityAWSModule as AnsibleAWSModule,
)


def ansible_filters_to_boto3_filters(filters_list):
    """Convert an Ansible filter list to boto3 filter format.

    Args:
        filters_list: List of dicts with 'name' and 'values' keys.

    Returns:
        List of dicts in boto3 filter format: [{'Name': name, 'Values': [values]}]
    """
    if not filters_list:
        return None
    return [{"Name": f["name"], "Values": f["values"]} for f in filters_list]


class EC2InstanceTypesManager:
    """Handles EC2 instance types information retrieval"""

    def __init__(self, module):
        self.module = module
        self.ec2 = module.client("ec2")

    def describe_instance_types(self, instance_types=None, filters=None):
        """Describe EC2 instance types with optional filtering.

        Args:
            instance_types: Optional list of instance type names/patterns
            filters: Optional list of boto3 filters

        Returns:
            List of instance type info dictionaries
        """
        params = {}

        if instance_types:
            params["InstanceTypes"] = instance_types

        if filters:
            params["Filters"] = filters

        try:
            results = []
            paginator = self.ec2.get_paginator("describe_instance_types")
            for page in paginator.paginate(**params):
                results.extend(page.get("InstanceTypes", []))
            return results
        except botocore.exceptions.ClientError as e:
            self.module.fail_json_aws(e, msg="Failed to describe instance types")
        except botocore.exceptions.BotoCoreError as e:
            self.module.fail_json_aws(e, msg="Failed to describe instance types")


def main():
    argument_spec = dict(
        instance_types=dict(required=False, type="list", elements="str", default=[]),
        filters=dict(
            required=False,
            type="list",
            elements="dict",
            default=[],
            options=dict(
                name=dict(required=True, type="str"),
                values=dict(required=True, type="list", elements="str"),
            ),
        ),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    instance_types = module.params["instance_types"]
    filters_list = module.params["filters"]

    # Convert filters list to boto3 format
    filters = ansible_filters_to_boto3_filters(filters_list)

    manager = EC2InstanceTypesManager(module)

    # Get instance type information
    raw_results = manager.describe_instance_types(
        instance_types=instance_types if instance_types else None,
        filters=filters,
    )

    # Convert keys to snake_case for Ansible convention
    instance_type_list = [camel_dict_to_snake_dict(item) for item in raw_results]

    module.exit_json(
        changed=False,
        instance_types=instance_type_list,
    )


if __name__ == "__main__":
    main()
