import { defineConfig } from 'vite';
import path from 'path';

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
    // Use standard build mode instead of lib mode for direct script inclusion
    rollupOptions: {
      input: path.resolve(__dirname, 'mcpgateway/static/js/admin.js'),
      output: {
        entryFileNames: 'bundle.js',
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
});