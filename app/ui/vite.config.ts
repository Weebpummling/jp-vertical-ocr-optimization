import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The UI talks to the FastAPI core (app/api.py) at /api. Proxying in dev keeps
// the browser same-origin, so there is no CORS configuration to get wrong and
// a production deployment can serve both from one host unchanged.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
