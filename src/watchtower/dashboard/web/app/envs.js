import { ocean, scotland, wales, japan } from './env_nature.js';
import { mumbai, korea, usa, dubai } from './env_cities.js';

export const BASE_PARAMS = { turbidity: 2.6, rayleigh: 2.1, mie: 0.0035, cover: 0.42, soft: 0.3, fog: 0xa6bfdc, fogDensity: 0.00042, exposure: 1, water: 0x0a3d58 };
const BUILD = { ocean, scotland, wales, japan, mumbai, korea, usa, dubai };
export function createEnv(name, ctx) { return (BUILD[name] || ocean)(BASE_PARAMS); }
