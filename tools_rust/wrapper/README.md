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