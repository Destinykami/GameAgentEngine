# 原神像素头像 / 全身 Sprite（本地可选）

界面支持：

- 状态面板 / 详情卡：64×64 像素化头像（32 色量化 + 1px 深色描边）。
- 世界内角色：40×56 像素化全身 Sprite，10 帧表（待机 2 + 走路 2 + 锤击/治疗/阅读各 2）。

官方原图、头像和 Sprite 都**不随仓库提交**，仅用于个人学习/本地演示；缺失时自动回退：头像隐藏、世界角色回到 16×16 原创像素。

## 版权

- 素材 © HoYoverse / miHoYo（Genshin Impact 角色图标与立绘；立绘来自 Genshin API 的透明 `portrait`，旅行者使用 Enka 单人立绘）。
- 以下目录均在 `.gitignore` 中，**不要提交、发布或再分发**：
  - `public/assets/portraits-src/`（官方头像原图）
  - `public/assets/portraits/`（像素头像）
  - `public/assets/fullbody-src/`（官方全身立绘）
  - `public/assets/fullbody/`（像素 Sprite 表）
- 发布项目时删除这些目录即可；代码会自动回退，不会 404。

## 生成步骤

```bash
cd visualization

# 1. 官方头像 + 像素化 (64x64)
node tools/fetch_official_portraits.mjs
python3 tools/pixelate_portraits.py --size 64 --colors 32

# 2. 官方全身立绘 + 像素化 (40x56, 10 帧表)
node tools/fetch_official_fullbody.mjs
python3 tools/pixelate_fullbody.py

# 3. 启动/构建 (Vite 构建期检测两套素材是否齐全)
npm run dev
```

像素化不是生成模型，而是：裁透明边界 → 中间 72% 宽度（去掉两侧大面积立绘特效）→ 等比缩放 → 32 色量化 → 1px 深色描边。活动帧在右上角加像素小图标。

## 文件映射

| 世界角色 | 头像原图 | 全身立绘 | Genshin 角色 |
|---|---|---|---|
| 旅行者 | `portraits-src/PlayerBoy.png` | `fullbody-src/PlayerBoy.png` | 空 |
| 桃音 | `portraits-src/Kokomi.png` | `fullbody-src/Kokomi.webp` | 心海 |
| 刚郎 | `portraits-src/Itto.png` | `fullbody-src/Itto.webp` | 一斗 |
| 小梅 | `portraits-src/Sayu.png` | `fullbody-src/Sayu.webp` | 早柚 |
| 执行官 | `portraits-src/Wanderer.png` | `fullbody-src/Wanderer.webp` | 流浪者 |
| 雷电将军 | `portraits-src/Shougun.png` | `fullbody-src/Shougun.webp` | 雷电将军 |

## 缺失/回退

- 两套素材都有：`__OFFICIAL_PORTRAITS__` / `__OFFICIAL_FULLBODY__` 为 true。
- 头像缺失：状态面板/详情卡不显示头像；全身 Sprite 仍可用。
- 全身 Sprite 缺失：世界角色回退到原 16×16 原创像素（`art/characters.ts`）。
- 新增素材后需要重启 `npm run dev`，让 Vite 重新检测。
