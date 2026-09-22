'use strict';
const assert=require('node:assert/strict');
const Client=require('../web/client.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class Socket {
  static all=[];
  constructor(url){this.url=url;this.sent=[];Socket.all.push(this);}
  send(wire){this.sent.push(JSON.parse(wire));}
  close(){this.closed=true;}
}
global.WebSocket=Socket;
(async()=>{
  const client=new Client();
  const first=client.connectWebSocket('ws://first/ws','test').catch(e=>e.message);
  const a=Socket.all.at(-1);a.onopen();await tick();
  const second=client.connectWebSocket('ws://second/ws','test');
  const b=Socket.all.at(-1);b.onopen();await tick();
  const auth=b.sent[0];
  b.onmessage({data:JSON.stringify({id:auth.id,ok:true,simulator:true})});
  await second;await first;await tick();
  assert(client.connected&&!b.closed,'old auth must not disconnect new connection');
  assert(client.simulator,'simulator flag must survive authentication');
  const command=client.setBrightness(64);const wire=b.sent.at(-1);
  assert.deepEqual({op:wire.op,value:wire.value},{op:'brightness',value:64});
  b.onmessage({data:JSON.stringify({id:wire.id,ok:true})});assert((await command).ok);
  const clock=client.syncClock();const clockWire=b.sent.at(-1);
  assert.equal(clockWire.op,'clock');assert(Number.isInteger(clockWire.epoch));assert(Number.isInteger(clockWire.utc_offset_min));
  b.onmessage({data:JSON.stringify({id:clockWire.id,ok:true})});assert((await clock).ok);
  const showTime=client.showTime();const timeWire=b.sent.at(-1);assert.equal(timeWire.op,'time');
  b.onmessage({data:JSON.stringify({id:timeWire.id,ok:true})});assert((await showTime).ok);
  client.disconnect();
  const unopened=client.connectWebSocket('ws://third/ws','test').catch(e=>e.message);
  client.disconnect();
  assert.equal(await unopened,'connection_cancelled','pre-open disconnect must settle connect');
  let finishChunk;const oldWrites=[],newWrites=[];
  client.mode='ble';client.connected=true;client._ready=true;
  client._write={writeValueWithResponse:bytes=>{oldWrites.push([...bytes]);return new Promise(resolve=>finishChunk=resolve);}};
  const pending=client.showText('A'.repeat(64));await tick();
  client.disconnect();client.mode='ble';client.connected=true;client._ready=true;
  client._write={writeValueWithResponse:async bytes=>{newWrites.push([...bytes]);}};
  finishChunk();await pending;await tick();await tick();
  assert.equal(oldWrites.length,1);assert.equal(newWrites.length,0,'old BLE chunks must never reach new characteristic');
  assert(client.connected,'old write failure must not disconnect new session');
  client.disconnect();
  console.log('PASS client: auth isolation, clock sync, cancellation, simulator label, BLE chunk isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
