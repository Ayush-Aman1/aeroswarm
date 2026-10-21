// matplotlib 'viridis' (CC0), 16 control points sampled at i/15; interpolated linearly into a 256-entry LUT.
export const VIRIDIS = [[68, 1, 84], [72, 26, 108], [71, 47, 125], [65, 68, 135], [57, 86, 140], [49, 104, 142], [42, 120, 142], [35, 136, 142], [31, 152, 139], [34, 168, 132], [53, 183, 121], [84, 197, 104], [122, 209, 81], [165, 219, 54], [210, 226, 27], [253, 231, 37]];

export function buildLut(stops = VIRIDIS, n = 256) {
  const data = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) {
    const t = (i / (n - 1)) * (stops.length - 1);
    const k = Math.min(Math.floor(t), stops.length - 2);
    const f = t - k;
    for (let c = 0; c < 3; c++) data[i * 4 + c] = Math.round(stops[k][c] * (1 - f) + stops[k + 1][c] * f);
    data[i * 4 + 3] = 255;
  }
  return data;
}

export function colorAt(t, stops = VIRIDIS) {
  t = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const k = Math.min(Math.floor(t), stops.length - 2);
  const f = t - k;
  return stops[k].map((v, c) => (v * (1 - f) + stops[k + 1][c] * f) / 255);
}
