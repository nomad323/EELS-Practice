// Offline browser latency probe; Node >=22 and an already installed Chromium.
// Usage: node tests/browser_latency.mjs /path/to/chrome [source-checkout]
// Starts only its own loopback server/private browser; writes JSON to stdout.
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';

const executable = process.argv[2];
if (!executable) throw new Error('Supply an installed Chromium; no dependencies are downloaded.');
const root = process.argv[3] ? resolve(process.argv[3]) : new URL('../', import.meta.url).pathname;
const listener = net.createServer(); listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
const origin = `http://127.0.0.1:${port}`;
const service = spawn('python3', ['run.py', '--port', String(port)], {
  cwd: root, env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}, stdio: ['ignore', 'pipe', 'pipe'],
});
let browser, socket, sessionId, nextId = 0;
const pending = new Map(), exceptions = [], requests = [], networkFrames = [];
async function waitFor(fn, description) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await fn()) return;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error(`Timeout: ${description}`);
}
function command(method, params = {}, target = sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve: value => { clearTimeout(timeout); resolve(value); }, reject: error => { clearTimeout(timeout); reject(error); }});
    socket.send(JSON.stringify({id, method, params, ...(target ? {sessionId: target} : {})}));
  });
}
async function evaluate(expression) {
  const r = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function idle() {
  await waitFor(() => evaluate(`document.body.dataset.ready === 'true' && !running && !dirty`), 'UI idle');
  assert.equal(await evaluate(`document.getElementById('error').textContent`), '');
}
function summary(rows) {
  return Object.fromEntries(Object.keys(rows[0]).map(key => {
    const sorted = rows.map(r => r[key]).sort((a, b) => a-b);
    return [key, {median: +sorted[Math.floor(sorted.length/2)].toFixed(2), p95: +sorted[Math.floor(sorted.length*0.95)].toFixed(2)}];
  }));
}
try {
  let serverReady = false;
  service.stdout.on('data', data => { if (String(data).includes('http://localhost:')) serverReady = true; });
  service.stderr.on('data', data => process.stderr.write(data));
  await waitFor(() => serverReady, 'local server');
  const profile = await mkdtemp(join(tmpdir(), 'eels-latency-'));
  browser = spawn(executable, ['--headless=new', '--no-sandbox', '--disable-gpu', '--no-proxy-server',
    '--disable-background-networking', '--disable-component-update', '--no-first-run', '--disable-default-apps',
    '--disable-dev-shm-usage', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
  let wsURL;
  browser.stderr.on('data', data => { const match = String(data).match(/DevTools listening on (ws:\/\/\S+)/); if (match) wsURL = match[1]; });
  await waitFor(() => wsURL, 'Chromium DevTools');
  socket = new WebSocket(wsURL); await once(socket, 'open');
  socket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const item = pending.get(data.id); if (!item) return; pending.delete(data.id);
      if (data.error) item.reject(new Error(JSON.stringify(data.error))); else item.resolve(data.result);
    } else if (data.method === 'Runtime.exceptionThrown') exceptions.push(data.params);
    else if (data.method === 'Network.requestWillBeSent') requests.push(data.params.request.url);
    else if (data.method === 'Network.responseReceived' && data.params.response.url === `${origin}/api/frame`) {
      const r = data.params.response;
      networkFrames.push({protocol: r.protocol, reused: r.connectionReused, connection: r.connectionId});
    }
  });
  const target = await command('Target.createTarget', {url: 'about:blank'}, null);
  sessionId = (await command('Target.attachToTarget', {targetId: target.targetId, flatten: true}, null)).sessionId;
  await command('Runtime.enable'); await command('Page.enable'); await command('Network.enable');
  await command('Emulation.setDeviceMetricsOverride', {width: 1366, height: 768, deviceScaleFactor: 1, mobile: false});
  await command('Page.navigate', {url: `${origin}/`}); await idle();
  // Observe the real application pipeline without adding response delays.
  await evaluate(`(() => {
    window.__sample = null;
    const originalPost = post;
    post = async (...args) => {
      const sample = window.__sample;
      if (sample && args[0] === '/api/frame') sample.sent = performance.now();
      const response = await originalPost(...args);
      if (sample && args[0] === '/api/frame') sample.received = performance.now();
      return response;
    };
    const originalRender = render;
    render = (frame, image) => {
      const before = performance.now(); originalRender(frame, image);
      const sample = window.__sample;
      if (sample) {
        window.__sample = null;
        sample.resolve({input_to_canvas_ms: performance.now()-sample.start,
          scheduling_ms: sample.sent-sample.start, http_json_ms: sample.received-sample.sent,
          image_ready_ms: before-sample.received, render_ms: performance.now()-before,
          backend_ms: frame.elapsed_ms});
      }
    };
  })()`);
  const cases = [];
  for (const [mode, difficulty, quality] of [['free','medium','normal'], ['practice','medium','normal'],
      ['practice','hell','normal'], ['free','medium','high'], ['practice','hell','high']]) {
    // Parent revisions without hell still support the other comparison cases.
    if (difficulty === 'hell' && !await evaluate(`Array.from(document.getElementById('difficulty').options).some(o => o.value==='hell')`)) continue;
    await evaluate(`(() => {
      finishWheel(); document.getElementById('mode').value=${JSON.stringify(mode)};
      document.getElementById('quality').value=${JSON.stringify(quality)};
      document.getElementById('difficulty').value=${JSON.stringify(difficulty)};
      document.getElementById('mode').dispatchEvent(new Event('change', {bubbles:true}));
    })()`); await idle();
    const rows = [];
    for (let i = 0; i < 44; i++) {
      const row = await evaluate(`new Promise(resolve => {
        window.__sample={start:performance.now(), resolve};
        const el=document.getElementById(${JSON.stringify(i%2 ? 'value-D01' : 'slide-D01')});
        el.value=${i/4}; el.dispatchEvent(new Event('input', {bubbles:true}));
      })`);
      assert.equal(await evaluate('lastFrame.controls.D01 === controls.D01'), true);
      if (i >= 4) rows.push(row);
    }
    cases.push({mode, difficulty, quality, samples: rows.length, milliseconds: summary(rows)});
  }
  // Compare PNG decoding mechanisms on exactly the same image, independently
  // of HTTP/backend work. Browser display refresh timing can dominate decode().
  const decode = await evaluate(`(async () => {
    const raw=atob(lastFrame.image_png), bytes=Uint8Array.from(raw, c=>c.charCodeAt(0));
    const blob=new Blob([bytes], {type:'image/png'}), rows=[];
    for (let i=0;i<24;i++) {
      let t=performance.now();
      const image=new Image(); image.src='data:image/png;base64,'+lastFrame.image_png; await image.decode();
      const html=performance.now()-t; t=performance.now();
      const bitmap=await createImageBitmap(blob); const bitmapTime=performance.now()-t;
      if (bitmap.width!==image.naturalWidth || bitmap.height!==image.naturalHeight) throw new Error('decode size mismatch');
      bitmap.close(); if (i>=4) rows.push({html_decode_ms:html, bitmap_decode_ms:bitmapTime});
    }
    return rows;
  })()`);
  assert.deepEqual(exceptions, []);
  assert.deepEqual(requests.filter(url => !url.startsWith(`${origin}/`) && !url.startsWith('data:')), []);
  console.log(JSON.stringify({status: 'PASS', browser: (await command('Browser.getVersion', {}, null)).product,
    scope: 'Linux loopback, warm caches; synthetic input event to canvas submission, not physical display presentation or Windows/WSL forwarding; no fixed speed assertion',
    cases, png_decoding: summary(decode), http: {frames: networkFrames.length,
      reused: networkFrames.filter(f => f.reused).length, connections: new Set(networkFrames.map(f => f.connection)).size,
      protocols: [...new Set(networkFrames.map(f => f.protocol))]}, temporary_profile: profile}, null, 2));
} finally {
  if (socket) socket.close();
  for (const child of [browser, service]) {
    if (child && child.exitCode === null) { child.kill('SIGTERM'); await Promise.race([once(child, 'exit'), new Promise(resolve => setTimeout(resolve, 3000))]); }
  }
}
