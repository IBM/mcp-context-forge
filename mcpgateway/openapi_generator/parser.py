import json
import yaml
from pathlib import Path

class OpenAPIParser:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self.data = {}
        self.endpoints = []
        self.schemas = {}

    def load(self):
        if self.file_path.suffix.lower() in [".yaml", ".yml"]:
            with open(self.file_path, "r") as f:
                self.data = yaml.safe_load(f)
        else:
            with open(self.file_path, "r") as f:
                self.data = json.load(f)

        self._read_schemas()
        self._read_get_endpoints()
        return {"schemas": self.schemas, "endpoints": self.endpoints}

    def _read_schemas(self):
        comps = self.data.get("components", {})
        raw = comps.get("schemas", {})

        for name, body in raw.items():
            props = {}
            for p, info in body.get("properties", {}).items():
                props[p] = info.get("type", "string")
            self.schemas[name] = props

    def _read_get_endpoints(self):
        paths = self.data.get("paths", {})

        for path, methods in paths.items():
            get_def = methods.get("get")
            if not get_def:
                continue

            item = {
                "path": path,
                "name": get_def.get("operationId", ""),
                "summary": get_def.get("summary", ""),
                "params": []
            }

            for p in get_def.get("parameters", []):
                item["params"].append({
                    "name": p.get("name", ""),
                    "type": p.get("schema", {}).get("type", "string"),
                    "required": p.get("required", False)
                })

            self.endpoints.append(item)


