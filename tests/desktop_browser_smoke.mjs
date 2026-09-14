// Linux/offline real-browser lifetime regression. Uses an existing Chromium;
// substitutes only the OS browser opener with a captured URL, never installs.
// Usage: node tests/desktop_browser_smoke.mjs /path/to/chrome
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';

const executable = process.argv[2];
if (!executable) throw new Error('Supply an existing Chromium executable; no downloads.');
const root = fileURLToPath(new URL('../', import.meta.url));
const children = [], pending = new Map(), exceptions = [];
let browser, socket, nextId = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await sleep(50); }
  throw new Error(`Timeout: ${label}`);
}
function command(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, {resolve: r => {clearTimeout(timer); resolve(r);}, reject: e => {clearTimeout(timer); reject(e);}});
    socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  });
}
async function evaluate(expression, sessionId) {
  const r = await command('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true}, sessionId);
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function launch() {
  const child = spawn('python3', ['-u', '-c', 'import sys; sys.path.insert(0,"src"); from eels_sim.desktop import run; run(opener=lambda url: print(url, flush=True) or True)'],
    {cwd:root, stdio:['ignore','pipe','pipe']});
  children.push(child);
  let text = '', errors = '';
  child.stdout.on('data', data => {text += data;});
  child.stderr.on('data', data => {errors += data;});
  await waitFor(() => text.includes('\n') || child.exitCode !== null, 'launcher URL');
  assert.equal(child.exitCode, null, errors);
  return {child, url:text.trim()};
}
async function ready(sessionId) {
  await waitFor(() => evaluate(`document.documentElement.dataset.desktop === 'connected' && document.body.dataset.ready === 'true' && !running && !dirty`, sessionId), 'connected and rendered');
  assert.equal(await evaluate(`document.getElementById('error').textContent`, sessionId), '');
  assert.ok(Math.abs(Number(await evaluate(`document.getElementById('fwhm').textContent`, sessionId)) - 8) < 0.2);
}
async function openPage(url) {
  const {targetId} = await command('Target.createTarget', {url:'about:blank'});
  const {sessionId} = await command('Target.attachToTarget', {targetId, flatten:true});
  await command('Runtime.enable', {}, sessionId);
  await command('Page.enable', {}, sessionId);
  await command('Page.navigate', {url}, sessionId);
  await ready(sessionId);
  return {targetId, sessionId};
}
async function exited(app) {
  await waitFor(() => app.child.exitCode !== null, 'launcher exits after last page', 15000);
  assert.equal(app.child.exitCode, 0);
  const parsed = new URL(app.url);
  const listening = await new Promise(resolve => {
    const connection = net.connect({host:parsed.hostname, port:Number(parsed.port)});
    connection.once('connect', () => {connection.destroy(); resolve(true);});
    connection.once('error', () => resolve(false));
  });
  assert.equal(listening, false, 'listening socket is released');
}
try {
  const profile = await mkdtemp(join(tmpdir(), 'eels-desktop-browser-'));
  browser = spawn(executable, ['--headless=new','--no-sandbox','--disable-gpu','--no-proxy-server',
    '--disable-background-networking','--disable-component-update','--no-first-run','--disable-default-apps',
    '--disable-dev-shm-usage','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], {stdio:['ignore','ignore','pipe']});
  children.push(browser);
  let wsURL;
  browser.stderr.on('data', data => {const match = String(data).match(/DevTools listening on (ws:\/\/\S+)/); if (match) wsURL = match[1];});
  await waitFor(() => wsURL, 'Chromium');
  socket = new WebSocket(wsURL); await once(socket, 'open');
  socket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const item = pending.get(data.id); if (!item) return; pending.delete(data.id);
      if (data.error) item.reject(new Error(JSON.stringify(data.error))); else item.resolve(data.result);
    } else if (data.method === 'Runtime.exceptionThrown') exceptions.push(data.params);
  });
  const product = (await command('Browser.getVersion')).product;
  const unrelated = await command('Target.createTarget', {url:'about:blank'});
  const app = await launch();
  const first = await openPage(app.url);
  await command('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:false}, first.sessionId);
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth', first.sessionId), false, 'portable status does not overflow narrow screens');
  await command('Emulation.setDeviceMetricsOverride', {width:1366, height:768, deviceScaleFactor:1, mobile:false}, first.sessionId);
  // Real reload, not synthetic unload: keeps the launcher, rebuilds the UI.
  const sessionBefore = await evaluate('session', first.sessionId);
  await command('Page.reload', {ignoreCache:true}, first.sessionId);
  await waitFor(() => evaluate(`typeof session !== 'undefined' && session !== ${JSON.stringify(sessionBefore)}`, first.sessionId), 'new session after reload');
  await ready(first.sessionId);
  const second = await openPage(app.url);
  await command('Target.closeTarget', {targetId:first.targetId});
  await sleep(8000);
  assert.equal(app.child.exitCode, null, 'one remaining page keeps the application alive');
  // Freeze page JS for longer than disconnect grace; stream is network-owned.
  await command('Page.setWebLifecycleState', {state:'frozen'}, second.sessionId);
  await sleep(8000);
  assert.equal(app.child.exitCode, null, 'frozen JS must not trigger timer-based shutdown');
  await command('Page.setWebLifecycleState', {state:'active'}, second.sessionId);
  await ready(second.sessionId);
  const closeStart = Date.now();
  await command('Target.closeTarget', {targetId:second.targetId});
  await exited(app);
  const closeSeconds = (Date.now() - closeStart) / 1000;
  assert.equal(browser.exitCode, null, 'does not kill the user browser');
  assert.ok((await command('Target.getTargets')).targetInfos.some(t => t.targetId === unrelated.targetId));
  // Repeated double-clicks are isolated instances, not competing fixed ports.
  const a = await launch(), b = await launch();
  assert.notEqual(new URL(a.url).port, new URL(b.url).port);
  const pageA = await openPage(a.url);
  await openPage(b.url);
  await command('Target.closeTarget', {targetId:pageA.targetId});
  await exited(a);
  assert.equal(b.child.exitCode, null, 'closing one instance does not stop another');
  // Hard browser termination has no pagehide/beacon; socket cleanup still exits.
  browser.kill('SIGKILL');
  await exited(b);
  assert.deepEqual(exceptions, []);
  console.log(JSON.stringify({status:'PASS', browser:product, last_page_exit_seconds:closeSeconds,
    checks:['initial render', 'portable status fits narrow screen', 'real reload reconnects', 'multiple tabs', 'frozen JS retains lifetime',
      'last tab releases port and exits process', 'unrelated browser tab survives', 'independent instances',
      'browser crash cleanup without pagehide', 'no JS exceptions'], temporary_profile:profile}, null, 2));
} finally {
  socket?.close();
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM');
      await Promise.race([once(child, 'exit'), sleep(3000)]);
    }
  }
}
