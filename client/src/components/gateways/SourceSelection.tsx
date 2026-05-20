import { useState } from "react";
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

export function SourceSelection({ actionCards }: { actionCards: ActionCard[] }) {
  const firstEnabledIndex = actionCards.findIndex((card) => !card.disabled);
  const initialSelectedIndex = firstEnabledIndex === -1 ? 0 : firstEnabledIndex;
  const [selectedIndex, setSelectedIndex] = useState(initialSelectedIndex);

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
      <div className="w-full max-w-5xl space-y-12 px-6">
        <div className="flex items-center justify-center gap-3">
          <MainNavIcon className="h-10 w-10 text-neutral-900 dark:text-neutral-50" />
          <h1 className="text-3xl font-semibold text-neutral-900 dark:text-neutral-50">
            Connect a source
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
      </div>
    </div>
  );
}
