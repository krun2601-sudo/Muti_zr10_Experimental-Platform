/** 三维区域专用交互：显示范围留在浏览器；任务ROI通过原配置接口校验。 */
import {AXES, checkedBounds} from './scene_math.js';
const $ = id => document.getElementById(id);
const names = {devices: '设备群', selected: '选中设备', roi: '观测区域', all: '全部观测内容', custom: '自定义范围'};
const storageKey = 'zr10-scene-view-v1';
const numeric = v => String(Number(v.toFixed(3)));

export class SceneControls {
  constructor(view, {snapshot, applyRoi, notify}) {
    this.view = view;
    this.snapshot = snapshot;
    this.applyRoi = applyRoi;
    this.notify = notify;
    this.spaceDirty = this.roiDirty = this.busy = false;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (saved && names[saved.scope]) {
        if (saved.scope === 'custom') view.customBounds = checkedBounds(saved.bounds);
        view.viewScope = saved.scope;
        view.setNavigation(saved.navigation);
      }
    } catch { /* 损坏的浏览器偏好只重置显示，不影响实验配置。 */ }
    this.run = action => async event => {
      event.preventDefault();
      try {await action(event);} catch (error) {notify(error.message, true);}
    };
    $('scene-settings-toggle').addEventListener('click', () => {
      const open = $('scene-settings').hidden;
      $('scene-settings').hidden = !open;
      $('scene-settings-toggle').setAttribute('aria-expanded', String(open));
      this.syncSpace();
    });
    for (const mode of ['rotate', 'pan']) $('scene-' + mode).addEventListener('click', () => {
      view.setNavigation(mode); this.updateNavigation(); this.remember();
    });
    document.querySelectorAll('[data-scene-scope]').forEach(button => button.addEventListener('click', this.run(() => {
      this.spaceDirty = false;
      view.setScope(button.dataset.sceneScope); this.syncSpace(); this.remember();
    })));
    document.querySelectorAll('[data-pan]').forEach(button => button.addEventListener('click', () => view.panScreen(...button.dataset.pan.split(',').map(Number))));
    $('scene-zoom-in').addEventListener('click', () => view.zoomBy(.8));
    $('scene-zoom-out').addEventListener('click', () => view.zoomBy(1.25));
    $('scene-space-source').addEventListener('change', this.run(() => {
      const scope = $('scene-space-source').value;
      if (scope === 'custom') {this.spaceDirty = true; return;}
      this.spaceDirty = false;
      view.setScope(scope); this.syncSpace(); this.remember();
    }));
    $('scene-space-form').querySelectorAll('input').forEach(input => input.addEventListener('input', () => {
      this.spaceDirty = true; $('scene-space-source').value = 'custom';
    }));
    $('scene-space-form').addEventListener('submit', this.run(() => {
      const bounds = this.readBounds('space');
      view.setScope('custom', bounds); this.spaceDirty = false;
      this.syncSpace(); this.remember(); notify('显示范围已应用');
    }));
    $('scene-roi-form').querySelectorAll('input').forEach(input => input.addEventListener('input', () => {this.roiDirty = true;}));
    $('scene-roi-reset').addEventListener('click', () => {
      this.roiDirty = false; this.roiKey = null; this.update(this.snapshot());
    });
    $('scene-roi-form').addEventListener('submit', this.run(async () => {
      if (this.busy) return;
      const current = this.snapshot();
      if (!current || !['idle', 'stopped', 'error'].includes(current.status)) throw new Error('请先结束实验，再修改任务观测区域');
      const roi = this.readBounds('roi');
      this.busy = true; this.update(current);
      try {
        await applyRoi(roi);
        this.roiDirty = false; this.roiKey = null;
        this.spaceDirty = false; view.setScope('roi'); this.syncSpace(); this.remember();
        notify('任务观测区域已应用', false, '需要下次继续使用时，请在“实验配置”中保存配置文件。');
      } finally {this.busy = false; this.update(this.snapshot());}
    }));
    view.container.addEventListener('sceneviewchange', event => {
      const {target, distance, scope} = event.detail;
      $('scene-scope-note').textContent = `显示范围：${names[scope]}`;
      $('scene-pivot-note').textContent = `旋转中心 (${target.map(numeric).join(', ')}) m · 视距 ${numeric(distance)} m`;
      this.syncSpace();
    });
    this.updateNavigation();
  }

  readBounds(prefix) {
    const result = {};
    for (const axis of AXES) result[axis] = ['min', 'max'].map(end => {
      const input = $(prefix + '-' + axis + '-' + end);
      if (!input.value.trim()) throw new Error('请完整填写 X/Y/Z 的最小值和最大值');
      return Number(input.value);
    });
    return checkedBounds(result);
  }

  writeBounds(prefix, bounds) {
    for (const axis of AXES) ['min', 'max'].forEach((end, i) => {
      const value = bounds[axis][i];
      $(prefix + '-' + axis + '-' + end).value = Number(prefix === 'space' && this.view.viewScope !== 'custom' ? value.toFixed(3) : value.toPrecision(12));
    });
  }

  syncSpace() {
    if (this.spaceDirty || !this.view.data) return;
    $('scene-space-source').value = this.view.viewScope;
    this.writeBounds('space', this.view.referenceBounds || this.view.getBounds());
    document.querySelectorAll('[data-scene-scope]').forEach(button => {
      const selected = button.dataset.sceneScope === this.view.viewScope;
      button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
    });
  }

  remember() {
    try {sessionStorage.setItem(storageKey, JSON.stringify({scope: this.view.viewScope, bounds: this.view.customBounds, navigation: this.view.navigationMode}));} catch { /* 无存储权限时仍可操作。 */ }
  }

  updateNavigation() {
    const pan = this.view.navigationMode === 'pan';
    for (const mode of ['rotate', 'pan']) {
      $('scene-' + mode).classList.toggle('active', (mode === 'pan') === pan);
      $('scene-' + mode).setAttribute('aria-pressed', String((mode === 'pan') === pan));
    }
    document.querySelector('.scene-instructions').textContent = `${pan ? '左键平移' : '左键旋转'} · 右键平移 · 滚轮朝鼠标缩放 · 双击设置旋转中心`;
  }

  update(snapshot) {
    if (!snapshot) return;
    const roi = snapshot.config?.policy?.roi;
    const key = JSON.stringify(roi);
    if (roi && !this.roiDirty && key !== this.roiKey) {this.writeBounds('roi', roi); this.roiKey = key;}
    const locked = this.busy || !['idle', 'stopped', 'error'].includes(snapshot.status);
    $('scene-roi-form').querySelectorAll('input,button').forEach(input => {input.disabled = locked;});
    $('scene-roi-note').textContent = locked ? '实验进行中，任务区域已锁定。左侧显示范围和平移缩放仍可自由调整。'
      : '应用到任务配置。需要下次继续使用时，在“实验配置”中保存配置文件。';
    $('scene-roi-scan-note').hidden = !snapshot.config?.policy?.scan_points_m?.length;
    this.syncSpace();
  }
}
