#!/usr/bin/env python3
"""Exercise the actual embedded setup-page script without an ESP32 radio."""
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / 'firmware/IconShow/IconShow.ino').read_text()
literal = re.search(r'page \+= F\(("const form=.*?")\);', source).group(1)
script = json.loads(literal).removesuffix('</script>')
harness = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const script = JSON.parse(process.argv[1]);
async function run(result) {
  const elements = Object.fromEntries(['form','#status','#ssid','#networks','#rescan'].map(k=>[k,{}]));
  elements['#networks'].replaceChildren = (...items)=>{elements['#networks'].items=items};
  let scans=0, polls=0, submitted=false;
  const context = {
    document:{querySelector:s=>elements[s],createElement:()=>({})},
    URLSearchParams, FormData:class extends Map {constructor(){super([['ssid','Test'],['password','placeholder']])}},
    setTimeout:fn=>setImmediate(fn),
    fetch:async (url,options)=>({json:async()=>{
      if(url==='/api/scan') return ++scans===1?{ok:true,pending:true}:{ok:true,networks:[{ssid:'<script>plain SSID</script>'}]};
      if(url==='/api/apply') {assert.equal(options.method,'POST');submitted=true;return {ok:true,pending:true}}
      if(url==='/api/status') {polls++;return {candidate_status:result,sta_ip:'192.0.2.10'}}
      throw Error(url);
    }})
  };
  vm.createContext(context);vm.runInContext(script,context);
  for(let i=0;i<10 && !elements['#networks'].items;i++) await new Promise(setImmediate);
  assert.equal(elements['#networks'].items[0].value,'<script>plain SSID</script>');
  let prevented=false;await elements.form.onsubmit({preventDefault(){prevented=true}});
  assert(prevented && submitted && polls>0);
  const text=elements['#status'].textContent;
  if(result==='connected') assert.match(text,/Connected: 192\.0\.2\.10/);
  else if(result==='failed') assert.match(text,/old configuration was kept/);
  else assert.match(text,/could not save/);
}
(async()=>{for(const result of ['connected','failed','save_failed']) await run(result);console.log('PASS embedded setup page: asynchronous scan, safe SSID, submit and connection/save outcomes')})().catch(e=>{console.error(e);process.exitCode=1});
'''
subprocess.run(['node', '-e', harness, json.dumps(script)], check=True, cwd=root)
