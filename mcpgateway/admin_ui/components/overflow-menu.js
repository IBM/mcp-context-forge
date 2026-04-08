/**
 * Alpine component: overflowMenu
 *
 * Three-dot actions dropdown for table rows. Positions the menu with fixed
 * coordinates to escape overflow:hidden parent containers, and suppresses
 * scroll on the main container and the given table wrapper while open.
 *
 * Usage:
 *   <div x-data="Admin.overflowMenu('tools-table-wrapper')" @click.away="menuOpen = false" @keydown.escape="menuOpen = false; $refs.trigger.focus()">
 */

export function overflowMenu(wrapperId = null) {
  return {
    menuOpen: false,
    menuTop: 0,
    menuLeft: 0,
    init() {
      this.$watch("menuOpen", (value) => {
        const main = document.querySelector("main[data-scroll-container]");
        if (main) main.style.overflow = value ? "hidden" : "";
        if (wrapperId) {
          const wrapper = document.getElementById(wrapperId);
          if (wrapper) wrapper.style.overflow = value ? "hidden" : "";
        }
      });
    },
    openMenu() {
      const rect = this.$refs.trigger.getBoundingClientRect();
      this.menuTop = rect.bottom + 4;
      this.menuLeft = rect.left;
      this.menuOpen = true;

      // Adjust position after menu renders to prevent viewport overflow
      this.$nextTick(() => {
        const menu = this.$refs.menu;
        if (menu) {
          const menuRect = menu.getBoundingClientRect();
          const viewportWidth = window.innerWidth;
          const viewportHeight = window.innerHeight;
          const padding = 8; // Safety padding from viewport edge

          // Adjust horizontal position if overflowing right edge
          if (menuRect.right > viewportWidth - padding) {
            this.menuLeft = Math.max(padding, viewportWidth - menuRect.width - padding);
          }

          // Adjust vertical position if overflowing bottom edge
          if (menuRect.bottom > viewportHeight - padding) {
            // Try flipping upward
            const upwardTop = rect.top - menuRect.height - 4;
            if (upwardTop >= padding) {
              this.menuTop = upwardTop;
            } else {
              // Clamp to visible area
              this.menuTop = Math.max(padding, viewportHeight - menuRect.height - padding);
            }
          }

          menu.querySelector("[role=menuitem]")?.focus();
        }
      });
    },
    navigate(dir) {
      const items = [...this.$refs.menu.querySelectorAll("[role=menuitem]")];
      const idx = items.indexOf(document.activeElement);
      items[(idx + dir + items.length) % items.length]?.focus();
    },
  };
}
