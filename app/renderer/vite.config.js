import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
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