import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "HUMSAFAR_");
  const proxy = {
    "/api": {
      target:
        process.env.HUMSAFAR_API_TARGET ||
        env.HUMSAFAR_API_TARGET ||
        "http://127.0.0.1:8000",
      changeOrigin: false,
      rewrite: (path) => path.replace(/^\/api/, ""),
    },
  };
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, proxy },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.js"],
      include: ["src/**/*.test.{js,jsx}"],
    },
  };
});
