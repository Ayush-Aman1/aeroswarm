// Pure building-edit maths (no three.js import) so it is unit-tested headlessly.
// A building mesh has its origin at the centre of its base: position = (cx, 0, -cy), scale = (w, h, d).
export const MIN_SIZE = 5;

export function buildingToTransform(b) {
  return { position: [b.x + b.w / 2, 0, -(b.y + b.d / 2)], scale: [b.w, b.h, b.d] };
}

const snap = (v, s) => Math.round(v / s) * s;

export function transformToBuilding(id, position, scale, { snapM = 1, minSize = MIN_SIZE } = {}) {
  const w = Math.max(minSize, snap(Math.abs(scale[0]), snapM));
  const h = Math.max(minSize, snap(Math.abs(scale[1]), snapM));
  const d = Math.max(minSize, snap(Math.abs(scale[2]), snapM));
  return { id, x: snap(position[0] - w / 2, snapM), y: snap(-position[2] - d / 2, snapM), w, d, h };
}

export function sameBuilding(a, b, eps = 1e-6) {
  return ['x', 'y', 'w', 'd', 'h'].every((k) => Math.abs(a[k] - b[k]) < eps);
}

// Controller-grab release: the dragged building keeps its size; only x,y move (z is dropped to the ground).
export function grabToBuilding(b, worldPos) {
  const [cx, , cz] = worldPos;
  return { id: b.id, x: snap(cx - b.w / 2, 1), y: snap(-cz - b.d / 2, 1), w: b.w, d: b.d, h: b.h };
}
