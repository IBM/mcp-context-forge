from mcpgateway.openapi_generator.parser import OpenAPIParser
from mcpgateway.openapi_generator.tool_generator import ToolGenerator
from mcpgateway.openapi_generator.writer import ToolWriter


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m mcpgateway.openapi_generator.cli <spec-file> [--base-url <URL>]")
        return

    filepath = sys.argv[1]
    base_url = None

    if "--base-url" in sys.argv:
        idx = sys.argv.index("--base-url")
        base_url = sys.argv[idx + 1]

    parser = OpenAPIParser(filepath)
    parsed = parser.load()

    generator = ToolGenerator(parsed, base_url=base_url)
    tools = generator.generate_tools()

    writer = ToolWriter()
    out_dir = writer.write(tools)

    print("Generated tools saved to:", out_dir)


if __name__ == "__main__":
    main()
