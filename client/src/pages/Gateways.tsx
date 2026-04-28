import { useRouter } from "@/router";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { MainNavIcon } from "@/components/icons/MainNavIcon";
import { NewMCPServerModal } from "@/components/mcpServers/NewMCPServerModal";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Blocks, Bot, Code } from "lucide-react";

interface ActionCard {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  buttonText: string;
  onAction?: () => void;
  renderButton?: () => React.ReactNode;
}

export function Gateways() {
  const { navigate } = useRouter();

  const actionCards: ActionCard[] = [
    {
      icon: MCPIcon,
      title: "MCP server",
      description: "Register an endpoint implementing the Model Context Protocol",
      buttonText: "+ Connect",
      renderButton: () => (
        <NewMCPServerModal
          triggerLabel="+ Connect"
          triggerVariant="outline"
          showTriggerIcon={false}
          triggerClassName="w-full opacity-0 transition-opacity group-hover/action-card:opacity-100 bg-neutral-900 text-white hover:bg-neutral-800 hover:text-white dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 dark:hover:text-neutral-900"
        />
      ),
    },
    {
      icon: Bot,
      title: "AI agent",
      description: "Add an agent over A2A, OpenAI, or Anthropic protocols",
      buttonText: "+ Connect",
      onAction: () => navigate("/app/agents"),
    },
    {
      icon: Code,
      title: "REST API",
      description: "Wrap a HTTP endpoint as a MCP tool",
      buttonText: "+ Connect",
      onAction: () => {
        // TODO: Implement REST API gateway creation
        console.log("REST API gateway creation not yet implemented");
      },
    },
    {
      icon: Blocks,
      title: "gRPC",
      description: "Translate a gRPC endpoint as a MCP tool.",
      buttonText: "+ Connect",
      onAction: () => {
        // TODO: Implement gRPC gateway creation
        console.log("gRPC gateway creation not yet implemented");
      },
    },
  ];

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
      <div className="w-full max-w-5xl space-y-12 px-6">
        {/* Header with logo */}
        <div className="flex items-center justify-center gap-3">
          <MainNavIcon className="h-10 w-10 text-neutral-900 dark:text-neutral-50" />
          <h1 className="text-3xl font-semibold text-neutral-900 dark:text-neutral-50">
            Connect a source
          </h1>
        </div>

        {/* Action Cards Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {actionCards.map((card, index) => {
            const IconComponent = card.icon;
            return (
              <Card
                key={index}
                className="group/action-card flex flex-col transition-all hover:shadow-md hover:border-[#FF832B] hover:ring-[#FF832B]"
              >
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-muted-foreground transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white">
                    <IconComponent className="h-5 w-5 text-muted-foreground transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white" />
                    {card.title}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex-grow">
                  <CardDescription className="transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white">
                    {card.description}
                  </CardDescription>
                </CardContent>
                <CardFooter className="mt-auto">
                  {card.renderButton ? (
                    card.renderButton()
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={card.onAction}
                      className="w-full opacity-0 transition-opacity group-hover/action-card:opacity-100 bg-neutral-900 text-white hover:bg-neutral-800 hover:text-white dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 dark:hover:text-neutral-900"
                    >
                      {card.buttonText}
                    </Button>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
