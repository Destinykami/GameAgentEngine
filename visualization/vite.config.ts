import { defineConfig } from "vite";

// base: './' 让构建产物可用相对路径访问 (不依赖部署在域名根)。
export default defineConfig({
  base: "./",
  server: { port: 5173, open: false },
  build: { outDir: "dist", assetsDir: "assets" },
});
