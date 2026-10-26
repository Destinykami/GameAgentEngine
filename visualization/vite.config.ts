import { defineConfig } from "vite";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

// 本地原神像素头像/全身 Sprite 是否齐全 (各 6 张)。只有齐全时才让前端加载, 避免 fresh clone 时 404。
// 图片目录在 .gitignore 中 (仅个人学习用); 新增后需重启 dev server。
const PORTRAIT_FILES = ["PlayerBoy", "Kokomi", "Itto", "Sayu", "Wanderer", "Shougun"];
const portraitsReady = PORTRAIT_FILES.every((f) =>
  existsSync(resolve(process.cwd(), "public", "assets", "portraits", `${f}.png`)),
);
const fullbodyReady = PORTRAIT_FILES.every((f) =>
  existsSync(resolve(process.cwd(), "public", "assets", "fullbody", `${f}.png`)),
);

// base: './' 让构建产物可用相对路径访问 (不依赖部署在域名根)。
export default defineConfig({
  base: "./",
  server: { port: 5173, open: false },
  build: {
    outDir: "dist",
    assetsDir: "assets",
    rollupOptions: {
      input: {
        main: resolve(process.cwd(), "index.html"),
        werewolf: resolve(process.cwd(), "werewolf.html"),
      },
    },
  },
  define: {
    __OFFICIAL_PORTRAITS__: JSON.stringify(portraitsReady),
    __OFFICIAL_FULLBODY__: JSON.stringify(fullbodyReady),
  },
});
