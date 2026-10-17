import { FLOORS, FLOOR_NAMES, FLOOR_HUE, PLACES, PLACE_NAMES, addressOf, shortTitle } from './logic.js';

const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = String(text); return e; };

export function createHud(root, api) {
  const top = h('div', 'wt-top'), title = h('div', 'wt-title', 'THE WATCHTOWER'), stats = h('div', 'wt-stats', 'connecting...'), jobs = h('div', 'wt-jobs');
  top.append(title, stats, jobs);
  const tip = h('div', 'wt-tip'); tip.hidden = true;
  const bar = h('div', 'wt-bar');
  const places = h('div', 'wt-row wt-places'), floors = h('div', 'wt-row wt-floors'), ctl = h('div', 'wt-row wt-ctl');
  const chip = (label, onClick, cls = '') => { const b = h('button', 'wt-chip ' + cls, label); b.type = 'button'; b.addEventListener('click', onClick); return b; };
  const placeBtns = new Map();
  const addPlace = (id, label) => { const b = chip(label, () => api.place(id)); placeBtns.set(id, b); places.append(b); };
  PLACES.forEach((p) => addPlace(p, PLACE_NAMES[p]));
  floors.append(chip('Overview', () => api.floor(-1), 'wt-floor'));
  FLOORS.forEach((f, k) => { const b = chip(FLOOR_NAMES[f].replace(/ - .*/, '').replace('Penthouse', 'PH'), () => api.floor(k), 'wt-floor'); b.title = FLOOR_NAMES[f]; b.style.setProperty('--hue', FLOOR_HUE[f]); floors.append(b); });
  const slider = h('input', 'wt-slider'); slider.type = 'range'; slider.min = '0'; slider.max = '24'; slider.step = '0.05'; slider.setAttribute('aria-label', 'time of day');
  const clock = h('span', 'wt-clock', '--:--');
  slider.addEventListener('input', () => api.hour(Number(slider.value)));
  const toggles = {};
  const toggle = (key, label, on) => { const b = chip(label, () => { toggles[key].on = !toggles[key].on; paint(); api.toggle(key, toggles[key].on); }); toggles[key] = { b, label, on }; return b; };
  const paint = () => { for (const k in toggles) { toggles[k].b.classList.toggle('on', toggles[k].on); } };
  ctl.append(h('span', 'wt-lbl', 'Time'), slider, clock, toggle('live', 'Live clock', true), toggle('spin', 'Auto-orbit', false), toggle('bloom', 'Glow', true), toggle('fx', 'Weather', true));
  bar.append(places, floors, ctl);
  root.append(top, bar, tip); paint();

  return {
    setBackdrops(names) {   // the owner's own photos, as extra places
      for (const [id, b] of [...placeBtns]) if (id.startsWith('photo:')) { b.remove(); placeBtns.delete(id); }
      names.forEach((n) => addPlace('photo:' + n, n.replace(/\.[^.]+$/, '').slice(0, 18)));
    },
    setPlace(id) { placeBtns.forEach((b, k) => b.classList.toggle('on', k === id)); },
    setHour(hour, live) { slider.value = String(hour); const hh = Math.floor(hour) % 24, mm = Math.floor((hour % 1) * 60); clock.textContent = String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0'); toggles.live.on = live; paint(); },
    setFloor(k) { floors.querySelectorAll('.wt-floor').forEach((b, i) => b.classList.toggle('on', i === k + 1)); },
    setState(s, awakeCount) {
      const run = s.jobs.filter((j) => j.status === 'running').length, wait = s.jobs.filter((j) => j.status === 'paused').length;
      stats.textContent = `${run} running | ${wait} waiting for you | ${awakeCount} agents awake | ${s.chain_ok === false ? 'AUDIT CHAIN BROKEN' : 'audit chain ok'}`;
      stats.classList.toggle('bad', s.chain_ok === false);
      jobs.replaceChildren(...s.jobs.filter((j) => j.status === 'running' || j.status === 'paused').slice(0, 4).map((j) => {
        const c = h('div', 'wt-job'); c.append(h('b', null, j.id.slice(0, 12) + '  ' + j.status + '  ' + (j.floor ? j.floor.toUpperCase() : 'planning')), h('span', null, j.prompt.slice(0, 60))); return c;
      }));
    },
    tooltip(x, y, person, working) {
      if (!person) { tip.hidden = true; return; }
      tip.replaceChildren(h('b', null, person.role.title), h('span', null, `${person.role.id}  |  ${working ? 'working' : 'idle'}`));
      tip.hidden = false; tip.style.setProperty('--x', Math.min(x + 16, innerWidth - 260) + 'px'); tip.style.setProperty('--y', Math.max(8, y - 10) + 'px');
    },
    note(text) { stats.textContent = text; },
  };
}
