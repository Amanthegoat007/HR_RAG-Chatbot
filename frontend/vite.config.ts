import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 9173,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@/components": path.resolve(__dirname, "./src/components"),
      "@/pages": path.resolve(__dirname, "./src/pages"),
      "@/services": path.resolve(__dirname, "./src/services"),
      "@/store": path.resolve(__dirname, "./src/store"),
      "@/types": path.resolve(__dirname, "./src/types"),
      "@/utils": path.resolve(__dirname, "./src/utils"),
      "@/hooks": path.resolve(__dirname, "./src/hooks"),
      "@/layouts": path.resolve(__dirname, "./src/layouts"),
      "@/theme": path.resolve(__dirname, "./src/theme"),
      "@/config": path.resolve(__dirname, "./src/config"),
      "@/app": path.resolve(__dirname, "./src/app"),
      "@/app-providers": path.resolve(__dirname, "./src/app-providers"),
      "@/mocks": path.resolve(__dirname, "./src/mocks"),
    },
  },
});
