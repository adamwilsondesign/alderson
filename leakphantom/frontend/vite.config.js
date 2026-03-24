import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8666",
      "/ws": {
        target: "ws://127.0.0.1:8666",
        ws: true,
      },
    },
  },
  build: {
    outDir: "../dist",
  },
});
