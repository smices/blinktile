#!/usr/bin/env python3
"""Focused checks for hook privacy, fail-open delivery, and display ownership."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
from websockets.asyncio.client import connect
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from codex_status import ACTOR_TIMEOUT, SerialDevice, StatusBridge  # noqa: E402


class FakeDevice:
    def __init__(self, clock=lambda: 0.0):
        self.clock = clock
        self.current_id = None
        self.content = None
        self.expires_at = 0
        self.commands = []

    async def command(self, command):
        self.commands.append(command.copy())
        op = command['op']
        if op == 'get':
            if self.current_id is not None and self.clock() >= self.expires_at:
                self.current_id = None
                self.content = None
            return {'ok': True, 'state': {'current_id': self.current_id, 'content': self.content}}
        if op == 'show':
            self.current_id = command['id']
            self.content = {'id': command['id'], 'icon': command['icon']}
            self.expires_at = self.clock() + command['duration_ms'] / 1000
            return {'ok': True}
        if op == 'keepalive':
            if command['target_id'] == self.current_id:
                self.expires_at = self.clock() + 15
                return {'ok': True}
            return {'ok': False}
        raise AssertionError(op)


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.lines = [b'boot diagnostic\r\n', b'{"id":7,"ok":true}\r\n']

    def write(self, value):
        self.writes.append(value)

    def readline(self):
        return self.lines.pop(0) if self.lines else b''


class CodexStatusTests(unittest.TestCase):
    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def test_hook_sends_only_identifiers_and_fails_open(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            hook = {'hook_event_name': 'PreToolUse', 'session_id': 's.1', 'turn_id': 't-2',
                    'agent_id': 'a:3', 'prompt': 'must not escape', 'tool_input': {'secret': 'x'}}
            proc = subprocess.run([sys.executable, str(ROOT / 'tools/codex_status.py'),
                                   'hook', '--port', str(server.server_port)],
                                  input=json.dumps(hook), text=True, capture_output=True, timeout=3)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(received, [{'hook_event_name': 'PreToolUse', 'session_id': 's.1',
                                         'turn_id': 't-2', 'agent_id': 'a:3'}])
            proc = subprocess.run([sys.executable, str(ROOT / 'tools/codex_status.py'),
                                   'hook', '--port', '1'], input='{}', text=True,
                                  capture_output=True, timeout=3)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout + proc.stderr, '')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_serial_json_line_framing(self):
        async def exercise():
            serial = FakeSerial()
            device = SerialDevice(serial)
            reply = await device.command({'id': 7, 'op': 'get'})
            self.assertEqual(reply, {'id': 7, 'ok': True})
            self.assertEqual(serial.writes, [b'{"id":7,"op":"get"}\n'])

        asyncio.run(exercise())

    def test_concurrency_foreign_content_and_completion(self):
        async def exercise():
            now = [0.0]
            device = FakeDevice(clock=lambda: now[0])
            bridge = StatusBridge(device, clock=lambda: now[0])
            self.assertTrue(bridge.accept({'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'turn_id': 't1'}))
            self.assertTrue(bridge.accept({'hook_event_name': 'SubagentStart', 'session_id': 's1',
                                           'turn_id': 't1', 'agent_id': 'a1'}))
            await bridge.tick()
            owned = device.current_id
            self.assertEqual(device.commands[-1]['icon'], 'loading')
            bridge.accept({'hook_event_name': 'PermissionRequest', 'session_id': 's1', 'turn_id': 't1'})
            await bridge.tick()
            waiting = device.commands[-1]
            self.assertEqual((waiting['icon'], waiting['color']['values'], waiting['effect']['type']),
                             ('question', ['orange'], 'breathe'))
            self.assertEqual(waiting['duration_ms'], 15000)
            bridge.accept({'hook_event_name': 'PostToolUse', 'session_id': 's1', 'turn_id': 't1'})
            await bridge.tick()
            self.assertEqual(device.commands[-1]['icon'], 'loading')
            owned = device.current_id
            await bridge.tick()
            self.assertEqual(device.commands[-1], {'id': bridge.request_id, 'op': 'keepalive', 'target_id': owned})

            device.current_id = bridge.owned_id
            device.content = {'id': bridge.owned_id, 'icon': 'heart'}  # foreign content reused the ID
            before = len(device.commands)
            await bridge.tick()
            self.assertEqual(device.commands[-1]['op'], 'get')
            self.assertEqual(device.content['icon'], 'heart')
            device.current_id = None
            device.content = None
            await bridge.tick()
            self.assertEqual(device.commands[-1]['icon'], 'loading')
            owned = device.current_id

            bridge.accept({'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'turn_id': 't2'})
            bridge.accept({'hook_event_name': 'Stop', 'session_id': 's1', 'turn_id': 't1'})
            self.assertEqual(bridge.desired(), 'running')  # late stop cannot clear a newer turn
            bridge.accept({'hook_event_name': 'Stop', 'session_id': 's1', 'turn_id': 't2'})
            bridge.accept({'hook_event_name': 'Stop', 'session_id': 's1', 'turn_id': 't1'})
            self.assertEqual(bridge.desired(), 'running')  # subagent still active
            bridge.accept({'hook_event_name': 'SubagentStop', 'session_id': 's1', 'turn_id': 't1', 'agent_id': 'a1'})
            self.assertEqual(bridge.desired(), 'success')
            await bridge.tick()
            self.assertEqual(device.commands[-1]['icon'], 'success')
            self.assertNotIn('release', [c['op'] for c in device.commands[-2:]])
            device.current_id = 777  # another app took over
            await bridge.tick()
            self.assertEqual(device.current_id, 777)
            self.assertNotIn('release', [c['op'] for c in device.commands])
            device.current_id = None
            await bridge.tick()
            self.assertEqual(device.commands[-1]['icon'], 'success')
            now[0] += 1
            before = len(device.commands)
            await bridge.tick()
            self.assertEqual(len(device.commands), before + 1)  # get only; success is not renewed or released
            self.assertEqual(device.commands[-1]['op'], 'get')
            now[0] += 3.1
            await bridge.tick()
            self.assertIsNone(device.current_id)
            self.assertEqual(device.commands[-1]['op'], 'get')
            bridge.accept({'hook_event_name': 'UserPromptSubmit', 'session_id': 'stale', 'turn_id': 't1'})
            now[0] += ACTOR_TIMEOUT + 1
            self.assertIsNone(bridge.desired())
            bridge.accept({'hook_event_name': 'SubagentStart', 'session_id': 'orphan',
                           'turn_id': 't1', 'agent_id': 'a1'})
            bridge.accept({'hook_event_name': 'SubagentStop', 'session_id': 'orphan',
                           'turn_id': 't1', 'agent_id': 'a1'})
            self.assertIsNone(bridge.desired(), 'subagent completion alone is not main-turn success')

        asyncio.run(exercise())

    def test_hook_bridge_to_existing_simulator(self):
        async def exercise():
            http_port, ws_port, bridge_port = self.free_port(), self.free_port(), self.free_port()
            token = 'codex-status-test-token'
            env = {**os.environ, 'ICONSHOW_SIM_TOKEN': token, 'ICONSHOW_TOKEN': token}
            simulator = subprocess.Popen(
                [sys.executable, str(ROOT / 'tools/simulator.py'), '--http-port', str(http_port),
                 '--ws-port', str(ws_port)], env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, start_new_session=True)
            bridge = None

            async def state():
                async with connect(f'ws://127.0.0.1:{ws_port}/ws') as ws:
                    async def send(value):
                        await ws.send(json.dumps(value))
                        return json.loads(await ws.recv())
                    self.assertTrue((await send({'id': 1, 'op': 'auth', 'token': token}))['ok'])
                    return await send({'id': 2, 'op': 'get'})

            def hook(event):
                request = Request(f'http://127.0.0.1:{bridge_port}/hook',
                                  data=json.dumps(event).encode(),
                                  headers={'Content-Type': 'application/json'}, method='POST')
                with urlopen(request, timeout=1) as response:
                    self.assertEqual(response.status, 204)

            try:
                deadline = time.monotonic() + 8
                while True:
                    if simulator.poll() is not None:
                        self.fail('simulator exited before WebSocket became ready')
                    try:
                        async with connect(f'ws://127.0.0.1:{ws_port}/ws'):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            self.fail('simulator did not start')
                        await asyncio.sleep(.05)
                bridge = subprocess.Popen(
                    [sys.executable, str(ROOT / 'tools/codex_status.py'), 'bridge',
                     '--ws-url', f'ws://127.0.0.1:{ws_port}/ws', '--listen-port', str(bridge_port)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                    start_new_session=True)
                deadline = time.monotonic() + 8
                while True:
                    if bridge.poll() is not None:
                        self.fail('bridge exited before hook listener became ready')
                    try:
                        with socket.create_connection(('127.0.0.1', bridge_port), timeout=.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            self.fail('bridge did not start')
                        await asyncio.sleep(.05)
                hook({'hook_event_name': 'UserPromptSubmit', 'session_id': 'e2e', 'turn_id': 't1'})
                deadline = time.monotonic() + 4
                while True:
                    result = await state()
                    content = (result.get('state') or {}).get('content') or {}
                    if content.get('icon') == 'loading':
                        break
                    if time.monotonic() > deadline:
                        self.fail('running status did not reach simulator')
                    await asyncio.sleep(.1)
                hook({'hook_event_name': 'Stop', 'session_id': 'e2e', 'turn_id': 't1'})
                deadline = time.monotonic() + 4
                while True:
                    result = await state()
                    content = (result.get('state') or {}).get('content') or {}
                    if content.get('icon') == 'success':
                        break
                    if time.monotonic() > deadline:
                        self.fail('success status did not reach simulator')
                    await asyncio.sleep(.1)
                await asyncio.sleep(3.2)
                result = await state()
                self.assertIsNone(result['state']['current_id'])
                self.assertEqual(result['state']['idle'], 'pet')
            finally:
                for process in (bridge, simulator):
                    if process:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGINT)
                            process.wait(timeout=5)
                            self.assertEqual(process.returncode, 0, process.stderr.read()[-1000:])
                        if process.stderr:
                            process.stderr.close()

        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
