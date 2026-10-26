import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'KoLife',
        short_name: 'KoLife',
        description: 'Life-admin assistant for foreigners in Korea and Malaysia',
        theme_color: '#0f172a',
        background_color: '#ffffff',
        display: 'standalone',
        icons: [{ src: 'favicon.svg', sizes: 'any', type: 'image/svg+xml' }],
      },
    }),
  ],
  // API routes live under /api in FastAPI itself; nginx and this proxy pass the path through unchanged.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
