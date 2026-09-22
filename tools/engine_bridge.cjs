// A single renderer instance shared by every simulated control connection.
'use strict';
require('../web/data.js');
const exported = require('../web/engine.js');
const Engine = exported.IconEngine || exported;
const engine = new Engine(globalThis.IconData);
const start = performance.now();
require('node:readline').createInterface({input: process.stdin}).on('line', line => {
  try {
    const request = JSON.parse(line);
    const now = request.now ?? performance.now() - start;
    const response = request.frame ? {frame: engine.frame(now)} : engine.execute(request.command, now);
    process.stdout.write(JSON.stringify(response) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({ok: false, error: 'bridge_error', detail: error.message}) + '\n');
  }
});
