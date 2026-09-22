#!/usr/bin/env python3
"""Compile actual .ino display functions on the host and compare against the JS renderer.

Only the NeoPixel output boundary and PROGMEM reads are substituted; pixels,
parsing and timing functions are extracted from the firmware on every run.
This is not an ESP32 radio, scheduler or electrical test.
"""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build/native'
SOURCE = ROOT / 'firmware/IconShow/IconShow.ino'


def block(source, pattern):
    match = re.search(pattern, source, re.M)
    if not match:
        raise AssertionError('Firmware test seam missing: ' + pattern)
    start = source.index('{', match.start())
    depth = 0
    tokens = re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/|[{}]', source[start:], re.S)
    for token in tokens:
        if token.group() == '{': depth += 1
        elif token.group() == '}':
            depth -= 1
            if depth == 0:
                return source[match.start():start+token.end()]
    raise AssertionError('Unclosed source block')


def build():
    source = SOURCE.read_text()
    library_data = json.loads(subprocess.check_output(['arduino-cli','lib','list','--format','json'], text=True))
    library = next(x['library']['install_dir'] for x in library_data['installed_libraries'] if x['library']['name']=='ArduinoJson')
    cpp = '''#include <ArduinoJson.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include "assets.h"
using std::min; using std::max;
#define pgm_read_byte(p) (*(const uint8_t*)(p))
#define pgm_read_word(p) (*(const uint16_t*)(p))
struct PixelOutput {
 uint32_t values[64] = {};
 static uint32_t Color(uint8_t r,uint8_t g,uint8_t b){return (uint32_t(r)<<16)|(uint32_t(g)<<8)|b;}
 void setPixelColor(uint16_t i,uint32_t c){values[i]=c;}
 void show(){}
} pixels;
'''
    cpp += source[source.index('constexpr uint8_t kWidth'):source.index('Adafruit_NeoPixel pixels')]
    for name in ['Mode','IdleMode','ColorMode','EffectType']:
        cpp += block(source,rf'^enum {name}\b[^{{]*\{{')+';\n'
    for name in ['ColorSpec','EffectSpec','AnimationSpec','RenderState']:
        cpp += block(source,rf'^struct {name}\s*\{{')+';\n'
    cpp += '''RenderState state;
IdleMode idleMode=IDLE_OFF;
float speed=1;
bool paused=false,frameDirty=true,lastPowerLimited=false;
float lastEstimatedMa=64;
uint32_t phaseRealOrigin=0,phaseVirtualOrigin=0,lastFrameAt=0;
'''
    names = ['timeReached','timeElapsed','parseUInt','parseByte','parseId','findIcon','parseHexColor','parseColorName',
      'parseColor','parseEffect','parseAnimation','parseCommon','parseIdFromRoot','virtualNow','resetPhase','setSpeed',
      'isActive','enterIdle','applyRenderState','mixChannel','mixColor','rainbowColor','colorAt','effectFactor',
      'iconPixel','iconFrameDuration','iconTotalDuration','iconFrameAt','drawPet','drawText','showFrame',
      'textIsScrolling','speedSupports','render','parseShow','parseText']
    functions = [block(source,rf'^[^\n;{{}}]*\b{name}\([^;{{]*\)\s*\{{') for name in names]
    # Declarations permit source function order to evolve without copying implementations.
    cpp += '\n'.join(fn[:fn.index('{')].strip()+';' for fn in functions)+'\n'
    cpp += '\n'.join(functions)
    cpp += r'''
int main(){
 std::string line;
 while(std::getline(std::cin,line)){
  JsonDocument request,response;
  if(deserializeJson(request,line)){return 2;}
  state=RenderState(); idleMode=IDLE_OFF; paused=false; speed=1; frameDirty=true;
  phaseRealOrigin=phaseVirtualOrigin=lastFrameAt=0;
  std::fill(std::begin(pixels.values),std::end(pixels.values),0);
  JsonObjectConst cmd=request["command"].as<JsonObjectConst>();
  const char* error=nullptr; RenderState next;
  bool ok=strcmp(cmd["op"]|"","show")==0?parseShow(cmd,next,error):parseText(cmd,next,error);
  if(ok){
   next.id=cmd["id"]|1; applyRenderState(next,0);
   uint32_t now=request["now"]|0;
   render(now);
   JsonArray frame=response["frame"].to<JsonArray>();
   for(int i=0;i<64;i++){
    int x=i%8,y=i/8; uint32_t c=pixels.values[y*8+(y%2?7-x:x)];
    JsonArray p=frame.add<JsonArray>(); p.add((c>>16)&255);p.add((c>>8)&255);p.add(c&255);
   }
  }else response["error"]=error?error:"rejected";
  response["ok"]=ok;
  serializeJson(response,std::cout);std::cout<<std::endl;
 }
}
'''
    BUILD.mkdir(parents=True,exist_ok=True)
    (BUILD/'render.cpp').write_text(cpp)
    result = subprocess.run(['c++','-std=c++17','-Wno-deprecated-declarations','-I'+str(Path(library)/'src'),
      '-I'+str(ROOT/'firmware/IconShow'), str(BUILD/'render.cpp'),'-o',str(BUILD/'render')],capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('Native compilation failed:\n'+result.stderr[-4000:])


def main():
    build()
    data=json.loads((ROOT/'data/icons.json').read_text())
    vectors=[]
    for name,icon in data['icons'].items():
        vectors += [({'id':1,'op':'show','icon':name},t) for t in (0,icon['period_ms']//2,icon['period_ms']-1)]
    for color in ('solid','step','gradient','rainbow_cycle','rainbow_flow'):
        spec={'mode':color,'period_ms':4000}
        if color=='solid': spec['values']=['white']
        elif color in ('step','gradient'): spec['values']=['red','blue']
        for effect in ('none','breathe','alternate','blink'):
            command={'id':1,'op':'show','icon':'heart','color':spec,'effect':{'type':effect,'period_ms':2000},'brightness':255}
            vectors += [(command,t) for t in (0,300,1200)]
    for value in ('0','007','3.14','100%','Hello','25% LEFT'):
        for direction in ('left','right'):
            vectors += [({'id':1,'op':'text','text':value,'scroll':{'direction':direction,'repeat':0}},t) for t in (0,80,640,1040)]
    vectors += [({'id':1,'op':'show','icon':'smile','animation':{'period_ms':8000}},t) for t in (0,1000,7500,7900)]
    native=subprocess.Popen([str(BUILD/'render')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    node_code="require('./web/data.js'); const E=require('./web/engine.js').IconEngine; require('readline').createInterface({input:process.stdin}).on('line',l=>{const v=JSON.parse(l),e=new E(IconData),r=e.execute(v.command,0); console.log(JSON.stringify({ok:r.ok,error:r.error,frame:e.frame(v.now)}));});"
    js=subprocess.Popen(['node','-e',node_code],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    failures=[]
    try:
        for command,now in vectors:
            line=json.dumps({'command':command,'now':now})+'\n'
            for proc in (native,js): proc.stdin.write(line);proc.stdin.flush()
            a=json.loads(native.stdout.readline());b=json.loads(js.stdout.readline())
            if not a['ok'] or not b['ok']:
                failures.append((command,now,a.get('error'),b.get('error')));continue
            delta=max(abs(x-y) for p,q in zip(a['frame'],b['frame']) for x,y in zip(p,q))
            if delta>1: failures.append((command,now,delta))
        for value in ('A\0中', 'A\0'+'X'*64, '中', 'X'*65, '\n'):
            command={'id':1,'op':'text','text':value}
            line=json.dumps({'command':command,'now':0})+'\n'
            for proc in (native,js): proc.stdin.write(line);proc.stdin.flush()
            a=json.loads(native.stdout.readline());b=json.loads(js.stdout.readline())
            if a['ok'] or b['ok']:
                failures.append((command,'invalid text accepted',a.get('ok'),b.get('ok')))
    finally:
        for proc in (native,js): proc.stdin.close();proc.wait(timeout=5)
    (BUILD/'parity-failures.json').write_text(json.dumps(failures,indent=2))
    assert not failures, f'{len(failures)}/{len(vectors)} render vectors differ: '+json.dumps(failures[:8])
    print(f'PASS native firmware/JavaScript parity: {len(vectors)} actual source render vectors, <=1 channel rounding tolerance; 5 invalid text cases rejected')

if __name__=='__main__': main()
