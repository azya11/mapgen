// Generator page: viewer + generation flow.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const $ = (id) => document.getElementById(id);
const CSRF = document.querySelector('meta[name=csrf-token]').content;

function toast(msg, kind = 'err') {
  const w = $('toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  w.appendChild(t);
  setTimeout(() => t.remove(), 4500);
}

// Escape user-controlled text before inserting as innerHTML (XSS guard).
function esc(s) {
  return (s || '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ----------------------------------------------------------- 3D viewer --- */
class Viewer {
  constructor(stage) {
    this.stage = stage;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.82;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    stage.insertBefore(this.renderer.domElement, stage.firstChild);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.5, 5_000_000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.maxPolarAngle = Math.PI * 0.495;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.sky = new Sky();
    this.sky.scale.setScalar(1_000_000);
    this.scene.add(this.sky);
    const u = this.sky.material.uniforms;
    u.turbidity.value = 8; u.rayleigh.value = 2.2;
    u.mieCoefficient.value = 0.005; u.mieDirectionalG.value = 0.8;

    this.scene.add(new THREE.HemisphereLight(0xbfd6ff, 0x3a352c, 0.55));
    this.sun = new THREE.DirectionalLight(0xfff3df, 2.6);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0004; this.sun.shadow.normalBias = 1.0;
    this.scene.add(this.sun, this.sun.target);

    this.span = 1000; this.center = new THREE.Vector3();
    this.meshes = [];
    this._resize();
    new ResizeObserver(() => this._resize()).observe(stage);
    this._loop();
  }

  _resize() {
    const w = this.stage.clientWidth || 1, h = this.stage.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  _sun(az = 315, el = 50) {
    const phi = THREE.MathUtils.degToRad(90 - el), theta = THREE.MathUtils.degToRad(az);
    const dir = new THREE.Vector3().setFromSphericalCoords(1, phi, theta);
    this.sky.material.uniforms.sunPosition.value.copy(dir);
    this.sun.position.copy(this.center).add(dir.multiplyScalar(this.span * 1.6));
    this.sun.target.position.copy(this.center);
    const s = this.span * 0.72, c = this.sun.shadow.camera;
    c.left = -s; c.right = s; c.top = s; c.bottom = -s;
    c.near = this.span * 0.05; c.far = this.span * 4.5; c.updateProjectionMatrix();
  }

  async load(url) {
    const gltf = await new GLTFLoader().loadAsync(url);
    if (this.model) this.scene.remove(this.model);
    this.model = gltf.scene;
    this.model.rotation.x = -Math.PI / 2;
    this.scene.add(this.model);
    this.meshes = [];
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      this.meshes.push(o);
      const name = (o.name || (o.parent && o.parent.name) || '').toLowerCase();
      const m = o.material; m.vertexColors = true; o.castShadow = true; o.receiveShadow = true;
      if (name.includes('water')) {
        m.roughness = 0.06; m.metalness = 0.15; m.transparent = true; m.opacity = 0.72;
        m.depthWrite = false; m.envMapIntensity = 1.0; o.castShadow = false; o.receiveShadow = false;
        m.color.setRGB(1, 1, 1);
      } else if (name.includes('building')) { m.roughness = 0.6; m.metalness = 0.08; m.envMapIntensity = 0.7; }
      else if (name.includes('veget')) { m.roughness = 0.9; m.metalness = 0; o.receiveShadow = false; }
      else { m.roughness = 0.96; m.metalness = 0; }
      m.needsUpdate = true;
    });
    this.frame();
    return this._info();
  }

  _info() {
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3());
    let tris = 0;
    this.model.traverse((o) => { if (o.isMesh) { const g = o.geometry; tris += (g.index ? g.index.count : g.attributes.position.count) / 3; } });
    return { km: Math.max(size.x, size.z) / 1000, relief: size.y, tris: Math.round(tris) };
  }

  frame() {
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3());
    this.center = box.getCenter(new THREE.Vector3());
    this.span = Math.max(size.x, size.z) || 1000;
    this.controls.target.copy(this.center);
    this.camera.position.set(
      this.center.x + this.span * 0.85,
      this.center.y + Math.max(size.y * 2.2, this.span * 0.55),
      this.center.z + this.span * 0.95);
    this.camera.near = this.span / 800; this.camera.far = this.span * 60; this.camera.updateProjectionMatrix();
    this.controls.maxDistance = this.span * 6; this.controls.minDistance = this.span * 0.05;
    this.scene.fog = new THREE.Fog(0x9fb8da, this.span * 1.6, this.span * 7);
    this._sun();
  }

  toggleRotate() { this.controls.autoRotate = !this.controls.autoRotate; this.controls.autoRotateSpeed = 0.7; return this.controls.autoRotate; }
  toggleWire() { this._wire = !this._wire; this.meshes.forEach((o) => (o.material.wireframe = this._wire)); return this._wire; }
  shot(name) {
    this.renderer.render(this.scene, this.camera);
    const a = document.createElement('a');
    a.download = (name || 'mapgen') + '.png';
    a.href = this.renderer.domElement.toDataURL('image/png'); a.click();
  }

  _loop() {
    let last = performance.now(), frames = 0, acc = 0;
    const hud = $('hud');
    const tick = (now) => {
      requestAnimationFrame(tick);
      acc += now - last; last = now; frames++;
      if (acc >= 500 && !hud.hidden) { hud.textContent = Math.round(1000 * frames / acc) + ' fps'; frames = 0; acc = 0; }
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    requestAnimationFrame(tick);
  }
}

/* ------------------------------------------------------------- usage UI --- */
function setUsage(remaining, limit) {
  const pct = limit ? (remaining / limit) * 100 : 0;
  $('usage-bar').style.width = pct + '%';
  $('usage-count').textContent = remaining + '/' + limit;
  const gen = $('generate');
  if (remaining <= 0) {
    gen.disabled = true;
    $('gen-label').textContent = 'No generations left';
  }
}

/* --------------------------------------------------------------- wiring --- */
const viewer = new Viewer($('stage'));

const usageEl = $('usage');
setUsage(parseInt(usageEl.dataset.remaining, 10), parseInt(usageEl.dataset.limit, 10));

$('extent').addEventListener('input', (e) => { $('extent-val').textContent = (+e.target.value).toFixed(1) + ' km'; });
$('logout').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': CSRF } }).catch(() => {});
  window.location.href = '/';
});

$('t-frame').addEventListener('click', () => viewer.frame());
$('t-rotate').addEventListener('click', (e) => e.currentTarget.classList.toggle('primary', viewer.toggleRotate()));
$('t-wire').addEventListener('click', (e) => e.currentTarget.classList.toggle('primary', viewer.toggleWire()));
$('t-shot').addEventListener('click', () => viewer.shot(lastId || 'mapgen'));

let lastId = null;

$('generate').addEventListener('click', async () => {
  const prompt = $('prompt').value.trim();
  $('err').textContent = '';
  if (prompt.length < 3) { $('err').textContent = 'Please enter a longer prompt.'; return; }

  const btn = $('generate');
  btn.disabled = true;
  const label = $('gen-label').textContent;
  $('gen-label').innerHTML = '<span class="spinner"></span> Generating…';
  $('spin').hidden = false;
  $('spin-txt').textContent = $('use-real').checked ? 'fetching real-world data…' : 'building terrain…';

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
      body: JSON.stringify({
        prompt,
        use_real: $('use-real').checked,
        extent_km: parseFloat($('extent').value),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $('err').textContent = data.error || 'Generation failed.';
      toast(data.error || 'Generation failed.');
    } else {
      lastId = data.id;
      $('empty').hidden = true; $('hud').hidden = false; $('tools').hidden = false;
      $('spin-txt').textContent = 'loading model…';
      const info = await viewer.load(`/files/${data.id}/${data.files.glb}`);
      renderResult(data, info);
      setUsage(data.remaining, data.limit);
      loadHistory();
      toast('Map generated · ' + data.remaining + ' left', 'ok');
    }
  } catch (_) {
    $('err').textContent = 'Network error. Please try again.';
    toast('Network error.');
  }
  $('spin').hidden = true;
  btn.disabled = false;
  $('gen-label').textContent = label;
});

function renderResult(data, info) {
  const s = data.stats || {};
  const rows = [
    ['Location', esc(data.location) + (data.used_real_data ? ' · real' : ' · procedural')],
    ['Style', esc(data.style)],
    ['Extent', info.km.toFixed(2) + ' km'],
    ['Relief', Math.round(info.relief) + ' m'],
  ];
  if (s.building_count) {
    let v = s.building_count.toLocaleString() + ' (OSM)';
    if (s.buildings_extent_km) v += ' · ' + s.buildings_extent_km + ' km core';
    rows.push(['Buildings', v]);
  } else if (s.buildings_source === 'procedural') rows.push(['Buildings', 'procedural']);
  if (s.trees) rows.push(['Forest', s.trees.toLocaleString() + ' trees']);
  rows.push(['Triangles', info.tris.toLocaleString()]);

  $('stats').innerHTML = rows.map(([k, v]) =>
    `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');

  const dl = Object.entries(data.files).map(([fmt, name]) =>
    `<a class="btn" href="/files/${data.id}/${name}" download>${fmt.toUpperCase()}</a>`).join('');
  $('downloads').innerHTML = dl;
  $('result').hidden = false;
}

/* ----------------------------------------------------------- My maps --- */
async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) return;
    const { items = [] } = await res.json();
    const el = $('history');
    if (!items.length) { el.innerHTML = '<div class="history-empty">No maps yet.</div>'; return; }
    el.innerHTML = '';
    for (const it of items) {
      const when = new Date(it.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      const b = document.createElement('button');
      b.className = 'hitem';
      b.innerHTML =
        `<div class="h-prompt">${esc(it.prompt)}</div>` +
        `<div class="h-meta"><span class="tag">${it.used_real ? 'real' : 'proc'}</span>` +
        `<span>${esc(it.location || '—')} · ${when}</span></div>`;
      b.addEventListener('click', () => openSaved(it));
      el.appendChild(b);
    }
  } catch (_) { /* non-fatal */ }
}

async function openSaved(it) {
  $('err').textContent = '';
  $('empty').hidden = true; $('hud').hidden = false; $('tools').hidden = false;
  $('spin').hidden = false; $('spin-txt').textContent = 'loading model…';
  try {
    lastId = it.id;
    const info = await viewer.load(it.glb);
    $('stats').innerHTML = [
      ['Location', esc(it.location || '—') + (it.used_real ? ' · real' : ' · procedural')],
      ['Extent', info.km.toFixed(2) + ' km'],
      ['Relief', Math.round(info.relief) + ' m'],
      ['Triangles', info.tris.toLocaleString()],
    ].map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');
    $('downloads').innerHTML = ['glb', 'obj', 'stl'].map((f) =>
      `<a class="btn" href="/files/${it.id}/scene.${f}" download>${f.toUpperCase()}</a>`).join('');
    $('result').hidden = false;
  } catch (_) {
    toast('Could not load that map.');
  } finally {
    $('spin').hidden = true;
  }
}

loadHistory();
