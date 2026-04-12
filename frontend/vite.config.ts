import { defineConfig } from 'vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import path from 'node:path';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';

export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],
  resolve: {
    alias: {
      '@': path.resolve(process.cwd(), 'src')
    }
  },
  server: {
    host: true, // expose on 0.0.0.0 (needed inside Docker)
    port: 5173,
    proxy: {
      '/api':       { target: BACKEND_URL, changeOrigin: true },
      '/socket.io': { target: BACKEND_URL, ws: true, changeOrigin: true }
    }
  }
});
