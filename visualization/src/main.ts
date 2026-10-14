import Phaser from "phaser";
import { CONFIG } from "./config";

// 入口: 创建 Phaser 游戏。BootScene 负责加载 timeline 并启动其余场景。
// 纯离线回放器 —— 无 LLM、无后端依赖, 只读 public/stub_timeline.json。
const game = new Phaser.Game(CONFIG);
(window as unknown as Record<string, unknown>).__PHASER_GAME__ = game;   // E2E 调试
