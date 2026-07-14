import { defineConfig } from 'vite';
import path from 'path';
import fs from 'fs';
import viteCompression from 'vite-plugin-compression';

// Plugin to clean up old bundle files before building
function cleanOldBundles() {
  return {
    name: 'clean-old-bundles',
    buildStart() {
      const outDir = path.resolve(__dirname, 'mcpgateway/static');
      if (fs.existsSync(outDir)) {
        const files = fs.readdirSync(outDir);
        for (const file of files) {
          // Remove old bundle files (bundle-*.js pattern)
          if (file.startsWith('bundle-') && file.endsWith('.js')) {
            fs.unlinkSync(path.join(outDir, file));
            console.log(`Removed old bundle: ${file}`);
          }
          // Remove old chunk files
          if (file.startsWith('chunk-') && file.endsWith('.js')) {
            fs.unlinkSync(path.join(outDir, file));
            console.log(`Removed old chunk: ${file}`);
          }
        }
      }
    },
  };
}

export default defineConfig({
  build: {
    minify: 'terser',
    // lightningcss ships no linux-ppc64(le)/s390x native binary, so fall back
    // to esbuild for CSS minification on those arches only; others keep lightningcss.
    cssMinify: ['ppc64', 's390x'].includes(process.arch) ? 'esbuild' : 'lightningcss',
    terserOptions: {
      compress: true,        // enable compress transforms
      mangle: {
        reserved: ['Admin'], // preserve 'Admin' identifier
        properties: false    // disable property mangling entirely
      },
      format: {
        beautify: false,     // remove whitespace and newlines
        comments: false      // strip comments
      }
    },
    // Generate manifest for Python to read the hashed filename
    manifest: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'mcpgateway/admin_ui/index.js'),
      output: {
        // Add content hash to filename for cache busting
        entryFileNames: 'bundle-[hash].js',
        chunkFileNames: 'chunk-[name]-[hash].js',
        format: 'es', // ES modules format for code splitting
        // Manual chunks for code splitting (function-based for Vite 8/rolldown)
        manualChunks(id) {
          // Vendor chunks - heavy libraries
          if (id.includes('node_modules/chart.js')) {
            return 'vendor-charts';
          }
          if (id.includes('node_modules/codemirror') ||
              id.includes('node_modules/@codemirror')) {
            return 'vendor-editor';
          }

          // Feature chunks - genuinely lazy loaded on tab click (see
          // lazy-loader.js featureModules). Each must stay in its own chunk,
          // never grouped with a statically-imported module, or Rollup will
          // pull it into the eager load graph too.
          if (id.includes('mcpgateway/admin_ui/metrics.js')) {
            return 'metrics';
          }
          if (id.includes('mcpgateway/admin_ui/llmChat.js')) {
            return 'llm-chat';
          }
          // tools.js, servers.js, gateways.js, teams.js, logging.js,
          // llmModels.js, and plugins.js are statically imported by
          // admin.js (they cross-import each other and several other
          // eagerly-loaded modules), so they are left to Rollup's default
          // chunking rather than split out here.
        }
      },
    },
    outDir: 'mcpgateway/static',
    emptyOutDir: false, // Don't clean the output directory
  },
  plugins: [
    cleanOldBundles(),
    viteCompression({
      algorithm: 'gzip',
      ext: '.gz',
      threshold: 10240, // Only compress files larger than 10KB
      deleteOriginFile: false, // Keep original files
    }),
  ],
});
