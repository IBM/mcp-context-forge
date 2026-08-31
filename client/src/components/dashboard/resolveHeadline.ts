/**
 * Status-headline rules seam (#5847, §9).
 *
 * The headline is resolved through this mapping, never a literal string in the
 * component. "Up and running" is the healthy resting state, not a hardcoded
 * default: it is what we show when `GET /version` reports the gateway reachable
 * and its dependencies healthy (#5842). A definitive negative health signal
 * (unreachable, or a degraded dependency) overrides it. While health is still
 * loading (both fields `undefined`) the headline stays optimistic so it never
 * flashes an error on first paint.
 *
 * Recent-activity error/warning escalation ("...with N errors") is added to the
 * rules here once the activity feed backend (#5944) lands, using the
 * `errorCount` / `warningCount` fields — without changing `StatusHeadline`'s
 * shape.
 */

import type { Severity } from "./homeStates";

/** System condition fed to the rules mapping. Extend as rules are defined (§9). */
export interface HeadlineCondition {
  /** `GET /version` responded — the gateway process is up. `undefined` while loading. */
  reachable?: boolean;
  /** DB reachable (and Redis when it is the cache backend). `undefined` while loading/unknown. */
  dependenciesHealthy?: boolean;
  /** Recent-activity error count. Stays `undefined` until the activity backend (#5944). */
  errorCount?: number;
  /** Recent-activity warning count. Stays `undefined` until the activity backend (#5944). */
  warningCount?: number;
}

export interface ResolvedHeadline {
  /** i18n message id for the headline text. */
  messageId: string;
  severity: Severity;
}

export function resolveHeadline(condition: HeadlineCondition = {}): ResolvedHeadline {
  const { reachable, dependenciesHealthy } = condition;

  // Definitive negative health signals override the healthy default. Loading
  // (`undefined`) stays optimistic so the headline never flashes an error.
  if (reachable === false) {
    return { messageId: "dashboard.home.headline.unreachable", severity: "error" };
  }
  if (dependenciesHealthy === false) {
    return { messageId: "dashboard.home.headline.degraded", severity: "warning" };
  }

  // §9: recent-activity error/warning escalation (errorCount/warningCount) is
  // added here once #5944 lands.

  // Healthy / resting state — also the loading and no-signal default.
  return { messageId: "dashboard.home.headline.default", severity: "success" };
}
