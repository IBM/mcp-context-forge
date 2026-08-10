import { Copy } from "lucide-react";
import { useIntl } from "react-intl";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/lib/clipboard";

interface TokenCreatedDialogProps {
  /** The raw access token to reveal, or null when the dialog is closed. */
  token: string | null;
  onClose: () => void;
}

/**
 * One-time reveal of a freshly created token. The raw secret is only returned by
 * the create call and can never be retrieved again, so the dialog leads with
 * that warning and offers a copy affordance. Closing discards the value.
 */
export function TokenCreatedDialog({ token, onClose }: TokenCreatedDialogProps) {
  const intl = useIntl();
  const isOpen = token !== null;

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="gap-6 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-xl leading-snug">
            {intl.formatMessage({ id: "tokens.created.title" })}
          </DialogTitle>
        </DialogHeader>
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-medium text-foreground">
            {intl.formatMessage({ id: "tokens.created.label" })}
          </p>
          <div className="flex w-full items-center gap-2 rounded-lg border border-input px-4 py-3">
            <span className="min-w-0 flex-1 truncate font-mono text-sm">{token ?? ""}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="size-5 shrink-0 text-muted-foreground"
              aria-label={intl.formatMessage(
                { id: "common.copyValue" },
                { label: intl.formatMessage({ id: "tokens.created.label" }) },
              )}
              onClick={() => copyToClipboard(token ?? "")}
            >
              <Copy className="size-3.5" />
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{intl.formatMessage({ id: "tokens.created.close" })}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
