/**
 * Status-headline rules seam (#5847, §9).
 *
 * The headline is resolved through this mapping, never a literal string in the
 * component. Rules are undefined for now; this ships the single default rule.
 * Additional conditions (major error, warnings, ...) are added here and return
 * a different message id + severity, so `StatusHeadline` never changes shape.
 */

import type { Severity } from "./homeStates";

/** System condition fed to the rules mapping. Extend as rules are defined (§9). */
export interface HeadlineCondition {
  errorCount?: number;
  warningCount?: number;
}

export interface ResolvedHeadline {
  /** i18n message id for the headline text. */
  messageId: string;
  severity: Severity;
}

export function resolveHeadline(_condition: HeadlineCondition = {}): ResolvedHeadline {
  // §9: real rules (condition -> message/severity) are deferred. Default only.
  return { messageId: "dashboard.home.headline.default", severity: "success" };
}
