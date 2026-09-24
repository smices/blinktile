#!/usr/bin/env python3
"""Exercise the embedded provisioning and AP controller scripts without Wi-Fi."""
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / 'firmware/IconShow/IconShow.ino').read_text()
literal = re.search(r'page \+= F\(("const form=.*?")\);', source).group(1)
script = json.loads(literal).removesuffix('</script>')
assert 'BlinkTile-' in source and 'setupPassword.length() != 8' in source
assert 'dnsServer.start(53, "*", WiFi.softAPIP())' in source
assert 'http.on("/api/finish", HTTP_POST, handleApFinish)' in source
assert 'candidateStatus = "connected";' in source
assert source.index('httpNonce = randomWord();') < source.index('void handleApRoot()')

harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),script=JSON.parse(process.argv[1]);
async function run(result){
  const selectors=['#status','#ssid','#networks','#rescan','#device','#token','#icons','#brightness','#time','#pet','#off','#finish','#copy'];
  const elements=Object.fromEntries(selectors.map(s=>[s,{}]));
  const csrf={value:'0123abcd'},form={querySelector:s=>csrf};elements.form=form;
  elements['#token'].value='0123456789abcdef';elements['#token'].select=()=>{};elements['#networks'].replaceChildren=(...x)=>elements['#networks'].items=x;
  const sent=[];let scans=0,polls=0,submitted=false,finishBody;
  class MockWebSocket{constructor(url){this.url=url;setImmediate(()=>this.onopen());}send(s){const c=JSON.parse(s);sent.push(c);if(c.op==='auth')setImmediate(()=>this.onmessage({data:JSON.stringify({id:c.id,ok:true})}));if(c.op==='get')setImmediate(()=>this.onmessage({data:JSON.stringify({id:c.id,ok:true,time:'12:34',state:{wifi_connected:true,idle:'pet',brightness:64}})}));} }
  const context={document:{querySelector:s=>elements[s],createElement:()=>({}),execCommand:()=>true},URLSearchParams,
    FormData:class extends Map{constructor(){super([['csrf','0123abcd'],['ssid','Test'],['password','placeholder']])}},
    WebSocket:MockWebSocket,location:{hostname:'192.168.4.1'},navigator:{clipboard:{writeText:async()=>{}}},
    setTimeout:fn=>setImmediate(fn),fetch:async(url,options={})=>{
      if(url==='/api/finish'){finishBody=options.body;return{ok:true};}
      return {ok:true,json:async()=>{
      if(url==='/api/scan')return ++scans===1?{ok:true,pending:true}:{ok:true,networks:[{ssid:'<script>plain SSID</script>'}]};
      if(url==='/api/apply'){assert.equal(options.method,'POST');submitted=true;return{ok:true,pending:true};}
      if(url==='/api/status'){polls++;return{candidate_status:result,sta_ip:'192.0.2.10'};}
      throw Error(url);
    }};}};
  vm.createContext(context);vm.runInContext(script,context);
  for(let i=0;i<20&&(!elements['#networks'].items||!elements['#icons'].textContent);i++)await new Promise(setImmediate);
  assert.equal(elements['#networks'].items[0].value,'<script>plain SSID</script>');
  assert.deepEqual(sent[0],{id:1,op:'auth',token:'0123456789abcdef'});assert(sent.some(x=>x.op==='get'));
  assert.match(elements['#icons'].textContent,/Wi-Fi.*BLE.*Pet.*64\/255/);
  let prevented=false;await elements.form.onsubmit({preventDefault(){prevented=true}});assert(prevented&&submitted&&polls>0);
  const text=elements['#status'].textContent;
  if(result==='connected')assert.match(text,/Connected: 192\.0\.2\.10.*hotspot stays open/);
  else if(result==='failed')assert.match(text,/old configuration was kept/);
  else assert.match(text,/could not save/);
  elements['#time'].onclick();elements['#pet'].onclick();elements['#off'].onclick();elements['#brightness'].onchange({target:{value:'128'}});
  await elements['#finish'].onclick();
  await new Promise(setImmediate);
  for(const op of ['clock','time','idle','off','brightness'])assert(sent.some(x=>x.op===op),op);
  assert(sent.some(x=>x.op==='idle'&&x.mode==='pet'));assert(sent.some(x=>x.op==='brightness'&&x.value===128));
  assert.equal(finishBody.toString(),'csrf=0123abcd');assert.match(elements['#status'].textContent,/Hotspot closed/);
}
(async()=>{for(const r of ['connected','failed','save_failed'])await run(r);console.log('PASS embedded AP setup/controller JS, auth, controls, provisioning outcomes and CSRF finish')})().catch(e=>{console.error(e);process.exitCode=1});
'''
subprocess.run(['node', '-e', harness, json.dumps(script)], check=True, cwd=root)
