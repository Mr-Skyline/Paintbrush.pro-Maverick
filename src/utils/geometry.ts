/** SVG elliptical arc path from three points (planar). */
export function arcPathFromThreePoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  x3: number,
  y3: number
): string | null {
  const d =
    2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2));
  if (Math.abs(d) < 1e-4) return null;
  const aSq = x1 * x1 + y1 * y1;
  const bSq = x2 * x2 + y2 * y2;
  const cSq = x3 * x3 + y3 * y3;
  const ux =
    (aSq * (y2 - y3) + bSq * (y3 - y1) + cSq * (y1 - y2)) / d;
  const uy =
    (aSq * (x3 - x2) + bSq * (x1 - x3) + cSq * (x2 - x1)) / d;
  const r = Math.hypot(x1 - ux, y1 - uy);
  if (r < 1) return null;

  const ang = (x: number, y: number) => Math.atan2(y - uy, x - ux);
  let a0 = ang(x1, y1);
  let a1 = ang(x3, y3);
  const am = ang(x2, y2);
  const norm = (t: number) => {
    let u = t;
    while (u < 0) u += Math.PI * 2;
    while (u >= Math.PI * 2) u -= Math.PI * 2;
    return u;
  };
  const between = (t: number, lo: number, hi: number) => {
    const tn = norm(t);
    const lon = norm(lo);
    const hin = norm(hi);
    if (lon < hin) return tn >= lon && tn <= hin;
    return tn >= lon || tn <= hin;
  };
  const sweep = between(am, a0, a1) ? 0 : 1;
  const large = Math.abs(a1 - a0) > Math.PI ? 1 : 0;

  const polar = (cx: number, cy: number, rad: number, a: number) => ({
    x: cx + rad * Math.cos(a),
    y: cy + rad * Math.sin(a),
  });
  const pStart = polar(ux, uy, r, a0);
  const pEnd = polar(ux, uy, r, a1);
  return [
    'M',
    pStart.x,
    pStart.y,
    'A',
    r,
    r,
    0,
    large,
    sweep,
    pEnd.x,
    pEnd.y,
  ].join(' ');
}
