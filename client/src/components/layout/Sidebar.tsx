import {
  Blocks,
  Box,
  ChartLine,
  Code,
  House,
  MessageSquareMore,
  Server,
  Settings,
  Shapes,
  Unplug,
  Wrench,
} from "lucide-react";
import { useIntl } from "react-intl";
import { useRouter } from "../../router";
import { AgentIcon } from "../icons/AgentIcon.tsx";
import { MCPIcon } from "../icons/MCPIcon.tsx";
import { MainNavIcon } from "../icons/MainNavIcon.tsx";
import { PromptIcon } from "../icons/PromptIcon.tsx";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "../ui/sidebar";
import { TeamSwitcher } from "./TeamSwitcher";

interface NavItem {
  labelKey: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
}

const MAIN_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.dashboard", path: "/app/", icon: House },
  { labelKey: "navigation.virtualServers", path: "/app/gateways", icon: Server },
  { labelKey: "navigation.observability", path: "/app/observability", icon: ChartLine },
  { labelKey: "navigation.playground", path: "/app/playground", icon: MessageSquareMore },
];

const COMPONENTS_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.servers", path: "/app/servers", icon: MCPIcon },
  { labelKey: "navigation.agents", path: "/app/agents", icon: AgentIcon },
  { labelKey: "navigation.restApi", path: "/app/rest-api", icon: Code },
  { labelKey: "navigation.grpc", path: "/app/grpc", icon: Unplug },
  { labelKey: "navigation.tools", path: "/app/tools", icon: Wrench },
  { labelKey: "navigation.resources", path: "/app/resources", icon: Box },
  { labelKey: "navigation.prompts", path: "/app/prompts", icon: PromptIcon },
];

const ECOSYSTEM_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.serverCatalog", path: "/app/server-catalog", icon: Shapes },
  { labelKey: "navigation.plugins", path: "/app/plugins", icon: Blocks },
];

const FOOTER_NAV_ITEM: NavItem = {
  labelKey: "navigation.settings",
  path: "/app/settings",
  icon: Settings,
};

export function AppSidebar() {
  const intl = useIntl();
  const { path, navigate } = useRouter();

  const renderNavItems = (items: NavItem[]) => {
    return items.map(({ labelKey, path: itemPath, icon: Icon }) => {
      const isActive = path === itemPath || (itemPath !== "/app/" && path.startsWith(itemPath));
      return (
        <SidebarMenuItem key={itemPath}>
          <SidebarMenuButton isActive={isActive} onClick={() => navigate(itemPath)}>
            <Icon className="h-4 w-4" />
            <span>{intl.formatMessage({ id: labelKey })}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      );
    });
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="flex items-center gap-2 w-full">
              <div className="flex h-8 w-8 items-center justify-center shrink-0">
                <span className="text-lg font-bold">
                  <MainNavIcon className="w-6 h-6" />
                </span>
              </div>
              <div className="flex-1 min-w-0 group-data-[collapsible=icon]:hidden">
                <TeamSwitcher />
              </div>
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {/* Main Navigation */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>{renderNavItems(MAIN_NAV_ITEMS)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Components Section */}
        <SidebarGroup>
          <SidebarGroupLabel>Components</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{renderNavItems(COMPONENTS_NAV_ITEMS)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Ecosystem Section */}
        <SidebarGroup>
          <SidebarGroupLabel>Ecosystem</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{renderNavItems(ECOSYSTEM_NAV_ITEMS)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={path === FOOTER_NAV_ITEM.path}
              onClick={() => navigate(FOOTER_NAV_ITEM.path)}
            >
              <FOOTER_NAV_ITEM.icon className="h-4 w-4" />
              <span>{intl.formatMessage({ id: FOOTER_NAV_ITEM.labelKey })}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
