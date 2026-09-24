#!/usr/bin/env python3
"""Forward sanitized localhost Codex hook events to a BlinkTile device."""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import secrets
import sys
import threading
import time
from urllib.request import Request, urlopen

EVENTS = {
    'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PermissionRequest',
    'Stop', 'Interrupt', 'SessionEnd', 'SubagentStart', 'SubagentStop',
}
IDENTIFIER = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
MAX_BODY = 4096
TTL_MS = 15000
ACTOR_TIMEOUT = 10 * 60
BLE_SERVICE_UUID = '6d8f0000-6f52-4af0-9a2c-7b6143b8e100'
BLE_WRITE_UUID = '6d8f0001-6f52-4af0-9a2c-7b6143b8e100'
BLE_NOTIFY_UUID = '6d8f0002-6f52-4af0-9a2c-7b6143b8e100'
BLE_MAX_RESPONSE = 2048
BLE_PAIRING_TIMEOUT = 30


def safe_identifier(value):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else None


def hook_event(data):
    """Project stdin onto the documented fields; discard all other hook data."""
    event = data.get('hook_event_name')
    session_id = safe_identifier(data.get('session_id'))
    turn_id = safe_identifier(data.get('turn_id'))
    agent_id = safe_identifier(data.get('agent_id'))
    if event not in EVENTS or not session_id:
        return None
    result = {'hook_event_name': event, 'session_id': session_id}
    if turn_id:
        result['turn_id'] = turn_id
    if agent_id:
        result['agent_id'] = agent_id
    return result


def post_hook(event, port):
    if event is None:
        return
    try:
        request = Request(f'http://127.0.0.1:{port}/hook',
                          data=json.dumps(event, separators=(',', ':')).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=0.2):
            pass
    except Exception:
        pass  # Codex hooks are best-effort and must never block the user.


class StatusBridge:
    def __init__(self, device, clock=time.monotonic):
        self.device = device
        self.clock = clock
        self.lock = threading.Lock()
        self.actors = {}
        self.completed_sessions = set()
        self.success_until = 0.0
        self.owned_id = None
        self.request_id = secrets.randbelow(2147483647)
        self.display = None

    def accept(self, event):
        if not isinstance(event, dict):
            return False
        clean = hook_event(event)
        if clean is None:
            return False
        session, agent = clean['session_id'], clean.get('agent_id', '')
        turn = clean.get('turn_id')
        kind = clean['hook_event_name']
        now = self.clock()
        with self.lock:
            was_active = bool(self.actors)
            key = (session, agent)
            actor = self.actors.get(key)
            if kind in ('UserPromptSubmit', 'PreToolUse', 'PostToolUse',
                        'PermissionRequest', 'SubagentStart'):
                if actor and turn and actor['turn'] and actor['turn'] != turn and kind != 'UserPromptSubmit':
                    return True
                self.actors[key] = {'turn': turn,
                                    'status': 'waiting' if kind == 'PermissionRequest' else 'running',
                                    'updated': now}
                if kind == 'UserPromptSubmit':
                    self.completed_sessions.discard(session)
            elif kind in ('Stop', 'Interrupt', 'SubagentStop'):
                if actor and turn and actor['turn'] and actor['turn'] != turn:
                    return True
                self.actors.pop(key, None)
                if kind == 'Stop' and actor:
                    self.completed_sessions.add(session)
                if was_active and not self.actors and session in self.completed_sessions:
                    self.success_until = now + 3
                    self.completed_sessions.discard(session)
            elif kind == 'SessionEnd':
                self.actors = {k: v for k, v in self.actors.items() if k[0] != session}
                self.completed_sessions.discard(session)
        return True

    def desired(self):
        with self.lock:
            now = self.clock()
            self.actors = {key: actor for key, actor in self.actors.items()
                           if now - actor['updated'] < ACTOR_TIMEOUT}
            if self.actors:
                self.success_until = 0
                return 'waiting' if any(actor['status'] == 'waiting' for actor in self.actors.values()) else 'running'
            self.completed_sessions.clear()
            return 'success' if now < self.success_until else None

    def next_id(self):
        self.request_id = self.request_id % 2147483647 + 1
        return self.request_id

    async def command(self, op, **fields):
        reply = await self.device.command({'id': self.next_id(), 'op': op, **fields})
        return isinstance(reply, dict) and reply.get('ok') is True

    async def tick(self):
        state_reply = await self.device.command({'id': self.next_id(), 'op': 'get'})
        if not isinstance(state_reply, dict) or state_reply.get('ok') is not True:
            return
        state = state_reply.get('state') or {}
        current = state.get('current_id')
        desired = self.desired()
        content = state.get('content') or {}
        expected_icon = {'running': 'loading', 'waiting': 'question', 'success': 'success'}.get(self.display)
        owns_content = (self.owned_id is not None and current == self.owned_id and
                        content.get('icon') == expected_icon)

        if owns_content:
            if desired in ('running', 'waiting'):
                if self.display != desired:
                    await self.show(desired)
                else:
                    await self.command('keepalive', target_id=self.owned_id)
                return
            if desired == 'success' and self.display == desired:
                return  # Let the device's three-second TTL return to its idle pet.
            if desired == 'success':
                await self.show(desired)
                return
            self.owned_id = None
            self.display = None
            return

        self.owned_id = None
        self.display = None
        if current is not None or desired is None:
            return  # Foreign active content wins; retry after it becomes idle.
        await self.show(desired)

    async def show(self, kind):
        request_id = self.next_id()
        self.owned_id = request_id
        self.display = kind
        icon = 'loading' if kind == 'running' else 'question' if kind == 'waiting' else 'success'
        duration = TTL_MS if kind in ('running', 'waiting') else 3000
        command = {'id': request_id, 'op': 'show', 'icon': icon, 'duration_ms': duration}
        if kind == 'running':
            command['color'] = {'mode': 'rainbow_orbit', 'period_ms': 12000}
        elif kind == 'waiting':
            command['color'] = {'mode': 'solid', 'values': ['orange']}
            command['effect'] = {'type': 'breathe', 'period_ms': 1000}
        reply = await self.device.command(command)
        if not isinstance(reply, dict) or reply.get('ok') is not True:
            self.owned_id = None
            self.display = None


class Device:
    def __init__(self, ws):
        self.ws = ws

    async def command(self, command):
        await self.ws.send(json.dumps(command, separators=(',', ':')))
        return json.loads(await asyncio.wait_for(self.ws.recv(), timeout=2))


class SerialDevice:
    def __init__(self, serial_port):
        self.serial = serial_port
        self.lock = threading.Lock()

    async def command(self, command):
        return await asyncio.to_thread(self._command, command)

    def _command(self, command):
        payload = (json.dumps(command, separators=(',', ':')) + '\n').encode()
        deadline = time.monotonic() + 2
        with self.lock:
            self.serial.write(payload)
            while time.monotonic() < deadline:
                line = self.serial.readline()
                try:
                    reply = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue  # Ignore boot diagnostics and blank serial lines.
                if isinstance(reply, dict) and reply.get('id') == command['id']:
                    return reply
        raise TimeoutError('BlinkTile serial response timed out')


class BleDevice:
    def __init__(self, client):
        self.client = client
        self.lines = asyncio.Queue()
        self.buffer = bytearray()
        self.overflow = False
        self.lock = asyncio.Lock()

    async def start(self):
        await self.client.start_notify(BLE_NOTIFY_UUID, self._notification)

    def _notification(self, _characteristic, data):
        for byte in data:
            if byte == 10:
                if self.overflow:
                    self.lines.put_nowait(ValueError('BlinkTile BLE response is too large'))
                elif self.buffer:
                    self.lines.put_nowait(bytes(self.buffer))
                self.buffer.clear()
                self.overflow = False
            elif not self.overflow:
                if len(self.buffer) >= BLE_MAX_RESPONSE:
                    self.buffer.clear()
                    self.overflow = True
                else:
                    self.buffer.append(byte)

    async def command(self, command):
        async with self.lock:
            payload = (json.dumps(command, separators=(',', ':')) + '\n').encode()
            if len(payload) > 512:
                raise ValueError('BlinkTile request is too large')
            await self.client.write_gatt_char(BLE_WRITE_UUID, payload, response=True)
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError('BlinkTile BLE response timed out')
                line = await asyncio.wait_for(self.lines.get(), timeout=remaining)
                if isinstance(line, Exception):
                    raise line
                try:
                    reply = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(reply, dict) and reply.get('id') == command.get('id'):
                    return reply


async def authenticate_ble(device, token=None, clock=None, sleep=None):
    if token:
        auth = await device.command({'id': 1, 'op': 'auth', 'token': token})
        if not isinstance(auth, dict) or auth.get('ok') is not True:
            raise ValueError('BlinkTile BLE authentication failed')
        return

    clock = time.monotonic if clock is None else clock
    sleep = asyncio.sleep if sleep is None else sleep
    deadline = clock() + BLE_PAIRING_TIMEOUT
    request_id = 0
    while clock() < deadline:
        request_id += 1
        try:
            reply = await asyncio.wait_for(
                device.command({'id': request_id, 'op': 'auth'}),
                timeout=deadline - clock())
        except TimeoutError:
            break
        if isinstance(reply, dict) and reply.get('ok') is True:
            return
        remaining = deadline - clock()
        if remaining > 0:
            await sleep(min(1, remaining))
    raise ValueError('BlinkTile BLE button pairing timed out; hold BOOT for at least 1 second and retry')


async def find_ble_device(scanner, name='BlinkTile', address=None, timeout=8):
    found = await scanner.discover(timeout=timeout, return_adv=True)
    devices = [pair for pair in found.values()]
    if address:
        matches = [device for device, _advertisement in devices
                   if device.address.casefold() == address.casefold()]
    else:
        matches = [device for device, advertisement in devices
                   if (advertisement.local_name or device.name) == name]
    if not matches:
        target = f'BLE address {address}' if address else f'BLE device named {name!r}'
        raise ValueError(f'No BlinkTile {target} found; check that Bluetooth is on and the device is advertising')
    if len(matches) > 1:
        candidates = ', '.join(f'{device.name or "BlinkTile"} ({device.address})' for device in matches)
        raise ValueError(f'Multiple BlinkTile BLE devices found: {candidates}; select one with --ble-address')
    return matches[0]


async def serve_hooks(args, device):
    bridge = StatusBridge(device)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/hook' or self.headers.get('Origin'):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 < length <= MAX_BODY:
                    raise ValueError
                event = json.loads(self.rfile.read(length))
                if not bridge.accept(event):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt, *args):
            pass  # Hook payloads and device tokens never enter logs.

    server = ThreadingHTTPServer(('127.0.0.1', args.listen_port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while True:
            await bridge.tick()
            await asyncio.sleep(1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def run_bridge(args):
    if args.serial_port:
        import serial

        device = SerialDevice(serial.Serial(args.serial_port, baudrate=115200, timeout=0.2))
        auth = await device.command({'id': 1, 'op': 'auth'})
        if not isinstance(auth, dict) or auth.get('ok') is not True:
            device.serial.close()
            raise ValueError('BlinkTile serial authentication failed')
        try:
            await serve_hooks(args, device)
        finally:
            device.serial.close()
        return

    if args.ble:
        token = os.environ.get(args.token_env)
        stage = 'scan'
        try:
            from bleak import BleakClient, BleakScanner
            from bleak.exc import BleakError
        except ImportError as error:
            raise ValueError("BLE mode requires optional dependency 'bleak'; install it with 'python3 -m pip install bleak'") from error
        try:
            peripheral = await find_ble_device(
                BleakScanner, name=args.ble_name, address=args.ble_address,
                timeout=args.ble_scan_seconds)
            stage = 'connect'
            async with BleakClient(peripheral) as client:
                if client.services.get_service(BLE_SERVICE_UUID) is None:
                    raise ValueError('Selected BLE device does not provide the BlinkTile service')
                device = BleDevice(client)
                stage = 'notification subscription'
                await device.start()
                stage = 'authentication'
                if token:
                    await authenticate_ble(device, token)
                else:
                    print('When the board is running, hold BOOT for at least 1 second to pair over BLE.',
                          flush=True)
                    await authenticate_ble(device)
                    print('BlinkTile BLE authenticated; release BOOT.', flush=True)
                await serve_hooks(args, device)
        except TimeoutError as error:
            raise ValueError(f'BlinkTile BLE {stage} timed out') from error
        except BleakError as error:
            raise ValueError(f'Bluetooth operation failed: {type(error).__name__}') from None
        return

    from websockets.asyncio.client import connect

    token = os.environ.get(args.token_env)
    if not token:
        raise ValueError(f'missing token environment variable: {args.token_env}')
    async with connect(args.ws_url) as ws:
        device = Device(ws)
        auth = await device.command({'id': 1, 'op': 'auth', 'token': token})
        if not isinstance(auth, dict) or auth.get('ok') is not True:
            raise ValueError('BlinkTile authentication failed')
        await serve_hooks(args, device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    hook_parser = sub.add_parser('hook', help='forward sanitized hook stdin')
    hook_parser.add_argument('--port', type=int, default=8766)
    bridge_parser = sub.add_parser('bridge', help='serve localhost hooks and drive BlinkTile')
    transport = bridge_parser.add_mutually_exclusive_group()
    transport.add_argument('--ws-url', default='ws://127.0.0.1:8765/ws')
    transport.add_argument('--serial-port', help='USB serial device path (115200 baud)')
    bridge_parser.add_argument('--token-env', default='ICONSHOW_TOKEN')
    bridge_parser.add_argument('--listen-port', type=int, default=8766)
    transport.add_argument('--ble', action='store_true', help='connect to BlinkTile over Bluetooth LE')
    bridge_parser.add_argument('--ble-name', default='BlinkTile', help='advertised BLE device name (default: BlinkTile)')
    bridge_parser.add_argument('--ble-address', help='BLE address/UUID to select when multiple devices are nearby')
    bridge_parser.add_argument('--ble-scan-seconds', type=float, default=8,
                               help='BLE scan duration before selecting a device (default: 8)')
    args = parser.parse_args()
    if args.mode == 'bridge':
        if args.ble_address and not args.ble:
            parser.error('--ble-address requires --ble')
        if not 0 < args.ble_scan_seconds <= 120:
            parser.error('--ble-scan-seconds must be between 0 and 120')
    if args.mode == 'hook':
        try:
            value = json.load(sys.stdin)
            post_hook(hook_event(value) if isinstance(value, dict) else None, args.port)
        except Exception:
            pass
        return
    try:
        asyncio.run(run_bridge(args))
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        parser.exit(1, f'Bridge could not start: {error}\n')


if __name__ == '__main__':
    main()
