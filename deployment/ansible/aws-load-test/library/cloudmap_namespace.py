#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: cloudmap_namespace
version_added: 1.0.0
short_description: Create or delete AWS Cloud Map namespaces
description:
  - Creates or deletes AWS Cloud Map namespaces for service discovery.
  - Supports both public and private DNS namespaces.
  - For details of the parameters and returns see U(https://docs.aws.amazon.com/cloud-map/latest/api/API_Operations.html).
author:
  - "Jonathan Springer <jps@s390x.com>"
options:
    state:
        description:
          - The desired state of the namespace.
        required: true
        choices: ["present", "absent"]
        type: str
    name:
        description:
          - The name of the namespace.
          - When creating a namespace, this becomes the DNS domain name.
          - For private namespaces, Cloud Map creates a Route 53 private hosted zone with this name.
        required: true
        type: str
    namespace_type:
        description:
          - The type of namespace to create.
          - Required when I(state=present).
        required: false
        choices: ["public", "private"]
        type: str
    description:
        description:
          - A description for the namespace.
        required: false
        type: str
    vpc:
        description:
          - The ID of the Amazon VPC to associate with a private namespace.
          - Required when I(namespace_type=private).
        required: false
        type: str
    properties:
        description:
          - Configuration properties for the namespace.
        required: false
        type: dict
        suboptions:
            dns_properties:
                description:
                  - DNS-specific properties for the namespace.
                type: dict
                suboptions:
                    soa:
                        description:
                          - SOA record configuration.
                        type: dict
    tags:
        description:
          - A dictionary of tags to add to the namespace.
        type: dict
        required: false
    creator_request_id:
        description:
          - A unique identifier for the request to ensure idempotency.
          - If not specified, a UUID will be generated.
        required: false
        type: str
    wait:
        description:
          - Whether to wait for the namespace operation to complete.
          - When I(wait=true), the module will poll the operation status until it succeeds or fails.
        type: bool
        default: false
        required: false
    wait_timeout:
        description:
          - Maximum time in seconds to wait for the operation to complete.
        type: int
        default: 300
        required: false
extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""
# Create a public DNS namespace
- cloudmap_namespace:
    state: present
    name: example.com
    namespace_type: public
    description: Public namespace for service discovery
    tags:
      Environment: production

# Create a private DNS namespace and wait for it to be available
- cloudmap_namespace:
    state: present
    name: internal.example.com
    namespace_type: private
    vpc: vpc-12345678
    description: Private namespace for internal services
    wait: true
    wait_timeout: 300
    tags:
      Environment: production

# Delete a namespace
- cloudmap_namespace:
    state: absent
    name: example.com
"""

RETURN = r"""
namespace:
    description: Details of the namespace operation.
    returned: when creating or deleting a namespace
    type: complex
    contains:
        operation_id:
            description: The ID of the operation that can be used to track the request.
            returned: always
            type: str
        namespace_id:
            description: The ID of the namespace.
            returned: when namespace exists
            type: str
        name:
            description: The name of the namespace.
            returned: when namespace exists
            type: str
        type:
            description: The type of the namespace (DNS_PUBLIC or DNS_PRIVATE).
            returned: when namespace exists
            type: str
        arn:
            description: The ARN of the namespace.
            returned: when namespace exists
            type: str
"""

import time
import uuid

try:
    import botocore
except ImportError:
    pass  # caught by AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import snake_dict_to_camel_dict

from ansible_collections.community.aws.plugins.module_utils.modules import (
    AnsibleCommunityAWSModule as AnsibleAWSModule,
)


class CloudMapNamespaceManager:
    """Handles AWS Cloud Map Namespaces"""

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

    def create_public_namespace(self, name, description, properties, tags, creator_request_id):
        """Create a public DNS namespace"""
        params = {
            "Name": name,
            "CreatorRequestId": creator_request_id,
        }

        if description:
            params["Description"] = description
        if properties:
            params["Properties"] = properties
        if tags:
            params["Tags"] = self._format_tags(tags)

        try:
            response = self.servicediscovery.create_public_dns_namespace(**params)
            return response
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg="Failed to create public namespace")

    def create_private_namespace(self, name, vpc, description, properties, tags, creator_request_id):
        """Create a private DNS namespace"""
        params = {
            "Name": name,
            "Vpc": vpc,
            "CreatorRequestId": creator_request_id,
        }

        if description:
            params["Description"] = description
        if properties:
            params["Properties"] = properties
        if tags:
            params["Tags"] = self._format_tags(tags)

        try:
            response = self.servicediscovery.create_private_dns_namespace(**params)
            return response
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg="Failed to create private namespace")

    def delete_namespace(self, namespace_id):
        """Delete a namespace"""
        try:
            response = self.servicediscovery.delete_namespace(Id=namespace_id)
            return response
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to delete namespace {namespace_id}")

    def get_operation(self, operation_id):
        """Get the status of an operation"""
        try:
            response = self.servicediscovery.get_operation(OperationId=operation_id)
            return response.get("Operation")
        except (
            botocore.exceptions.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.module.fail_json_aws(e, msg=f"Failed to get operation status for {operation_id}")

    def wait_for_operation(self, operation_id, timeout=300):
        """Wait for an operation to complete"""
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                self.module.fail_json(msg=f"Timeout waiting for operation {operation_id} to complete after {timeout} seconds")

            operation = self.get_operation(operation_id)
            status = operation.get("Status")

            if status == "SUCCESS":
                # Get the namespace ID from the operation targets
                targets = operation.get("Targets", {})
                namespace_id = targets.get("NAMESPACE")
                return namespace_id
            elif status == "FAIL":
                error_message = operation.get("ErrorMessage", "Unknown error")
                self.module.fail_json(msg=f"Operation {operation_id} failed: {error_message}")

            # Operation is still in progress, wait before checking again
            time.sleep(5)

    def _format_tags(self, tags):
        """Convert Ansible tags dict to AWS tags list"""
        if not tags:
            return []
        return [{"Key": k, "Value": v} for k, v in tags.items()]


def main():
    argument_spec = dict(
        state=dict(required=True, choices=["present", "absent"]),
        name=dict(required=True, type="str"),
        namespace_type=dict(required=False, choices=["public", "private"]),
        description=dict(required=False, type="str"),
        vpc=dict(required=False, type="str"),
        properties=dict(required=False, type="dict"),
        tags=dict(required=False, type="dict"),
        creator_request_id=dict(required=False, type="str"),
        wait=dict(required=False, type="bool", default=False),
        wait_timeout=dict(required=False, type="int", default=300),
    )

    module = AnsibleAWSModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ("state", "present", ["namespace_type"]),
            ("namespace_type", "private", ["vpc"]),
        ],
    )

    state = module.params["state"]
    name = module.params["name"]
    namespace_type = module.params["namespace_type"]
    description = module.params["description"]
    vpc = module.params["vpc"]
    properties = module.params["properties"]
    tags = module.params["tags"]
    creator_request_id = module.params["creator_request_id"] or str(uuid.uuid4())
    wait = module.params["wait"]
    wait_timeout = module.params["wait_timeout"]

    # Convert properties to camelCase if provided
    if properties:
        properties = snake_dict_to_camel_dict(properties)

    manager = CloudMapNamespaceManager(module)

    # Find existing namespace
    existing = manager.find_namespace_by_name(name)

    results = dict(changed=False)

    if state == "present":
        if existing:
            # Namespace already exists
            results["namespace"] = existing
            results["changed"] = False
        else:
            # Create new namespace
            if not module.check_mode:
                if namespace_type == "public":
                    response = manager.create_public_namespace(name, description, properties, tags, creator_request_id)
                elif namespace_type == "private":
                    response = manager.create_private_namespace(name, vpc, description, properties, tags, creator_request_id)

                operation_id = response.get("OperationId")

                # Wait for operation to complete if requested
                if wait:
                    namespace_id = manager.wait_for_operation(operation_id, wait_timeout)
                    namespace_details = manager.get_namespace(namespace_id)
                    results["namespace"] = namespace_details
                else:
                    results["namespace"] = {
                        "operation_id": operation_id,
                        "name": name,
                    }
            results["changed"] = True

    elif state == "absent":
        if existing:
            # Delete the namespace
            if not module.check_mode:
                response = manager.delete_namespace(existing["Id"])
                results["namespace"] = {
                    "operation_id": response.get("OperationId"),
                    "namespace_id": existing["Id"],
                    "name": name,
                }
            results["changed"] = True
        else:
            # Namespace doesn't exist, nothing to do
            results["changed"] = False

    module.exit_json(**results)


if __name__ == "__main__":
    main()
