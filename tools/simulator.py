#!/usr/bin/env python3
"""Local-only WebSocket device simulator plus static HTML server. No hardware I/O."""
import argparse
import asyncio
import functools
import http.server
import json
import os
from pathlib import Path
import secrets
import signal
import threading

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    token = os.environ.get('ICONSHOW_SIM_TOKEN') or secrets.token_hex(16)
    http_server = http.server.ThreadingHTTPServer(('127.0.0.1', args.http_port),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / 'web')))
    bridge = await asyncio.create_subprocess_exec(
        'node', str(ROOT / 'tools/engine_bridge.cjs'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    lock = asyncio.Lock()

    async def command(value):
        async with lock:
            bridge.stdin.write((json.dumps({'command': value}) + '\n').encode())
            await bridge.stdin.drain()
            result = await asyncio.wait_for(bridge.stdout.readline(), timeout=3)
            if not result:
                raise RuntimeError('renderer stopped')
            return json.loads(result)

    async def handler(socket):
        if socket.request.path != '/ws':
            await socket.close(1008, 'Use /ws')
            return
        authenticated = False
        failures = 0
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=None if authenticated else 10)
                except asyncio.TimeoutError:
                    await socket.close(1008, 'Authentication timeout')
                    return
                request_id = None
                try:
                    if not isinstance(raw, str):
                        raise ValueError('text_required')
                    value = json.loads(raw)
                    if not isinstance(value, dict):
                        raise ValueError('invalid_command')
                    request_id = value.get('id')
                    if type(request_id) is not int or not 1 <= request_id <= 2147483647:
                        reply = {'id': None, 'ok': False, 'error': 'invalid_id'}
                    elif value.get('op') == 'auth' and (set(value) != {'id', 'op', 'token'} or not isinstance(value.get('token'), str)):
                        reply = {'id': request_id, 'ok': False, 'error': 'invalid_parameters'}
                    elif value.get('op') == 'auth':
                        supplied = value.get('token')
                        authenticated = secrets.compare_digest(supplied.encode('utf-8'), token.encode('utf-8'))
                        reply = {'id': request_id, 'ok': authenticated, 'simulator': True}
                        if not authenticated:
                            reply['error'] = 'unauthorized'
                            failures += 1
                    elif not authenticated:
                        reply = {'id': request_id, 'ok': False, 'error': 'unauthorized'}
                        failures += 1
                    elif value.get('op') == 'provision':
                        reply = {'id': request_id, 'ok': False, 'error': 'hardware_required' if set(value) == {'id', 'op'} else 'invalid_parameters'}
                    else:
                        reply = await command(value)
                    await socket.send(json.dumps(reply, separators=(',', ':')))
                    if failures >= 3:
                        await socket.close(1008, 'Authentication failed')
                        return
                except (ValueError, json.JSONDecodeError):
                    await socket.send(json.dumps({'id': request_id, 'ok': False, 'error': 'invalid_json'}))
        except ConnectionClosed:
            pass

    # Bind to loopback only: the simulator is a development tool, never a LAN device.
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    print(f'HTML: http://localhost:{args.http_port}', flush=True)
    print(f'Simulated device: ws://localhost:{args.ws_port}/ws', flush=True)
    # Only a generated development token; never print a user-supplied credential.
    print('Token: ' + (token if not os.environ.get('ICONSHOW_SIM_TOKEN') else '(from ICONSHOW_SIM_TOKEN)'), flush=True)
    print('SIMULATOR ONLY — no BLE or LED hardware is connected.', flush=True)
    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)
    try:
        async with serve(handler, '127.0.0.1', args.ws_port, max_size=512, max_queue=8):
            await stopping.wait()
    finally:
        http_server.shutdown()
        http_server.server_close()
        bridge.terminate()
        await bridge.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-port', type=int, default=8000)
    parser.add_argument('--ws-port', type=int, default=8765)
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        parser.exit(1, f'Simulator could not start: {error.strerror}. Choose free --http-port / --ws-port values.\n')
