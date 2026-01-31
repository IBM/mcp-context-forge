import json
from pathlib import Path

class ToolWriter:
    def __init__(self, output_dir="generated_tools"):
        self.output = Path(output_dir)
        self.output.mkdir(exist_ok=True)

    def write(self, tools):
        path = self.output / "tools.json"

        data = [t.model_dump() for t in tools]

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return path
