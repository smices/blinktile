(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.IconEngine = api.IconEngine;
})(globalThis, function () {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const blank = () => Array.from({length:64}, () => [0,0,0]);
  const fail = code => { throw new Error(code); };
  const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  const integer = (n, lo, hi, code) => { if (!Number.isInteger(n) || n < lo || n > hi) fail(code); return n; };
  const PET = ['smile','happy','wink','sleepy'];
  const RAINBOW = ['red','orange','yellow','green','cyan','blue','purple'];
  function fields(value, names) {
    if (!object(value) || Object.keys(value).some(k => !names.includes(k))) fail('invalid_parameters');
  }
  function rgb(value, colors) {
    if (typeof value !== 'string') fail('invalid_color');
    const resolved = colors[value] || value;
    if (!/^#[0-9a-fA-F]{6}$/.test(resolved)) fail('invalid_color');
    return [1,3,5].map(i => parseInt(resolved.slice(i,i+2),16));
  }
  function blend(colors, phase) {
    const at = ((phase % 1 + 1) % 1) * colors.length;
    const index = Math.floor(at), ratio = at - index;
    return colors[index].map((v,c) => Math.round(v + (colors[(index+1)%colors.length][c]-v)*ratio));
  }
  class IconEngine {
    constructor(data) {
      this.data = data;
      this.brightness = 64; this.speed = 1; this.idle = 'off'; this.paused = false;
      this.content = null; this.phase = 0; this.petPhase = 0; this.last = null; this.expires = null;
      this.powerLimited = false; this.estimatedMA = 64;
    }
    _release(now) {
      this.content = null; this.phase = 0; this.petPhase = 0; this.expires = null;
      this.paused = false; this.last = now;
    }
    _tick(now) {
      if (!Number.isFinite(now)) fail('invalid_time');
      const c = this.content;
      const previous = this.last === null ? now : this.last;
      let endedAt = this.expires === null ? Infinity : this.expires;
      if (c && c.op === 'text' && c.scroll.mode !== 'never' && c.scroll.repeat > 0 && !this.paused) {
        const limit = (c.text.length*6-1+11)*c.scroll.step_ms*c.scroll.repeat;
        endedAt = Math.min(endedAt,previous+Math.max(0,limit-this.phase)/this.speed);
      }
      if (c && endedAt <= now) {
        this._release(endedAt);
        this.petPhase = Math.max(0,now-endedAt)*this.speed;
      } else if (!this.paused) {
        const delta = Math.max(0,now-previous)*this.speed;
        this.phase += delta; this.petPhase += delta;
      }
      this.last = now;
    }
    _effective(c, speed) {
      if (!c) return;
      if (c.op === 'show' && c.animation.enabled) {
        const icon = this.data.icons[c.icon];
        if (icon.frames.some(f => f.duration_ms*c.animation.period_ms/icon.period_ms/speed < 20-1e-8)) fail('invalid_period');
      }
      if (c.op === 'text' && c.scroll.mode !== 'never' && c.scroll.step_ms/speed < 20) fail('invalid_period');
      if (c.color.mode !== 'solid' && c.color.period_ms/speed < 500) fail('invalid_period');
      if (c.effect.type !== 'none' && c.effect.period_ms/speed < (c.effect.type === 'breathe'?600:500)) fail('invalid_period');
    }
    _normalize(cmd) {
      const c = clone(cmd);
      if (c.op === 'show' && typeof c.icon !== 'string') fail('invalid_icon');
      const fallback = c.op === 'show' ? this.data.icons[c.icon]?.color : '#FFFFFF';
      if (c.op === 'show' && !fallback) fail('unknown_icon');
      if (c.op === 'text' && (typeof c.text !== 'string' || !/^[\x20-\x7e]{1,64}$/.test(c.text))) fail('invalid_text');
      if (c.brightness !== undefined) integer(c.brightness,0,255,'invalid_brightness');
      c.duration_ms = integer(c.duration_ms === undefined ? 0 : c.duration_ms,0,86400000,'invalid_duration');
      const rawColor = c.color === undefined ? {} : c.color;
      fields(rawColor,['mode','values','period_ms','scope']);
      c.color = {mode:'solid',period_ms:5000,scope:'primary',...rawColor};
      if (!['solid','step','gradient','rainbow_cycle','rainbow_flow'].includes(c.color.mode)) fail('invalid_color_mode');
      if (!['primary','all'].includes(c.color.scope)) fail('invalid_scope');
      integer(c.color.period_ms,100,60000,'invalid_period');
      if (c.color.mode.startsWith('rainbow')) {
        if (rawColor.values !== undefined) fail('invalid_color_values');
      } else {
        c.color.values = rawColor.values === undefined ? [fallback] : rawColor.values;
        if (!Array.isArray(c.color.values) || (c.color.mode === 'solid' ? c.color.values.length!==1 : c.color.values.length<2 || c.color.values.length>8)) fail('invalid_color_values');
        c.color.values.forEach(v => rgb(v,this.data.colors));
      }
      const rawEffect = c.effect === undefined ? {} : c.effect;
      fields(rawEffect,['type','period_ms','min','max']);
      c.effect = {type:'none',period_ms:2000,min:0,max:255,...rawEffect};
      if (!['none','breathe','alternate','blink'].includes(c.effect.type)) fail('invalid_effect');
      integer(c.effect.period_ms,100,60000,'invalid_period');
      integer(c.effect.min,0,255,'invalid_effect'); integer(c.effect.max,0,255,'invalid_effect');
      if (c.effect.min>c.effect.max || (c.effect.type==='blink' && c.effect.min!==0)) fail('invalid_effect');
      if (c.op === 'show') {
        const icon = this.data.icons[c.icon];
        const raw = c.animation === undefined ? {} : c.animation;
        fields(raw,['enabled','period_ms','repeat']);
        c.animation = {enabled:icon.frames.length>1,period_ms:icon.period_ms,repeat:0,...raw};
        if (typeof c.animation.enabled !== 'boolean' || (c.animation.enabled && icon.frames.length<2)) fail('invalid_animation');
        integer(c.animation.period_ms,100,60000,'invalid_period');
        integer(c.animation.repeat,0,65535,'invalid_repeat');
      } else {
        const raw = c.scroll === undefined ? {} : c.scroll;
        fields(raw,['mode','direction','step_ms','repeat']);
        c.scroll = {mode:'auto',direction:'left',step_ms:80,repeat:1,...raw};
        if (!['auto','always','never'].includes(c.scroll.mode) || !['left','right'].includes(c.scroll.direction)) fail('invalid_scroll');
        integer(c.scroll.step_ms,20,60000,'invalid_period'); integer(c.scroll.repeat,0,65535,'invalid_repeat');
        const width = c.text.length*6-1;
        if (c.scroll.mode==='auto') c.scroll.mode=width>8?'always':'never';
        if (c.scroll.mode==='never' && width>8) fail('text_too_wide');
      }
      this._effective(c,this.speed);
      return c;
    }
    execute(cmd, now=performance.now()) {
      const id = object(cmd) && Number.isInteger(cmd.id) ? cmd.id : null;
      try {
        this._tick(now);
        if (!object(cmd)) fail('invalid_command');
        integer(cmd.id,1,2147483647,'invalid_id');
        const common = ['id','op'];
        if (cmd.op==='show' || cmd.op==='text') {
          fields(cmd,common.concat(cmd.op==='show'?['icon','animation']:['text','scroll'],['color','effect','brightness','duration_ms']));
          const next = this._normalize(cmd);
          this.content = next; this.phase = 0; this.last = now; this.paused = false;
          this.expires = next.duration_ms>0?now+next.duration_ms:null;
          if (next.brightness!==undefined) this.brightness=next.brightness;
        } else if (cmd.op==='brightness') {
          fields(cmd,common.concat('value')); this.brightness=integer(cmd.value,0,255,'invalid_brightness');
        } else if (cmd.op==='speed') {
          fields(cmd,common.concat('value'));
          if (typeof cmd.value!=='number' || !Number.isFinite(cmd.value) || cmd.value<.25 || cmd.value>4) fail('invalid_speed');
          this._effective(this.content,cmd.value); this.speed=cmd.value;
        } else if (cmd.op==='idle') {
          fields(cmd,common.concat('mode'));
          if (!['off','pet'].includes(cmd.mode)) fail('invalid_idle');
          this.idle=cmd.mode;
          if (!this.content) {this.petPhase=0;this.paused=false;}
        } else if (cmd.op==='keepalive') {
          fields(cmd,common.concat('target_id'));
          integer(cmd.target_id,1,2147483647,'invalid_id');
          if (!this.content || this.content.id!==cmd.target_id) fail('stale_display');
          if (this.content.duration_ms===0) fail('no_expiry');
          this.expires=now+this.content.duration_ms;
        } else {
          fields(cmd,common);
          if (cmd.op==='pause') this.paused=true;
          else if (cmd.op==='resume') this.paused=false;
          else if (cmd.op==='release') this._release(now);
          else if (cmd.op==='off') {this.idle='off';this._release(now);}
          else if (cmd.op==='get') return {id,ok:true,state:this.getState(now)};
          else fail('unknown_op');
        }
        return {id,ok:true};
      } catch(error) { return {id,ok:false,error:error.message}; }
    }
    _mask(c,phase) {
      if (c.op==='show') {
        const icon=this.data.icons[c.icon];
        if (!c.animation.enabled) return icon.frames[icon.static_frame].pixels;
        if (c.animation.repeat>0 && phase>=c.animation.period_ms*c.animation.repeat) return icon.frames.at(-1).pixels;
        let t=(phase%c.animation.period_ms)*icon.period_ms/c.animation.period_ms;
        for (const f of icon.frames) { if(t<f.duration_ms) return f.pixels; t-=f.duration_ms; }
        return icon.frames.at(-1).pixels;
      }
      const pixels=Array(64).fill(0), width=c.text.length*6-1;
      const step=Math.floor(phase/c.scroll.step_ms)%(width+11);
      const start=c.scroll.mode==='never'?Math.floor((8-width)/2):c.scroll.direction==='left'?8-step:-width+step;
      for (let x=0;x<8;x++) {
        const sx=x-start;
        if (sx<0 || sx>=width || sx%6===5) continue;
        const col=this.data.font[c.text[Math.floor(sx/6)]][sx%6];
        for(let y=0;y<7;y++) if(col&(1<<y)) pixels[y*8+x]=255;
      }
      return pixels;
    }
    frame(now=performance.now()) {
      this._tick(now);
      let c=this.content, phase=this.phase;
      if(!c) {
        if(this.idle==='off') {this.powerLimited=false;this.estimatedMA=64;return blank();}
        const id=PET[Math.floor(this.petPhase/20000)%PET.length], icon=this.data.icons[id];
        c={op:'show',icon:id,animation:{enabled:true,period_ms:icon.period_ms,repeat:0},color:{mode:'solid',values:[icon.color],period_ms:5000},effect:{type:'none',period_ms:2000,min:0,max:255}};
        phase=this.petPhase%20000;
      }
      const mask=this._mask(c,phase), e=c.effect;
      const t=(phase%e.period_ms)/e.period_ms;
      const wave=e.type==='breathe'?(1+Math.cos(2*Math.PI*t))/2:(t<.5?1:0);
      const intensity=e.type==='none'?1:(e.min+(e.max-e.min)*wave)/255;
      const palette=(c.color.mode.startsWith('rainbow')?RAINBOW:c.color.values).map(v=>rgb(v,this.data.colors));
      const colorPhase=phase/c.color.period_ms;
      let pixels=mask.map((level,i)=>{
        let color;
        if(c.color.mode==='solid') color=palette[0];
        else if(c.color.mode==='step') color=palette[Math.floor(colorPhase*palette.length)%palette.length];
        else color=blend(palette,colorPhase+(c.color.mode==='rainbow_flow'?(i%8)/8:0));
        return color.map(v=>Math.round(v*level/255*intensity*this.brightness/255));
      });
      const load=pixels.flat().reduce((a,b)=>a+b,0)*20/255;
      this.powerLimited=load>436;
      if(this.powerLimited) pixels=pixels.map(p=>p.map(v=>Math.floor(v*436/load)));
      this.estimatedMA=64+pixels.flat().reduce((a,b)=>a+b,0)*20/255;
      return pixels;
    }
    getState(now=performance.now()) {
      this.frame(now);
      return {brightness:this.brightness,speed:this.speed,idle:this.idle,paused:this.paused,
        current_id:this.content?.id??null,current_type:this.content?.op??null,
        content:this.content?clone(this.content):null,
        remaining_ms:this.expires===null?null:Math.max(0,Math.ceil(this.expires-now)),
        animation_complete:!!(this.content?.op==='show' && this.content.animation.enabled && this.content.animation.repeat>0 && this.phase>=this.content.animation.period_ms*this.content.animation.repeat),
        power_limited:this.powerLimited,estimated_mA:Math.round(this.estimatedMA*100)/100};
    }
  }
  return {IconEngine};
});
