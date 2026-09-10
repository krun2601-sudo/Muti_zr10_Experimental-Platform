/** 仅用于显示范围和相机取景的数学；不参与观测、定位或设备动作。 */
export const AXES = ['x', 'y', 'z'];
export const finitePoint = p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);

export function checkedBounds(value) {
  const result = {};
  for (const axis of AXES) {
    const pair = value?.[axis];
    if (!Array.isArray(pair) || pair.length !== 2 || !pair.every(Number.isFinite)
        || pair[1] - pair[0] < .01 || pair.some(v => Math.abs(v) > 1e7)) {
      throw new Error(`${axis.toUpperCase()} 范围应为有限数值，最大值至少比最小值大 0.01 米，坐标绝对值不超过 1000 万米`);
    }
    result[axis] = [...pair];
  }
  return result;
}

export function corners(bounds) {
  return bounds.x.flatMap(x => bounds.y.flatMap(y => bounds.z.map(z => [x, y, z])));
}

export function pointBounds(points, padding = .12, minimumSpan = 2) {
  const finite = points.filter(finitePoint);
  if (!finite.length) return {x: [-5, 5], y: [-5, 5], z: [0, 10]};
  return Object.fromEntries(AXES.map((axis, i) => {
    const low = Math.min(...finite.map(p => p[i])), high = Math.max(...finite.map(p => p[i]));
    const center = (low + high) / 2;
    const half = Math.max(minimumSpan, high - low) * (.5 + padding);
    return [axis, [center - half, center + half]];
  }));
}

export function displayBounds(data, scope = 'devices', custom = null, selected = null) {
  if (scope === 'custom' && custom) return checkedBounds(custom);
  const devices = (data?.devices || []).filter(d => d.enabled !== false && finitePoint(d.position_m));
  if (scope === 'roi' && data?.roi) return checkedBounds(data.roi);
  if (scope === 'selected') {
    const device = devices.find(d => d.id === selected);
    const group = pointBounds(devices.map(d => d.position_m));
    const scale = Math.max(.025, Math.min(1, Math.max(...AXES.map(a => group[a][1] - group[a][0])) / 100));
    // 与渲染器的站点符号尺度一致，单台聚焦时也容纳模型及其上方标签。
    return pointBounds(device ? [device.position_m] : devices.map(d => d.position_m), .12, Math.max(2, 14 * scale));
  }
  const points = devices.map(d => d.position_m);
  if (scope === 'all') {
    if (data?.roi) points.push(...corners(checkedBounds(data.roi)));
    for (const device of devices) {
      if (device.valid || device.frustum?.is_preview) points.push(...(device.frustum?.boundary || device.frustum?.corners || []));
    }
    points.push(...(data?.tracks || []).filter(t => t.valid !== false).map(t => t.position_m));
  }
  return pointBounds(points);
}

/** 给定相机正交基，逐个检查角点，以纵/横视角中较紧的约束决定距离。 */
export function fitDistance(points, center, right, up, forward, verticalFovDeg, aspect) {
  const tanV = Math.tan(verticalFovDeg * Math.PI / 360), tanH = tanV * aspect;
  const dot = (a, b) => a.reduce((sum, v, i) => sum + v * b[i], 0);
  let distance = .1;
  for (const point of points) {
    const offset = point.map((v, i) => v - center[i]);
    // forward 朝场景内；角点越靠近相机，所需中心距离越大。
    const depth = dot(offset, forward);
    distance = Math.max(distance, Math.abs(dot(offset, right)) / tanH * 1.18 - depth,
      Math.abs(dot(offset, up)) / tanV * 1.18 - depth, -depth + .1);
  }
  return distance;
}

/** 网格间距使用 1/2/5 × 10^n，避免小场地仍被固定50米网格撑大。 */
export function gridStep(span) {
  const raw = Math.max(.01, span) / 10;
  const base = 10 ** Math.floor(Math.log10(raw));
  const value = raw / base;
  return (value <= 1 ? 1 : value <= 2 ? 2 : value <= 5 ? 5 : 10) * base;
}
