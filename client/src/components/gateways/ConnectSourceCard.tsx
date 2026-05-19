import { Plus } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function ConnectSourceCard({ onAction }: { onAction: () => void }) {
  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      className="min-h-35 cursor-pointer justify-center transition-colors hover:bg-muted/40"
      onClick={onAction}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onAction();
        }
      }}
    >
      <CardHeader className="gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-6 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Plus className="size-4" />
          </span>
          <CardTitle>Connect a source</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-[13px] leading-4">
          Make an external source available through a virtual server endpoint. Sources can be
          running MCP servers, REST APIs, gRPC services, or A2A agents
        </CardDescription>
      </CardContent>
    </Card>
  );
}
