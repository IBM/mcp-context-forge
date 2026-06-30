export function teamSelector() {
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
          // Cache is frozen at page load — verify with the server before
          // stripping a team_id that may be newer than the cache.
          const rootPath = window.ROOT_PATH || '';
          fetch(rootPath + '/admin/teams/ids', { credentials: 'same-origin' })
            .then((resp) => (resp.ok ? resp.json() : null))
            .then((data) => {
              const ids = (data && data.team_ids) || [];
              if (!ids.includes(requestedTeamId)) {
                const cleanUrl = new URL(window.location.href);
                cleanUrl.searchParams.delete('team_id');
                if (window.Admin) window.Admin.safeReplaceState({}, '', cleanUrl);
              }
            })
            .catch(() => { /* fail open: don't strip on network error */ });
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
}
