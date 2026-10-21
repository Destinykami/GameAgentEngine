// 下载原神官方角色头像到 public/assets/portraits-src/ (仅个人本地学习用)。
// 素材 © HoYoverse/miHoYo, 不随仓库分发; 该目录已在 .gitignore 中。
// 用法: node tools/fetch_official_portraits.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, "..", "public", "assets", "portraits-src");
const BASE = "https://enka.network/ui";
// 世界角色 → Genshin 头像资源名 (Enka.Network UI 资源)
const MAP = {
  旅行者: "PlayerBoy",
  桃音: "Kokomi",
  刚郎: "Itto",
  小梅: "Sayu",
  执行官: "Wanderer",
  雷电将军: "Shougun",
};

mkdirSync(OUT, { recursive: true });
let ok = 0;
for (const [name, file] of Object.entries(MAP)) {
  const url = `${BASE}/UI_AvatarIcon_${file}.png`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    writeFileSync(resolve(OUT, `${file}.png`), buf);
    console.log(`✓ ${name} ← ${file}.png`);
    ok++;
  } catch (e) {
    console.warn(`✗ ${name} (${file}): ${e.message}`);
  }
}
console.log(`\n${ok}/${Object.keys(MAP).length} 张官方原图已下载到 ${OUT}`);
console.log("下一步: python3 tools/pixelate_portraits.py  # 生成 64px 像素风头像");
console.log("提醒: 仅限个人学习/本地演示, 不要随项目发布或再分发。");
