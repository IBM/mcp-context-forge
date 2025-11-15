from mcpgateway.schemas import ToolCreate, AuthenticationValues

class ToolGenerator:
    def __init__(self, parsed, base_url):
        self.schemas = parsed.get("schemas", {})
        self.endpoints = parsed.get("endpoints", [])
        self.base_url = base_url.rstrip("/")

    def generate_tools(self):
        tools = []

        for ep in self.endpoints:
            name = ep.get("name") or ep.get("operationId") or "autoTool"

            props = {}
            required = []
            for p in ep.get("params", []):
                props[p["name"]] = {"type": p["type"]}
                if p.get("required"):
                    required.append(p["name"])

            input_schema = {
                "type": "object",
                "properties": props
            }
            if required:
                input_schema["required"] = required

            full_url = f"{self.base_url}{ep['path']}"

            auth = AuthenticationValues(
                auth_type="bearer",
                auth_value=None,
                username=None,
                password=None,
                token="", 
                auth_header_key=None,
                auth_header_value=None
            )

            tool = ToolCreate(
                name=name,
                displayName=name,
                url=full_url,
                description=ep.get("summary", ""),
                integration_type="REST",
                request_type="GET",
                headers=None,
                input_schema=input_schema,
                output_schema=None,
                annotations={},
                jsonpath_filter="",
                auth=auth,
                gateway_id=None,
                tags=[],  # type: ignore
                team_id=None,
                owner_email=None,
                base_url=self.base_url,
                path_template=ep["path"],
                query_mapping=None,
                header_mapping=None,
                expose_passthrough=True,
                allowlist=None,
                plugin_chain_pre=None,
                plugin_chain_post=None
            )

            tools.append(tool)

        return tools
