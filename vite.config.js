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

          // Feature chunks - lazy loaded on tab click
          if (id.includes('mcpgateway/admin_ui/tools.js')) {
            return 'tools';
          }
          if (id.includes('mcpgateway/admin_ui/servers.js')) {
            return 'servers';
          }
          if (id.includes('mcpgateway/admin_ui/gateways.js')) {
            return 'gateways';
          }
          if (id.includes('mcpgateway/admin_ui/teams.js')) {
            return 'teams';
          }
          if (id.includes('mcpgateway/admin_ui/logging.js') ||
              id.includes('mcpgateway/admin_ui/metrics.js')) {
            return 'monitoring';
          }
          if (id.includes('mcpgateway/admin_ui/llmChat.js') ||
              id.includes('mcpgateway/admin_ui/llmModels.js')) {
            return 'llm';
          }
          if (id.includes('mcpgateway/admin_ui/plugins.js')) {
            return 'plugins';
          }
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
