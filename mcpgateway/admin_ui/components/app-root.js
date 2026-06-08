export function appRoot() {
  return {
    darkMode: false,
    init: function () {
      try {
        this.darkMode = JSON.parse(localStorage.getItem('darkMode') || 'false');
      } catch (e) {
        if (window.Admin) window.Admin.logRestrictedContext(e);
      }
      const self = this;
      this.$watch('darkMode', function (val) {
        try {
          localStorage.setItem('darkMode', String(val));
        } catch (e) {
          if (window.Admin) window.Admin.logRestrictedContext(e);
        }
      });
    },
  };
}
