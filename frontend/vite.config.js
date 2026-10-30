import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// SECURITY WARNING: Never expose API keys via import.meta.env.VITE_*
// API calls should be made from a backend server, not the frontend
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Pages are lazy chunks (src/lib/lazyPage.js). Without this, every lucide icon shared by
        // two pages became its own tiny file, fetched in a chain after the page chunk.
        manualChunks(id) {
          if (id.includes('node_modules/lucide-react')) return 'icons';
          // React + router change only on upgrades, so this chunk stays cached across deploys.
          // Page-only libraries (e.g. papaparse) stay with the page that uses them.
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|cookie|set-cookie-parser)\//.test(id)) return 'vendor';
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
