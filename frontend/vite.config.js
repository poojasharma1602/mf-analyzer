import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser only ever talks to the local FastAPI backend. In dev, /api is proxied to it,
// so no browser security flags are needed. (The backend also sends CORS headers for the
// Vite origin in case you point VITE_API_BASE at http://127.0.0.1:8000 directly.)
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
})
