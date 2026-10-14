import Phaser from "phaser";
import { InazumaScene } from "./scenes/InazumaScene";

// 固定低分辨率逻辑画布 + 整数倍缩放 + 关线性过滤 + 像素对齐 (计划 §3.1 像素显示约束)。
// 统一在这里设 pixelArt/roundPixels, 不让每个 Sprite 自己决定显示策略。
// 单场景 (InazumaScene) 内完成加载/地图/实体/HUD/播放, 避免多场景时钟不进更新相位。
export const CONFIG: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  parent: "game",
  width: 960,
  height: 540,
  pixelArt: true,
  roundPixels: true,
  backgroundColor: "#1a1a1f",
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [InazumaScene],
};
