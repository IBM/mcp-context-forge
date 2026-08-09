import { createContext, useContext, useEffect } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";

interface SettingsTabsContextValue {
  /**
   * DOM node of the Settings tab-row toolbar slot, or `null` when a page is
   * rendered outside the Settings shell (e.g. in isolation in tests).
   */
  toolbar: HTMLElement | null;
  /** Hide or show the Settings tab strip (and its toolbar). */
  setTabsHidden: (hidden: boolean) => void;
}

const SettingsTabsContext = createContext<SettingsTabsContextValue>({
  toolbar: null,
  setTabsHidden: () => {},
});

export const SettingsTabsProvider = SettingsTabsContext.Provider;

/**
 * Renders its children into the Settings tab-row toolbar slot when available,
 * so a tab's actions (search, create, …) sit on the same line as the tab
 * triggers. When no slot is present it falls back to rendering inline, which
 * keeps the hosted page usable on its own.
 */
export function SettingsToolbar({ children }: { children: ReactNode }) {
  const { toolbar } = useContext(SettingsTabsContext);
  if (toolbar) return createPortal(children, toolbar);
  return <>{children}</>;
}

/**
 * Hides the Settings tab strip (the Users/Teams tabs and their toolbar) while
 * `hidden` is true — e.g. when a hosted page shows a full-page create or edit
 * form. No-ops when the page is rendered outside the Settings shell.
 */
export function useHideSettingsTabs(hidden: boolean) {
  const { setTabsHidden } = useContext(SettingsTabsContext);
  useEffect(() => {
    setTabsHidden(hidden);
    return () => setTabsHidden(false);
  }, [hidden, setTabsHidden]);
}
