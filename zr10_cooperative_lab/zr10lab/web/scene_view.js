/**
 * 三维视图只负责渲染服务端生成的 ENU 几何，不自行换算云台角度。
 * Three.js 默认 y 向上，这里明确采用 z 向上，使 x 东、y 北、z 上与定位模块一致。
 * 每次移除动态几何时同步释放 GPU 对象，长时间实验不会不断累积显存。
 */
import * as THREE from 'three';
import {OrbitControls} from '/vendor/OrbitControls.js';
import {checkedBounds, corners, displayBounds, fitDistance, gridStep} from './scene_math.js';

export const DEVICE_COLORS = ['#14899c', '#4382e7', '#9a6cdd', '#d79135', '#ce6f9c', '#639855'];
const finitePoint = p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);

function disposeObject(object) {
  object.traverse(child => {
    child.geometry?.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials) {
      if (!material) continue;
      material.map?.dispose();
      material.dispose();
    }
  });
  object.removeFromParent();
}

function label(text, color = '#668195', scale = 12, minimumPixels = 22) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = '500 25px "Segoe UI", "Microsoft YaHei", sans-serif';
  canvas.width = Math.ceil(ctx.measureText(text).width) + 26;
  canvas.height = 44;
  ctx.font = '500 25px "Segoe UI", "Microsoft YaHei", sans-serif';
  ctx.fillStyle = '#ffffffeb';
  ctx.beginPath();
  ctx.roundRect(0, 0, canvas.width, canvas.height, 8);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, canvas.width / 2, 23);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, transparent: true, depthTest: false}));
  sprite.scale.set(scale * canvas.width / canvas.height, scale, 1);
  // 保留世界尺寸用于近看自然缩放，同时给远景设置可读像素下限。
  // 实际换算在绘制前按相机深度更新，缩放/旋转/窗口尺寸变化后仍然清晰。
  sprite.userData.label = {baseHeight: scale, aspect: canvas.width / canvas.height,
    minimumPixels, maximumPixels: minimumPixels + 10};
  sprite.renderOrder = 9;
  return sprite;
}

function line(points, color, dashed = false, opacity = 1) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points.map(p => new THREE.Vector3(...p)));
  const material = dashed
    ? new THREE.LineDashedMaterial({color, dashSize: 2, gapSize: 1.6, transparent: true, opacity})
    : new THREE.LineBasicMaterial({color, transparent: true, opacity});
  const object = new THREE.Line(geometry, material);
  if (dashed) object.computeLineDistances();
  return object;
}

export class SceneView {
  constructor(container, onSelect) {
    this.container = container;
    this.onSelect = onSelect;
    this.data = null;
    this.hiddenDevices = new Set();
    this.deviceGroups = new Map();
    this.trackGroups = new Map();
    this.histories = new Map();
    this.flags = {roi: true, frusta: true, trails: true};
    this.selected = null;
    this.sizeScale = 1;
    this.viewScope = 'devices';
    this.customBounds = null;
    this.navigationMode = 'rotate';
    this.fitted = false;
    this.needsRender = true;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#f5f8fb');
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1000000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(240, -250, 200);
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, preserveDrawingBuffer: true});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.setAttribute('aria-label', 'ENU 三维设备、视场与轨迹视图');
    this.renderer.domElement.tabIndex = 0;
    this.container.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = .12;
    this.controls.minDistance = .05;
    this.controls.maxDistance = 1e8;
    this.controls.screenSpacePanning = true;
    this.controls.zoomToCursor = true;
    this.controls.panSpeed = 1;
    this.controls.zoomSpeed = .85;
    this.controls.addEventListener('change', () => {this.needsRender = true; this.publishView();});
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb5c7d6, 2.7));
    const sun = new THREE.DirectionalLight(0xffffff, 2.1);
    sun.position.set(40, -100, 200);
    this.scene.add(sun);
    this.referenceGroup = new THREE.Group();
    this.roiGroup = new THREE.Group();
    this.scene.add(this.referenceGroup, this.roiGroup);
    this.pointer = new THREE.Vector2();
    this.raycaster = new THREE.Raycaster();
    this.pointerStart = null;
    this.renderer.domElement.addEventListener('pointerdown', e => {
      this.renderer.domElement.focus({preventScroll: true});
      this.pointerStart = [e.clientX, e.clientY, e.button];
    });
    this.renderer.domElement.addEventListener('pointerup', e => {
      if (!this.pointerStart || this.pointerStart[2] !== 0 || Math.hypot(e.clientX - this.pointerStart[0], e.clientY - this.pointerStart[1]) > 5) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.pointer.set((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1);
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hits = this.raycaster.intersectObjects([...this.deviceGroups.values()].filter(g => g.visible), true);
      const hit = hits.find(h => h.object.userData.deviceId);
      if (hit) this.onSelect?.(hit.object.userData.deviceId);
    });
    this.renderer.domElement.addEventListener('dblclick', e => this.focusAtPointer(e));
    this.renderer.domElement.addEventListener('keydown', e => {
      const delta = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]}[e.key];
      if (delta) {e.preventDefault(); this.panScreen(...delta.map(v => v * (e.shiftKey ? 3 : 1)));}
      else if (['+', '=', '-', '_'].includes(e.key)) {e.preventDefault(); this.zoomBy(['+', '='].includes(e.key) ? .8 : 1.25);}
    });
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.animate();
  }

  resize() {
    const {width, height} = this.container.getBoundingClientRect();
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.needsRender = true;
  }

  animate() {
    if (this.disposed) return;
    this.animationId = requestAnimationFrame(() => this.animate());
    this.controls.update();
    // 页面在后台时不主动绘制；数据轮询由主界面继续负责控制心跳。
    if (this.needsRender && !document.hidden) {
      this.updateLabelSizes();
      this.renderer.render(this.scene, this.camera);
      this.needsRender = false;
    }
  }

  updateLabelSizes() {
    const height = this.renderer.domElement.clientHeight;
    if (!height) return;
    const forward = this.camera.getWorldDirection(new THREE.Vector3());
    const position = new THREE.Vector3();
    const offset = new THREE.Vector3();
    const tangent = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.scene.traverse(object => {
      const data = object.userData.label;
      if (!data) return;
      object.getWorldPosition(position);
      const depth = Math.max(this.camera.near, offset.copy(position).sub(this.camera.position).dot(forward));
      const unitsPerPixel = 2 * depth * tangent / height;
      const naturalPixels = data.baseHeight / unitsPerPixel;
      const pixels = THREE.MathUtils.clamp(naturalPixels, data.minimumPixels, data.maximumPixels);
      const worldHeight = pixels * unitsPerPixel;
      object.scale.set(worldHeight * data.aspect, worldHeight, 1);
    });
  }

  setFlag(name, value) {
    this.flags[name] = value;
    this.roiGroup.visible = this.flags.roi;
    for (const group of this.deviceGroups.values()) {
      const frustum = group.getObjectByName('frustum');
      if (frustum) frustum.visible = this.flags.frusta;
    }
    for (const group of this.trackGroups.values()) {
      const trail = group.getObjectByName('trail');
      if (trail) trail.visible = this.flags.trails;
    }
    this.needsRender = true;
  }

  setDeviceVisible(id, visible) {
    visible ? this.hiddenDevices.delete(id) : this.hiddenDevices.add(id);
    if (this.deviceGroups.has(id)) this.deviceGroups.get(id).visible = visible;
    this.needsRender = true;
  }

  select(id) {this.selected = id; if (this.data) this.update(this.data);}

  getBounds() {return displayBounds(this.data, this.viewScope, this.customBounds, this.selected);}

  setScope(scope, bounds = null) {
    if (!['devices', 'selected', 'roi', 'all', 'custom'].includes(scope)) throw new Error('未知显示范围');
    if (scope === 'custom') this.customBounds = checkedBounds(bounds || this.customBounds);
    this.viewScope = scope;
    this.referenceKey = null;
    if (this.data) this.update(this.data);
    this.fit();
  }

  setNavigation(mode) {
    this.navigationMode = mode === 'pan' ? 'pan' : 'rotate';
    this.controls.mouseButtons.LEFT = this.navigationMode === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    this.controls.touches.ONE = this.navigationMode === 'pan' ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
    this.renderer.domElement.style.cursor = this.navigationMode === 'pan' ? 'grab' : 'default';
  }

  flushMotion() {
    // 消耗旧的阻尼增量，再设置新视角，防止“聚焦”后继续被上次拖拽带走。
    const damping = this.controls.enableDamping;
    this.controls.enableDamping = false;
    this.controls.update();
    this.controls.enableDamping = damping;
  }

  publishView() {
    const canvas = this.renderer?.domElement;
    if (!canvas) return;
    // 同时提供可读的当前旋转中心；测试也可通过DOM核对，而无需访问控制器内部。
    canvas.dataset.viewTarget = JSON.stringify(this.controls.target.toArray());
    canvas.dataset.viewDistance = String(this.camera.position.distanceTo(this.controls.target));
    canvas.dataset.viewScope = this.viewScope;
    const distance = Number(canvas.dataset.viewDistance);
    this.camera.near = Math.max(.0001, Math.min(1, distance / 1000));
    this.camera.far = Math.max(10000, distance * 30);
    this.camera.updateProjectionMatrix();
    this.container.dispatchEvent(new CustomEvent('sceneviewchange', {detail: {
      target: this.controls.target.toArray(), distance: Number(canvas.dataset.viewDistance), scope: this.viewScope}}));
  }

  fit(top = false) {
    if (!this.data) return;
    this.flushMotion();
    // “全部”按点击时的最新视场取景；后续实时数据不触发自动居中。
    if (this.viewScope === 'all') this.buildReference(this.data);
    const bounds = this.getBounds(), points = corners(bounds);
    const center = new THREE.Vector3(...['x', 'y', 'z'].map(a => (bounds[a][0] + bounds[a][1]) / 2));
    const direction = top ? new THREE.Vector3(0, -.0001, 1).normalize() : new THREE.Vector3(-.74, -1.15, .85).normalize();
    this.camera.position.copy(center).add(direction);
    this.camera.lookAt(center);
    this.camera.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
    const forward = this.camera.getWorldDirection(new THREE.Vector3());
    const distance = fitDistance(points, center.toArray(), right.toArray(), up.toArray(), forward.toArray(), this.camera.fov, this.camera.aspect);
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.controls.target.copy(center);
    this.controls.update();
    this.needsRender = true;
    this.publishView();
  }

  panScreen(horizontal, vertical) {
    this.flushMotion();
    this.camera.updateMatrixWorld();
    const distance = this.camera.position.distanceTo(this.controls.target);
    const step = 2 * distance * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * .08;
    const offset = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0).multiplyScalar(-horizontal * step)
      .addScaledVector(new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1), -vertical * step);
    // 平移同时改变相机与旋转中心，因此之后的旋转围绕新中心，不弹回场地中心。
    this.camera.position.add(offset);
    this.controls.target.add(offset);
    this.controls.update();
  }

  zoomBy(factor) {
    this.flushMotion();
    const offset = this.camera.position.clone().sub(this.controls.target);
    const distance = THREE.MathUtils.clamp(offset.length() * factor, this.controls.minDistance, this.controls.maxDistance);
    this.camera.position.copy(this.controls.target).add(offset.setLength(distance));
    this.controls.update();
  }

  focusAtPointer(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects([...this.deviceGroups.values()].filter(g => g.visible), true)
      .find(h => h.object.userData.deviceId);
    let point;
    if (hit) point = new THREE.Vector3(...this.data.devices.find(d => d.id === hit.object.userData.deviceId).position_m);
    else {
      // 空白处在当前焦点所在的屏幕平面选点，俯视/仰视均可使用，不依赖地面交点。
      const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(this.camera.getWorldDirection(new THREE.Vector3()), this.controls.target);
      point = this.raycaster.ray.intersectPlane(plane, new THREE.Vector3());
    }
    if (!point) return;
    this.flushMotion();
    const offset = point.clone().sub(this.controls.target);
    this.camera.position.add(offset);
    this.controls.target.copy(point);
    this.controls.update();
  }

  buildReference(data) {
    for (const c of [...this.referenceGroup.children]) disposeObject(c);
    const b = this.getBounds(), low = ['x', 'y', 'z'].map(a => b[a][0]), high = ['x', 'y', 'z'].map(a => b[a][1]);
    this.referenceBounds = b;
    const extent = Math.max(...high.map((v, i) => v - low[i]));
    // 设备符号大小跟随设备间距，不随远处ROI/大视场膨胀。
    const station = displayBounds(data, 'devices');
    this.sizeScale = Math.max(.025, Math.min(1, Math.max(...['x', 'y', 'z'].map(a => station[a][1] - station[a][0])) / 100));
    const step = gridStep(Math.max(high[0] - low[0], high[1] - low[1]));
    const floor = low[2], format = value => String(Number(value.toFixed(Math.max(0, 2 - Math.floor(Math.log10(step))))));
    // 只在明确的X/Y范围内铺网格，最多约20条/轴；坐标不强制包含远处原点。
    for (let axis = 0; axis < 2; axis++) {
      const first = Math.ceil(low[axis] / step), last = Math.floor(high[axis] / step);
      for (let i = first; i <= last; i++) {
        const value = i * step, from = [...low], to = [...high];
        from[axis] = to[axis] = value; from[2] = to[2] = floor;
        this.referenceGroup.add(line([from, to], '#d8e3ed', false, .7));
        if (i % 2) continue;
        const item = label(format(value), '#8a9fb0', extent * .015, 16);
        const at = [...low]; at[axis] = value; at[1 - axis] -= step * .35;
        item.position.set(...at); this.referenceGroup.add(item);
      }
    }
    const box = new THREE.BoxGeometry(...high.map((v, i) => v - low[i]));
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({color: '#bbccdc', transparent: true, opacity: .45}));
    outline.position.set(...high.map((v, i) => (v + low[i]) / 2));
    this.referenceGroup.add(outline); box.dispose();
    [['X 东', '#5994bf', 0], ['Y 北', '#65a790', 1], ['Z 上', '#c9a258', 2]].forEach(([text, color, axis]) => {
      const end = [...low]; end[axis] = high[axis];
      this.referenceGroup.add(line([low, end], color, false, .9));
      const item = label(`${text}  ${format(high[axis])}`, color, extent * .02, 19);
      item.position.set(...end); this.referenceGroup.add(item);
    });
    this.renderer.domElement.dataset.displayBounds = JSON.stringify(b);
  }

  buildRoi(roi) {
    for (const c of [...this.roiGroup.children]) disposeObject(c);
    if (!roi || !['x', 'y', 'z'].every(k => Array.isArray(roi[k]) && roi[k].length === 2)) return;
    const geometry = new THREE.BoxGeometry(roi.x[1] - roi.x[0], roi.y[1] - roi.y[0], roi.z[1] - roi.z[0]);
    const edges = new THREE.EdgesGeometry(geometry);
    const frame = new THREE.LineSegments(edges, new THREE.LineDashedMaterial({color: '#a7b8ca', dashSize: 2.3, gapSize: 1.8, transparent: true, opacity: .7}));
    frame.position.set((roi.x[1] + roi.x[0]) / 2, (roi.y[1] + roi.y[0]) / 2, (roi.z[1] + roi.z[0]) / 2);
    frame.computeLineDistances();
    this.roiGroup.add(frame);
    geometry.dispose();
    const title = label('观测区域 ROI', '#889fb2', 4.2 * this.sizeScale);
    title.position.set(frame.position.x, roi.y[1], roi.z[1] + 4 * this.sizeScale);
    this.roiGroup.add(title);
    this.roiGroup.visible = this.flags.roi;
  }

  buildDevice(device, index, existing = null) {
    let group = existing || new THREE.Group();
    const color = DEVICE_COLORS[index % DEVICE_COLORS.length];
    const p = device.position_m;
    if (!finitePoint(p)) return group;
    const s = this.sizeScale;
    const positionKey = JSON.stringify([p, s, color]);
    if (existing && existing.userData.positionKey !== positionKey) {
      disposeObject(existing);
      existing = null;
      group = new THREE.Group();
    }
    // 站点模型与文字纹理在位置不变时复用，只替换姿态相关视锥。
    // 因此实时角度更新不会反复创建 CanvasTexture。
    let camera;
    if (!existing) {
    const marker = new THREE.Mesh(new THREE.CylinderGeometry(1.7 * s, 2.1 * s, 1.1 * s, 16), new THREE.MeshStandardMaterial({color, roughness: .5}));
    marker.rotation.x = Math.PI / 2;
    marker.position.set(p[0], p[1], p[2] - .7 * s);
    marker.userData.deviceId = device.id;
    group.add(marker);
    camera = new THREE.Mesh(new THREE.BoxGeometry(3 * s, 2.3 * s, 1.8 * s), new THREE.MeshStandardMaterial({color: '#f1f6fa', roughness: .5, metalness: .2}));
    camera.name = 'camera-body';
    camera.position.set(p[0], p[1], p[2] + .55 * s);
    camera.userData.deviceId = device.id;
    group.add(camera);
    const ring = new THREE.Mesh(new THREE.RingGeometry(3.1 * s, (device.id === this.selected ? 3.7 : 3.3) * s, 40), new THREE.MeshBasicMaterial({color, side: THREE.DoubleSide, transparent: true, opacity: device.id === this.selected ? .8 : .28}));
    ring.position.set(p[0], p[1], .1);
    ring.name = 'selection-ring';
    ring.userData.deviceId = device.id;
    group.add(ring);
    if (p[2] > .5) group.add(line([[p[0], p[1], 0], p], color, true, .35));
    const tag = label(device.id.replace('zr10_', 'ZR10 · '), color, 4.3 * s);
    tag.position.set(p[0], p[1], p[2] + 7 * s);
    tag.userData.deviceId = device.id;
    group.add(tag);
    group.userData.positionKey = positionKey;
    } else camera = group.getObjectByName('camera-body');
    const ring = group.getObjectByName('selection-ring');
    ring.material.opacity = device.id === this.selected ? .8 : .28;
    ring.scale.setScalar(device.id === this.selected ? 1.07 : 1);
    const geometryKey = JSON.stringify([device.valid, device.frustum]);
    if (group.userData.geometryKey === geometryKey) {
      group.visible = !this.hiddenDevices.has(device.id);
      return group;
    }
    group.userData.geometryKey = geometryKey;
    const oldFrustum = group.getObjectByName('frustum');
    if (oldFrustum) disposeObject(oldFrustum);
    if (device.frustum && (device.valid || device.frustum.is_preview)) {
      const f = device.frustum;
      const points = (f.boundary?.length ? f.boundary : f.corners).filter(finitePoint);
      if (points.length >= 4 && finitePoint(f.origin)) {
        const frustum = new THREE.Group();
        frustum.name = 'frustum';
        const isPreview = !device.valid;
        const vertices = [];
        for (let i = 0; i < points.length; i++) vertices.push(...f.origin, ...points[i], ...points[(i + 1) % points.length]);
        const surfaceGeometry = new THREE.BufferGeometry();
        surfaceGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
        const surface = new THREE.Mesh(surfaceGeometry, new THREE.MeshBasicMaterial({color, transparent: true, opacity: isPreview ? .025 : .065, side: THREE.DoubleSide, depthWrite: false}));
        frustum.add(surface);
        frustum.add(line([...points, points[0]], color, isPreview, isPreview ? .3 : .63));
        for (const corner of f.corners || []) if (finitePoint(corner)) frustum.add(line([f.origin, corner], color, isPreview, isPreview ? .26 : .42));
        if (finitePoint(f.center_direction)) {
          const end = f.origin.map((v, i) => v + f.center_direction[i] * f.range_m);
          frustum.add(line([f.origin, end], color, true, .35));
          // 设备小模型朝向仅由后端光轴向量决定，不从 AE 自行重建。
          camera.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), new THREE.Vector3(...f.center_direction).normalize());
        }
        frustum.visible = this.flags.frusta;
        group.add(frustum);
      }
    }
    group.visible = !this.hiddenDevices.has(device.id);
    return group;
  }

  buildTrack(track) {
    const position = track.position_m || track.position;
    if (!finitePoint(position) || track.valid === false) return null;
    const group = new THREE.Group();
    const s = this.sizeScale;
    const measured = track.measured === true;
    const color = measured ? '#e97960' : '#d69b79';
    const point = new THREE.Mesh(new THREE.SphereGeometry(1.8 * s, 16, 10), new THREE.MeshBasicMaterial({color, wireframe: !measured, transparent: true, opacity: measured ? .95 : .8}));
    point.position.set(...position);
    group.add(point);
    const tag = label(`${track.track_id} · ${measured ? '测量' : '预测'}`, color, 3.8 * s);
    tag.position.set(position[0], position[1], position[2] + 6 * s);
    group.add(tag);
    group.add(line([position, [position[0], position[1], 0]], color, true, .18));
    let history = this.histories.get(track.track_id) || [];
    // 采用后台保存的有来源历史，页面刷新后也能恢复测量/预测虚实线。
    // 旧history只有坐标，无法证明其是测量点，因此不猜测其来源。
    if (Array.isArray(track.history_samples) && track.history_samples.length) {
      history = track.history_samples.filter(sample => Number.isFinite(sample.t) && finitePoint(sample.position_m))
        .slice(-480).map(sample => ({t: sample.t, p: [...sample.position_m], measured: sample.measured === true}));
      this.histories.set(track.track_id, history);
    }
    const last = history[history.length - 1];
    if (!last || track.t !== last.t) {
      history.push({t: track.t, p: [...position], measured});
      if (history.length > 480) history = history.slice(-480);
      this.histories.set(track.track_id, history);
    }
    if (history.length > 1) {
      const trail = new THREE.Group();
      trail.name = 'trail';
      // 每段的类型跟随该次更新来源，预测段始终虚线，避免误认为持续实测。
      const measuredPoints = [], predictedPoints = [];
      for (let i = 1; i < history.length; i++) {
        const target = history[i].measured ? measuredPoints : predictedPoints;
        target.push(...history[i - 1].p, ...history[i].p);
      }
      for (const [vertices, dashed] of [[measuredPoints, false], [predictedPoints, true]]) {
        if (!vertices.length) continue;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
        const material = dashed ? new THREE.LineDashedMaterial({color: '#d69b79', dashSize: 1.4, gapSize: 1, opacity: .55, transparent: true}) : new THREE.LineBasicMaterial({color: '#e97960', opacity: .7, transparent: true});
        const path = new THREE.LineSegments(geometry, material);
        if (dashed) path.computeLineDistances();
        trail.add(path);
      }
      trail.visible = this.flags.trails;
      group.add(trail);
    }
    return group;
  }

  update(data) {
    this.data = data;
    // 只有布局/范围设置变化才重新取景；遥测、目标和姿态的周期刷新不影响自由视角。
    const referenceKey = JSON.stringify([this.viewScope, this.customBounds,
      this.viewScope === 'selected' ? this.selected : null,
      this.viewScope === 'all' ? data.range_m : null,
      this.viewScope === 'roi' || this.viewScope === 'all' ? data.roi : null,
      (data.devices || []).map(d => [d.id, d.enabled, d.position_m])]);
    if (this.referenceKey !== referenceKey) {
      this.referenceKey = referenceKey;
      this.buildReference(data);
      this.fitted = false;
    }
    const roiKey = JSON.stringify(data.roi);
    if (this.roiKey !== roiKey || !this.fitted) {this.roiKey = roiKey; this.buildRoi(data.roi);}
    const newIds = new Set((data.devices || []).map(d => d.id));
    for (const [id, group] of this.deviceGroups) if (!newIds.has(id)) {disposeObject(group); this.deviceGroups.delete(id);}
    (data.devices || []).forEach((device, i) => {
      const group = this.buildDevice(device, i, this.deviceGroups.get(device.id));
      this.deviceGroups.set(device.id, group);
      if (group.parent !== this.scene) this.scene.add(group);
    });
    for (const group of this.trackGroups.values()) disposeObject(group);
    this.trackGroups.clear();
    const activeTrackIds = new Set();
    for (const track of data.tracks || []) {
      activeTrackIds.add(track.track_id);
      const group = this.buildTrack(track);
      if (group) {this.trackGroups.set(track.track_id, group); this.scene.add(group);}
    }
    for (const id of this.histories.keys()) if (!activeTrackIds.has(id)) this.histories.delete(id);
    if (!this.fitted) {this.fit(); this.fitted = true;}
    this.needsRender = true;
  }

  clearTrails() {
    this.histories.clear();
    for (const group of this.trackGroups.values()) disposeObject(group);
    this.trackGroups.clear();
    // 清场后点选站点不能把上一次场景中的轨迹重新放回来。
    if (this.data) this.data = {...this.data, tracks: []};
    this.needsRender = true;
  }

  exportImage() {
    this.updateLabelSizes();
    this.renderer.render(this.scene, this.camera);
    const anchor = document.createElement('a');
    anchor.download = `zr10_scene_${new Date().toISOString().replaceAll(':', '-')}.png`;
    anchor.href = this.renderer.domElement.toDataURL('image/png');
    anchor.click();
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.animationId);
    this.resizeObserver.disconnect();
    this.controls.dispose();
    for (const child of [...this.scene.children]) disposeObject(child);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
