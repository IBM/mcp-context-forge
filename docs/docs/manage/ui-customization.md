# Customizing the Admin UI

The MCP Gateway Admin UI provides extensive customization options to tailor the interface to your organization's needs and preferences. This guide covers theme customization, layout configuration, user preferences, and accessibility settings.

## Overview

The Admin UI is built with modern web technologies (HTMX, Alpine.js, and Tailwind CSS) that enable dynamic customization without page refreshes. All customization settings are persisted locally and can be exported for sharing across teams.

## Theme Customization

### Dark/Light Mode

The Admin UI includes built-in support for dark and light themes that automatically persist your preference:

```javascript
// Theme is automatically saved to localStorage
localStorage.setItem('theme', 'dark');  // or 'light'
```

To toggle between themes programmatically:

```html
<!-- Theme toggle button in the UI -->
<button @click="toggleTheme()" class="theme-toggle">
    <span x-show="theme === 'light'">🌙</span>
    <span x-show="theme === 'dark'">☀️</span>
</button>
```

### Custom Color Schemes

You can customize the color palette by modifying CSS variables in your custom stylesheet:

```css
/* custom-theme.css */
:root {
    /* Light theme colors */
    --color-primary: #3b82f6;
    --color-secondary: #10b981;
    --color-accent: #f59e0b;
    --color-background: #ffffff;
    --color-surface: #f3f4f6;
    --color-text: #1f2937;
    --color-text-muted: #6b7280;
}

[data-theme="dark"] {
    /* Dark theme colors */
    --color-primary: #60a5fa;
    --color-secondary: #34d399;
    --color-accent: #fbbf24;
    --color-background: #111827;
    --color-surface: #1f2937;
    --color-text: #f9fafb;
    --color-text-muted: #9ca3af;
}
```

To apply custom themes, add your stylesheet to the Admin UI configuration:

```python
# In your mcpgateway configuration
MCPGATEWAY_ADMIN_CUSTOM_CSS = "/static/custom-theme.css"
```

### Brand Customization

#### Logo and Icons

Replace the default logo with your organization's branding:

```python
# Environment variables for branding
MCPGATEWAY_ADMIN_LOGO_URL = "/static/company-logo.svg"
MCPGATEWAY_ADMIN_FAVICON_URL = "/static/favicon.ico"
MCPGATEWAY_ADMIN_TITLE = "Your Company MCP Gateway"
```

#### Custom Icons for Servers and Tools

Define custom icons for different server types and tools:

```json
{
  "server_icons": {
    "database": "database-icon.svg",
    "api": "api-icon.svg",
    "file": "file-icon.svg"
  },
  "tool_icons": {
    "search": "magnifying-glass.svg",
    "create": "plus-circle.svg",
    "delete": "trash.svg"
  }
}
```

## Layout Configuration

### Panel Management

The Admin UI supports flexible panel arrangements with drag-and-drop functionality:

```javascript
// Enable panel customization
const panelConfig = {
    virtualServers: { 
        visible: true, 
        order: 1, 
        width: 'full' 
    },
    tools: { 
        visible: true, 
        order: 2, 
        width: 'half' 
    },
    resources: { 
        visible: true, 
        order: 3, 
        width: 'half' 
    },
    prompts: { 
        visible: false, 
        order: 4, 
        width: 'full' 
    }
};

// Save layout preferences
localStorage.setItem('panel-layout', JSON.stringify(panelConfig));
```

### Section Visibility

Control which sections appear in the Admin UI:

```python
# Configure visible sections via environment variables
MCPGATEWAY_ADMIN_SHOW_SERVERS = true
MCPGATEWAY_ADMIN_SHOW_TOOLS = true
MCPGATEWAY_ADMIN_SHOW_RESOURCES = true
MCPGATEWAY_ADMIN_SHOW_PROMPTS = false
MCPGATEWAY_ADMIN_SHOW_GATEWAYS = true
MCPGATEWAY_ADMIN_SHOW_METRICS = true
```

### Widget Dashboard

Create custom dashboards with configurable widgets:

```javascript
// Widget configuration example
const dashboardWidgets = [
    {
        id: 'server-status',
        type: 'status-card',
        position: { x: 0, y: 0, w: 4, h: 2 },
        config: {
            title: 'Server Status',
            refreshInterval: 5000
        }
    },
    {
        id: 'recent-tools',
        type: 'list',
        position: { x: 4, y: 0, w: 4, h: 3 },
        config: {
            title: 'Recently Used Tools',
            limit: 10
        }
    },
    {
        id: 'metrics-chart',
        type: 'chart',
        position: { x: 0, y: 2, w: 8, h: 4 },
        config: {
            title: 'Request Metrics',
            chartType: 'line',
            dataSource: '/api/metrics'
        }
    }
];
```

## User Preferences

### Profile Management

User profiles store personal customization settings:

```javascript
// User profile structure
const userProfile = {
    username: 'admin',
    preferences: {
        theme: 'dark',
        language: 'en',
        fontSize: 'medium',
        highContrast: false,
        reducedMotion: false,
        keyboardShortcuts: true
    },
    layout: {
        // Panel configuration
    },
    quickActions: [
        'create-server',
        'refresh-tools',
        'export-config'
    ]
};

// Save profile
localStorage.setItem('user-profile', JSON.stringify(userProfile));
```

### Import/Export Settings

Export and share configuration across teams:

```javascript
// Export current settings
function exportSettings() {
    const settings = {
        profile: JSON.parse(localStorage.getItem('user-profile')),
        theme: localStorage.getItem('theme'),
        layout: JSON.parse(localStorage.getItem('panel-layout')),
        widgets: JSON.parse(localStorage.getItem('dashboard-widgets'))
    };
    
    const blob = new Blob([JSON.stringify(settings, null, 2)], 
                          { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mcpgateway-ui-settings.json';
    a.click();
}

// Import settings
function importSettings(file) {
    const reader = new FileReader();
    reader.onload = function(e) {
        const settings = JSON.parse(e.target.result);
        
        // Apply imported settings
        if (settings.profile) {
            localStorage.setItem('user-profile', 
                               JSON.stringify(settings.profile));
        }
        if (settings.theme) {
            localStorage.setItem('theme', settings.theme);
        }
        if (settings.layout) {
            localStorage.setItem('panel-layout', 
                               JSON.stringify(settings.layout));
        }
        
        // Reload UI to apply changes
        location.reload();
    };
    reader.readAsText(file);
}
```

### Quick Actions and Shortcuts

Configure frequently used actions for quick access:

```javascript
// Define keyboard shortcuts
const keyboardShortcuts = {
    'ctrl+n': 'createNewServer',
    'ctrl+r': 'refreshAll',
    'ctrl+/': 'toggleSearch',
    'ctrl+d': 'toggleTheme',
    'ctrl+,': 'openSettings',
    'esc': 'closeModal'
};

// Quick action toolbar configuration
const quickActions = [
    {
        id: 'create-server',
        label: 'New Server',
        icon: 'plus',
        action: () => openModal('create-server')
    },
    {
        id: 'refresh-tools',
        label: 'Refresh Tools',
        icon: 'refresh',
        action: () => refreshToolList()
    }
];
```

## Accessibility Options

### High Contrast Mode

Enable high contrast for better visibility:

```css
/* High contrast mode styles */
[data-high-contrast="true"] {
    --color-contrast-ratio: 7:1;
    --border-width: 2px;
    
    /* Stronger colors for better contrast */
    --color-primary: #0066cc;
    --color-secondary: #008844;
    --color-danger: #cc0000;
    --color-warning: #ff6600;
    
    /* Enhanced borders */
    border-width: var(--border-width);
    outline-width: 2px;
}
```

### Font Size Adjustments

Support dynamic font sizing:

```javascript
// Font size preferences
const fontSizeOptions = {
    small: '14px',
    medium: '16px',
    large: '18px',
    xlarge: '20px'
};

function setFontSize(size) {
    document.documentElement.style.setProperty('--base-font-size', 
                                               fontSizeOptions[size]);
    localStorage.setItem('font-size', size);
}
```

### Keyboard Navigation

Full keyboard navigation support:

```javascript
// Enhanced keyboard navigation
document.addEventListener('keydown', (e) => {
    // Tab navigation between sections
    if (e.key === 'Tab') {
        const focusableElements = document.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        // Handle focus management
    }
    
    // Arrow key navigation in lists
    if (e.key.startsWith('Arrow')) {
        const currentItem = document.activeElement;
        const items = Array.from(currentItem.parentElement.children);
        // Navigate through list items
    }
});
```

### Screen Reader Support

Ensure proper ARIA labels and descriptions:

```html
<!-- Properly labeled UI elements -->
<section aria-label="Virtual Servers" role="region">
    <h2 id="servers-heading">Virtual Servers</h2>
    <div role="list" aria-labelledby="servers-heading">
        <div role="listitem" aria-label="Server: API Gateway">
            <!-- Server content -->
        </div>
    </div>
</section>

<!-- Status announcements -->
<div role="status" aria-live="polite" aria-atomic="true">
    <span id="status-message">Server created successfully</span>
</div>
```

## Mobile and Responsive Design

### Touch-Friendly Interface

Optimize for touch interactions:

```css
/* Touch-friendly buttons and controls */
@media (pointer: coarse) {
    button, .clickable {
        min-height: 44px;
        min-width: 44px;
        padding: 12px;
    }
    
    /* Increased spacing for touch targets */
    .tool-list > * {
        margin-bottom: 8px;
    }
}
```

### Mobile-Specific Layouts

Responsive layout configurations:

```css
/* Mobile layout adjustments */
@media (max-width: 768px) {
    /* Stack panels vertically on mobile */
    .panel-container {
        display: flex;
        flex-direction: column;
    }
    
    /* Hide less critical sections */
    .desktop-only {
        display: none;
    }
    
    /* Collapsible navigation */
    .nav-menu {
        position: fixed;
        transform: translateX(-100%);
        transition: transform 0.3s;
    }
    
    .nav-menu.open {
        transform: translateX(0);
    }
}
```

### Progressive Web App Features

Enable PWA capabilities for mobile users:

```json
{
  "name": "MCP Gateway Admin",
  "short_name": "MCP Admin",
  "description": "Admin interface for MCP Gateway",
  "start_url": "/admin",
  "display": "standalone",
  "theme_color": "#3b82f6",
  "background_color": "#ffffff",
  "icons": [
    {
      "src": "/static/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/static/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

## Localization Support

### Multi-Language Configuration

Support multiple languages in the UI:

```javascript
// Language configuration
const translations = {
    en: {
        'servers.title': 'Virtual Servers',
        'servers.create': 'Create Server',
        'servers.empty': 'No servers configured'
    },
    es: {
        'servers.title': 'Servidores Virtuales',
        'servers.create': 'Crear Servidor',
        'servers.empty': 'No hay servidores configurados'
    },
    fr: {
        'servers.title': 'Serveurs Virtuels',
        'servers.create': 'Créer un Serveur',
        'servers.empty': 'Aucun serveur configuré'
    }
};

// Apply translations
function setLanguage(lang) {
    const t = translations[lang];
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.dataset.i18n;
        if (t[key]) {
            el.textContent = t[key];
        }
    });
    localStorage.setItem('language', lang);
}
```

### RTL Support

Support for right-to-left languages:

```css
/* RTL language support */
[dir="rtl"] {
    /* Flip layout direction */
    .panel-container {
        flex-direction: row-reverse;
    }
    
    /* Adjust text alignment */
    .text-left {
        text-align: right;
    }
    
    /* Mirror icons */
    .icon-arrow {
        transform: scaleX(-1);
    }
}
```

## Advanced Customization

### Custom Plugins

Extend the Admin UI with custom plugins:

```javascript
// Plugin registration
class CustomPlugin {
    constructor(config) {
        this.name = config.name;
        this.version = config.version;
    }
    
    init() {
        // Add custom functionality
        this.registerCustomPanel();
        this.addCustomMenuItems();
    }
    
    registerCustomPanel() {
        const panel = document.createElement('div');
        panel.className = 'custom-panel';
        panel.innerHTML = this.renderPanel();
        document.querySelector('#panels').appendChild(panel);
    }
    
    renderPanel() {
        return `
            <div class="panel">
                <h3>${this.name}</h3>
                <!-- Custom content -->
            </div>
        `;
    }
}

// Register plugin
const plugin = new CustomPlugin({
    name: 'Custom Analytics',
    version: '1.0.0'
});
plugin.init();
```

### Custom CSS Framework Integration

Integrate alternative CSS frameworks:

```html
<!-- Replace Tailwind with Bootstrap -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" 
      rel="stylesheet">

<!-- Custom Bootstrap theme -->
<style>
    :root {
        --bs-primary: #3b82f6;
        --bs-secondary: #10b981;
        --bs-success: #10b981;
        --bs-danger: #ef4444;
    }
</style>
```

### API Extensions

Add custom API endpoints for UI features:

```python
# Custom API endpoint for UI preferences
from fastapi import APIRouter, Depends
from mcpgateway.auth import get_current_user

ui_router = APIRouter(prefix="/api/ui")

@ui_router.get("/preferences")
async def get_preferences(user = Depends(get_current_user)):
    """Get user UI preferences"""
    return {
        "theme": user.preferences.get("theme", "light"),
        "layout": user.preferences.get("layout", {}),
        "language": user.preferences.get("language", "en")
    }

@ui_router.post("/preferences")
async def save_preferences(preferences: dict, 
                          user = Depends(get_current_user)):
    """Save user UI preferences"""
    user.preferences.update(preferences)
    # Save to database
    return {"status": "saved"}
```

## Performance Optimization

### Lazy Loading

Implement lazy loading for better performance:

```javascript
// Lazy load panels
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const panel = entry.target;
            loadPanelContent(panel.dataset.panelId);
            observer.unobserve(panel);
        }
    });
});

document.querySelectorAll('.lazy-panel').forEach(panel => {
    observer.observe(panel);
});
```

### Caching Strategies

Cache UI preferences and data:

```javascript
// Service Worker for offline support
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open('ui-v1').then((cache) => {
            return cache.addAll([
                '/admin',
                '/static/admin.css',
                '/static/admin.js',
                '/static/icons/'
            ]);
        })
    );
});

// Cache API responses
const cacheAPI = async (url, data) => {
    const cache = await caches.open('api-cache');
    const response = new Response(JSON.stringify(data));
    await cache.put(url, response);
};
```

## Container CSS Overrides

When running MCP Gateway in a Docker container, you can override the default CSS by mounting custom stylesheets. The Admin UI CSS is located at `/app/mcpgateway/static/admin.css` inside the container.

### Mounting Custom CSS

To override the default CSS when running the container:

```bash
# Create a local directory for custom styles
mkdir -p ./custom-ui

# Create your custom CSS file
cat > ./custom-ui/admin.css << 'EOF'
/* Custom theme overrides */
:root {
    --color-primary: #your-brand-color;
    --color-secondary: #your-secondary-color;
}

/* Additional custom styles */
.admin-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
EOF

# Run container with custom CSS mounted
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -v $(pwd)/custom-ui/admin.css:/app/mcpgateway/static/admin.css:ro \
  -v $(pwd)/data:/data \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  ghcr.io/MCP-Mirror/mcpgateway:latest
```

### Mounting Multiple Static Assets

To override multiple static files (CSS, JavaScript, images):

```bash
# Create custom static directory structure
mkdir -p ./custom-static
cp -r /path/to/original/mcpgateway/static/* ./custom-static/

# Modify files as needed
vim ./custom-static/admin.css
vim ./custom-static/admin.js

# Mount entire static directory
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -v $(pwd)/custom-static:/app/mcpgateway/static:ro \
  -v $(pwd)/data:/data \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  ghcr.io/MCP-Mirror/mcpgateway:latest
```

### Docker Compose with Custom CSS

Using Docker Compose for easier management:

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcpgateway:
    image: ghcr.io/MCP-Mirror/mcpgateway:latest
    container_name: mcpgateway
    restart: unless-stopped
    ports:
      - "4444:4444"
    volumes:
      # Mount custom CSS file
      - ./custom-ui/admin.css:/app/mcpgateway/static/admin.css:ro
      # Or mount entire static directory
      # - ./custom-static:/app/mcpgateway/static:ro
      
      # Mount data directory for persistence
      - ./data:/data
      
      # Optional: Mount custom favicon and JavaScript
      - ./custom-ui/favicon.ico:/app/mcpgateway/static/favicon.ico:ro
      - ./custom-ui/admin.js:/app/mcpgateway/static/admin.js:ro
    environment:
      - MCPGATEWAY_UI_ENABLED=true
      - MCPGATEWAY_ADMIN_API_ENABLED=true
      - HOST=0.0.0.0
      - PORT=4444
      - JWT_SECRET_KEY=${JWT_SECRET_KEY:-change-me-in-production}
      - DATABASE_URL=sqlite:////data/mcp.db
```

### CSS File Locations

The default static files in the container are located at:

- **CSS**: `/app/mcpgateway/static/admin.css`
- **JavaScript**: `/app/mcpgateway/static/admin.js`
- **Favicon**: `/app/mcpgateway/static/favicon.ico`

### Custom CSS Best Practices

When creating custom CSS overrides:

1. **Preserve Core Functionality**: Don't remove critical styles that affect functionality
2. **Use CSS Variables**: Override CSS custom properties for consistent theming
3. **Test Responsiveness**: Ensure custom styles work on mobile devices
4. **Maintain Accessibility**: Keep contrast ratios and focus indicators

Example custom CSS file structure:

```css
/* custom-ui/admin.css */

/* Import original CSS if needed */
@import url('/static/admin.css');

/* Override CSS variables */
:root {
    /* Brand colors */
    --color-primary: #1e40af;
    --color-primary-hover: #1e3a8a;
    --color-secondary: #059669;
    
    /* Custom spacing */
    --spacing-unit: 0.5rem;
    --border-radius: 0.375rem;
    
    /* Custom fonts */
    --font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

/* Dark mode overrides */
[data-theme="dark"] {
    --color-primary: #3b82f6;
    --color-background: #0f172a;
    --color-surface: #1e293b;
}

/* Component-specific overrides */
.admin-header {
    background: var(--color-primary);
    padding: calc(var(--spacing-unit) * 3);
}

.server-card {
    border-radius: var(--border-radius);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

/* Custom animations */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}

.panel {
    animation: fadeIn 0.3s ease-out;
}
```

### Kubernetes ConfigMap for CSS

For Kubernetes deployments, use a ConfigMap:

```yaml
# configmap-custom-css.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcpgateway-custom-css
  namespace: default
data:
  admin.css: |
    :root {
      --color-primary: #2563eb;
      --color-secondary: #10b981;
    }
    /* Additional custom styles */
---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway
spec:
  template:
    spec:
      containers:
      - name: mcpgateway
        image: ghcr.io/MCP-Mirror/mcpgateway:latest
        volumeMounts:
        - name: custom-css
          mountPath: /app/mcpgateway/static/admin.css
          subPath: admin.css
          readOnly: true
      volumes:
      - name: custom-css
        configMap:
          name: mcpgateway-custom-css
```

### Verifying Custom CSS

To verify your custom CSS is loaded:

1. Access the Admin UI at `http://localhost:4444/admin`
2. Open browser developer tools (F12)
3. Check the Network tab for `admin.css`
4. Inspect elements to see applied styles
5. Look for your custom CSS variables in the computed styles

### Troubleshooting Container CSS Issues

Common issues and solutions:

1. **CSS not updating**: Clear browser cache or use hard refresh (Ctrl+Shift+R)
2. **Permission denied**: Ensure mounted files are readable (`chmod 644 admin.css`)
3. **Path not found**: Verify the container path is exactly `/app/mcpgateway/static/`
4. **Styles not applying**: Check CSS specificity and use `!important` if necessary

## Configuration Examples

### Environment Variables

Complete list of UI customization environment variables:

```bash
# Theme and Appearance
MCPGATEWAY_ADMIN_THEME=dark
MCPGATEWAY_ADMIN_HIGH_CONTRAST=false
MCPGATEWAY_ADMIN_FONT_SIZE=medium
MCPGATEWAY_ADMIN_ANIMATIONS=true

# Branding
MCPGATEWAY_ADMIN_TITLE="Custom MCP Gateway"
MCPGATEWAY_ADMIN_LOGO_URL="/static/logo.svg"
MCPGATEWAY_ADMIN_FAVICON_URL="/static/favicon.ico"
MCPGATEWAY_ADMIN_CUSTOM_CSS="/static/custom.css"

# Layout
MCPGATEWAY_ADMIN_DEFAULT_LAYOUT=dashboard
MCPGATEWAY_ADMIN_SHOW_SERVERS=true
MCPGATEWAY_ADMIN_SHOW_TOOLS=true
MCPGATEWAY_ADMIN_SHOW_RESOURCES=true
MCPGATEWAY_ADMIN_SHOW_PROMPTS=true
MCPGATEWAY_ADMIN_SHOW_METRICS=true

# Features
MCPGATEWAY_ADMIN_ENABLE_SEARCH=true
MCPGATEWAY_ADMIN_ENABLE_EXPORT=true
MCPGATEWAY_ADMIN_ENABLE_SHORTCUTS=true
MCPGATEWAY_ADMIN_ENABLE_DRAG_DROP=true

# Localization
MCPGATEWAY_ADMIN_DEFAULT_LANGUAGE=en
MCPGATEWAY_ADMIN_AVAILABLE_LANGUAGES=en,es,fr,de,ja

# Performance
MCPGATEWAY_ADMIN_LAZY_LOAD=true
MCPGATEWAY_ADMIN_CACHE_DURATION=3600
MCPGATEWAY_ADMIN_UPDATE_INTERVAL=5000
```

### Docker Configuration

Mount custom configuration in Docker:

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcpgateway:
    image: mcpgateway:latest
    environment:
      - MCPGATEWAY_ADMIN_THEME=dark
      - MCPGATEWAY_ADMIN_TITLE=My Custom Gateway
    volumes:
      - ./custom-ui:/app/static/custom:ro
      - ./ui-config.json:/app/config/ui.json:ro
    ports:
      - "4444:4444"
```

## Troubleshooting

### Common Issues

1. **Theme not persisting**: Check browser localStorage permissions
2. **Custom CSS not loading**: Verify file path and permissions
3. **Layout reset on refresh**: Ensure localStorage is not being cleared
4. **Mobile layout issues**: Check viewport meta tag in HTML

### Debug Mode

Enable debug mode for UI troubleshooting:

```javascript
// Enable UI debug mode
localStorage.setItem('ui-debug', 'true');

// Debug logging
if (localStorage.getItem('ui-debug') === 'true') {
    console.log('Panel configuration:', panelConfig);
    console.log('Theme:', currentTheme);
    console.log('User preferences:', userProfile);
}
```

## Building Your Own Custom UI

The MCP Gateway provides comprehensive REST APIs that enable you to build completely custom user interfaces. This section covers API endpoints, authentication, real-time communication, and how to disable the built-in UI.

### Disabling the Built-in UI

When using a custom UI, you can disable the default Admin UI:

```bash
# Disable built-in UI completely
MCPGATEWAY_UI_ENABLED=false         # Disables static file serving and root redirect
MCPGATEWAY_ADMIN_API_ENABLED=false  # Disables admin-specific API endpoints

# Or keep APIs but disable UI
MCPGATEWAY_UI_ENABLED=false         # Disable UI only
MCPGATEWAY_ADMIN_API_ENABLED=true   # Keep admin APIs for custom UI
```

When the UI is disabled:
- Root path (`/`) returns API information instead of redirecting to `/admin`
- Static files (`/static/*`) are not served
- Admin UI routes (`/admin/*`) return 404
- All API endpoints remain accessible (unless `MCPGATEWAY_ADMIN_API_ENABLED=false`)

### API Documentation

The gateway provides interactive API documentation:

- **`/docs`** - Swagger UI interactive documentation
- **`/redoc`** - ReDoc API documentation
- **`/openapi.json`** - OpenAPI 3.0 schema (for code generation)

Access the Swagger UI at `http://localhost:4444/docs` to explore all available endpoints interactively.

### Core API Endpoints

#### Virtual Server Management
```bash
GET    /servers              # List all virtual servers
POST   /servers              # Create new virtual server
GET    /servers/{id}         # Get specific server details
PUT    /servers/{id}         # Update server configuration
DELETE /servers/{id}         # Delete virtual server
```

#### Tool Registry
```bash
GET    /tools                # List all available tools
POST   /tools                # Register new tool
GET    /tools/{id}           # Get tool details
PUT    /tools/{id}           # Update tool
DELETE /tools/{id}           # Remove tool
POST   /tools/{id}/invoke    # Invoke a specific tool
```

#### Resource Management
```bash
GET    /resources            # List all resources
POST   /resources            # Create new resource
GET    /resources/{id}       # Get resource details
PUT    /resources/{id}       # Update resource
DELETE /resources/{id}       # Delete resource
GET    /resources/{id}/read  # Read resource content
```

#### Prompt Templates
```bash
GET    /prompts              # List all prompts
POST   /prompts              # Create new prompt
GET    /prompts/{id}         # Get prompt details
PUT    /prompts/{id}         # Update prompt
DELETE /prompts/{id}         # Delete prompt
POST   /prompts/{id}/execute # Execute prompt
```

#### Gateway Federation
```bash
GET    /gateways             # List peer gateways
POST   /gateways             # Register new gateway
GET    /gateways/{id}        # Get gateway details
DELETE /gateways/{id}        # Remove gateway
GET    /gateways/{id}/health # Check gateway health
```

#### System Information
```bash
GET    /version              # System diagnostics and metrics
GET    /health               # Health check endpoint
GET    /ready                # Readiness check
GET    /metrics              # Prometheus-compatible metrics
```

#### MCP Protocol Operations
```bash
POST   /                     # JSON-RPC endpoint for MCP protocol
POST   /rpc                  # Alternative JSON-RPC endpoint
POST   /protocol/initialize  # Initialize MCP session
POST   /protocol/ping        # Ping for keepalive
POST   /protocol/notify      # Send notifications
```

### Authentication

#### Generate JWT Token
```bash
# Generate a JWT token for API access
python3 -m mcpgateway.utils.create_jwt_token \
    --username admin \
    --exp 10080 \
    --secret $JWT_SECRET_KEY

# Export for use in API calls
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 0 --secret my-test-key)
```

#### Using Authentication in API Calls
```bash
# Bearer token authentication (recommended)
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:4444/servers

# Basic authentication (alternative)
curl -u admin:changeme \
     http://localhost:4444/servers

# Cookie-based (for browser sessions)
curl -c cookies.txt -X POST \
     -d '{"username":"admin","password":"changeme"}' \
     http://localhost:4444/auth/login
```

### Real-time Communication

#### Server-Sent Events (SSE)
```javascript
// Connect to SSE endpoint for real-time updates
const eventSource = new EventSource(
    `/servers/${serverId}/sse`,
    { headers: { 'Authorization': `Bearer ${token}` } }
);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Server update:', data);
};

eventSource.addEventListener('tool-invoked', (event) => {
    console.log('Tool invoked:', JSON.parse(event.data));
});
```

#### WebSocket Connection
```javascript
// WebSocket for bidirectional communication
const ws = new WebSocket(`ws://localhost:4444/ws`);

ws.onopen = () => {
    // Send authentication
    ws.send(JSON.stringify({
        type: 'auth',
        token: token
    }));
    
    // Subscribe to updates
    ws.send(JSON.stringify({
        jsonrpc: '2.0',
        method: 'subscribe',
        params: { topics: ['tools', 'servers'] },
        id: 1
    }));
};

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('WebSocket message:', message);
};
```

#### HTTP Streaming
```bash
# Stream responses using HTTP chunked encoding
curl -N -H "Authorization: Bearer $TOKEN" \
     -H "Accept: text/event-stream" \
     http://localhost:4444/servers/stream
```

### Building a React-Based Custom UI

Example React application structure:

```jsx
// api/client.js
class MCPGatewayClient {
    constructor(baseUrl, token) {
        this.baseUrl = baseUrl;
        this.token = token;
    }
    
    async fetchServers() {
        const response = await fetch(`${this.baseUrl}/servers`, {
            headers: {
                'Authorization': `Bearer ${this.token}`,
                'Content-Type': 'application/json'
            }
        });
        return response.json();
    }
    
    async createServer(config) {
        const response = await fetch(`${this.baseUrl}/servers`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${this.token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        return response.json();
    }
    
    connectSSE(serverId, onMessage) {
        const eventSource = new EventSource(
            `${this.baseUrl}/servers/${serverId}/sse`,
            { 
                headers: { 
                    'Authorization': `Bearer ${this.token}` 
                } 
            }
        );
        
        eventSource.onmessage = onMessage;
        return eventSource;
    }
}

// components/ServerDashboard.jsx
import React, { useState, useEffect } from 'react';
import { MCPGatewayClient } from '../api/client';

export function ServerDashboard() {
    const [servers, setServers] = useState([]);
    const client = new MCPGatewayClient(
        process.env.REACT_APP_GATEWAY_URL,
        process.env.REACT_APP_TOKEN
    );
    
    useEffect(() => {
        // Load initial data
        client.fetchServers().then(setServers);
        
        // Subscribe to real-time updates
        const sse = client.connectSSE('all', (event) => {
            const update = JSON.parse(event.data);
            if (update.type === 'server-update') {
                setServers(prev => 
                    prev.map(s => s.id === update.server.id 
                        ? update.server : s)
                );
            }
        });
        
        return () => sse.close();
    }, []);
    
    return (
        <div className="dashboard">
            <h1>MCP Gateway Servers</h1>
            <div className="server-grid">
                {servers.map(server => (
                    <ServerCard key={server.id} server={server} />
                ))}
            </div>
        </div>
    );
}
```

### Python Custom UI Example

```python
# custom_ui_client.py
import requests
import sseclient
from typing import Dict, List

class MCPGatewayClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def list_servers(self) -> List[Dict]:
        """List all virtual servers"""
        response = requests.get(
            f"{self.base_url}/servers",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def create_server(self, config: Dict) -> Dict:
        """Create a new virtual server"""
        response = requests.post(
            f"{self.base_url}/servers",
            json=config,
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def invoke_tool(self, tool_id: str, params: Dict) -> Dict:
        """Invoke a tool"""
        response = requests.post(
            f"{self.base_url}/tools/{tool_id}/invoke",
            json={"params": params},
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def stream_events(self, server_id: str = "all"):
        """Stream real-time events via SSE"""
        response = requests.get(
            f"{self.base_url}/servers/{server_id}/sse",
            headers=self.headers,
            stream=True
        )
        client = sseclient.SSEClient(response)
        for event in client.events():
            yield event

# Example usage
if __name__ == "__main__":
    client = MCPGatewayClient(
        base_url="http://localhost:4444",
        token="your-jwt-token"
    )
    
    # List servers
    servers = client.list_servers()
    print(f"Found {len(servers)} servers")
    
    # Stream events
    for event in client.stream_events():
        print(f"Event: {event.event}, Data: {event.data}")
```

### TypeScript SDK Example

```typescript
// mcp-gateway-sdk.ts
export interface Server {
    id: string;
    name: string;
    description?: string;
    tools: string[];
    resources: string[];
    status: 'active' | 'inactive';
}

export interface Tool {
    id: string;
    name: string;
    description: string;
    parameters: Record<string, any>;
}

export class MCPGatewaySDK {
    constructor(
        private baseUrl: string,
        private token: string
    ) {}
    
    private async request<T>(
        path: string,
        options: RequestInit = {}
    ): Promise<T> {
        const response = await fetch(`${this.baseUrl}${path}`, {
            ...options,
            headers: {
                'Authorization': `Bearer ${this.token}`,
                'Content-Type': 'application/json',
                ...options.headers,
            },
        });
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        return response.json();
    }
    
    async getServers(): Promise<Server[]> {
        return this.request<Server[]>('/servers');
    }
    
    async createServer(config: Partial<Server>): Promise<Server> {
        return this.request<Server>('/servers', {
            method: 'POST',
            body: JSON.stringify(config),
        });
    }
    
    async getTools(): Promise<Tool[]> {
        return this.request<Tool[]>('/tools');
    }
    
    async invokeTool(
        toolId: string, 
        params: Record<string, any>
    ): Promise<any> {
        return this.request(`/tools/${toolId}/invoke`, {
            method: 'POST',
            body: JSON.stringify({ params }),
        });
    }
    
    subscribeToEvents(
        serverId: string = 'all',
        onMessage: (event: MessageEvent) => void
    ): EventSource {
        const eventSource = new EventSource(
            `${this.baseUrl}/servers/${serverId}/sse`,
            {
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                },
            }
        );
        
        eventSource.onmessage = onMessage;
        
        eventSource.onerror = (error) => {
            console.error('SSE Error:', error);
        };
        
        return eventSource;
    }
}
```

### CORS Configuration

For browser-based custom UIs, configure CORS:

```bash
# Enable CORS for your custom UI domain
CORS_ENABLED=true
ALLOWED_ORIGINS=http://localhost:3000,https://my-custom-ui.com
```

### API Rate Limiting

When building custom UIs, be aware of rate limits:

```python
# Rate limiting configuration
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10
```

Handle rate limit responses:
```javascript
async function apiCall(url, options) {
    const response = await fetch(url, options);
    
    if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After');
        console.log(`Rate limited. Retry after ${retryAfter} seconds`);
        // Implement exponential backoff
        await sleep(retryAfter * 1000);
        return apiCall(url, options);
    }
    
    return response;
}
```

### Monitoring Your Custom UI

Track custom UI interactions:

```javascript
// Send custom metrics to the gateway
fetch('/metrics/custom', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        metric: 'ui.page_view',
        value: 1,
        labels: {
            page: 'dashboard',
            user: 'admin'
        }
    })
});
```

## Best Practices

1. **Test customizations** across different browsers and devices
2. **Backup configurations** before major changes
3. **Use version control** for custom CSS and JavaScript files
4. **Document custom changes** for team members
5. **Monitor performance** impact of customizations
6. **Follow accessibility guidelines** (WCAG 2.1 AA)
7. **Implement progressive enhancement** for better compatibility
8. **Use API versioning** when building custom UIs to handle future changes
9. **Implement proper error handling** for API failures
10. **Cache API responses** appropriately to reduce load

## Related Documentation

- [Admin UI Overview](/overview/ui/) - Basic UI concepts and navigation
- [Security Configuration](/manage/securing/) - Securing the Admin UI
- [Performance Tuning](/manage/tuning/) - Optimizing UI performance
- [API Reference](/api/admin/) - Admin API endpoints