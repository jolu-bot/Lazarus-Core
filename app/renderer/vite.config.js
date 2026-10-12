import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// CSP stricte uniquement en production (le serveur de dev de Vite injecte un script inline pour le HMR)
const strictCsp = {
  name: 'strict-csp',
  apply: 'build',
  transformIndexHtml: (html) => html.replace("script-src 'self' 'unsafe-inline'", "script-src 'self'"),
};

export default defineConfig({
  plugins: [react(), strictCsp],
  base: './',
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  build: {
    outDir:      'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id){
          if(id.includes('node_modules/framer-motion')) return 'motion';
          if(id.includes('node_modules/react-dom')||id.includes('node_modules/react/')) return 'vendor';
        },
      },
    },
  },
  server: { port: 3000 },
});