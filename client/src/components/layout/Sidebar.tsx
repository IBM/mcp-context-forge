import { useIntl } from "react-intl";
import {
  Blocks,
  Bot,
  ChartLine,
  FileCode2,
  House,
  KeyRound,
  MessageSquareMore,
  MonitorCog,
  Server,
  Settings,
  Shapes,
  Users,
  Wrench,
} from "lucide-react";
import { useRouter } from "../../router";
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
import { GatewayIcon,  } from "../icons/GatewayIcon.tsx";
import { MCPIcon } from "../icons/MCPIcon.tsx";
import { MainNavIcon } from "../icons/MainNavIcon.tsx";

interface NavItem {
  labelKey: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
}

const MAIN_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.dashboard", path: "/app/", icon: House },
  { labelKey: "navigation.gateways", path: "/app/gateways", icon: GatewayIcon },
  { labelKey: "navigation.observability", path: "/app/observability", icon: ChartLine },
  { labelKey: "navigation.playground", path: "/app/playground", icon: MessageSquareMore },
];

const COMPONENTS_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.servers", path: "/app/servers", icon: MCPIcon },
  { labelKey: "navigation.virtualServers", path: "/app/gateways", icon: Server },
  { labelKey: "navigation.agents", path: "/app/agents", icon: Bot },
  { labelKey: "navigation.tools", path: "/app/tools", icon: Wrench },
  { labelKey: "navigation.resources", path: "/app/resources", icon: MonitorCog },
  { labelKey: "navigation.prompts", path: "/app/prompts", icon: FileCode2 },
  { labelKey: "navigation.plugins", path: "/app/plugins", icon: Blocks },
  { labelKey: "navigation.serverCatalog", path: "/app/server-catalog", icon: Shapes },
];

const TEAM_NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.tokens", path: "/app/tokens", icon: KeyRound },
  { labelKey: "navigation.members", path: "/app/members", icon: Users },
];

const FOOTER_NAV_ITEM: NavItem = { labelKey: "navigation.settings", path: "/app/settings", icon: Settings };

export function AppSidebar() {
  const intl = useIntl();
  const { path, navigate } = useRouter();

  const renderNavItems = (items: NavItem[]) => {
    return items.map(({ labelKey, path: itemPath, icon: Icon }) => {
      const isActive =
        path === itemPath ||
        (itemPath !== "/app/" && path.startsWith(itemPath));
      return (
        <SidebarMenuItem key={itemPath}>
          <SidebarMenuButton
            isActive={isActive}
            onClick={() => navigate(itemPath)}
          >
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
        <div className="flex items-center gap-2 px-2 py-1">
          <div className="flex h-8 w-8 items-center justify-center">
            <span className="text-lg font-bold"><MainNavIcon className="w-6 h-6" /></span>
          </div>
        </div>
      </SidebarHeader>
      
      <SidebarContent>
        {/* Main Navigation */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {renderNavItems(MAIN_NAV_ITEMS)}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Components Section */}
        <SidebarGroup>
          <SidebarGroupLabel>Components</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {renderNavItems(COMPONENTS_NAV_ITEMS)}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Team Section */}
        <SidebarGroup>
          <SidebarGroupLabel>Team</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {renderNavItems(TEAM_NAV_ITEMS)}
            </SidebarMenu>
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
