// 按行数截断长文本, 在最后一行追加省略号。
// 此前的截断用 slice(0, maxLines) 直接砍行, 半句话结尾且没有任何提示;
// 这里统一保留前 maxLines 行并在末行加 "…", 可选按宽度从末行末尾删字保证省略号不越界。
import { measureTextWidth } from "./wrapText";

export function truncateLines(
  text: string,
  maxLines: number,
  maxWidth?: number,
  font?: string,
): string {
  if (maxLines <= 0) return "";
  const lines = text.split("\n");
  if (lines.length <= maxLines) return text;

  const kept = lines.slice(0, maxLines);
  let last = kept[kept.length - 1] ?? "";
  const ellipsis = "…";
  if (maxWidth != null && font) {
    while (last.length > 0 && measureTextWidth(last + ellipsis, font) > maxWidth) {
      last = last.slice(0, -1);
    }
  }
  kept[kept.length - 1] = last + ellipsis;
  return kept.join("\n");
}
