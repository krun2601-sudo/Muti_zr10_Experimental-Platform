// 显示几何回归；Node仅用于开发验收，用户运行控制中心不需要Node。
import test from 'node:test';
import assert from 'node:assert/strict';
import {checkedBounds, corners, displayBounds, fitDistance, gridStep} from '../../zr10lab/web/scene_math.js';

test('小设备群不受远处ROI、视锥或世界原点撑大', () => {
  const data = {roi: {x:[100,160],y:[-50,50],z:[35,85]}, devices:[
    {id:'a',position_m:[1000,1000,2],enabled:true,valid:true,frustum:{boundary:[[2000,2000,200]]}},
    {id:'b',position_m:[1002,1002,2],enabled:true},
    {id:'unused',position_m:[1e6,1e6,1e6],enabled:false},
  ]};
  const bounds = displayBounds(data);
  assert.ok(bounds.x[1]-bounds.x[0] < 3);
  assert.ok(bounds.x[0] > 990);
  assert.ok(displayBounds(data,'all').x[1] > 2000);
  assert.deepEqual(displayBounds(data,'roi'),data.roi);
  const selected=displayBounds(data,'selected',null,'b');
  assert.equal((selected.x[0]+selected.x[1])/2,1002);
});

test('自定义坐标框严格检查，且不修改调用者数据', () => {
  const input={x:[-5,5],y:[-2,2],z:[0,3]};
  const bounds=checkedBounds(input); bounds.x[0]=-100;
  assert.equal(input.x[0],-5);
  for (const bad of [[1,1],[2,1],[0,NaN],[0,Infinity],['0',2],[0,1e8],[]]) {
    assert.throws(()=>checkedBounds({...input,x:bad}));
  }
  assert.deepEqual(displayBounds({},'custom',input),input);
});

test('网格可覆盖厘米到公里量级，间隔数量有界', () => {
  for (const span of [.05,.5,2,10,130,10000]) {
    const step=gridStep(span);
    assert.ok(step>0 && span/step <= 10+1e-10);
    assert.ok(span/step >= 2);
  }
});

test('横屏、竖屏、俯视和斜视取景都容纳所有角点', () => {
  const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const normalize=a=>a.map(v=>v/Math.hypot(...a));
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  for (const aspect of [.4,1,2,4]) for (const forward of [[0,0,-1],normalize([.74,1.15,-.85])]) {
    const right=normalize(cross(forward,forward[2]===-1?[0,1,0]:[0,0,1]));
    const up=normalize(cross(right,forward));
    for (const size of [[2,2,2],[200,5,10],[.1,.2,5],[25,20,3]]) {
      const center=[100,-40,2], bounds=Object.fromEntries(['x','y','z'].map((a,i)=>[a,[center[i]-size[i]/2,center[i]+size[i]/2]]));
      const pts=corners(bounds), distance=fitDistance(pts,center,right,up,forward,42,aspect);
      for (const p of pts) {
        const delta=p.map((v,i)=>v-center[i]), depth=distance+dot(delta,forward);
        assert.ok(depth>0);
        assert.ok(Math.abs(dot(delta,right))/(depth*Math.tan(21*Math.PI/180)*aspect)<1);
        assert.ok(Math.abs(dot(delta,up))/(depth*Math.tan(21*Math.PI/180))<1);
      }
    }
  }
});
