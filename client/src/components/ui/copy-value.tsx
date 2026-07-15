import { Copy } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { truncateMiddle } from "@/components/gateways/utils";
import { copyToClipboard } from "@/lib/clipboard";

export interface CopyValueProps {
  /** Human-readable name of the value, used to build the copy button's accessible label. */
  label: string;
  /** The full value copied to the clipboard (the visible text is middle-truncated). */
  value: string;
}

/**
 * A truncated, monospaced value paired with a copy-to-clipboard button.
 *
 * Shared across the entity detail panels (tools, resources, prompts, servers,
 * virtual servers). The visible text is middle-truncated for layout; the full
 * `value` is what gets copied. The copy button's accessible label is localized
 * via the `common.copyValue` message so screen readers announce it in the
 * active locale.
 */
export function CopyValue({ label, value }: CopyValueProps) {
  const intl = useIntl();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{truncateMiddle(value)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="size-5 text-muted-foreground"
        aria-label={intl.formatMessage({ id: "common.copyValue" }, { label })}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}
