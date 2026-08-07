/**
 * V2 Home state model (#5532).
 *
 * The home is an adaptive, data-driven interface: one main content view is
 * visible at a time, chosen by the active view state, alongside a status
 * summary and a right-hand mini-card navigation column. States are declared
 * here as configuration, NOT as hardcoded conditionals in the page, so that
 * error/warning states and real REST/gRPC content can be added later as a data
 * change rather than a structural one.
 *
 * The active view is persisted in the URL as `?view=<id>`; the `default` state
 * omits the param. See `readActiveView()`.
 */

import { Activity, Code, List, Unplug } from "lucide-react";
import type { ComponentType } from "react";

import { AgentIcon } from "@/components/icons/AgentIcon";
import { MCPIcon } from "@/components/icons/MCPIcon";

// ---------------------------------------------------------------------------
// View ids
// ---------------------------------------------------------------------------

/** All home view states. `default` is the resting state (no `?view=`). */
export const HOME_VIEW_IDS = [
  "default",
  "activity",
  "mcp",
  "a2a",
  "rest",
  "grpc",
  "system",
] as const;

export type HomeViewId = (typeof HOME_VIEW_IDS)[number];

/**
 * The six mini cards, in their fixed display order. In any non-default state the
 * card matching the active view is hidden, so five of six are shown. The right
 * column is not rendered at all in the `default` state. (Fixed order, never
 * cycled: matches the Figma right-column ordering across states.)
 */
export const MINI_CARD_ORDER = ["system", "activity", "mcp", "a2a", "rest", "grpc"] as const;

export type MiniCardId = (typeof MINI_CARD_ORDER)[number];

// ---------------------------------------------------------------------------
// Severity (status summary) — extensible without restructuring (§ error/warning)
// ---------------------------------------------------------------------------

export type Severity = "info" | "success" | "warning" | "error";

// ---------------------------------------------------------------------------
// Mini card metadata
// ---------------------------------------------------------------------------

export interface MiniCardMeta {
  id: MiniCardId;
  /** i18n message id for the card label. */
  labelId: string;
  /** The view this card navigates to (same as `id`). */
  view: HomeViewId;
  icon: ComponentType<{ className?: string }>;
}

export const MINI_CARDS: Record<MiniCardId, MiniCardMeta> = {
  system: { id: "system", labelId: "dashboard.home.card.system", view: "system", icon: Activity },
  activity: {
    id: "activity",
    labelId: "dashboard.home.card.activity",
    view: "activity",
    icon: List,
  },
  mcp: { id: "mcp", labelId: "dashboard.home.card.mcp", view: "mcp", icon: MCPIcon },
  a2a: { id: "a2a", labelId: "dashboard.home.card.a2a", view: "a2a", icon: AgentIcon },
  rest: { id: "rest", labelId: "dashboard.home.card.rest", view: "rest", icon: Code },
  grpc: { id: "grpc", labelId: "dashboard.home.card.grpc", view: "grpc", icon: Unplug },
};

/**
 * Icon for a view's title row and mini card. Single source of truth (MINI_CARDS)
 * so the title icon and the nav icon can never drift. The `default` (resting)
 * state has no title, so no icon.
 */
export function getViewIcon(view: HomeViewId): ComponentType<{ className?: string }> | undefined {
  return view === "default" ? undefined : MINI_CARDS[view].icon;
}

// ---------------------------------------------------------------------------
// Per-state configuration
// ---------------------------------------------------------------------------

export interface HomeStateConfig {
  id: HomeViewId;
  /** i18n message id for the main-content title (non-default states). */
  titleId?: string;
  /** Permission required to view the main content; undefined = no gate. */
  requiredPermission?: string;
}

export const HOME_STATES: Record<HomeViewId, HomeStateConfig> = {
  default: { id: "default" },
  activity: {
    id: "activity",
    titleId: "dashboard.home.card.activity",
    requiredPermission: "audit:read",
  },
  mcp: {
    id: "mcp",
    titleId: "dashboard.home.card.mcp",
    // No gate: the card self-gates. Its source (GET /gateways) is RBAC-scoped
    // server-side, so a caller without gateways.read gets a 403 the card
    // surfaces as PermissionDenied, and a scoped caller sees only their servers.
  },
  a2a: { id: "a2a", titleId: "dashboard.home.card.a2a" },
  rest: { id: "rest", titleId: "dashboard.home.card.rest" },
  grpc: { id: "grpc", titleId: "dashboard.home.card.grpc" },
  system: {
    id: "system",
    titleId: "dashboard.home.card.system",
    requiredPermission: "metrics:read",
  },
};

/**
 * The right-column mini cards for a given active view: the fixed order minus the
 * active card. Empty for the `default` state (right column is not rendered).
 */
export function getRightColumnCards(active: HomeViewId): MiniCardId[] {
  if (active === "default") return [];
  return MINI_CARD_ORDER.filter((id) => id !== active);
}

// ---------------------------------------------------------------------------
// URL <-> state
// ---------------------------------------------------------------------------

function isHomeViewId(value: string): value is HomeViewId {
  return (HOME_VIEW_IDS as readonly string[]).includes(value);
}

/**
 * Resolve the active view from a router path (which includes the query string,
 * e.g. `/app/?view=mcp`). Unknown or absent `?view=` resolves to `default`.
 */
export function readActiveView(path: string): HomeViewId {
  const queryString = path.split("?")[1] ?? "";
  const view = new URLSearchParams(queryString).get("view");
  if (view && isHomeViewId(view) && view !== "default") return view;
  return "default";
}

/** The `/app` destination for a given view. `default` drops the `?view=` param. */
export function viewHref(view: HomeViewId): string {
  return view === "default" ? "/app/" : `/app/?view=${view}`;
}
