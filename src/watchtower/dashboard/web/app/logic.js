// Pure rules shared by the 3D scene: no three.js here, so they run (and are tested) in plain node.
export const FLOORS = ['csuite', 'f5', 'f4', 'f3', 'f2', 'f1'];            // top to bottom
export const FLOOR_NAMES = { csuite: 'Penthouse - C-suite', f5: 'F5 - Oversight', f4: 'F4 - QA & Deploy', f3: 'F3 - Build', f2: 'F2 - Dev', f1: 'F1 - Research' };
export const FLOOR_HUE = { csuite: 44, f5: 285, f4: 160, f3: 24, f2: 205, f1: 120 };
export const PLACES = ['ocean', 'scotland', 'wales', 'mumbai', 'japan', 'korea', 'usa', 'dubai'];
export const PLACE_NAMES = { ocean: 'Open ocean', scotland: 'Scotland', wales: 'Wales', mumbai: 'Mumbai', japan: 'Japan', korea: 'Korea', usa: 'USA', dubai: 'Dubai' };
export const PLACE_VIEW = { ocean: 0.9, scotland: 2.55, wales: 0.95, mumbai: 3.7, japan: 2.7, korea: 0.85, usa: 4.0, dubai: 2.55 };   // the direction each place's scenery lies in, seen from the tower
export const PLACE_HOUR = { ocean: 17.2, scotland: 18.4, wales: 19.3, mumbai: 17.9, japan: 6.3, korea: 17.6, usa: 18.1, dubai: 18.0 };   // a flattering default light for each place

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

export function sunElevation(hour) {                  // degrees above the horizon: sunrise 6, noon 12 (+62), sunset 18
  return 62 * Math.sin(Math.PI * (hour - 6) / 12);
}
export function daylight(hour) {                      // 0 deep night .. 1 full day
  return smooth(-8, 10, sunElevation(hour));
}
export function sunAzimuth(hour) {                    // degrees: east in the morning, west in the evening
  return 90 + 180 * clamp((hour - 6) / 12, -0.3, 1.3);
}

// What the page knows about the staff, from the polled state: which agents are awake and which floors have live work.
export function activity(state) {
  const awake = new Set(), lit = new Set(), floorOf = new Map();
  for (const j of (state && state.jobs) || []) {
    const live = j.status === 'running', held = j.status === 'paused';
    if (live) for (const a of j.awake || []) awake.add(a);
    if ((live || held) && FLOORS.includes(j.floor)) lit.add(j.floor);
    if (FLOORS.includes(j.floor)) floorOf.set(j.id, j.floor);
  }
  return { awake, lit, floorOf };
}

export function rosterByFloor(roster) {
  const by = Object.fromEntries(FLOORS.map((f) => [f, []]));
  for (const r of roster) if (by[r.floor]) by[r.floor].push(r);
  return by;
}

export const shortTitle = (t) => String(t).replace(/\(.*\)/, '').trim().slice(0, 26);
export const addressOf = (d) => (d && d.port ? '127.0.0.1:' + d.port : '-');
