// 角色头像 (可选, 本地原神官方图标)。
// 素材 © HoYoverse/miHoYo, 只放在 public/assets/portraits/ 本地个人学习用, 已被 .gitignore 排除;
// 不随仓库分发。目录缺失/文件缺失时 UI 自动隐藏头像, 不报错。
// 下载: node tools/fetch_official_portraits.mjs
export const PORTRAIT_FILES: Record<string, string> = {
  旅行者: "PlayerBoy",
  桃音: "Kokomi",
  刚郎: "Itto",
  小梅: "Sayu",
  执行官: "Wanderer",
  雷电将军: "Shougun",
};

export function portraitTextureKey(name: string): string {
  return `portrait_${name}`;
}

export function portraitUrl(file: string): string {
  return `assets/portraits/${file}.png`;
}
