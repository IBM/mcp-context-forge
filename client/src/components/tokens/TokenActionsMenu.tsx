import { MoreVertical } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { TokenResponse } from "@/types/token";

interface TokenActionsMenuProps {
  token: TokenResponse;
  onDelete: (token: TokenResponse) => void;
}

/**
 * Per-row overflow menu for a token. Phase 1 exposes revoke (delete) only; edit
 * lands in a later phase, so it is intentionally absent rather than a dead item.
 */
export function TokenActionsMenu({ token, onDelete }: TokenActionsMenuProps) {
  const intl = useIntl();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          aria-label={intl.formatMessage(
            { id: "tokens.table.actions.label" },
            { name: token.name },
          )}
          aria-haspopup="menu"
        >
          <MoreVertical className="h-4 w-4" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48" role="menu">
        <DropdownMenuItem onClick={() => onDelete(token)} role="menuitem">
          {intl.formatMessage({ id: "tokens.table.actions.delete" })}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
