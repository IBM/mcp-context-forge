import { defineConfig } from 'vite';
import path from 'path';
import fs from 'fs';

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
        }
      }
    },
  };
}

export default defineConfig({
  build: {
    minify: 'terser',
    terserOptions: {
      compress: false,       // disable compress transforms
      mangle: false,         // disable all renaming
      format: {
        beautify: false,     // remove whitespace and newlines
        comments: false      // strip comments
      }
    },
    // Generate manifest for Python to read the hashed filename
    manifest: true,
    // Use standard build mode instead of lib mode for direct script inclusion
    rollupOptions: {
      input: path.resolve(__dirname, 'mcpgateway/static/js/index.js'),
      output: {
        // Add content hash to filename for cache busting
        entryFileNames: 'bundle-[hash].js',
        format: 'iife', // IIFE format for direct script inclusion
        // Externalize dependencies that are loaded separately
        globals: {
          marked: 'marked',
          DOMPurify: 'DOMPurify',
          htmx: 'htmx',
          Alpine: 'Alpine',
          Chart: 'Chart',
          CodeMirror: 'CodeMirror',
        },
      },
      external: [
        'marked',
        'DOMPurify',
        'htmx',
        'Alpine',
        'Chart',
        'CodeMirror',
      ],
    },
    outDir: 'mcpgateway/static',
    emptyOutDir: false, // Don't clean the output directory
  },
  plugins: [cleanOldBundles()],
});