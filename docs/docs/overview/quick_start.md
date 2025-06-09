# Quick Start

Install MCP Context Forge Gateway in local machine using Pypi package and git repository.


## 🐍 Using Python Package Manager (Pypi)

    - pip install mcp-contextforge-gateway
    - BASIC_AUTH_PASSWORD=password mcpgateway --host 127.0.0.1 --port 4444

## 🛠️ Setup Instructions for mcp-context-forge

1. Fork the Repository
    Fork the IBM/mcp-context-forge repository to your own GitHub account.

2. Clone Your Fork
    ``` git clone https://github.com/<your-username>/mcp-context-forge.git ```
    ``` cd mcp-context-forge ```

3. Create a Virtual Environment
    ``` make venv ```

4. Install Dependencies
    ``` make install ```

5. Start the Development Server
    ``` make serve ```

6. Access the App
    ``` http:\\localhost:4444 ```

7. Login Credentials
    Username: admin
    Password: changeme
