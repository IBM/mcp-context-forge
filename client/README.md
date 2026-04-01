# ContextForge Client

React-based client application for ContextForge MCP Gateway.

## Structure

```
client/
├── src/
│   ├── components/     # Reusable components
│   ├── pages/          # Page components
│   │   ├── Dashboard.jsx
│   │   ├── Servers.jsx
│   │   ├── Tools.jsx
│   │   └── Settings.jsx
│   ├── utils/          # Utility functions
│   ├── App.jsx         # Main app with TanStack Router
│   ├── main.jsx        # Entry point
│   └── index.css       # Tailwind CSS imports
└── index.html          # HTML template
```

## Features

- **Dashboard**: Overview with stats cards and MCP servers table
- **Servers**: Manage MCP server connections
- **Tools**: Browse available MCP tools catalog
- **Settings**: Configure application preferences
- **Sidebar Navigation**: Easy navigation between pages with active state
- **Tailwind CSS**: Utility-first styling
- **TanStack Router**: Type-safe client-side routing

## Development

```bash
# Install dependencies
npm install

# Start dev server (runs on http://localhost:5173)
npm run dev

# Build for production
npm run build
```

## Deployment

The application is configured to:
- Build to: `mcpgateway/static/app/`
- Serve from: `/app/` URL path
- Base path: `/app/` (configured in vite.config.js)

## Routes

- `/app/` - Dashboard
- `/app/servers` - Servers management
- `/app/tools` - Tools catalog
- `/app/settings` - Settings

## Tech Stack

- React 18.3.1
- TanStack Router 1.91.6
- Tailwind CSS 4.2.2
- Vite 8.0.3 (build tool)

## Next Steps

1. Connect to backend API endpoints
2. Add authentication/authorization
3. Implement real data fetching
4. Add form validation
5. Add error handling and loading states
6. Add unit tests with Vitest
