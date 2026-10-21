# 原神头像（本地可选，像素化）

界面支持在每个角色旁边显示 **2D 像素风头像**，底图来自原神官方角色图标。官方原图和像素化结果都**不随仓库提交**，仅用于个人学习/本地演示。

## 版权

- 官方头像素材 © HoYoverse / miHoYo（Genshin Impact 角色图标，通过 Enka.Network 的公开 UI 资源获取）。
- `public/assets/portraits-src/`（官方原图）和 `public/assets/portraits/`（像素化衍生图）都在 `.gitignore` 中，**不要提交、发布或再分发**。
- 要发布项目时删除这两个目录即可；界面会自动隐藏头像，不会报错。

## 生成步骤

```bash
cd visualization

# 1. 下载官方头像原图 (6 张, 需要网络)
node tools/fetch_official_portraits.mjs

# 2. 程序化像素化: 裁透明边界 → 64x64 LANCZOS → 32 色量化 → 1px 深色描边
python3 tools/pixelate_portraits.py --size 64 --colors 32

# 3. 启动/构建 (Vite 会检测 public/assets/portraits/ 是否齐全)
npm run dev
```

像素化后文件：

| 世界角色 | 官方原图 | 界面头像 |
|---|---|---|
| 旅行者 | `portraits-src/PlayerBoy.png` | `portraits/PlayerBoy.png` |
| 桃音 | `portraits-src/Kokomi.png` | `portraits/Kokomi.png` |
| 刚郎 | `portraits-src/Itto.png` | `portraits/Itto.png` |
| 小梅 | `portraits-src/Sayu.png` | `portraits/Sayu.png` |
| 执行官 | `portraits-src/Wanderer.png` | `portraits/Wanderer.png` |
| 雷电将军 | `portraits-src/Shougun.png` | `portraits/Shougun.png` |

## 缺失时

所有 6 张像素头像都存在时，Vite 构建期变量 `__OFFICIAL_PORTRAITS__` 为 true，前端才去加载；否则完全不请求图片，头像位置留空、其余 UI 正常，不产生 404/console 错误。新增图片后需要重启 `npm run dev` 让 Vite 重新检测。
