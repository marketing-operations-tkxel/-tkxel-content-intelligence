import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only: proxy API calls to the deployed backend so `npm run dev` works with
// live data out of the box. Production builds ignore this (they serve the static
// dist via `serve` and read the API URL from .env.production).
const API_PROXY = process.env.VITE_DEV_API || "https://tkxel-api-production.up.railway.app";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_PROXY, changeOrigin: true },
      "/health": { target: API_PROXY, changeOrigin: true },
    },
  },
});
