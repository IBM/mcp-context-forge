"""Location: ./plugins/apiconnect_fam/fam/payloads/runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

FAM Runtime Payload Builder.
"""

# Standard
from typing import Any, Dict, List, Optional


class FAMRuntimePayload:
    """
    Builder for FAM Runtime payloads following API v2 spec.

    Builds runtime registration payloads for POST /api/assetcatalog/v2/runtimes.

    Deployment types:
    - ON_PREMISE: On-premise deployment
    - CLOUD: Cloud deployment
    - HYBRID: Hybrid deployment
    """

    # Deployment type enums
    DEPLOYMENT_ON_PREMISE = "ON_PREMISE"
    DEPLOYMENT_CLOUD = "CLOUD"
    DEPLOYMENT_HYBRID = "HYBRID"

    @staticmethod
    def build_payload(
        runtime_id: str,
        name: str,
        description: str,
        runtime_type: str,
        deployment_type: str = DEPLOYMENT_ON_PREMISE,
        region: Optional[str] = None,
        location: Optional[str] = None,
        host: Optional[str] = None,
        tags: Optional[List[str]] = None,
        capacity_value: Optional[str] = None,
        capacity_unit: Optional[str] = None,
        heartbeat_interval: int = 6000,
        publish_assets: bool = True,
        sync_assets: bool = True,
        send_metrics: bool = True,
    ) -> Dict[str, Any]:
        """Build runtime registration payload.

        Args:
            runtime_id: Runtime ID (required)
            name: Runtime display name (required)
            description: Runtime description (required)
            runtime_type: Runtime type enum (default: MCP_CONTEXT_FORGE)
            deployment_type: Deployment type enum (default: ON_PREMISE)
            region: Region identifier (e.g., "us-east-1")
            location: Location description (e.g., "US East")
            host: Host identifier
            tags: List of tags for the runtime
            capacity_value: Capacity value (e.g., "50")
            capacity_unit: Capacity unit (e.g., "per minute")
            heartbeat_interval: Heartbeat sync interval in milliseconds (default: 6000)
            publish_assets: Whether to publish assets (default: True)
            sync_assets: Whether to sync assets (default: True)
            send_metrics: Whether to send metrics (default: True)

        Returns:
            Runtime registration payload dict
        """
        payload: Dict[str, Any] = {
            "id": runtime_id,
            "name": name,
            "description": description,
            "type": runtime_type,
            "deploymentType": deployment_type,
            "heartBeatSynchInterval": heartbeat_interval,
            "publishAssets": publish_assets,
            "syncAssets": sync_assets,
            "sendMetrics": send_metrics,
            "icon": "",
        }

        # Add optional fields
        if region:
            payload["region"] = region
        if location:
            payload["location"] = location
        if host:
            payload["host"] = host
        if tags:
            payload["tags"] = tags[:50]  # Limit to 50 tags

        # Add capacity if both value and unit are provided
        if capacity_value and capacity_unit:
            payload["capacity"] = {"value": capacity_value, "unit": capacity_unit}

        return payload
