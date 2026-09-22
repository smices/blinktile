#!/usr/bin/env python3
"""Real loopback WebSocket checks; does not contact or flash a physical device."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'iconshow-automated-test-only'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def exercise(port):
    async with connect(f'ws://127.0.0.1:{port}/ws') as ws:
        for value in [None,True,0,2147483648]:
            request={'op':'auth','token':TOKEN}
            if value is not None: request['id']=value
            await ws.send(json.dumps(request))
            assert json.loads(await ws.recv())['error']=='invalid_id'
        await ws.send(json.dumps({'id':1,'op':'auth','token':TOKEN,'extra':1}))
        assert json.loads(await ws.recv())['error']=='invalid_parameters'
        await ws.send(json.dumps({'id':2,'op':'auth','token':'测试'}))
        assert json.loads(await ws.recv())['error']=='unauthorized'
        await ws.send(json.dumps({'id':3,'op':'auth','token':TOKEN}))
        assert json.loads(await ws.recv())['ok'], 'connection survives invalid Unicode authentication'
    async with connect(f'ws://127.0.0.1:{port}/ws') as ws:
        async def send(command):
            await ws.send(json.dumps(command))
            return json.loads(await asyncio.wait_for(ws.recv(), 5))
        denied = await send({'id': 1, 'op': 'show', 'icon': 'success'})
        assert denied['ok'] is False and denied['error'] == 'unauthorized'
        assert (await send({'id': 2, 'op': 'auth', 'token': TOKEN}))['ok']
        assert (await send({'id': 3, 'op': 'show', 'icon': 'loading', 'duration_ms': 10000}))['ok']
        assert (await send({'id': 4, 'op': 'keepalive', 'target_id': 3}))['ok']
        assert not (await send({'id': 5, 'op': 'keepalive', 'target_id': 99}))['ok']
        assert (await send({'id': 6, 'op': 'text', 'text': '100%'}))['ok']
        assert not (await send({'id': 7, 'op': 'text', 'text': 'hello\nworld'}))['ok']
        await ws.send('{bad json')
        assert json.loads(await ws.recv())['error'] == 'invalid_json'
        assert (await send({'id': 8, 'op': 'get'}))['ok']
        assert (await send({'id': 9, 'op': 'off'}))['ok']
        assert (await send({'id': 10, 'op': 'provision'}))['error'] == 'hardware_required'
    async with connect(f'ws://127.0.0.1:{port}/ws') as ws:
        await ws.send('x' * 513)
        try:
            await ws.recv()
            raise AssertionError('oversized WebSocket message accepted')
        except ConnectionClosed:
            pass
    print('PASS transport: real WebSocket auth, commands, renewal, invalid JSON, size limit, hardware boundary')


if __name__ == '__main__':
    http_port, ws_port = free_port(), free_port()
    while http_port == ws_port:
        ws_port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / 'tools/simulator.py'), '--http-port', str(http_port), '--ws-port', str(ws_port)],
        env={**os.environ, 'ICONSHOW_SIM_TOKEN': TOKEN},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while True:
            if proc.poll() is not None:
                raise AssertionError('simulator failed: ' + proc.stderr.read()[-1500:])
            try:
                with urlopen(f'http://127.0.0.1:{http_port}/index.html', timeout=.3) as response:
                    assert response.status == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AssertionError('simulator did not start')
                time.sleep(.1)
        asyncio.run(exercise(ws_port))
        script = """const Client=require('./web/client.js');
(async()=>{const c=new Client();await c.connectWebSocket(process.argv[1],process.env.ICONSHOW_SIM_TOKEN);
if(!c.connected||!c.simulator)throw Error('auth state');
for(const result of [await c.showIcon('loading'),await c.showText('100%'),await c.setBrightness(64),await c.off()])if(!result.ok)throw Error(result.error);
const state=await c.getState();if(state.state.brightness!==64)throw Error('brightness');c.disconnect();
console.log('PASS actual JavaScript client to WebSocket simulator');})().catch(e=>{console.error(e);process.exitCode=1;});"""
        subprocess.run(['node','-e',script,f'ws://127.0.0.1:{ws_port}/ws'],cwd=ROOT,
          env={**os.environ,'ICONSHOW_SIM_TOKEN':TOKEN},check=True,timeout=15)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
