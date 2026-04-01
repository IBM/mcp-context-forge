import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  root: 'client',
  base: '/app/',
  plugins: [tailwindcss(), react()],
  build: {
    outDir: '../mcpgateway/static/app',
    emptyOutDir: true,
  },
});
