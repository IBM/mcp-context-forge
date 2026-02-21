# mcp-stdio-wrapper

This project is a pipeline-oriented command-line tool designed to process data. It reads input from standard in (`stdin`), processes this data concurrently using a system of workers, and then writes the results to standard out (`stdout`).

The core functionality involves an `McpStreamClient` (defined in `src/streamer.rs`) which is used by `mcp_workers.rs` to send processed data to an external service. It also handles receiving Server-Sent Events (SSE) in response from this external service. The application's configuration is managed through `src/config.rs`, which integrates settings from command-line arguments and environment variables.

## Collaboration Diagram

Here is a high-level overview of the module collaboration:

```mermaid
graph TD
    subgraph "Input"
        A[stdio_reader]
    end
    subgraph "Processing"
        B[main.rs]
        C[mcp_workers]
        D[mcp_client]
        E[streamer]
    end
    subgraph "Output"
        F[stdio_writer]
    end
    subgraph "Configuration"
        G[config.rs]
        H[config_from_cli.rs]
        I[config_from_env.rs]
        J[config_defaults.rs]
    end

    A -- "data" --> B
    B -- "spawns" --> C
    B -- "spawns" --> A
    B -- "spawns" --> F
    C -- "uses" --> D
    D -- "uses" --> E
    C -- "results" --> F

    B -- "uses" --> G
    G -- "uses" --> H
    G -- "uses" --> I
    G -- "uses" --> J
```

## Logic Diagram

Here is a diagram showing the logic of the utility:

```mermaid
graph TD
    subgraph "Input"
        A[stdin] --> B(stdio_reader);
    end
    subgraph "Processing Pipeline"
        B --> C{Input Channel};
        C --> D1(Worker 1);
        C --> D2(Worker 2);
        C --> D3(...);
        C --> Dn(Worker N);
        D1 --> E{MCP Server};
        D2 --> E;
        D3 --> E;
        Dn --> E;
        E --> F1(Worker 1);
        E --> F2(Worker 2);
        E --> F3(...);
        E --> Fn(Worker N);
        F1 --> G{Output Channel};
        F2 --> G;
        F3 --> G;
        Fn --> G;
    end
    subgraph "Output"
        G --> H(stdio_writer);
        H --> I[stdout];
    end
```
## Testing

To verify the functionality of the `mcp-stdio-wrapper`, you can use the provided test scripts in the `scripts/` directory.
Start gateway with:
```
make compose-up
```
before running test scripts.

### `test-fast-time-curl.sh`

This script directly interacts with the virtual server of the ContextForge using `curl`. It's useful for verifying that the ContextForge is running and responding as expected.

```bash
./scripts/test-fast-time-curl.sh
```

### `test-fast-time-wrapper.sh`

By default, the test scripts run against the release version of the `mcp-stdio-wrapper`. If you need to test a development version, you must update the executable path within the relevant test script to point to your development build.

This script utilizes the `mcp-stdio-wrapper` to send requests to the ContextForge. It demonstrates how the wrapper processes input and communicates with the gateway.

```bash
./scripts/test-fast-time-wrapper.sh
```


```

**Note** Update the PORT and SERVER_ID variables at the top of each script to match your environment, or set them as environment variables before execution.
