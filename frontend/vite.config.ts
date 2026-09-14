import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend port for local development. FastAPI serves the API (and, in production,
// the built frontend) on this port. Keep in sync with deploy/apps.json.
const BACKEND_PORT = 9001

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Same-origin API calls (see src/api.ts) are proxied to the backend in dev.
      '/calculate': `http://localhost:${BACKEND_PORT}`,
      '/profiles': `http://localhost:${BACKEND_PORT}`,
    },
  },
})
