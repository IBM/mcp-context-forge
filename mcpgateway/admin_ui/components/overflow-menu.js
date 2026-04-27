/**
 * Alpine component: overflowMenu
 *
 * Three-dot actions dropdown for table rows. Positions the menu with fixed
 * coordinates to escape overflow:hidden parent containers, and suppresses
 * scroll on the main container and the given table wrapper while open.
 *
 * Required markup contract:
 *   - The action button must have `x-ref="trigger"`.
 *   - The dropdown container must have `x-ref="menu"` and `role="menu"`.
 *   - Each action inside the menu must carry `role="menuitem"`.
 *
 * Usage:
 *   <div x-data="Admin.overflowMenu('tools-table-wrapper')"
 *        @click.away="menuOpen = false"
 *        @keydown.escape="menuOpen = false; $refs.trigger.focus()">
 *     <button x-ref="trigger" @click="menuOpen ? (menuOpen = false) : openMenu()" ...>…</button>
 *     <div x-ref="menu" role="menu" ...>
 *       <button role="menuitem" ...>Edit</button>
 *     </div>
 *   </div>
 *
 * @param {string|null} wrapperId - Optional id of a scroll-constrained wrapper
 *   (e.g. `tools-table-wrapper`) whose `overflow` should also be pinned while
 *   the menu is open so the fixed-positioned dropdown isn't clipped.
 */

// Module-level single-open coordinator: a newer instance opens → any currently
// open instance closes itself. Avoids per-row window listeners.
let currentlyOpen = null;

export function _resetCurrentlyOpenForTests() {
  currentlyOpen = null;
}

export function overflowMenu(wrapperId = null) {
  return {
    menuOpen: false,
    menuTop: 0,
    menuLeft: 0,
    _applyScrollLock(locked) {
      const main = document.querySelector("main[data-scroll-container]");
      if (main) main.style.overflow = locked ? "hidden" : "";
      if (wrapperId) {
        const wrapper = document.getElementById(wrapperId);
        if (wrapper) wrapper.style.overflow = locked ? "hidden" : "";
      }
    },
    init() {
      this.$watch("menuOpen", (value) => {
        this._applyScrollLock(value);
        if (!value && currentlyOpen === this) {
          currentlyOpen = null;
        }
      });
    },
    destroy() {
      // Clear scroll-lock if the component is torn down mid-open (HTMX swap,
      // row removal) so <main> doesn't stay frozen at overflow:hidden.
      if (this.menuOpen) this._applyScrollLock(false);
      if (currentlyOpen === this) currentlyOpen = null;
    },
    openMenu() {
      const trigger = this.$refs.trigger;
      if (!trigger) {
        console.warn('overflowMenu: missing x-ref="trigger" on the action button');
        return;
      }

      // Close any peer that's currently open before opening this one.
      if (currentlyOpen && currentlyOpen !== this) {
        currentlyOpen.menuOpen = false;
      }
      currentlyOpen = this;

      const rect = trigger.getBoundingClientRect();
      this.menuTop = rect.bottom + 4;
      this.menuLeft = rect.left;
      this.menuOpen = true;

      // Adjust position after menu renders to prevent viewport overflow.
      this.$nextTick(() => {
        const menu = this.$refs.menu;
        if (!menu) {
          console.warn('overflowMenu: missing x-ref="menu" on the dropdown container');
          return;
        }

        // Reset any constraints from a previous open so measurement is honest.
        menu.style.maxHeight = "";
        menu.style.overflowY = "";

        const menuRect = menu.getBoundingClientRect();

        // Skip clamping if the menu is not laid out yet (e.g. hidden ancestor);
        // a zero-sized rect produces nonsense math and a visible jump.
        if (menuRect.width === 0 || menuRect.height === 0) {
          menu.querySelector("[role=menuitem]")?.focus();
          return;
        }

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const padding = 8; // Minimum gap in px between menu and viewport edge before clamping/flipping

        // Adjust horizontal position if overflowing right edge
        if (menuRect.right > viewportWidth - padding) {
          this.menuLeft = Math.max(padding, viewportWidth - menuRect.width - padding);
        }

        // Adjust vertical position if overflowing bottom edge:
        // flip above trigger if it fits, otherwise clamp or cap with internal scroll.
        if (menuRect.bottom > viewportHeight - padding) {
          const availableHeight = viewportHeight - padding * 2;
          const upwardTop = rect.top - menuRect.height - 4;

          if (menuRect.height > availableHeight) {
            // Menu is taller than the viewport — since scroll is locked on
            // the main container, cap the menu itself and let it scroll
            // internally so the lower items remain reachable.
            this.menuTop = padding;
            menu.style.maxHeight = `${availableHeight}px`;
            menu.style.overflowY = "auto";
          } else if (upwardTop >= padding) {
            this.menuTop = upwardTop;
          } else {
            this.menuTop = Math.max(padding, viewportHeight - menuRect.height - padding);
          }
        }

        menu.querySelector("[role=menuitem]")?.focus();
      });
    },
    navigate(dir) {
      const menu = this.$refs.menu;
      if (!menu) {
        console.warn('overflowMenu: missing x-ref="menu" on the dropdown container');
        return;
      }
      const items = [...menu.querySelectorAll("[role=menuitem]")];
      if (items.length === 0) return;
      const idx = items.indexOf(document.activeElement);
      items[(idx + dir + items.length) % items.length]?.focus();
    },
  };
}
