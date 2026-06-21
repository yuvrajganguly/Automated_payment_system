import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Dev server proxies /api/* to the FastAPI backend so the SPA and the API
// can share an origin during development and JWT works without CORS hassle.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
        },
    },
});
