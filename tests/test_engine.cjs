'use strict';
const assert = require('node:assert/strict');
require('../web/data.js');
const exported = require('../web/engine.js');
const Engine = exported.IconEngine || exported;
const fresh = () => new Engine(globalThis.IconData);
const ok = (engine, cmd, now = 0) => {
  const r = engine.execute(cmd, now);
  assert.equal(r.ok, true, JSON.stringify(r));
  return r;
};
const lit = frame => frame.some(rgb => rgb.some(v => v > 0));
const engine = fresh();
assert(lit(engine.frame(0)), 'boot must show matrix rain');
assert.notDeepEqual(engine.frame(0),engine.frame(1000),'matrix rain must move');
const seam=fresh();
const rainCounts=[], rainGreens=new Set();
for (let t=0;t<=5000;t+=250) for (const [i,rgb] of seam.frame(t).entries()) {
  if (!rgb.some(v=>v>0)) continue;
  assert([0,1,2,4,5,7].includes(i%8), 'rain uses only six vertical lanes');
  assert.equal(rgb[0]+rgb[2],0,'rain is pure green');
  rainGreens.add(rgb[1]);
}
const density=fresh();
for(let t=0;t<=15000;t+=200) rainCounts.push(density.frame(t).filter(rgb=>rgb[1]>0).length);
assert(Math.max(...rainCounts)-Math.min(...rainCounts)>=4,'rain density varies');
assert(rainGreens.size>=4,'rain has varied green depths');
const wink=fresh();
const rain=wink.frame(0);
const smile=wink.frame(42000);
assert.deepEqual(smile,wink.frame(45000),'brief smile must remain still');
const open=wink.frame(46000);
const closed=wink.frame(48100);
assert.notDeepEqual(closed,open,'wink closes one eye once');
ok(wink,{id:90,op:'idle',mode:'pet'},48100);
assert.deepEqual(wink.frame(48100),closed,'repeated idle pet must not restart a wink');
assert.notDeepEqual(wink.frame(48200),smile,'wink returns to matrix rain');
const heart=fresh();
heart.frame(0);
const heartFrame=heart.frame(97200);
assert.notDeepEqual(heartFrame,rain,'heart appears after a rain dwell');
assert.notDeepEqual(heart.frame(99400),heartFrame,'heart ends after one preview cycle');
ok(engine, {id: 1, op: 'show', icon: 'success'});
assert(lit(engine.frame(0)), 'success must be visible');
assert(Math.max(...engine.frame(0).flat()) <= 64, 'default brightness must be 25%');
const before = engine.frame(0);
assert.equal(engine.execute({id: 2, op: 'show', icon: 'nonexistent'}, 0).ok, false);
assert.deepEqual(engine.frame(0), before, 'invalid command must preserve display');
for (const command of [
  {op:'brightness',value:-1}, {op:'brightness',value:256}, {op:'speed',value:0},
  {op:'text',text:'中文'}, {op:'text',text:'x'.repeat(65)},
  {op:'text',text:'100%',scroll:{mode:'never'}},
  {op:'show',icon:'loading',effect:{type:'blink',period_ms:100}},
  {op:'show',icon:'loading',color:{mode:'solid',values:['not-a-color']}},
]) {
  assert.equal(engine.execute({...command,id:3}, 0).ok, false, JSON.stringify(command));
}
ok(engine, {id:4,op:'show',icon:'loading',duration_ms:1000}, 0);
const frame = engine.frame(200);
ok(engine, {id:5,op:'pause'}, 200);
assert.deepEqual(engine.frame(500), frame, 'pause freezes visual phase');
assert.equal(engine.getState(1001).content,null,'TTL expires while paused and restores pet');
ok(engine, {id:6,op:'show',icon:'loading',duration_ms:1000}, 1100);
assert.equal(engine.execute({id:7,op:'keepalive',target_id:4},1500).ok,false);
ok(engine, {id:8,op:'keepalive',target_id:6},1500);
assert(lit(engine.frame(2200)), 'keepalive renews TTL');
assert.equal(engine.getState(2501).content,null,'renewed TTL still expires');
ok(engine, {id:9,op:'idle',mode:'pet'}, 2600);
assert(lit(engine.frame(2600)), 'pet should be visible');
ok(engine, {id:10,op:'show',icon:'success',duration_ms:100}, 2600);
assert(lit(engine.frame(2800)), 'expiration restores pet');
ok(engine, {id:11,op:'off'}, 2800);
assert(!lit(engine.frame(50000)), 'off must disable pet');
const text = fresh();
ok(text, {id:12,op:'text',text:'100%',scroll:{step_ms:80,repeat:1}}, 0);
assert(!lit(text.frame(0)), 'scroll starts outside');
assert(lit(text.frame(640)), 'text enters pixel by pixel');
assert.equal(text.getState(10000).content,null,'one-pass text releases to pet');
ok(text, {id:13,op:'text',text:'7'}, 11000);
assert(lit(text.frame(60000)), 'short static text does not expire by repeat');
const speed = fresh();
ok(speed, {id:14,op:'show',icon:'loading'}, 0);
const phase = speed.frame(200);
ok(speed, {id:15,op:'speed',value:2}, 200);
assert.deepEqual(speed.frame(200), phase, 'speed must not reset phase');
const reference = fresh();
ok(reference, {id:16,op:'show',icon:'loading'}, 0);
assert.deepEqual(speed.frame(300),reference.frame(400),'speed must scale elapsed time');
const power = fresh();
ok(power, {id:17,op:'brightness',value:255});
ok(power, {id:18,op:'show',icon:'heart',color:{mode:'solid',values:['white']}});
const estimated = 64 + power.frame(0).flat().reduce((a,b)=>a+b,0)*20/255;
assert(estimated <= 501, `power budget: ${estimated}`);
console.log('PASS engine: atomic validation, 25% brightness, TTL, pause, renewal, pet, text, speed, power');

const modes = fresh();
for (const mode of ['solid','step','gradient','rainbow_cycle','rainbow_flow','rainbow_orbit']) {
  const color = {mode,period_ms:4000};
  if (mode==='solid') color.values=['pink'];
  if (mode==='step'||mode==='gradient') color.values=['red','blue'];
  ok(modes,{id:20,op:'show',icon:'loading',color,effect:{type:'breathe',period_ms:2000,min:20,max:255},duration_ms:0},0);
  assert(lit(modes.frame(500)),mode);
}
ok(modes,{id:21,op:'text',text:'100%',scroll:{repeat:0,step_ms:20}},1000);
assert.equal(modes.execute({id:22,op:'speed',value:2},1000).ok,false,'reject speed that exceeds pixel step rate');
assert.equal(modes.getState(1000).speed,1,'invalid speed is atomic');
ok(modes,{id:23,op:'show',icon:'loading',animation:{enabled:false},duration_ms:86400000},1100);
assert.deepEqual(modes.frame(1200),modes.frame(1800),'static representative frame');
assert.equal(modes.execute({id:24,op:'show',icon:'success',animation:{enabled:true}},1800).ok,false);
assert.equal(modes.execute({id:25,op:'show',icon:'loading',effect:{type:'blink',min:10}},1800).ok,false);
ok(modes,{id:26,op:'show',icon:'success',duration_ms:1000},2000);
ok(modes,{id:27,op:'idle',mode:'pet'},2100);
assert.equal(modes.getState(2100).current_id,26,'idle command must not replace overlay');
const saved=modes.getState(2100);
assert.equal(modes.execute({id:28,op:'show',icon:'missing',brightness:255},2100).ok,false);
assert.equal(modes.getState(2100).brightness,saved.brightness,'invalid show must not partially set brightness');
assert.equal(modes.execute({op:'off'},2100).ok,false,'ID required');
console.log('PASS protocol: all color modes, static frame, infinite scroll, speed limits, full-day TTL, atomic idle/config');
for(const bad of [{icon:['success']},{icon:'success',duration_ms:null}]){
  const previous=modes.getState(2100);
  assert.equal(modes.execute({id:29,op:'show',brightness:255,...bad},2100).ok,false);
  assert.deepEqual(modes.getState(2100),previous,'malformed parameter rejection must be atomic');
}
for(const content of [{op:'show',icon:'success',duration_ms:1000},{op:'text',text:'100%'}]){
  const continuous=fresh(), sparse=fresh();
  for(const e of [continuous,sparse]){ok(e,{id:30,op:'idle',mode:'pet'},0);ok(e,{id:31,...content},0);}
  for(let t=0;t<=21100;t+=100) continuous.frame(t);
  assert.deepEqual(sparse.frame(21100),continuous.frame(21100),'pet phase cannot depend on polling frequency');
}
console.log('PASS reviewer regressions: strict icon/duration types and sparse-tick pet restoration');
