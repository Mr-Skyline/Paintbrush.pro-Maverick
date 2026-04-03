import { fabric } from 'fabric';

/** Canvas pixel bounds (same space as Boost / takeoff geometry). */
export type AiFocusBoundingRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export function getAiFocusBoundingRectPx(
  canvas: fabric.Canvas | null | undefined
): AiFocusBoundingRect | null {
  if (!canvas) return null;
  const o = canvas
    .getObjects()
    .find(
      (x) => (x as fabric.Object & { aiScope?: boolean }).aiScope === true
    );
  if (!o) return null;
  const br = o.getBoundingRect(true);
  if (br.width < 4 || br.height < 4) return null;
  return {
    left: br.left,
    top: br.top,
    width: br.width,
    height: br.height,
  };
}

/**
 * Region the user boxed for Grok / voice — same coordinate space as takeoff marks
 * (overlay canvas pixels, origin top-left of the sheet).
 */
export function buildAiFocusContextForGrok(
  canvas: fabric.Canvas | null | undefined,
  pageNum: number
) {
  const rect = getAiFocusBoundingRectPx(canvas);
  if (!rect || !canvas) return null;
  const cw = canvas.getWidth() || 1;
  const ch = canvas.getHeight() || 1;
  return {
    page: pageNum,
    instruction:
      'The user drew a purple dashed rectangle on this sheet. Treat plan content INSIDE this box as the primary scope for takeoff questions, measurements, and advice unless they explicitly ask about the whole sheet.',
    boundingRectCanvasPx: {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    },
    normalized01: {
      left: round3(rect.left / cw),
      top: round3(rect.top / ch),
      width: round3(rect.width / cw),
      height: round3(rect.height / ch),
    },
    canvasSize: { width: cw, height: ch },
  };
}

function round3(n: number) {
  return Math.round(n * 1000) / 1000;
}
