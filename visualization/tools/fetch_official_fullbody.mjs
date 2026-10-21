// 下载原神官方全身立绘到 public/assets/fullbody-src/ (仅个人本地学习用)。
// 素材 © HoYoverse/miHoYo, 不随仓库分发; 该目录已在 .gitignore 中。
// 用法: node tools/fetch_official_fullbody.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, "..", "public", "assets", "fullbody-src");
const SOURCES = {
  // 旅行者用 Enka 的单人立绘 (Genshin API 的 traveler portrait 同时含空/荧两人)
  PlayerBoy: { url: "https://enka.network/ui/UI_Gacha_AvatarImg_PlayerBoy.png", ext: "png" },
  // 其余用 Genshin API 的透明角色立绘 (不含背景)
  Kokomi:   { url: "https://genshin.jmp.blue/characters/kokomi/portrait", ext: "webp" },
  Itto:     { url: "https://genshin.jmp.blue/characters/arataki-itto/portrait", ext: "webp" },
  Sayu:     { url: "https://genshin.jmp.blue/characters/sayu/portrait", ext: "webp" },
  Wanderer: { url: "https://genshin.jmp.blue/characters/wanderer/portrait", ext: "webp" },
  Shougun:  { url: "https://genshin.jmp.blue/characters/raiden/portrait", ext: "webp" },
};

mkdirSync(OUT, { recursive: true });
let ok = 0;
for (const [name, { url, ext }] of Object.entries(SOURCES)) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    writeFileSync(resolve(OUT, `${name}.${ext}`), buf);
    console.log(`✓ ${name}.${ext}`);
    ok++;
  } catch (e) {
    console.warn(`✗ ${name}: ${e.message}`);
  }
}
console.log(`\n${ok}/${Object.keys(SOURCES).length} 张立绘已下载到 ${OUT}`);
console.log("下一步: python3 tools/pixelate_fullbody.py  # 生成 48x64 的 10 帧像素表");
console.log("提醒: 仅限个人学习/本地演示, 不要随项目发布或再分发。");
