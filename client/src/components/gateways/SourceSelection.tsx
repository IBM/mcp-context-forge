import { useState } from "react";
import { useIntl } from "react-intl";
import { ArrowLeft, ChevronRight, Plus } from "lucide-react";
import { MainNavIcon } from "@/components/icons/MainNavIcon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ActionCard } from "@/components/gateways/types";

export function SourceSelection({
  actionCards,
  createServerActions,
}: {
  actionCards: ActionCard[];
  createServerActions?: {
    onBack: () => void;
    onAddComponents: () => void;
    onSkip: () => void;
    isSkipping?: boolean;
    skipError?: string | null;
  };
}) {
  const intl = useIntl();
  const firstEnabledIndex = actionCards.findIndex((card) => !card.disabled);
  const initialSelectedIndex = firstEnabledIndex === -1 ? 0 : firstEnabledIndex;
  const [selectedIndex, setSelectedIndex] = useState(initialSelectedIndex);

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
      <div className="w-full max-w-5xl space-y-12 px-6">
        {createServerActions && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={createServerActions.onBack}
            className="h-8 gap-2 px-0 text-sm font-medium text-foreground hover:bg-transparent hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            {intl.formatMessage({ id: "common.button.back" })}
          </Button>
        )}

        <div className="flex items-center justify-center gap-3">
          <MainNavIcon className="h-10 w-10 text-neutral-900 dark:text-neutral-50" />
          <h1 className="text-3xl font-semibold text-neutral-900 dark:text-neutral-50">
            {intl.formatMessage({ id: "gateways.source.heading" })}
          </h1>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {actionCards.map((card, index) => {
            const IconComponent = card.icon;
            const isDisabled = Boolean(card.disabled);
            const isSelected = index === selectedIndex && !isDisabled;
            const cardClasses = isDisabled
              ? "group/action-card flex cursor-not-allowed flex-col opacity-60"
              : `group/action-card flex cursor-pointer flex-col transition-all hover:border-primary hover:shadow-md hover:ring-primary ${
                  isSelected ? "border-primary shadow-md ring-1 ring-primary" : ""
                }`;
            return (
              <Card
                key={card.title}
                aria-disabled={isDisabled || undefined}
                data-testid={`action-card-${card.title}`}
                className={cardClasses}
                onClick={() => {
                  if (!isDisabled) setSelectedIndex(index);
                }}
              >
                <CardHeader>
                  <CardTitle
                    className={`flex items-center gap-2 transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                      isSelected ? "text-neutral-900 dark:text-white" : "text-muted-foreground"
                    }`}
                  >
                    <IconComponent
                      className={`h-5 w-5 transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                        isSelected ? "text-neutral-900 dark:text-white" : "text-muted-foreground"
                      }`}
                    />
                    {card.title}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex-grow">
                  <CardDescription
                    className={`transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                      isSelected ? "text-neutral-900 dark:text-white" : ""
                    }`}
                  >
                    {card.description}
                    {isDisabled && card.disabledReason && (
                      <span className="mt-1 block text-xs italic">{card.disabledReason}</span>
                    )}
                  </CardDescription>
                </CardContent>
                <CardFooter className="mt-auto">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isDisabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!isDisabled) card.onAction();
                    }}
                    aria-label={
                      isDisabled ? `${card.buttonText} ${card.title} (coming soon)` : undefined
                    }
                    className="w-full bg-neutral-900 text-white hover:bg-neutral-800 hover:text-white dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 dark:hover:text-neutral-900"
                  >
                    {card.buttonText}
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>

        {createServerActions && (
          <div className="space-y-7">
            <button
              type="button"
              onClick={createServerActions.onAddComponents}
              className="flex min-h-20 w-full items-center gap-4 rounded-xl border border-border px-6 text-left transition hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background dark:border-[#252529]"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted text-foreground dark:bg-[#252529]">
                <Plus className="size-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1 text-base font-semibold text-muted-foreground">
                {intl.formatMessage({ id: "gateways.source.addComponents" })}
              </span>
              <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
            </button>

            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={createServerActions.onSkip}
                disabled={createServerActions.isSkipping}
                className="h-8 rounded-md bg-background px-3 text-sm"
              >
                {createServerActions.isSkipping
                  ? intl.formatMessage({ id: "gateways.createServer.creating" })
                  : intl.formatMessage({ id: "gateways.source.skipForNow" })}
              </Button>
            </div>
            {createServerActions.skipError && (
              <p role="alert" className="text-right text-sm text-destructive">
                {createServerActions.skipError}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
