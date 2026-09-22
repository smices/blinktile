(function (root) {
  'use strict';
  const SERVICE='6d8f0000-6f52-4af0-9a2c-7b6143b8e100';
  const WRITE='6d8f0001-6f52-4af0-9a2c-7b6143b8e100';
  const NOTIFY='6d8f0002-6f52-4af0-9a2c-7b6143b8e100';
  const encoder=new TextEncoder();
  class IconClient {
    constructor(options={}) {
      this.onConnection=options.onConnection||(()=>{}); this.onState=options.onState||(()=>{});
      this.onEvent=options.onEvent||(()=>{}); this.connected=false; this.mode=null; this.simulator=false;
      this._generation=0; this._id=0; this._pending=new Map(); this._queue=Promise.resolve();
      this._buffer=''; this._decoder=new TextDecoder();
    }
    _event(detail) {this.onConnection({connected:this.connected,mode:this.mode,simulator:this.simulator,detail});}
    _alive(generation) {if(generation!==this._generation) throw new Error('connection_cancelled');}
    _response(response,generation) {
      if(generation!==this._generation || !response || typeof response.ok!=='boolean') return;
      const pending=this._pending.get(response.id);
      if(!pending) return;
      clearTimeout(pending.timer); this._pending.delete(response.id);
      if(response.state) this.onState(response.state);
      pending.resolve(response);
    }
    _json(text,generation) {
      if(encoder.encode(text).length>2048) {this.onEvent({error:'response_too_large'});return;}
      try {this._response(JSON.parse(text),generation);} catch(_) {this.onEvent({error:'invalid_response'});}
    }
    _chunk(value,generation) {
      if(generation!==this._generation) return;
      this._buffer+=this._decoder.decode(value,{stream:true});
      let end;
      while((end=this._buffer.indexOf('\n'))>=0) {
        const line=this._buffer.slice(0,end);this._buffer=this._buffer.slice(end+1);
        if(line.trim()) this._json(line,generation);
      }
      clearTimeout(this._bufferTimer);
      if(encoder.encode(this._buffer).length>2048) {this.onEvent({error:'response_too_large'});this.disconnect();return;}
      if(this._buffer) this._bufferTimer=setTimeout(()=>{
        if(generation!==this._generation)return;
        this.onEvent({error:'response_timeout'});this.disconnect();
      },2000);
    }
    async _auth(token,generation) {
      const result=await this.send({op:'auth',token});this._alive(generation);
      if(!result.ok) throw new Error(result.error||'unauthorized');
      this.simulator=result.simulator===true; this.connected=true;this._event('authenticated');
      return result;
    }
    async connectWebSocket(url,token) {
      this.disconnect(); const generation=this._generation; this.mode='websocket';
      try {
        const socket=new WebSocket(url);this._socket=socket;
        await new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>reject(new Error('connection_timeout')),5000);
          this._connecting={reject,timer};
          socket.onopen=()=>{if(generation!==this._generation)return;clearTimeout(timer);this._connecting=null;this._ready=true;resolve();};
          socket.onmessage=event=>{if(generation===this._generation && typeof event.data==='string')this._json(event.data,generation);};
          socket.onerror=()=>{if(generation!==this._generation)return;reject(new Error('network_error'));this.disconnect();};
          socket.onclose=()=>{if(generation!==this._generation)return;reject(new Error('disconnected'));this.disconnect();};
        });
        this._alive(generation);return await this._auth(token,generation);
      } catch(error) {if(generation===this._generation)this.disconnect();throw error;}
    }
    async connectBLE(token) {
      this.disconnect(); const generation=this._generation;this.mode='ble';
      if(!root.navigator?.bluetooth || !root.isSecureContext) throw new Error('BLE requires a supported browser on localhost or HTTPS');
      try {
        const device=await root.navigator.bluetooth.requestDevice({filters:[{services:[SERVICE]}]});
        this._alive(generation); this._device=device;
        device.addEventListener('gattserverdisconnected',()=>{if(generation===this._generation)this.disconnect();});
        const server=await device.gatt.connect();
        if(generation!==this._generation){device.gatt.disconnect();this._alive(generation);}
        const service=await server.getPrimaryService(SERVICE);this._alive(generation);
        const write=await service.getCharacteristic(WRITE);this._alive(generation);
        const notify=await service.getCharacteristic(NOTIFY);this._alive(generation);
        this._write=write;
        notify.addEventListener('characteristicvaluechanged',e=>this._chunk(e.target.value,generation));
        await notify.startNotifications();this._alive(generation);this._ready=true;
        return await this._auth(token,generation);
      } catch(error) {if(generation===this._generation)this.disconnect();throw error;}
    }
    async _writeBLE(wire,generation,characteristic) {
      const bytes=encoder.encode(wire+'\n');
      let timer;
      try {
        await Promise.race([(async()=>{
          for(let offset=0;offset<bytes.length;offset+=20){
            this._alive(generation);
            await characteristic.writeValueWithResponse(bytes.slice(offset,offset+20));
          }
        })(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('write_timeout')),2000);})]);
      } finally {clearTimeout(timer);}
    }
    send(command) {
      const next={...command};
      if(next.id===undefined){do{this._id=this._id>=2147483647?1:this._id+1;}while(this._pending.has(this._id));next.id=this._id;}
      if(!Number.isInteger(next.id)||next.id<1||next.id>2147483647)return Promise.reject(new Error('invalid_id'));
      this._id=Math.max(this._id,next.id);
      const wire=JSON.stringify(next);
      if(encoder.encode(wire).length>512)return Promise.reject(new Error('request_too_large'));
      if(this._pending.has(next.id))return Promise.reject(new Error('duplicate_id'));
      if(!this.connected && !(next.op==='auth' && this._ready))return Promise.resolve({id:next.id,ok:false,error:'disconnected'});
      const generation=this._generation, characteristic=this._write;
      return new Promise(resolve=>{
        const timer=setTimeout(()=>{
          this._pending.delete(next.id);resolve({id:next.id,ok:false,error:'request_timeout'});
        },5000);
        this._pending.set(next.id,{resolve,timer});
        const failed=error=>{
          if(generation!==this._generation)return;
          const pending=this._pending.get(next.id);if(pending){clearTimeout(pending.timer);this._pending.delete(next.id);pending.resolve({id:next.id,ok:false,error:error.message});}
          this.disconnect();
        };
        if(this.mode==='websocket') {try{this._socket.send(wire);}catch(error){failed(error);}}
        else {
          this._queue=this._queue.catch(()=>{}).then(()=>{
            this._alive(generation);
            if(!this._pending.has(next.id))return;
            return this._writeBLE(wire,generation,characteristic);
          }).catch(failed);
        }
      });
    }
    showIcon(icon,options={}){return this.send({...options,op:'show',icon});}
    showText(text,options={}){return this.send({...options,op:'text',text});}
    setBrightness(value){return this.send({op:'brightness',value});}
    setSpeed(value){return this.send({op:'speed',value});}
    pause(){return this.send({op:'pause'});} resume(){return this.send({op:'resume'});}
    release(){return this.send({op:'release'});} off(){return this.send({op:'off'});}
    setIdle(mode){return this.send({op:'idle',mode});}
    syncClock(){return this.send({op:'clock',epoch:Math.floor(Date.now()/1000),utc_offset_min:-new Date().getTimezoneOffset()});}
    showTime(){return this.send({op:'time'});}
    keepalive(target_id){return this.send({op:'keepalive',target_id});}
    getState(){return this.send({op:'get'});}
    openProvisioningHotspot(){return this.send({op:'provision'});}
    disconnect(){
      this._generation++;this.connected=false;this._ready=false;this.simulator=false;
      if(this._connecting){clearTimeout(this._connecting.timer);this._connecting.reject(new Error('connection_cancelled'));this._connecting=null;}
      this._pending.forEach((p,id)=>{clearTimeout(p.timer);p.resolve({id,ok:false,error:'disconnected'});});this._pending.clear();
      const socket=this._socket,device=this._device;this._socket=null;this._device=null;this._write=null;
      clearTimeout(this._bufferTimer);this._buffer='';this._decoder=new TextDecoder();this._queue=Promise.resolve();
      if(socket){socket.onopen=socket.onmessage=socket.onclose=socket.onerror=null;try{socket.close();}catch(_){}}
      if(device?.gatt?.connected)device.gatt.disconnect();this._event('disconnected');
    }
  }
  IconClient.SERVICE_UUID=SERVICE;IconClient.WRITE_UUID=WRITE;IconClient.NOTIFY_UUID=NOTIFY;
  if(typeof module==='object'&&module.exports)module.exports=IconClient;else root.IconClient=IconClient;
})(globalThis);
