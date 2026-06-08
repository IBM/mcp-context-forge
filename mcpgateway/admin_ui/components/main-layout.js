export function mainLayout() {
  return {
    sidebarOpen: true,
    sidebarCollapsed: false,
    isDesktop: window.innerWidth >= 1024,
    init: function () {
      const self = this;
      window.addEventListener('resize', function () {
        self.isDesktop = window.innerWidth >= 1024;
        if (window.innerWidth >= 1024) self.sidebarOpen = true;
      });
    },
  };
}
