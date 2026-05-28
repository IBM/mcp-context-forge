import { useIntl } from "react-intl";
import { Plus } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function ConnectSourceCard({ onAction }: { onAction: () => void }) {
  const intl = useIntl();

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
          <CardTitle>{intl.formatMessage({ id: "gateways.createServer.card.title" })}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-[13px] leading-4">
          {intl.formatMessage({ id: "gateways.createServer.card.description" })}
        </CardDescription>
      </CardContent>
    </Card>
  );
}
