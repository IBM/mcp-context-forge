/**
 * Alpine component for the Maintenance Panel
 */
export const maintenancePanel = function (config) {
  return {
    cleanupLoading: false,
    rollupLoading: false,
    cleanupResult: null,
    rollupResult: null,
    showCleanupConfirm: false,
    showRollupConfirm: false,
    retentionDays: config?.retentionDays ?? 7,
    deleteAll: false,
    rollupHoursBack: 1,
    includeRollupData: true,
    rootPath: config?.rootPath || '',

    get cleanupDuration() {
      return this.cleanupResult?.duration_seconds?.toFixed(2) || '0.00';
    },

    get rollupDuration() {
      return this.rollupResult?.duration_seconds?.toFixed(2) || '0.00';
    },

    _getToken() {
      return document.cookie.match(/jwt_token=([^;]+)/)?.[1] || '';
    },

    runCleanup() {
      this.showCleanupConfirm = false;
      this.cleanupLoading = true;
      this.cleanupResult = null;

      fetch(`${this.rootPath}/api/metrics/cleanup`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + this._getToken()
        },
        body: JSON.stringify({
          retention_days: this.deleteAll ? 0 : this.retentionDays,
          include_rollup: this.includeRollupData
        })
      })
      .then(r => r.json())
      .then(data => {
        this.cleanupResult = data;
        this.cleanupLoading = false;
      })
      .catch(e => {
        this.cleanupResult = {error: e.message};
        this.cleanupLoading = false;
      });
    },

    runRollup() {
      this.showRollupConfirm = false;
      this.rollupLoading = true;
      this.rollupResult = null;

      fetch(`${this.rootPath}/api/metrics/rollup`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + this._getToken()
        },
        body: JSON.stringify({hours_back: parseInt(this.rollupHoursBack)})
      })
      .then(r => r.json())
      .then(data => {
        this.rollupResult = data;
        this.rollupLoading = false;
      })
      .catch(e => {
        this.rollupResult = {error: e.message};
        this.rollupLoading = false;
      });
    }
  };
};
