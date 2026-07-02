/**
 * Lazy loader for admin UI feature modules
 * Loads feature chunks on-demand when tabs are clicked
 */

// Map of feature names to their dynamic import functions
const featureModules = {
  tools: () => import('./tools.js'),
  servers: () => import('./servers.js'),
  gateways: () => import('./gateways.js'),
  teams: () => import('./teams.js'),
  logging: () => import('./logging.js'),
  metrics: () => import('./metrics.js'),
  llmChat: () => import('./llmChat.js'),
  llmModels: () => import('./llmModels.js'),
  plugins: () => import('./plugins.js')
};

// Track loaded modules to avoid duplicate loads
const loadedModules = new Set();

// Track in-flight loads to avoid race conditions
const loadingPromises = new Map();

/**
 * Load a feature module on-demand
 * @param {string} featureName - Name of the feature to load
 * @returns {Promise<void>}
 */
export async function loadFeature(featureName) {
  // Already loaded - skip
  if (loadedModules.has(featureName)) {
    console.log(`✓ Feature already loaded: ${featureName}`);
    return;
  }

  // Currently loading - return existing promise
  if (loadingPromises.has(featureName)) {
    console.log(`⏳ Feature already loading: ${featureName}`);
    return loadingPromises.get(featureName);
  }

  const loader = featureModules[featureName];
  if (!loader) {
    console.warn(`⚠️ Unknown feature: ${featureName}`);
    return;
  }

  console.log(`📦 Loading feature: ${featureName}...`);

  // Create loading promise
  const loadPromise = (async () => {
    try {
      const module = await loader();

      // Merge module exports into window.Admin
      if (module && typeof module === 'object') {
        Object.assign(window.Admin, module);
      }

      loadedModules.add(featureName);
      console.log(`✅ Loaded feature: ${featureName}`);
    } catch (error) {
      console.error(`❌ Failed to load feature ${featureName}:`, error);
      throw error;
    } finally {
      loadingPromises.delete(featureName);
    }
  })();

  loadingPromises.set(featureName, loadPromise);
  return loadPromise;
}

/**
 * Load multiple features in parallel
 * @param {string[]} featureNames - Array of feature names to load
 * @returns {Promise<void>}
 */
export async function loadFeatures(featureNames) {
  const promises = featureNames.map(name => loadFeature(name));
  await Promise.all(promises);
}

/**
 * Check if a feature is loaded
 * @param {string} featureName - Name of the feature
 * @returns {boolean}
 */
export function isFeatureLoaded(featureName) {
  return loadedModules.has(featureName);
}

/**
 * Check if a feature is currently loading
 * @param {string} featureName - Name of the feature
 * @returns {boolean}
 */
export function isFeatureLoading(featureName) {
  return loadingPromises.has(featureName);
}

/**
 * Get list of loaded features
 * @returns {string[]}
 */
export function getLoadedFeatures() {
  return Array.from(loadedModules);
}

// Expose to window.Admin for global access
if (typeof window !== 'undefined') {
  window.Admin = window.Admin || {};
  window.Admin.loadFeature = loadFeature;
  window.Admin.loadFeatures = loadFeatures;
  window.Admin.isFeatureLoaded = isFeatureLoaded;
  window.Admin.isFeatureLoading = isFeatureLoading;
  window.Admin.getLoadedFeatures = getLoadedFeatures;
}
