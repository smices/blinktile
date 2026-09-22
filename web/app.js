(function (root) {
  'use strict';
  var data = root.IconData || { colors: {}, icons: {}, font: {} };
  var assets = root.AssetManifest || { examples: [] };
  var engine = new root.IconEngine(data);
  var client = new root.IconClient({
    onConnection: function (info) { setConnection(info); },
    onState: function (state) { text('device-state', JSON.stringify(state, null, 2)); },
    onEvent: function (event) { if (event.error) setNotice(event.error, true); }
  });
  var canvas;
  var ctx;
  var noticeTimer;
  var localId = 0;
  var lastCommand = null;
  var syncing = false;
  var connectVersion = 0;
  var previewMode = "show";

  function byId(id) { return document.getElementById(id); }
  function text(id, value) { var el = byId(id); if (el) el.textContent = value; }
  function setNotice(message, error) {
    var el = byId('notice');
    if (!el) return;
    el.textContent = message;
    el.className = error ? 'notice is-error' : 'notice';
    clearTimeout(noticeTimer);
    if (!error) noticeTimer = setTimeout(function () { el.textContent = ''; }, 3500);
  }
  function setConnection(info) {
    var state = byId('connection-state');
    if (!state) return;
    state.textContent = info.connected ? (info.simulator ? '模拟设备已认证' : '真实设备已认证') : '仅本地预览';
    state.className = 'connection-state ' + (info.connected ? 'is-connected' : 'is-local');
  }
  function selectedValues() {
    var input = byId('colors');
    return (input ? input.value : '').split(',').map(function (v) { return v.trim(); }).filter(Boolean);
  }
  function common() {
    var effect = byId('effect');
    var mode = byId('color-mode');
    var duration = Number(byId('duration').value);
    var animationPeriod = Number(byId('animation-period').value);
    var color = { mode: mode ? mode.value : 'solid' };
    color.period_ms = Number(byId('color-period').value);
    var colorValues = selectedValues();
    if (!color.mode.startsWith('rainbow_') && colorValues.length) color.values = colorValues;
    return {
      color: color,
      effect: {
        type: effect ? effect.value : 'none',
        min: Number(byId('effect-min').value),
        max: Number(byId('effect-max').value),
        period_ms: Number(byId('effect-period').value)
      },
      duration_ms: duration || undefined,
      animation_period_ms: animationPeriod || undefined
    };
  }
  function iconCommand() {
    var options = common();
    var animation = { repeat: Number(byId('icon-repeat').value) };
    var enabled = byId('animation-enabled').value;
    if (enabled !== 'auto') animation.enabled = enabled === 'true';
    if (options.animation_period_ms) animation.period_ms = options.animation_period_ms;
    options.animation = animation;
    delete options.animation_period_ms;
    return Object.assign(options, { op: 'show', icon: byId('icon-select').value });
  }
  function textCommand() {
    var scroll = byId('scroll-mode');
    var options = common();
    delete options.animation_period_ms;
    return Object.assign(options, {
      op: 'text',
      text: byId('text-input').value,
      scroll: {
        mode: scroll.value,
        direction: byId('direction').value,
        step_ms: Number(byId('step-ms').value),
        repeat: Number(byId('text-repeat').value)
      }
    });
  }
  async function copy(value) {
    try {
      if (!navigator.clipboard) throw new Error('当前环境不能自动复制，请在指令框中手动复制。');
      await navigator.clipboard.writeText(value); setNotice('已复制。');
    } catch (error) { setNotice(error.message || '复制失败，请手动复制。', true); }
  }
  function preview(command) {
    command = Object.assign({}, command, {id: ++localId});
    if (localId >= 2147483647) localId = 0;
    var result = engine.execute(command, performance.now());
    if (result.ok) {
      lastCommand = command;
      byId('command-json').value = JSON.stringify(command, null, 2);
    } else setNotice(result.error, true);
    return result;
  }
  async function sendAction(command) {
    if (syncing) { setNotice('正在同步设备设置，请稍候。'); return; }
    var result = preview(command);
    if (!result.ok) return result;
    if (!client.connected) { setNotice('已更新本地预览；连接设备后才能发送。'); return result; }
    try {
      var response = await client.send(lastCommand);
      text('device-state', JSON.stringify({acknowledgment:response},null,2));
      setNotice(response.ok ? (client.simulator ? '模拟设备已确认。' : '设备已确认。') : response.error, !response.ok);
      return response;
    } catch (error) { setNotice(error.message,true); }
  }
  async function synchronize(version) {
    syncing = true;
    try {
      var reply = await client.getState();
      if(version !== connectVersion)return;
      if (!reply.ok || !reply.state) throw new Error(reply.error || '无法读取设备状态');
      var state = reply.state;
      engine.execute({id:++localId,op:'off'},performance.now());
      engine.execute({id:++localId,op:'brightness',value:state.brightness},performance.now());
      engine.execute({id:++localId,op:'speed',value:state.speed},performance.now());
      byId('brightness').value=state.brightness;
      byId('brightness-value').value=Math.round(state.brightness/255*100)+'%';
      byId('speed').value=state.speed; byId('speed-value').value=state.speed+'×';
      if (state.idle==='pet') engine.execute({id:++localId,op:'idle',mode:'pet'},performance.now());
      text('device-state',JSON.stringify(state,null,2));
      setNotice('连接成功，已同步设备亮度和速度。');
    } catch(error) {if(version===connectVersion){client.disconnect();setNotice(error.message,true);}}
    finally {if(version===connectVersion)syncing=false;}
  }
  function draw() {
    if (!ctx) return;
    var now = performance.now();
    var frame = engine.frame(now);
    var w = canvas.width / 8;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    frame.forEach(function (rgb, i) {
      ctx.fillStyle = 'rgb(' + rgb.join(',') + ')';
      ctx.fillRect((i % 8) * w + 1, Math.floor(i / 8) * w + 1, w - 2, w - 2);
    });
    var state = engine.getState(now);
    text('preview-state', state.content ? (state.content.icon || state.content.text || state.current_type || 'active') : (state.idle === 'pet' ? 'idle pet' : 'off'));
    root.requestAnimationFrame(draw);
  }
  function fillSelect() {
    var select = byId('icon-select');
    if (!select) return;
    Object.keys(data.icons || {}).forEach(function (id) {
      var option = document.createElement('option');
      option.value = id;
      option.textContent = data.icons[id].label || id;
      select.appendChild(option);
    });
  }
  function assetUrl(file) { return file ? (file.indexOf('/') >= 0 ? file : 'assets/' + file) : ''; }
  function loadCommand(command) {
    if (!command || typeof command !== 'object') return;
    if (command.op==='idle') {preview(command);return;}
    previewMode=command.op;
    if(command.icon) byId('icon-select').value=command.icon;
    if(command.text) byId('text-input').value=command.text;
    var color=command.color||{}, effect=command.effect||{}, anim=command.animation||{}, scroll=command.scroll||{};
    byId('color-mode').value=color.mode||'solid';byId('colors').value=(color.values||[]).join(',');
    byId('color-period').value=color.period_ms||5000;
    byId('effect').value=effect.type||'none';byId('effect-period').value=effect.period_ms||2000;
    byId('effect-min').value=effect.min||0;byId('effect-max').value=effect.max===undefined?255:effect.max;
    byId('animation-enabled').value=anim.enabled===undefined?'auto':String(anim.enabled);
    byId('animation-period').value=anim.period_ms||'';byId('icon-repeat').value=anim.repeat||0;
    byId('scroll-mode').value=scroll.mode||'auto';byId('direction').value=scroll.direction||'left';
    byId('step-ms').value=scroll.step_ms||80;byId('text-repeat').value=scroll.repeat===undefined?1:scroll.repeat;
    byId('duration').value=command.duration_ms||'';
    preview(command);setNotice('已载入本地预览。');
  }
  function galleryCard(item) {
    var card=document.createElement('article');card.className='gallery-card';card.dataset.id=item.id;
    var still=assetUrl(item.poster||item.png||item.id+'-preview.png');
    var gif=item.gif||(item.file && item.file.endsWith('.gif')?item.file:null);
    var poster=document.createElement('img');poster.loading='lazy';poster.alt=(item.label||item.id)+' 像素预览';poster.src=still;card.appendChild(poster);
    var body=document.createElement('div');body.className='gallery-card-body';
    var title=document.createElement('h3');title.textContent=item.label||item.id;body.appendChild(title);
    var meta=document.createElement('p');meta.className='muted';meta.textContent=item.id;
    if(data.icons[item.id])meta.textContent+=' · '+data.icons[item.id].color+' · '+data.icons[item.id].period_ms+'ms';body.appendChild(meta);
    var actions=document.createElement('div');actions.className='card-actions';
    function button(label,handler){var b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',handler);actions.appendChild(b);return b;}
    function download(path,label){var a=document.createElement('a');a.href=assetUrl(path);a.download=path.split('/').pop();a.textContent=label;actions.appendChild(a);}
    if(gif){
      var play=button('播放 GIF',function(){var playing=play.getAttribute('aria-pressed')==='true';poster.src=playing?still:assetUrl(gif);play.setAttribute('aria-pressed',String(!playing));play.textContent=playing?'播放 GIF':'停止 GIF';});
      play.setAttribute('aria-pressed','false');download(gif,'下载 GIF');
    }
    download(item.png||item.poster||item.id+'.png','下载 PNG');
    var command=item.command&&typeof item.command==='object'?item.command:{op:'show',icon:item.id};
    button('复制指令',()=>copy(JSON.stringify({id:1,...command})));
    button('载入预览',()=>loadCommand(command));
    body.appendChild(actions);card.appendChild(body);return card;
  }
  function fillGallery() {
    var list = byId('gallery-list');
    if (!list) return;
    var items = Array.isArray(assets) ? assets : (assets.icons || []);
    if (!items.length) items = Object.keys(data.icons || {}).map(function (id) { return { id: id, label: data.icons[id].label || id, png: 'assets/' + id + '.png', file: 'assets/' + id + '.png', gif: data.icons[id].frames.length>1 ? 'assets/' + id + '.gif' : null, kind: 'icon' }; });
    items.forEach(function (item) { list.appendChild(galleryCard(item)); });
    var examples = Array.isArray(assets.examples) ? assets.examples : [];
    var examplesList = byId('examples-list');
    examples.forEach(function (item) { examplesList && examplesList.appendChild(galleryCard(item)); });
  }
  function wire() {
    canvas = byId('preview');
    if (canvas) { ctx = canvas.getContext('2d'); canvas.width = 320; canvas.height = 320; }
    fillSelect(); fillGallery();
    byId('send-icon').addEventListener('click',()=>{previewMode='show';sendAction(iconCommand());});
    byId('send-text').addEventListener('click',()=>{previewMode='text';sendAction(textCommand());});
    ['off','release','pause','resume'].forEach(op=>byId(op).addEventListener('click',()=>sendAction({op})));
    byId('set-brightness').addEventListener('click',()=>sendAction({op:'brightness',value:Number(byId('brightness').value)}));
    byId('set-speed').addEventListener('click',()=>sendAction({op:'speed',value:Number(byId('speed').value)}));
    byId('get-state').addEventListener('click',async()=>{
      try {var reply=client.connected?await client.getState():{ok:true,state:engine.getState(performance.now())};text('device-state',JSON.stringify(reply,null,2));}
      catch(error){setNotice(error.message,true);}
    });
    byId('idle-pet').addEventListener('click',()=>sendAction({op:'idle',mode:'pet'}));
    byId('idle-off').addEventListener('click',()=>sendAction({op:'idle',mode:'off'}));
    byId('copy-command').addEventListener('click', function () { if(lastCommand)copy(JSON.stringify(lastCommand));else setNotice('请先选择图标或文字。'); });
    async function connect(kind) {
      var version=++connectVersion; syncing=true;
      try {
        if(kind==='ws')await client.connectWebSocket(byId('ws-url').value,byId('token').value);
        else await client.connectBLE(byId('token').value);
        if(version===connectVersion)await client.syncClock();
        if(version===connectVersion)await synchronize(version);
      } catch(error){if(version===connectVersion){syncing=false;setNotice(error.message,true);}}
    }
    byId('connect-ws').addEventListener('click',()=>connect('ws'));
    byId('connect-ble').addEventListener('click',()=>connect('ble'));
    byId('disconnect').addEventListener('click',()=>{connectVersion++;syncing=false;client.disconnect();});
    byId('provision').addEventListener('click', function () { client.openProvisioningHotspot().then(function (r) { setNotice(r.ok ? 'Hotspot opened. Connect your phone, then visit http://192.168.4.1.' : r.error, !r.ok); }); });
    document.querySelectorAll('.controls input:not([type=range]), .controls select').forEach(el=>el.addEventListener('change',()=>{if(el.id==='text-input')previewMode='text';if(el.id==='icon-select')previewMode='show';preview(previewMode==='text'?textCommand():iconCommand());}));
    setConnection({ connected: false });
    draw();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
  root.IconShowApp = { engine: engine, client: client, sendAction: sendAction };
})(typeof globalThis !== 'undefined' ? globalThis : window);
