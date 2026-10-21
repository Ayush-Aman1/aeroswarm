const $ = (id) => document.getElementById(id);

export function toast(text, level = 'info', ms = 5000) {
  const el = document.createElement('div');
  el.className = 'toast' + (level === 'error' ? '' : ' info'); el.textContent = text;
  $('toasts').appendChild(el); setTimeout(() => el.remove(), ms);
}

export function setConn(ok, text) {
  const c = $('conn'); c.textContent = text; c.className = ok ? 'ok' : 'bad';
}

export function setBanner(on) { $('banner').style.display = on ? 'block' : 'none'; }

const f1 = (v) => (Number.isFinite(v) ? v.toFixed(1) : '–');

export function updateHud({ stats, fpsView, bytes, snap }) {
  if (snap) $('m-step').textContent = `${snap.step} / ${snap.simTime.toFixed(1)} s`;
  $('m-fps').textContent = `${Math.round(fpsView)} / ${stats ? f1(stats.fps_server) : '–'}`;
  const kb = bytes ? bytes / 1024 : (stats ? stats.snapshot_bytes / 1024 : 0);
  $('m-bytes').textContent = kb ? `${kb.toFixed(0)} kB` : '–';
  if (!stats) return;
  const w = stats.wind || {};
  $('m-wind').textContent = w.mlups ? `${w.mlups.toFixed(0)} MLUPS · ${f1(w.step_ms)} ms` : `${stats.tier} · ${f1(stats.step_ms)} ms/tick`;
  const m = stats.metrics || {};
  $('m-del').textContent = `${m.delivered ?? 0}`;
  $('m-dt').textContent = m.completed ? `${f1(m.mean_delivery_s)} s` : '–';
  $('m-en').textContent = m.completed ? f1(m.energy) : '–';
  $('m-dr').textContent = m.completed ? `${(m.drift_mean ?? 0).toFixed(2)} m` : '–';
  $('m-nc').textContent = `${m.near_collisions ?? 0}`;
  $('m-act').textContent = `${m.active ?? 0}`;
  $('route-naive').classList.toggle('on', stats.routing === 'naive');
  $('route-aware').classList.toggle('on', stats.routing === 'aware');
  if (stats.tier && $('tier').value !== stats.tier) $('tier').value = stats.tier;
  $('btn-pause').textContent = stats.paused ? 'Resume' : 'Pause';
  if (stats.inflow) $('m-inflow').textContent = `${stats.inflow.speed_ms.toFixed(1)} m/s @ ${stats.inflow.direction_deg.toFixed(0)}°`;
}

export function fillSelect(id, values, current) {
  const sel = $(id); sel.innerHTML = '';
  for (const v of values) { const o = document.createElement('option'); o.value = o.textContent = v; sel.appendChild(o); }
  if (current) sel.value = current;
}
