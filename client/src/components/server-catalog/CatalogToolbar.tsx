import { useId } from "react";
import { Filter, Search } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { CardTag } from "@/components/ui/card-tag";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const OPEN_AUTH_TYPE = "Open";
const ALL_FILTER_VALUE = "__all__";

export type CatalogSingleFilterKey = "category" | "provider" | "auth_type";

interface CatalogToolbarProps {
  search: string;
  installedOnly: boolean;
  category: string;
  provider: string;
  authType: string;
  selectedTags: string[];
  categories: string[];
  providers: string[];
  availableTags: string[];
  activeFilterCount: number;
  onSearchChange: (value: string) => void;
  onInstalledChange: (installedOnly: boolean) => void;
  onSetSingleFilter: (key: CatalogSingleFilterKey, value: string | null) => void;
  onToggleTag: (tag: string, checked: boolean) => void;
  onClear: () => void;
}

function CatalogViewToggle({
  installedOnly,
  onChange,
}: {
  installedOnly: boolean;
  onChange: (installedOnly: boolean) => void;
}) {
  const intl = useIntl();

  return (
    <div
      role="group"
      aria-label={intl.formatMessage({ id: "mcpServer.catalog.viewOptions" })}
      className="flex h-10 w-full gap-0 rounded-md bg-muted p-1 sm:w-[292px]"
    >
      <Button
        type="button"
        variant="ghost"
        aria-pressed={!installedOnly}
        className="h-8 flex-1 rounded-md font-medium aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-xs"
        onClick={() => onChange(false)}
      >
        {intl.formatMessage({ id: "mcpServer.catalog.all" })}
      </Button>
      <Button
        type="button"
        variant="ghost"
        aria-pressed={installedOnly}
        className="h-8 flex-1 rounded-md font-medium aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-xs"
        onClick={() => onChange(true)}
      >
        {intl.formatMessage({ id: "mcpServer.catalog.installed" })}
      </Button>
    </div>
  );
}

function CatalogFiltersPopover({
  category,
  provider,
  authType,
  selectedTags,
  categories,
  providers,
  availableTags,
  activeFilterCount,
  onSetSingleFilter,
  onToggleTag,
  onClear,
}: Omit<CatalogToolbarProps, "search" | "installedOnly" | "onSearchChange" | "onInstalledChange">) {
  const intl = useIntl();
  const id = useId();
  const filtersTitleId = `${id}-title`;
  const categoryTriggerId = `${id}-category`;
  const providerTriggerId = `${id}-provider`;
  const authTriggerId = `${id}-auth`;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className="h-10 justify-start sm:justify-center"
          aria-label={intl.formatMessage(
            { id: "mcpServer.catalog.filtersActive" },
            { count: activeFilterCount },
          )}
        >
          <Filter className="size-4" aria-hidden="true" />
          {intl.formatMessage({ id: "mcpServer.catalog.filters" })}
          {activeFilterCount > 0 && (
            <CardTag variant="neutral" className="rounded-full" aria-hidden="true">
              {activeFilterCount}
            </CardTag>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-4" aria-labelledby={filtersTitleId}>
        <div className="flex items-center justify-between">
          <h2 id={filtersTitleId} className="text-sm font-semibold">
            {intl.formatMessage({ id: "mcpServer.catalog.filters" })}
          </h2>
          {activeFilterCount > 0 && (
            <Button type="button" variant="ghost" size="xs" onClick={onClear}>
              {intl.formatMessage({ id: "mcpServer.catalog.clearFilters" })}
            </Button>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor={categoryTriggerId} className="text-xs">
            {intl.formatMessage({ id: "mcpServer.catalog.category" })}
          </Label>
          <Select
            value={category || ALL_FILTER_VALUE}
            onValueChange={(value) =>
              onSetSingleFilter("category", value === ALL_FILTER_VALUE ? null : value)
            }
          >
            <SelectTrigger id={categoryTriggerId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>
                {intl.formatMessage({ id: "mcpServer.catalog.allCategories" })}
              </SelectItem>
              {categories.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor={providerTriggerId} className="text-xs">
            {intl.formatMessage({ id: "mcpServer.catalog.provider" })}
          </Label>
          <Select
            value={provider || ALL_FILTER_VALUE}
            onValueChange={(value) =>
              onSetSingleFilter("provider", value === ALL_FILTER_VALUE ? null : value)
            }
          >
            <SelectTrigger id={providerTriggerId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>
                {intl.formatMessage({ id: "mcpServer.catalog.allProviders" })}
              </SelectItem>
              {providers.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor={authTriggerId} className="text-xs">
            {intl.formatMessage({ id: "mcpServer.catalog.authentication" })}
          </Label>
          <Select
            value={authType || ALL_FILTER_VALUE}
            onValueChange={(value) =>
              onSetSingleFilter("auth_type", value === ALL_FILTER_VALUE ? null : value)
            }
          >
            <SelectTrigger id={authTriggerId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>
                {intl.formatMessage({ id: "mcpServer.catalog.allAuthTypes" })}
              </SelectItem>
              <SelectItem value={OPEN_AUTH_TYPE}>{OPEN_AUTH_TYPE}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {availableTags.length > 0 && (
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium">
              {intl.formatMessage({ id: "mcpServer.catalog.tags" })}
            </legend>
            <div className="max-h-40 space-y-2 overflow-y-auto rounded-md border p-2">
              {availableTags.map((tag, index) => {
                const checkboxId = `${id}-tag-${index}`;
                return (
                  <div key={tag} className="flex items-center gap-2">
                    <Checkbox
                      id={checkboxId}
                      checked={selectedTags.includes(tag)}
                      onCheckedChange={(checked) => onToggleTag(tag, checked === true)}
                    />
                    <Label htmlFor={checkboxId} className="cursor-pointer text-sm font-normal">
                      {tag}
                    </Label>
                  </div>
                );
              })}
            </div>
          </fieldset>
        )}
      </PopoverContent>
    </Popover>
  );
}

export function CatalogToolbar({
  search,
  installedOnly,
  onSearchChange,
  onInstalledChange,
  ...filterProps
}: CatalogToolbarProps) {
  const intl = useIntl();

  return (
    <div className="flex flex-col gap-4 py-6 lg:flex-row lg:items-center lg:justify-between">
      <CatalogViewToggle installedOnly={installedOnly} onChange={onInstalledChange} />

      <div className="flex w-full flex-col gap-3 sm:flex-row lg:w-auto">
        <div className="relative w-full sm:w-[432px]">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={intl.formatMessage({ id: "mcpServer.catalog.searchPlaceholder" })}
            aria-label={intl.formatMessage({ id: "mcpServer.catalog.searchLabel" })}
            className="h-10 pl-9"
          />
        </div>

        <CatalogFiltersPopover {...filterProps} />
      </div>
    </div>
  );
}
