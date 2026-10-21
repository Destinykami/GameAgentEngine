// 加载 Phaser 的全局命名空间类型 (Phaser.Scene / Phaser.GameObjects.* / Phaser.Scale 等),
// 让各文件无需 import 即可用 Phaser.* 类型。
/// <reference types="phaser" />

// Vite define: 本地原神像素头像 6 张是否齐全 (vite.config.ts 构建期检测)。
declare const __OFFICIAL_PORTRAITS__: boolean;
