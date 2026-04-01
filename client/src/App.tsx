import React from 'react';
import { createRouter, RouterProvider, createRoute, createRootRoute, Link, Outlet, useMatchRoute } from '@tanstack/react-router';
import Dashboard from './pages/Dashboard';
import Servers from './pages/Servers';
import Tools from './pages/Tools';
import Settings from './pages/Settings';

function Sidebar() {
  const matchRoute = useMatchRoute();
  
  const navItems = [
    { path: '/', label: 'Dashboard', icon: '📊' },
    { path: '/servers', label: 'Servers', icon: '🖥️' },
    { path: '/tools', label: 'Tools', icon: '🔧' },
    { path: '/settings', label: 'Settings', icon: '⚙️' },
  ];

  return (
    <aside className="w-64 bg-gray-900 text-white min-h-screen p-4">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">ContextForge</h1>
        <p className="text-sm text-gray-400">Client Dashboard</p>
      </div>
      <nav>
        <ul className="space-y-2">
          {navItems.map((item) => {
            const isActive = matchRoute({ to: item.path, fuzzy: false });
            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-300 hover:bg-gray-800'
                  }`}
                >
                  <span className="text-xl">{item.icon}</span>
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}

function Layout() {
  return (
    <div className="flex min-h-screen bg-gray-100">
      <Sidebar />
      <main className="flex-1 p-8">
        <Outlet />
      </main>
    </div>
  );
}

// Create root route
const rootRoute = createRootRoute({
  component: Layout,
});

// Create child routes
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: Dashboard,
});

const serversRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/servers',
  component: Servers,
});

const toolsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tools',
  component: Tools,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: Settings,
});

// Create route tree
const routeTree = rootRoute.addChildren([
  indexRoute,
  serversRoute,
  toolsRoute,
  settingsRoute,
]);

// Create router
const router = createRouter({
  routeTree,
  basepath: '/app',
});

function App() {
  return <RouterProvider router={router} />;
}

export default App;
