#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: cloudmap_info
version_added: 1.0.0
short_description: Retrieve information about AWS Cloud Map services and instances
description:
  - Retrieves information about AWS Cloud Map namespaces, services, and instances.
  - Can list services in a namespace and get instance details including container IPs.
  - Useful for service discovery in ECS environments using AWS Cloud Map.
author:
  - "Jonathan Springer <jps@s390x.com>"
options:
    namespace_id:
        description:
          - The ID of the Cloud Map namespace to query.
          - Either I(namespace_id) or I(namespace_name) must be provided.
        required: false
        type: str
    namespace_name:
        description:
          - The name of the Cloud Map namespace to query.
          - Either I(namespace_id) or I(namespace_name) must be provided.
        required: false
        type: str
    service_id:
        description:
          - The ID of a specific service to get instances for.
          - If not provided, all services in the namespace will be queried.
        required: false
        type: str
    service_name:
        description:
          - The name of a specific service to get instances for.
          - If not provided, all services in the namespace will be queried.
        required: false
        type: str
    include_instances:
        description:
          - Whether to include instance details for each service.
          - When true, retrieves instance information including IP addresses.
        type: bool
        default: true
        required: false
extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""
# Get all services and instances in a namespace by ID
- cloudmap_info:
    namespace_id: ns-abcdef1234567890
  register: cloudmap_info

# Get all services and instances in a namespace by name
- cloudmap_info:
    namespace_name: my-ecs-cluster
  register: cloudmap_info

# Get instances for a specific service
- cloudmap_info:
    namespace_name: my-ecs-cluster
    service_name: api
  register: api_service_info

# Get only service information without instances
- cloudmap_info:
    namespace_name: my-ecs-cluster
    include_instances: false
  register: services_only

# Display container IPs
- debug:
    msg: "{{ item.name }}: {{ item.instances | map(attribute='ipv4') | join(', ') }}"
  loop: "{{ cloudmap_info.services }}"
"""

RETURN = r"""
namespace:
    description: Details of the namespace.
    returned: always
    type: dict
    contains:
        id:
            description: The ID of the namespace.
            returned: always
            type: str
        name:
            description: The name of the namespace.
            returned: always
            type: str
        arn:
            description: The ARN of the namespace.
            returned: always
            type: str
        type:
            description: The type of the namespace.
            returned: always
            type: str
services:
    description: List of services in the namespace with their instances.
    returned: always
    type: list
    elements: dict
    contains:
        id:
            description: The ID of the service.
            returned: always
            type: str
        name:
            description: The name of the service.
            returned: always
            type: str
        arn:
            description: The ARN of the service.
            returned: always
            type: str
        instances:
            description: List of instances registered to the service.
            returned: when include_instances=true
            type: list
            elements: dict
            contains:
                id:
                    description: The ID of the instance.
                    returned: always
                    type: str
                ipv4:
                    description: The IPv4 address of the instance.
                    returned: when available
                    type: str
                ipv6:
                    description: The IPv6 address of the instance.
                    returned: when available
                    type: str
                port:
                    description: The port number for the instance.
                    returned: when available
                    type: int
                attributes:
                    description: Custom attributes associated with the instance.
                    returned: always
                    type: dict
"""

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible_collections.community.aws.plugins.module_utils.modules import (
    AnsibleCommunityAWSModule as AnsibleAWSModule,
)


class CloudMapInfoManager:
    """Handles AWS Cloud Map information retrieval"""

    def __init__(self, module):
        self.module = module
        self.servicediscovery = module.client("servicediscovery")

    def find_namespace_by_name(self, name):
        """Find a namespace by name"""
        try:
            paginator = self.servicediscovery.get_paginator("list_namespaces")
            for page in paginator.paginate():
                for namespace in page.get("Namespaces", []):
                    if namespace["Name"] == name:
                        return namespace
            return None
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg="Failed to list namespaces")

    def get_namespace(self, namespace_id):
        """Get detailed information about a namespace"""
        try:
            response = self.servicediscovery.get_namespace(Id=namespace_id)
            return response.get("Namespace")
        except self.servicediscovery.exceptions.NamespaceNotFound:
            return None
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to get namespace {namespace_id}")

    def list_services(self, namespace_id):
        """List all services in a namespace"""
        try:
            services = []
            paginator = self.servicediscovery.get_paginator("list_services")
            for page in paginator.paginate(Filters=[{"Name": "NAMESPACE_ID", "Values": [namespace_id]}]):
                services.extend(page.get("Services", []))
            return services
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to list services in namespace {namespace_id}")

    def get_service(self, service_id):
        """Get detailed information about a service"""
        try:
            response = self.servicediscovery.get_service(Id=service_id)
            return response.get("Service")
        except self.servicediscovery.exceptions.ServiceNotFound:
            return None
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to get service {service_id}")

    def find_service_by_name(self, namespace_id, service_name):
        """Find a service by name in a namespace"""
        services = self.list_services(namespace_id)
        for service in services:
            if service.get("Name") == service_name:
                return service
        return None

    def list_instances(self, service_id):
        """List all instances for a service"""
        try:
            instances = []
            paginator = self.servicediscovery.get_paginator("list_instances")
            for page in paginator.paginate(ServiceId=service_id):
                instances.extend(page.get("Instances", []))
            return instances
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to list instances for service {service_id}")

    def format_namespace(self, namespace):
        """Format namespace data for output"""
        return {
            "id": namespace.get("Id"),
            "name": namespace.get("Name"),
            "arn": namespace.get("Arn"),
            "type": namespace.get("Type"),
            "description": namespace.get("Description"),
        }

    def format_service(self, service, instances=None):
        """Format service data for output"""
        result = {
            "id": service.get("Id"),
            "name": service.get("Name"),
            "arn": service.get("Arn"),
            "description": service.get("Description"),
        }
        if instances is not None:
            result["instances"] = [self.format_instance(i) for i in instances]
        return result

    def format_instance(self, instance):
        """Format instance data for output"""
        attributes = instance.get("Attributes", {})
        result = {
            "id": instance.get("Id"),
            "attributes": attributes,
        }
        # Extract common attributes for convenience
        if "AWS_INSTANCE_IPV4" in attributes:
            result["ipv4"] = attributes["AWS_INSTANCE_IPV4"]
        if "AWS_INSTANCE_IPV6" in attributes:
            result["ipv6"] = attributes["AWS_INSTANCE_IPV6"]
        if "AWS_INSTANCE_PORT" in attributes:
            result["port"] = int(attributes["AWS_INSTANCE_PORT"])
        return result


def main():
    argument_spec = dict(
        namespace_id=dict(required=False, type="str"),
        namespace_name=dict(required=False, type="str"),
        service_id=dict(required=False, type="str"),
        service_name=dict(required=False, type="str"),
        include_instances=dict(required=False, type="bool", default=True),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[("namespace_id", "namespace_name")],
        mutually_exclusive=[
            ("namespace_id", "namespace_name"),
            ("service_id", "service_name"),
        ],
    )

    namespace_id = module.params["namespace_id"]
    namespace_name = module.params["namespace_name"]
    service_id = module.params["service_id"]
    service_name = module.params["service_name"]
    include_instances = module.params["include_instances"]

    manager = CloudMapInfoManager(module)

    # Resolve namespace
    if namespace_name:
        namespace = manager.find_namespace_by_name(namespace_name)
        if not namespace:
            module.fail_json(msg=f"Namespace '{namespace_name}' not found")
        namespace_id = namespace["Id"]
    else:
        namespace = manager.get_namespace(namespace_id)
        if not namespace:
            module.fail_json(msg=f"Namespace with ID '{namespace_id}' not found")

    results = {
        "namespace": manager.format_namespace(namespace),
        "services": [],
    }

    # Get services
    if service_id:
        service = manager.get_service(service_id)
        if not service:
            module.fail_json(msg=f"Service with ID '{service_id}' not found")
        services = [service]
    elif service_name:
        service = manager.find_service_by_name(namespace_id, service_name)
        if not service:
            module.fail_json(msg=f"Service '{service_name}' not found in namespace")
        services = [service]
    else:
        services = manager.list_services(namespace_id)

    # Format services and optionally include instances
    for service in services:
        instances = None
        if include_instances:
            instances = manager.list_instances(service["Id"])
        results["services"].append(manager.format_service(service, instances))

    module.exit_json(**results)


if __name__ == "__main__":
    main()
