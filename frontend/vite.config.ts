import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // In development the React app runs on :5173. Forward same-origin API
  // requests to the locally published FastAPI port rather than returning
  // Vite's index.html (which looks like invalid JSON to the dashboard).
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
