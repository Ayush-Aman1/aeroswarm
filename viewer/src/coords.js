// Sim frame: x east, y north, z up.  three.js frame: x right, y up, z toward the viewer (= -north).
export const simToThree = (x, y, z) => [x, z, -y];
export const threeToSim = (x, y, z) => [x, -z, y];
