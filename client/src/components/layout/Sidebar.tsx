import { useRouter } from "../../router";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "../ui/sidebar";

interface NavItem {
  label: string;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", path: "/app/" },
  { label: "Gateways", path: "/app/gateways" },
  { label: "Servers", path: "/app/servers" },
  { label: "Tools", path: "/app/tools" },
  { label: "Resources", path: "/app/resources" },
  { label: "Prompts", path: "/app/prompts" },
  { label: "Agents", path: "/app/agents" },
  { label: "Users", path: "/app/users" },
  { label: "Teams", path: "/app/teams" },
  { label: "Tokens", path: "/app/tokens" },
  { label: "LLM Providers", path: "/app/llm/providers" },
  { label: "LLM Models", path: "/app/llm/models" },
  { label: "Metrics", path: "/app/metrics" },
  { label: "Observability", path: "/app/observability" },
  { label: "Plugins", path: "/app/plugins" },
  { label: "Performance", path: "/app/performance" },
  { label: "Maintenance", path: "/app/maintenance" },
  { label: "Settings", path: "/app/settings" },
];

export function AppSidebar() {
  const { path, navigate } = useRouter();

  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader>
        <span className="px-2 text-sm font-semibold tracking-wide text-sidebar-foreground">
          ContextForge
        </span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map(({ label, path: itemPath }) => {
                const isActive =
                  path === itemPath ||
                  (itemPath !== "/app/" && path.startsWith(itemPath));
                return (
                  <SidebarMenuItem key={itemPath}>
                    <SidebarMenuButton
                      isActive={isActive}
                      onClick={() => navigate(itemPath)}
                    >
                      <span>{label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
