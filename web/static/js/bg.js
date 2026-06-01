/* Landing-page background: a real 3D map of San Francisco that slowly rotates
   and cycles through "texture modes" (realistic → wireframe → topographic →
   blueprint) every 5 seconds. Loaded as a module; pointer-events are disabled
   on the canvas so it never intercepts clicks. Respects prefers-reduced-motion. */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const canvas = document.getElementById('bg3d');
const label  = document.getElementById('bg3d-mode');
if (canvas) start();

function start() {
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- renderer ----------
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(46, innerWidth / innerHeight, 1, 5_000_000);

  // ---------- environment + sky + sun ----------
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const sky = new Sky();
  sky.scale.setScalar(1_000_000);
  scene.add(sky);
  const skyU = sky.material.uniforms;
  skyU['turbidity'].value = 9;
  skyU['rayleigh'].value = 2.4;
  skyU['mieCoefficient'].value = 0.005;
  skyU['mieDirectionalG'].value = 0.8;

  const hemi = new THREE.HemisphereLight(0xbfd6ff, 0x2a251c, 0.75);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xfff3df, 2.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 1.0;
  scene.add(sun, sun.target);

  // ---------- spinning pivot that holds the model ----------
  const spinner = new THREE.Group();
  scene.add(spinner);

  let span = 1000;
  const meshes = [];               // { mesh, kind, baseColor, topoColor }

  function classify(name = '') {
    name = name.toLowerCase();
    if (name.includes('water')) return 'water';
    if (name.includes('terrain')) return 'terrain';
    if (name.includes('building')) return 'buildings';
    if (name.includes('veget') || name.includes('tree') || name.includes('forest')) return 'vegetation';
    return 'other';
  }

  // height → topographic colour (deep blue → green → yellow → brown → snow)
  const STOPS = [
    [0.00, 0x14324f], [0.12, 0x1f6f54], [0.38, 0x6f9a3a],
    [0.62, 0xc6b24a], [0.82, 0x8a6a44], [1.00, 0xf2f4fa],
  ];
  const _a = new THREE.Color(), _b = new THREE.Color(), _o = new THREE.Color();
  function topo(t) {
    t = Math.min(1, Math.max(0, t));
    for (let i = 1; i < STOPS.length; i++) {
      if (t <= STOPS[i][0]) {
        const [p0, c0] = STOPS[i - 1], [p1, c1] = STOPS[i];
        const k = (t - p0) / (p1 - p0 || 1);
        _a.setHex(c0); _b.setHex(c1);
        return _o.copy(_a).lerp(_b, k);
      }
    }
    return _o.setHex(STOPS[STOPS.length - 1][1]);
  }

  // ---------- load the model ----------
  const loader = new GLTFLoader();
  loader.load('/static/models/sf.glb', (gltf) => {
    const model = gltf.scene;
    model.rotation.x = -Math.PI / 2;           // Z-up (metres) → Y-up
    spinner.add(model);

    // centre the model on the spinner's axis
    let box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    model.position.sub(center);

    box = new THREE.Box3().setFromObject(spinner);
    const size = box.getSize(new THREE.Vector3());
    span = Math.max(size.x, size.z) || 1000;
    const minY = box.min.y, relief = Math.max(size.y, 1);

    // catalogue meshes; precompute topographic vertex colours from height
    model.traverse((o) => {
      if (!o.isMesh) return;
      const kind = classify(o.name || (o.parent && o.parent.name));
      const m = o.material;
      m.vertexColors = true;
      m.envMapIntensity = 0.6;
      o.castShadow = true; o.receiveShadow = true;
      if (kind === 'water') {
        m.roughness = 0.07; m.metalness = 0.15; m.transparent = true;
        m.opacity = 0.72; m.depthWrite = false; m.envMapIntensity = 1.0;
        o.castShadow = o.receiveShadow = false; m.color.setRGB(1, 1, 1);
      } else if (kind === 'buildings') {
        m.roughness = 0.6; m.metalness = 0.08;
      } else {
        m.roughness = 0.95; m.metalness = 0.0;
      }

      // build a height-coloured attribute (world Y), used by topographic mode
      const g = o.geometry;
      const pos = g.attributes.position;
      const topoCol = new Float32Array(pos.count * 3);
      const v = new THREE.Vector3();
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i); o.localToWorld(v);
        const c = topo((v.y - minY) / relief);
        topoCol[i * 3] = c.r; topoCol[i * 3 + 1] = c.g; topoCol[i * 3 + 2] = c.b;
      }
      meshes.push({
        mesh: o, kind,
        baseColor: g.attributes.color ? g.attributes.color.clone() : null,
        topoColor: new THREE.BufferAttribute(topoCol, 3),
      });
    });

    // camera framing — a low, cinematic 3/4 angle, kept fairly close
    camera.position.set(span * 0.6, Math.max(size.y * 1.7, span * 0.42), span * 0.7);
    camera.lookAt(0, 0, 0);
    camera.near = span / 800; camera.far = span * 60;
    camera.updateProjectionMatrix();

    // sun placement + shadow frustum
    const dir = new THREE.Vector3().setFromSphericalCoords(
      1, THREE.MathUtils.degToRad(48), THREE.MathUtils.degToRad(315));
    skyU['sunPosition'].value.copy(dir);
    sun.position.copy(dir).multiplyScalar(span * 1.6);
    sun.target.position.set(0, 0, 0);
    const s = span * 0.72, cam = sun.shadow.camera;
    cam.left = -s; cam.right = s; cam.top = s; cam.bottom = -s;
    cam.near = span * 0.05; cam.far = span * 4.5; cam.updateProjectionMatrix();
    scene.fog = new THREE.Fog(0x0a0a0b, span * 3.0, span * 9.0);

    applyMode(0);
    canvas.classList.add('ready');
  });

  // ---------- texture modes ----------
  const MODES = [
    { name: 'satellite',   apply: m => paint(m, 'base') },
    { name: 'wireframe',   apply: m => paint(m, 'base', { wire: true }) },
    { name: 'topographic', apply: m => paint(m, 'topo') },
    { name: 'blueprint',   apply: m => paint(m, 'mono') },
  ];

  function paint(entry, scheme, opts = {}) {
    const { mesh, kind, baseColor, topoColor } = entry;
    const m = mesh.material, g = mesh.geometry;
    m.wireframe = !!opts.wire;
    mesh.visible = !(kind === 'water' && opts.wire);

    if (scheme === 'mono') {
      // blueprint: dark surfaces, vermilion glow on the edges
      if (g.attributes.color) g.deleteAttribute('color');
      m.vertexColors = false;
      m.color.setHex(kind === 'buildings' ? 0x10131c : 0x0b0e16);
      m.emissive.setHex(0xff4a1c);
      m.emissiveIntensity = kind === 'buildings' ? 0.22 : 0.07;
      m.metalness = 0.1; m.roughness = 0.8; m.wireframe = false;
    } else {
      m.emissive.setHex(0x000000); m.emissiveIntensity = 1;
      m.vertexColors = true;
      if (scheme === 'topo') g.setAttribute('color', topoColor);
      else if (baseColor) g.setAttribute('color', baseColor.clone());
      m.color.setRGB(1, 1, 1);   // white base so vertex colours show unmodified
    }
    m.needsUpdate = true;
  }

  let modeIdx = 0;
  function applyMode(i) {
    modeIdx = i;
    for (const e of meshes) MODES[i].apply(e);
    sky.visible = MODES[i].name !== 'blueprint';
    scene.background = MODES[i].name === 'blueprint' ? new THREE.Color(0x05070d) : null;
    if (label) {
      label.textContent = MODES[i].name;
      label.classList.remove('flash'); void label.offsetWidth; label.classList.add('flash');
    }
  }

  if (!reduceMotion) {
    setInterval(() => applyMode((modeIdx + 1) % MODES.length), 5000);
  }

  // ---------- resize + render loop ----------
  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  let last = performance.now();
  (function animate(now) {
    requestAnimationFrame(animate);
    const dt = (now - last) / 1000; last = now;
    if (!reduceMotion) spinner.rotation.y += dt * 0.07;
    renderer.render(scene, camera);
  })(performance.now());
}
