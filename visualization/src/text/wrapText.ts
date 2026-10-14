// 手动换行工具 (气泡 / 事件框共用)。
// 此环境 (无头 WebGL) Phaser 的 wordWrap 对无空格 CJK 长文本不生效 —— 长文本不换行会溢出。
// 用离屏 canvas 逐字符测量, 每行超 maxWidth 就插 \n (CJK 逐字断行正确)。测量 canvas 建一次。
let measureCtx: CanvasRenderingContext2D | null = null;
function getMeasureCtx(): CanvasRenderingContext2D {
  if (!measureCtx) {
    measureCtx = document.createElement("canvas").getContext("2d") as CanvasRenderingContext2D;
  }
  return measureCtx;
}

// 逐字符累加, 超 maxWidth 断行; 保留显式 \n。返回带 \n 的文本。
export function wrapText(text: string, maxWidth: number, font: string): string {
  const ctx = getMeasureCtx();
  ctx.font = font;
  const lines: string[] = [];
  let cur = "";
  for (const ch of text) {
    if (ch === "\n") { lines.push(cur); cur = ""; continue; }
    const test = cur + ch;
    if (ctx.measureText(test).width > maxWidth && cur.length > 0) {
      lines.push(cur);
      cur = ch;
    } else {
      cur = test;
    }
  }
  if (cur) lines.push(cur);
  return lines.join("\n");
}
