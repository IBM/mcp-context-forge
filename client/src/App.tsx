import { AuthProvider } from "./auth/AuthContext";
import { ThemeProvider } from "./hooks/useTheme";
import { RouterProvider, Route, Redirect, AuthGuard, useRouter } from "./router";
import { AppShell } from "./components/layout/AppShell";
import { Login } from "./pages/Login";
import { ForgotPassword } from "./pages/ForgotPassword";
import { ResetPassword } from "./pages/ResetPassword";
import { ChangePassword } from "./pages/ChangePassword";
import { Dashboard } from "./pages/Dashboard";
import { Gateways } from "./pages/Gateways";
import { CreateServer } from "./pages/CreateServer";
import { Servers } from "./pages/Servers";
import { Tools } from "./pages/Tools";
import { Resources } from "./pages/Resources";
import { ServerCatalog } from "./pages/ServerCatalog";
import { Prompts } from "./pages/Prompts";
import { Agents } from "./pages/Agents";
import { RestApi } from "./pages/RestApi";
import { Grpc } from "./pages/Grpc";
import { Users } from "./pages/Users";
import { Teams } from "./pages/Teams";
import { Tokens } from "./pages/Tokens";
import { LLMProviders } from "./pages/LLMProviders";
import { LLMModels } from "./pages/LLMModels";
import { Metrics } from "./pages/Metrics";
import { Observability } from "./pages/Observability";
import { Plugins } from "./pages/Plugins";
import { Performance } from "./pages/Performance";
import { Maintenance } from "./pages/Maintenance";
import { Settings } from "./pages/Settings";
import { NotFound } from "./pages/NotFound";

// ---------------------------------------------------------------------------
// Unauthenticated shell (full-page, no sidebar/header)
// ---------------------------------------------------------------------------
function PublicRoutes() {
  return (
    <>
      <Route path="/app/login" component={Login} />
      <Route path="/app/forgot-password" component={ForgotPassword} />
      <Route path="/app/reset-password/:token" component={ResetPassword} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Authenticated shell (sidebar + header via AppShell)
// ---------------------------------------------------------------------------
function PrivateRoutes() {
  return (
    <AuthGuard>
      <AppShell>
        <Route path="/app/" component={Dashboard} />
        <Route path="/app/change-password" component={ChangePassword} />
        <Route path="/app/gateways" component={Gateways} />
        <Route path="/app/gateways/create-server" component={CreateServer} />
        <Route path="/app/servers" component={Servers} />
        <Route path="/app/tools" component={Tools} />
        <Route path="/app/resources" component={Resources} />
        <Route path="/app/prompts" component={Prompts} />
        <Route path="/app/agents" component={Agents} />
        <Route path="/app/rest-api" component={RestApi} />
        <Route path="/app/grpc" component={Grpc} />
        <Route path="/app/users" component={Users} />
        <Route path="/app/teams" component={Teams} />
        <Route path="/app/tokens" component={Tokens} />
        <Route path="/app/llm/providers" component={LLMProviders} />
        <Route path="/app/llm/models" component={LLMModels} />
        <Route path="/app/metrics" component={Metrics} />
        <Route path="/app/observability" component={Observability} />
        <Route path="/app/plugins" component={Plugins} />
        <Route path="/app/performance" component={Performance} />
        <Route path="/app/maintenance" component={Maintenance} />
        <Route path="/app/settings" component={Settings} />
        <Route path="/app/not-found" component={NotFound} />
        <Route path="/app/server-catalog" component={ServerCatalog} />
      </AppShell>
    </AuthGuard>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export function App() {
  return (
    <RouterProvider>
      <ThemeProvider>
        <AuthProvider>
          <Routes />
        </AuthProvider>
      </ThemeProvider>
    </RouterProvider>
  );
}

function Routes() {
  const { path } = useRouter();

  // Bare /app (no trailing slash) → redirect to dashboard
  if (path === "/app") {
    return <Redirect to="/app/" />;
  }

  return (
    <>
      <PublicRoutes />
      <PrivateRoutes />
    </>
  );
}
