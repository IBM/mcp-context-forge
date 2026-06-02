import Alpine from '@alpinejs/csp';
import { buildTableUrl, syncCheckboxFromUrl } from './utils.js';

Alpine.data('appRoot', function () {
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
});

Alpine.data('mainLayout', function () {
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
});

Alpine.data('teamSelector', function () {
  return {
    open: false,
    selectedTeam: '',
    selectedTeamName: 'All Teams',
    init: function () {
      const urlParams = new URLSearchParams(window.location.search);
      const requestedTeamId = urlParams.get('team_id') || '';
      this.selectedTeam = '';
      this.selectedTeamName = 'All Teams';
      if (requestedTeamId) {
        const teams =
          Array.isArray(window.USER_TEAMS_DATA) && window.USER_TEAMS_DATA.length > 0
            ? window.USER_TEAMS_DATA
            : Array.isArray(window.USER_TEAMS)
              ? window.USER_TEAMS
              : [];
        const team = teams.find(function (t) {
          return t.id === requestedTeamId;
        });
        if (team) {
          this.selectedTeam = requestedTeamId;
          this.selectedTeamName = (team.is_personal ? '👤 ' : '🏢 ') + team.name;
        } else if (teams.length > 0) {
          const cleanUrl = new URL(window.location.href);
          cleanUrl.searchParams.delete('team_id');
          if (window.Admin) window.Admin.safeReplaceState({}, '', cleanUrl);
        }
      }
    },
    toggleOpen: function () {
      this.open = !this.open;
      this.loadTeams();
    },
    selectAllTeams: function () {
      this.selectedTeam = '';
      this.selectedTeamName = 'All Teams';
      this.open = false;
      this.updateTeamContext('');
    },
    loadTeams: function () {
      if (this.open && window.Admin) window.Admin.loadTeamSelectorDropdown();
    },
    updateTeamContext: function (teamId) {
      if (typeof window.updateTeamContext === 'function') window.updateTeamContext(teamId);
    },
  };
});

Alpine.magic('syncCheckbox', function () {
  return syncCheckboxFromUrl;
});

Alpine.magic('tableHxGet', function (el) {
  return function (tableName, baseUrl, checkboxId, defaultChecked, extraParams) {
    const checkbox = document.getElementById(checkboxId);
    const checked = checkbox !== null ? checkbox.checked : defaultChecked;
    const params = { include_inactive: String(checked) };
    if (extraParams) Object.assign(params, extraParams);
    el.setAttribute('hx-get', buildTableUrl(tableName, baseUrl, params));
  };
});

export default Alpine;
