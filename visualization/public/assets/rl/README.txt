# Kenney Roguelike/RPG 村庄素材（CC0）

- 来源: https://kenney.nl/assets/roguelike-rpg-pack
- 许可证: CC0 1.0（公共领域，无需署名，可自由使用/修改）
- 许可证全文: `../Kenney-Roguelike-LICENSE.txt`
- tileset: `../kenney-roguelike.png`（968×526，16×16，1px 间距）

## 文件

- `../rl-town.png`：60×34 村庄底图（960×544），由 `tools/build_rl_town.py` 生成。
  石板广场、土路、营地/花圃和草叶都来自同一 tileset。
- `house_*.png`：从该 pack 示例地图裁出的透明房屋 Sprite（参与 y-sort）。
- `tree_*.png` / `tent.png` / `stall.png` / `pool.png` / `torii.png` / `gate.png`：
  透明装饰 Sprite。`tree_sakura` 是圆树染粉；`torii`/`gate` 为本项目按 RL 调色板补画。

建筑/树木的 depth 取脚底 y，和角色同一深度空间，因此角色可以走到房屋/树后被遮挡。
如果这套素材缺失，前端会自动回退到原 Tiny Town 地图（`art/townTiles.ts` / `art/ArtFactory.ts`）。
