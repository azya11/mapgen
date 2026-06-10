// Generator page: viewer + generation flow.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const $ = (id) => document.getElementById(id);
const CSRF = document.querySelector('meta[name=csrf-token]').content;

// scratch objects reused by the shadow-frustum fit (avoid per-frame allocation)
const _v0 = new THREE.Vector3();
const _lightView = new THREE.Matrix4();
const UP_Y = new THREE.Vector3(0, 1, 0);
const UP_Z = new THREE.Vector3(0, 0, 1);

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

/* ------------------------------------------------ viewer theme helpers --- */
function classifyMesh(name = '') {
  name = name.toLowerCase();
  if (name.includes('water')) return 'water';
  if (name.includes('building')) return 'buildings';
  if (name.includes('veget') || name.includes('tree') || name.includes('forest')) return 'vegetation';
  return 'terrain';
}

// height → topographic colour (deep blue → green → yellow → brown → snow)
const TOPO_STOPS = [
  [0.00, 0x14324f], [0.12, 0x1f6f54], [0.38, 0x6f9a3a],
  [0.62, 0xc6b24a], [0.82, 0x8a6a44], [1.00, 0xf2f4fa],
];
const _ca = new THREE.Color(), _cb = new THREE.Color(), _co = new THREE.Color();
function topoColor(t) {
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < TOPO_STOPS.length; i++) {
    if (t <= TOPO_STOPS[i][0]) {
      const [p0, c0] = TOPO_STOPS[i - 1], [p1, c1] = TOPO_STOPS[i];
      const k = (t - p0) / (p1 - p0 || 1);
      _ca.setHex(c0); _cb.setHex(c1);
      return _co.copy(_ca).lerp(_cb, k);
    }
  }
  return _co.setHex(TOPO_STOPS[TOPO_STOPS.length - 1][1]);
}

// Solar position (compact SunCalc, MIT). `date` is a JS Date (a UTC instant).
// Returns { azimuth, altitude } in radians; azimuth is compass bearing
// clockwise from North, altitude is angle above the horizon.
function sunPosition(date, lat, lng) {
  const rad = Math.PI / 180, dayMs = 86400000, J1970 = 2440588, J2000 = 2451545;
  const e = rad * 23.4397;                                  // obliquity
  const d = date.valueOf() / dayMs - 0.5 + J1970 - J2000;   // days since J2000
  const M = rad * (357.5291 + 0.98560028 * d);              // mean anomaly
  const C = rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
  const L = M + C + rad * 102.9372 + Math.PI;               // ecliptic longitude
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const ra = Math.atan2(Math.sin(L) * Math.cos(e), Math.cos(L));
  const lw = rad * -lng, phi = rad * lat;
  const th = rad * (280.16 + 360.9856235 * d) - lw;         // sidereal time
  const H = th - ra;                                        // hour angle
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi));
  const alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
  return { azimuth: az + Math.PI, altitude: alt };          // from-south → from-north
}

// Real-world distance formatter (metres → m / km).
function fmtDist(m) {
  return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : (m < 10 ? m.toFixed(2) : Math.round(m)) + ' m';
}

// Compass bearing + altitude → world direction. Model frame: +X=East, +Y=Up,
// North=−Z (terrain is built x=east, y=north, then rotated z-up → y-up).
function sunDirWorld(azimuth, altitude) {
  const ca = Math.cos(altitude);
  return new THREE.Vector3(
    Math.sin(azimuth) * ca,    // east
    Math.sin(altitude),        // up
    -Math.cos(azimuth) * ca,   // −north
  ).normalize();
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
    this.sun.shadow.mapSize.set(4096, 4096);
    this.sun.shadow.bias = -0.00015; this.sun.shadow.normalBias = 0.2;
    this.scene.add(this.sun, this.sun.target);

    this.span = 1000; this.center = new THREE.Vector3();
    // world-space bounds of the shadow casters (buildings if any, else the whole
    // model); the shadow frustum is fit tightly to this — see _fitShadow().
    this.casterBox = new THREE.Box3();
    this.meshes = [];
    // themes + sun state
    this.THEMES = ['satellite', 'wireframe', 'topographic', 'blueprint'];
    this.theme = 'satellite';
    this.lat = null; this.lon = null;           // geocoded centre (real maps)
    this.sunMode = 'default';                    // 'default' | 'real'
    this.sunDate = new Date();                   // chosen local date
    this.sunMinutes = 720;                       // chosen local minutes-of-day
    // measuring (real-world distances; world units are metres)
    this.raycaster = new THREE.Raycaster();
    this.measureMode = false;
    this.measurePoints = [];                     // world-space Vector3s
    this.measureSegments = [];                   // { mid, el, horiz }
    this.measureGroup = new THREE.Group();
    this.scene.add(this.measureGroup);
    this._initMeasurePointer();
    this._resize();
    new ResizeObserver(() => this._resize()).observe(stage);
    this._loop();
  }

  _resize() {
    const w = this.stage.clientWidth || 1, h = this.stage.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  // Place sun + sky + shadow frustum along a unit direction.
  _applySunDir(dir) {
    this.sky.material.uniforms.sunPosition.value.copy(dir);
    this.sun.position.copy(this.center).addScaledVector(dir, this.span * 1.6);
    this.sun.target.position.copy(this.center);
    this._fitShadow(this.casterBox);
  }

  // Fit the directional-light shadow ortho frustum to a world-space box, as seen
  // from the light. Tighter frustum -> far more shadow-map texels per metre, so
  // building shadows on the terrain are sharp instead of lost across the extent.
  _fitShadow(box) {
    if (!box || box.isEmpty()) return;
    const cam = this.sun.shadow.camera;
    const dir = _v0.copy(this.sun.position).sub(this.center).normalize();
    const up = Math.abs(dir.y) > 0.999 ? UP_Z : UP_Y;
    _lightView.lookAt(this.sun.position, this.center, up);
    _lightView.setPosition(this.sun.position);
    _lightView.invert();
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    for (let i = 0; i < 8; i++) {
      _v0.set(i & 1 ? box.max.x : box.min.x,
              i & 2 ? box.max.y : box.min.y,
              i & 4 ? box.max.z : box.min.z).applyMatrix4(_lightView);
      minX = Math.min(minX, _v0.x); maxX = Math.max(maxX, _v0.x);
      minY = Math.min(minY, _v0.y); maxY = Math.max(maxY, _v0.y);
      minZ = Math.min(minZ, _v0.z); maxZ = Math.max(maxZ, _v0.z);
    }
    const pad = Math.max(maxX - minX, maxY - minY) * 0.15 + 1;
    cam.left = minX - pad; cam.right = maxX + pad;
    cam.bottom = minY - pad; cam.top = maxY + pad;
    cam.near = Math.max(-maxZ - pad, 0.1); cam.far = -minZ + pad;
    cam.updateProjectionMatrix();
  }

  // Cinematic default sun (used until "real sun" is enabled).
  _sun(az = 315, el = 50) {
    const phi = THREE.MathUtils.degToRad(90 - el), theta = THREE.MathUtils.degToRad(az);
    this._applySunDir(new THREE.Vector3().setFromSphericalCoords(1, phi, theta));
  }

  // Convert the chosen local date + minutes-of-day to a UTC instant, using a
  // longitude-estimated timezone so "noon" reads as local noon at the place.
  _sunInstant() {
    const d = this.sunDate;
    const tzHours = this.lon == null ? 0 : Math.round(this.lon / 15);
    const ms = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
      + this.sunMinutes * 60000 - tzHours * 3600000;
    return new Date(ms);
  }

  applySun() {
    if (this.sunMode === 'real' && this.lat != null) {
      const p = sunPosition(this._sunInstant(), this.lat, this.lon == null ? 0 : this.lon);
      // Keep the light a touch above the horizon so the scene stays lit even
      // when the real sun has just set (still report the true values).
      const alt = Math.max(p.altitude, THREE.MathUtils.degToRad(1.5));
      this._applySunDir(sunDirWorld(p.azimuth, alt));
      this._sunInfo(p);
    } else {
      this._sun();
      const el = $('sun-info'); if (el) el.textContent = '';
    }
  }

  _sunInfo(p) {
    const el = $('sun-info'); if (!el) return;
    const azDeg = ((p.azimuth * 180 / Math.PI) % 360 + 360) % 360;
    const elDeg = p.altitude * 180 / Math.PI;
    const dir = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(azDeg / 45) % 8];
    el.textContent = elDeg < 0
      ? `☾ Sun below horizon (${elDeg.toFixed(0)}°)`
      : `☀ ${azDeg.toFixed(0)}° ${dir} · ${elDeg.toFixed(0)}° above horizon`;
  }

  // The map's geocoded centre (null for procedural maps).
  setLocation(lat, lon) { this.lat = lat; this.lon = lon; }

  /* ---- colour / texture themes (mirrors the landing-page background) ---- */
  setTheme(name) {
    this.theme = name;
    const blueprint = name === 'blueprint';
    const wire = name === 'wireframe';
    for (const e of this.meshes) {
      const { mesh, kind, base, topo } = e;
      const m = mesh.material, g = mesh.geometry;
      mesh.visible = !(kind === 'water' && wire);
      if (blueprint) {
        if (g.attributes.color) g.deleteAttribute('color');
        m.vertexColors = false; m.wireframe = false;
        m.color.setHex(kind === 'buildings' ? 0x10131c : 0x0b0e16);
        m.emissive.setHex(0xff4a1c);
        m.emissiveIntensity = kind === 'buildings' ? 0.22 : 0.07;
        m.metalness = 0.1; m.roughness = 0.8;
      } else {
        m.emissive.setHex(0x000000); m.emissiveIntensity = 1;
        m.vertexColors = true;
        m.wireframe = wire && kind !== 'water';
        if (name === 'topographic') g.setAttribute('color', topo);
        else if (base) g.setAttribute('color', base.clone());
        m.color.setRGB(1, 1, 1);   // white base so vertex colours show; restores water too
      }
      m.needsUpdate = true;
    }
    this.scene.background = blueprint ? new THREE.Color(0x05070d) : null;
    this.sky.visible = !blueprint;
    const lbl = $('theme-name'); if (lbl) lbl.textContent = name;
  }

  cycleTheme() {
    const i = (this.THEMES.indexOf(this.theme) + 1) % this.THEMES.length;
    this.setTheme(this.THEMES[i]);
    return this.theme;
  }

  // Rotate the compass so North (world −Z) reads correctly for the camera.
  updateCompass() {
    const rose = $('compass-rose'); if (!rose || !this.model) return;
    const dx = this.controls.target.x - this.camera.position.x;
    const dz = this.controls.target.z - this.camera.position.z;
    const heading = Math.atan2(dx, -dz) * 180 / Math.PI;   // 0=looking N, 90=E
    rose.style.transform = `rotate(${-heading}deg)`;
  }

  /* ---- measuring tool (real-world distances) ---- */
  _initMeasurePointer() {
    const el = this.renderer.domElement;
    let dx = 0, dy = 0, moved = false;
    el.addEventListener('pointerdown', (e) => { dx = e.clientX; dy = e.clientY; moved = false; });
    el.addEventListener('pointermove', (e) => {
      if (Math.abs(e.clientX - dx) > 4 || Math.abs(e.clientY - dy) > 4) moved = true;
    });
    el.addEventListener('pointerup', (e) => {
      // A click (not an orbit drag) while measuring drops a point on the surface.
      if (!this.measureMode || moved || !this.model) return;
      const rect = el.getBoundingClientRect();
      const ptr = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1);
      this.raycaster.setFromCamera(ptr, this.camera);
      const meshes = this.meshes.filter((m) => m.mesh.visible).map((m) => m.mesh);
      const hit = this.raycaster.intersectObjects(meshes, false)[0];
      if (hit) this.addMeasurePoint(hit.point.clone());
    });
  }

  toggleMeasure() {
    this.measureMode = !this.measureMode;
    this.renderer.domElement.style.cursor = this.measureMode ? 'crosshair' : '';
    const panel = $('measure-panel'); if (panel) panel.hidden = !this.measureMode;
    if (!this.measureMode) this.clearMeasure();
    else this._updateMeasurePanel();
    return this.measureMode;
  }

  addMeasurePoint(p) {
    const r = Math.max(this.span * 0.006, 0.5);
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(r, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xff5a1f, depthTest: false }));
    marker.position.copy(p); marker.renderOrder = 999;
    this.measureGroup.add(marker);

    const prev = this.measurePoints[this.measurePoints.length - 1];
    this.measurePoints.push(p);
    if (prev) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([prev, p]),
        new THREE.LineBasicMaterial({ color: 0xff5a1f, depthTest: false }));
      line.renderOrder = 998;
      this.measureGroup.add(line);
      const horiz = Math.hypot(p.x - prev.x, p.z - prev.z);  // metres (x=E, z=−N)
      const el = document.createElement('div');
      el.className = 'measure-label';
      const host = $('measure-labels'); if (host) host.appendChild(el);
      this.measureSegments.push({ mid: prev.clone().lerp(p, 0.5), el, horiz });
    }
    this._updateMeasurePanel();
    this.updateMeasureLabels();
  }

  updateMeasureLabels() {
    if (!this.measureSegments.length) return;
    const el = this.renderer.domElement;
    const w = el.clientWidth, h = el.clientHeight;
    const v = new THREE.Vector3();
    for (const s of this.measureSegments) {
      v.copy(s.mid).project(this.camera);
      const behind = v.z > 1;
      s.el.style.display = behind ? 'none' : 'block';
      if (behind) continue;
      s.el.style.left = ((v.x * 0.5 + 0.5) * w) + 'px';
      s.el.style.top = ((-v.y * 0.5 + 0.5) * h) + 'px';
      s.el.textContent = fmtDist(s.horiz);
    }
  }

  clearMeasure() {
    for (const c of [...this.measureGroup.children]) {
      this.measureGroup.remove(c);
      if (c.geometry) c.geometry.dispose();
      if (c.material) c.material.dispose();
    }
    for (const s of this.measureSegments) s.el.remove();
    this.measurePoints = []; this.measureSegments = [];
    this._updateMeasurePanel();
  }

  _updateMeasurePanel() {
    const out = $('measure-readout'); if (!out) return;
    if (this.measurePoints.length < 2) {
      out.textContent = this.measurePoints.length === 1
        ? 'Click another point…' : 'Click two points on the map to measure.';
      return;
    }
    let total = 0;
    for (const s of this.measureSegments) total += s.horiz;
    const a = this.measurePoints[this.measurePoints.length - 2];
    const b = this.measurePoints[this.measurePoints.length - 1];
    const seg = Math.hypot(b.x - a.x, b.z - a.z);
    const dz = b.y - a.y;
    out.innerHTML =
      `<div class="m-row"><span>Segment</span><b>${fmtDist(seg)}</b></div>` +
      `<div class="m-row"><span>Elevation Δ</span><b>${dz >= 0 ? '+' : ''}${Math.round(dz)} m</b></div>` +
      `<div class="m-row total"><span>Total path</span><b>${fmtDist(total)}</b></div>`;
  }

  async load(url) {
    const gltf = await new GLTFLoader().loadAsync(url);
    if (this.model) this.scene.remove(this.model);
    this.model = gltf.scene;
    this.model.rotation.x = -Math.PI / 2;
    this.scene.add(this.model);
    this.scene.updateMatrixWorld(true);
    this.clearMeasure();   // drop any measurement from the previous model

    // height range (world Y) for the topographic theme
    const box0 = new THREE.Box3().setFromObject(this.model);
    const minY = box0.min.y, relief = Math.max(box0.max.y - box0.min.y, 1);

    this.meshes = [];
    const v = new THREE.Vector3();
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const kind = classifyMesh(o.name || (o.parent && o.parent.name) || '');
      const m = o.material; m.vertexColors = true; o.castShadow = true; o.receiveShadow = true;
      // The GLB ships without vertex normals, so GLTFLoader turns on flatShading;
      // a mesh in that state isn't lit/shadowed correctly. Give every mesh real
      // normals. Buildings are de-indexed first so each face keeps its own normal
      // (crisp edges, not smoothed blobs); the terrain stays indexed so its hills
      // shade smoothly and show the building shadows on the "floor".
      if (!o.geometry.attributes.normal) {
        if (kind === 'buildings' && o.geometry.index) o.geometry = o.geometry.toNonIndexed();
        o.geometry.computeVertexNormals();
      }
      m.flatShading = false;
      if (kind === 'water') {
        m.roughness = 0.06; m.metalness = 0.15; m.transparent = true; m.opacity = 0.72;
        m.depthWrite = false; m.envMapIntensity = 1.0; o.castShadow = false; o.receiveShadow = false;
        m.color.setRGB(1, 1, 1);
      } else if (kind === 'buildings') { m.roughness = 0.6; m.metalness = 0.08; m.envMapIntensity = 0.7; }
      else if (kind === 'vegetation') { m.roughness = 0.9; m.metalness = 0; o.receiveShadow = false; }
      else { m.roughness = 0.96; m.metalness = 0; }
      m.needsUpdate = true;

      // precompute a height-based (topographic) colour attribute
      const g = o.geometry, pos = g.attributes.position;
      const topo = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i); o.localToWorld(v);
        const c = topoColor((v.y - minY) / relief);
        topo[i * 3] = c.r; topo[i * 3 + 1] = c.g; topo[i * 3 + 2] = c.b;
      }
      this.meshes.push({
        mesh: o, kind,
        base: g.attributes.color ? g.attributes.color.clone() : null,
        topo: new THREE.BufferAttribute(topo, 3),
      });
    });

    this.setTheme(this.theme);
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
    // shadow casters: the buildings (tight box) if any, otherwise the whole model
    this.casterBox.makeEmpty();
    const _b = new THREE.Box3();
    for (const e of this.meshes)
      if (e.kind === 'buildings') this.casterBox.union(_b.setFromObject(e.mesh));
    if (this.casterBox.isEmpty()) this.casterBox.copy(box);
    this.controls.target.copy(this.center);

    // Cinematic 3/4 view direction (from above + corner), kept as the look angle.
    const dir = new THREE.Vector3(
      this.span * 0.85,
      Math.max(size.y * 2.2, this.span * 0.55),
      this.span * 0.95,
    ).normalize();

    // Camera basis for that direction (signs don't matter — we use magnitudes).
    const look = dir.clone().negate();                 // camera looks this way
    const right = new THREE.Vector3().crossVectors(look, new THREE.Vector3(0, 1, 0)).normalize();
    const up = new THREE.Vector3().crossVectors(right, look).normalize();

    // Fit distance so all 8 box corners sit inside the frustum with no margin:
    // for each corner, the camera must be far enough that its lateral offset
    // fits the horizontal/vertical half-angles at that corner's depth.
    const vTan = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    const hTan = vTan * this.camera.aspect;
    const hx = size.x / 2, hy = size.y / 2, hz = size.z / 2;
    let dist = 0;
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
      const c = new THREE.Vector3(sx * hx, sy * hy, sz * hz); // corner rel. to center
      const along = c.dot(dir);                                // depth toward camera
      const lateralH = Math.abs(c.dot(right)) / hTan;
      const lateralV = Math.abs(c.dot(up)) / vTan;
      dist = Math.max(dist, along + lateralH, along + lateralV);
    }
    dist *= 1.02; // a hair of breathing room, otherwise edge-to-edge

    this.camera.position.copy(this.center).addScaledVector(dir, dist);
    this.camera.near = Math.max(this.span / 800, dist / 5000);
    this.camera.far = dist * 8 + this.span * 4;
    this.camera.updateProjectionMatrix();
    this.controls.maxDistance = dist * 4; this.controls.minDistance = this.span * 0.05;
    this.scene.fog = new THREE.Fog(0x9fb8da, dist * 1.4, dist * 6 + this.span * 4);
    this.applySun();
    this.updateCompass();
  }

  toggleRotate() { this.controls.autoRotate = !this.controls.autoRotate; this.controls.autoRotateSpeed = 0.7; return this.controls.autoRotate; }
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
      if (this.model) this.updateCompass();
      if (this.measureMode) this.updateMeasureLabels();
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

$('extent').addEventListener('input', () => { $('extent-val').textContent = $('extent').value + ' m'; });
$('logout').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': CSRF } }).catch(() => {});
  window.location.href = '/';
});

$('t-frame').addEventListener('click', () => viewer.frame());
$('t-rotate').addEventListener('click', (e) => e.currentTarget.classList.toggle('primary', viewer.toggleRotate()));
$('t-theme').addEventListener('click', () => viewer.cycleTheme());
$('t-sun').addEventListener('click', (e) => {
  const open = $('sun-panel').hidden;
  $('sun-panel').hidden = !open;
  e.currentTarget.classList.toggle('primary', open);
});
$('t-measure').addEventListener('click', (e) => e.currentTarget.classList.toggle('primary', viewer.toggleMeasure()));
$('measure-clear').addEventListener('click', () => viewer.clearMeasure());
$('t-shot').addEventListener('click', () => viewer.shot(lastId || 'mapgen'));

/* ---- sun panel ---- */
(function initSun() {
  const today = new Date();
  $('sun-date').value = today.toISOString().slice(0, 10);
  viewer.sunDate = today; viewer.sunMinutes = 720;
})();
function fmtTime(min) {
  const h = Math.floor(min / 60), m = min % 60;
  return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}
$('sun-real').addEventListener('change', (e) => {
  viewer.sunMode = e.target.checked ? 'real' : 'default';
  $('sun-fields').hidden = !e.target.checked;
  viewer.applySun();
});
$('sun-date').addEventListener('change', (e) => {
  const [y, m, d] = e.target.value.split('-').map(Number);
  if (y) { viewer.sunDate = new Date(y, m - 1, d); viewer.applySun(); }
});
$('sun-time').addEventListener('input', (e) => {
  viewer.sunMinutes = +e.target.value;
  $('sun-time-val').textContent = fmtTime(viewer.sunMinutes);
  viewer.applySun();
});
$('sun-lat').addEventListener('input', (e) => {
  viewer.lat = +e.target.value;
  $('sun-lat-val').textContent = (+e.target.value).toFixed(1) + '°';
  viewer.applySun();
});

// Sync the sun controls to a freshly loaded map (real maps carry lat/lon).
function syncSun(meta) {
  viewer.lon = (meta && meta.lon != null) ? meta.lon : null;
  const latSlider = $('sun-lat');
  if (meta && meta.lat != null) {
    latSlider.value = (+meta.lat).toFixed(1);
    $('sun-lat-val').textContent = (+meta.lat).toFixed(1) + '°';
  }
  viewer.lat = parseFloat(latSlider.value);
  viewer.applySun();
}

let lastId = null;

/* ---- voxel loading overlay: green while generating, blue while loading ----
   The cube DOM is built once; all motion is CSS (compositor) so it keeps
   animating even while the main thread parses the model. */
function buildVoxLoader() {
  const cube = $('vox-cube');
  if (!cube || cube.childElementCount) return;
  const S = 22, CX = 3, CZ = 3, CY = 4;          // grid: 3×3 footprint, 4 tall
  cube.style.setProperty('--s', S + 'px');
  cube.style.setProperty('--hs', (S / 2) + 'px');
  for (let L = 0; L < CY; L++)                    // layers, bottom (0) first
    for (let i = 0; i < CX; i++)
      for (let k = 0; k < CZ; k++) {
        const v = document.createElement('div');
        v.className = 'vox';
        v.style.setProperty('--x', ((i - (CX - 1) / 2) * S) + 'px');
        v.style.setProperty('--y', (((CY - 1) / 2 - L) * S) + 'px');
        v.style.setProperty('--z', ((k - (CZ - 1) / 2) * S) + 'px');
        v.style.setProperty('--d', (L * 0.16) + 's');   // stagger the rise upward
        v.innerHTML = '<div class="f t"></div><div class="f l"></div><div class="f r"></div>';
        cube.appendChild(v);
      }
}
function showSpin(phase, text) {
  const s = $('spin');
  s.classList.toggle('gen', phase === 'gen');
  s.classList.toggle('load', phase === 'load');
  if (text != null) $('spin-txt').textContent = text;
  s.hidden = false;
}
function hideSpin() { $('spin').hidden = true; }
buildVoxLoader();

$('generate').addEventListener('click', async () => {
  const prompt = $('prompt').value.trim();
  $('err').textContent = '';
  if (prompt.length < 3) { $('err').textContent = 'Please enter a longer prompt.'; return; }

  const btn = $('generate');
  btn.disabled = true;
  const label = $('gen-label').textContent;
  $('gen-label').innerHTML = '<span class="spinner"></span> Generating…';
  showSpin('gen', 'building terrain…');

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
      body: JSON.stringify({
        prompt,
        extent_m: parseFloat($('extent').value),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $('err').textContent = data.error || 'Generation failed.';
      toast(data.error || 'Generation failed.');
    } else if (data.mode === 'worker') {
      await runOnWorker(data);
    } else {
      // Local in-process mode: files served same-origin.
      lastId = data.id;
      $('empty').hidden = true; $('hud').hidden = false; $('tools').hidden = false;
      showSpin('load', 'loading model…');
      const info = await viewer.load(`/files/${data.id}/${data.files.glb}`);
      syncSun(data);
      renderResult(data, '', info);
      setUsage(data.remaining, data.limit);
      loadHistory();
      toast('World generated · ' + data.remaining + ' left', 'ok');
    }
  } catch (_) {
    $('err').textContent = 'Network error. Please try again.';
    toast('Network error.');
  }
  hideSpin();
  btn.disabled = false;
  $('gen-label').textContent = label;
});

// Split mode: run the heavy generation directly on the worker (avoids Vercel's
// 60s / 4.5 MB limits), then confirm back to the app to commit/refund quota.
async function runOnWorker(data) {
  const base = data.worker_url.replace(/\/$/, '');
  let wd = {};
  let success = false;
  try {
    const w = await fetch(`${base}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket: data.ticket }),
    });
    wd = await w.json().catch(() => ({}));
    success = w.ok && wd && wd.id;
  } catch (_) { /* handled below */ }

  // Tell the app the outcome (commits the row, or refunds the reserved slot).
  let conf = {};
  try {
    const c = await fetch('/api/generate/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
      body: JSON.stringify({ ticket: data.ticket, ok: !!success, metadata: success ? wd : null }),
    });
    conf = await c.json().catch(() => ({}));
  } catch (_) { /* non-fatal */ }

  if (!success) {
    const msg = (wd && wd.error) || 'Generation failed. Please try again.';
    $('err').textContent = msg;
    toast(msg);
    if (conf.limit != null) setUsage(conf.remaining, conf.limit);
    return;
  }

  lastId = wd.id;
  $('empty').hidden = true; $('hud').hidden = false; $('tools').hidden = false;
  showSpin('load', 'loading model…');
  const info = await viewer.load(`${base}/files/${wd.id}/${wd.files.glb}`);
  syncSun(wd);
  renderResult(wd, base, info);
  if (conf.limit != null) setUsage(conf.remaining, conf.limit);
  loadHistory();
  toast('World generated · ' + (conf.remaining != null ? conf.remaining : '?') + ' left', 'ok');
}

function renderResult(data, base, info) {
  const s = data.stats || {};
  const rows = [
    ['World', esc(data.name || '—')],
    ['Style', esc(data.style || '—')],
    ['Extent', Math.round(data.extent_m || info.km * 1000) + ' m'],
    ['Relief', Math.round(info.relief) + ' m'],
  ];
  if (s.prop_intents) rows.push(['Props', s.prop_intents.toLocaleString() + ' intents']);
  rows.push(['Triangles', info.tris.toLocaleString()]);

  $('stats').innerHTML = rows.map(([k, v]) =>
    `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');

  const dl = Object.entries(data.files).map(([fmt, name]) =>
    `<a class="btn" href="${base}/files/${data.id}/${name}" download>${fmt.toUpperCase()}</a>`).join('');
  $('downloads').innerHTML = dl;
  $('result').hidden = false;
}

/* ----------------------------------------------------------- My maps --- */
let historyBase = '';

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) return;
    const { items = [], base = '' } = await res.json();
    historyBase = base;
    const el = $('history');
    if (!items.length) { el.innerHTML = '<div class="history-empty">No maps yet.</div>'; return; }
    el.innerHTML = '';
    for (const it of items) {
      const when = new Date(it.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      const b = document.createElement('button');
      b.className = 'hitem';
      b.innerHTML =
        `<div class="h-prompt">${esc(it.prompt)}</div>` +
        `<div class="h-meta"><span>${esc(it.location || '—')} · ${when}</span></div>`;
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
    syncSun(it);   // history rows have no lat/lon; falls back to the lat slider
    $('stats').innerHTML = [
      ['World', esc(it.location || '—')],
      ['Extent', Math.round(info.km * 1000) + ' m'],
      ['Relief', Math.round(info.relief) + ' m'],
      ['Triangles', info.tris.toLocaleString()],
    ].map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');
    $('downloads').innerHTML = ['glb', 'obj', 'stl'].map((f) =>
      `<a class="btn" href="${historyBase}/files/${it.id}/scene.${f}" download>${f.toUpperCase()}</a>`).join('');
    $('result').hidden = false;
  } catch (_) {
    toast('Could not load that map.');
  } finally {
    $('spin').hidden = true;
  }
}

loadHistory();
