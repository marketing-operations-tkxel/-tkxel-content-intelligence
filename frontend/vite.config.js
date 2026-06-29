import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const PROXY = "https://tkxel-api-production.up.railway.app";
export default defineConfig({ plugins: [react()], server: { port: 5173, proxy: { "/api": { target: PROXY, changeOrigin: true }, "/health": { target: PROXY, changeOrigin: true } } } });
