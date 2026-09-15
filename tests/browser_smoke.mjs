// Optional actual-browser regression with Node >=22 and an existing Chromium.
// No npm dependencies or downloads. Usage: node tests/browser_smoke.mjs /path/to/chrome [artifact-directory]
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdir, writeFile, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';

const executable = process.argv[2];
if (!executable) throw new Error('Supply an already installed Chromium executable; this test installs nothing.');
const listener = net.createServer(); listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
const root = new URL('../', import.meta.url).pathname;
const artifactDirectory = process.argv[3] || 'processed/validation';
const service = spawn('python3', ['run.py', '--port', String(port)], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let browser, socket;
const pending = new Map(); let nextId = 0, sessionId;
const exceptions = [], requests = [];
async function waitFor(fn, description, timeout = 20000) {
  const deadline = Date.now()+timeout;
  while (Date.now() < deadline) { if (await fn()) return; await new Promise(r => setTimeout(r, 60)); }
  throw new Error(`Timeout: ${description}`);
}
function command(method, params = {}, target = sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve: value => { clearTimeout(timeout); resolve(value); }, reject: e => { clearTimeout(timeout); reject(e); }});
    socket.send(JSON.stringify({id, method, params, ...(target ? {sessionId: target} : {})}));
  });
}
async function evaluate(expression) {
  const r = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function idle() { await waitFor(() => evaluate(`document.body.dataset.ready === 'true' && !running && !dirty`), 'UI idle'); assert.equal(await evaluate(`document.getElementById('error').textContent`), ''); }
async function change(id, value, event = 'change') {
  await evaluate(`(() => {const el=document.getElementById(${JSON.stringify(id)});el.value=${JSON.stringify(String(value))};el.dispatchEvent(new Event(${JSON.stringify(event)}, {bubbles:true}));})()`);
  await idle();
}
async function click(id) { await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`); await idle(); }
async function centre(id) {
  return evaluate(`(() => {
    const el=document.getElementById(${JSON.stringify(id)});el.scrollIntoView({block:'nearest'});
    let r=el.getBoundingClientRect();
    if (!el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))) {
      el.scrollIntoView({block:'end'});r=el.getBoundingClientRect();
    }
    return {x:r.x+r.width/2,y:r.y+r.height/2,scroll:scrollY};
  })()`);
}
async function assertWorkbenchVisible(description, allControls = true) {
  const result = await evaluate(`(() => {
    const ids = ['spot','spectrum','fwhm', ...${Array.isArray(allControls) ? JSON.stringify(allControls) : allControls ? "pageTerms(currentPage)" : "['D03']"}.flatMap(n => ['row-'+n,'slide-'+n,'value-'+n,'wheel-toggle-'+n,'wheel-step-'+n])];
    const headerBottom = document.querySelector('header').getBoundingClientRect().bottom;
    const banner = document.getElementById('wheel-session'), notice = banner.getBoundingClientRect();
    const boxes = {};
    const hidden = ids.filter(id => {
      const el = document.getElementById(id), r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
      boxes[id] = {rect:r.toJSON(),hit:hit?.id || hit?.tagName,headerBottom};
      const coveredByNotice = !banner.hidden && r.left < notice.right && r.right > notice.left && r.top < notice.bottom && r.bottom > notice.top;
      // scrollIntoView rounds scroll offsets, but grid row boxes can retain
      // fractions of a CSS pixel. Allow only the row's outer padding this error;
      // actual controls/canvases and overlay checks remain strict.
      const edge = id.startsWith('row-') ? 0.5 : 0;
      return r.width <= 0 || r.height <= 0 || r.left < -edge || r.top < headerBottom-edge || r.right > innerWidth+edge || r.bottom > innerHeight+edge || !el.contains(hit) || coveredByNotice;
    });
    return {hidden, boxes:Object.fromEntries(hidden.map(id => [id,boxes[id]])), width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth};
  })()`);
  assert.deepEqual(result.hidden, [], `${description}: controls and both plots must be visible without occlusion (${result.width}×${result.height}), ${JSON.stringify(result.boxes)}`);
  assert.equal(result.overflow, false, `${description}: no horizontal overflow`);
}
async function doubleClick(id) {
  const {x, y} = await centre(id);
  for (const clickCount of [1, 2]) {
    await command('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', clickCount});
    await command('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', clickCount});
  }
  await idle();
}
async function pointerClick(id) {
  const {x, y} = await centre(id);
  await command('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', clickCount: 1});
  await command('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', clickCount: 1});
  await idle();
}
async function key(key, extra = {}) {
  await command('Input.dispatchKeyEvent', {type: 'keyDown', key, code: key, ...extra});
  await command('Input.dispatchKeyEvent', {type: 'keyUp', key, code: key});
  await idle();
}
async function escape() { await key('Escape'); }
async function wheelAt(id, deltaY) {
  const point = await centre(id);
  await command('Input.dispatchMouseEvent', {type: 'mouseWheel', x: point.x, y: point.y, deltaX: 0, deltaY});
  await new Promise(resolve => setTimeout(resolve, 80));
  await idle();
  return {before: point.scroll, after: await evaluate('scrollY')};
}
try {
  let serverReady = false;
  service.stdout.on('data', data => { if (String(data).includes('http://localhost:')) serverReady = true; });
  service.stderr.on('data', data => process.stderr.write(data));
  await waitFor(() => serverReady, 'local server');
  const profile = await mkdtemp(join(tmpdir(), 'eels-browser-'));
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
  });
  const target = await command('Target.createTarget', {url: 'about:blank'}, null);
  sessionId = (await command('Target.attachToTarget', {targetId: target.targetId, flatten: true}, null)).sessionId;
  await command('Runtime.enable'); await command('Page.enable'); await command('Network.enable');
  await command('Emulation.setDeviceMetricsOverride', {width: 1600, height: 1150, deviceScaleFactor: 1, mobile: false});
  await command('Page.navigate', {url: `http://127.0.0.1:${port}/`}); await idle();
  assert.equal(await evaluate(`document.querySelectorAll('.coefficient').length`), 20);
  assert.equal(await evaluate(`names.every(n => ['slide-','value-'].every(prefix => {
    const el=document.getElementById(prefix+n);return el.min==='-300' && el.max==='300';
  }) && document.getElementById('wheel-step-'+n).max==='300')`), true, 'all twenty controls and step editors share the new limit');
  assert.deepEqual(await evaluate(`names.map(n => document.getElementById('wheel-step-'+n).value)`), Array(20).fill('1'), 'all orders start with a 1 meV tuning step');
  assert.equal(await evaluate(`document.getElementById('practice').hidden && document.getElementById('timer-start').disabled && document.getElementById('timer-stop').disabled`), true, 'timer is unavailable in free mode');
  assert.equal(await evaluate(`document.querySelectorAll('.coefficient:not([hidden])').length`), 9);
  await command('Emulation.setDeviceMetricsOverride', {width: 1366, height: 768, deviceScaleFactor: 1, mobile: false});
  await assertWorkbenchVisible('desktop free mode');
  const baseline = Number(await evaluate(`document.getElementById('fwhm').textContent`));
  assert.ok(Math.abs(baseline-8) < 0.2, `baseline=${baseline}`);
  await change('slide-D01', 40, 'input');
  assert.ok(Number(await evaluate(`document.getElementById('fwhm').textContent`)) > 60);
  await change('value-D20', 25, 'input');
  assert.equal(await evaluate(`document.getElementById('slide-D20').value`), '25');
  const beforeGamma = await evaluate(`JSON.stringify(lastFrame.spectrum)`);
  await change('gamma', 1.2, 'input');
  assert.equal(await evaluate(`JSON.stringify(lastFrame.spectrum)`), beforeGamma);
  await click('zero');
  assert.equal(Number(await evaluate(`document.getElementById('fwhm').textContent`)), baseline);
  // Network work must not wait for requestAnimationFrame (which browsers can
  // delay/throttle independently of a ready local backend). Hold fetches to
  // deterministically verify synchronous coalescing and the next latest input.
  for (const mode of ['free', 'practice']) {
    await change('mode', mode);
    await evaluate(`(() => {
      window.__probeRAF = window.requestAnimationFrame; window.__probeFetch = window.fetch;
      window.__probeSent = []; window.__probeRelease = [];
      window.requestAnimationFrame = () => 0; // Deliberately never invoke it.
      window.fetch = async (...args) => {
        if (args[0] !== '/api/frame') return window.__probeFetch(...args);
        window.__probeSent.push(JSON.parse(args[1].body));
        await new Promise(resolve => window.__probeRelease.push(resolve));
        return window.__probeFetch(...args);
      };
      for (const value of [1,2,3]) {
        const el=document.getElementById('value-D01'); el.value=value;
        el.dispatchEvent(new Event('input',{bubbles:true}));
      }
    })()`);
    try {
      await waitFor(() => evaluate('window.__probeSent.length === 1'), 'send without animation-frame callback');
      assert.equal(await evaluate('window.__probeSent[0].controls.D01'), 3, 'same-task edits coalesce to latest value');
      await evaluate(`for (const value of [4,5]) {
        const el=document.getElementById('slide-D01'); el.value=value;
        el.dispatchEvent(new Event('input',{bubbles:true}));
      }`);
      assert.equal(await evaluate('window.__probeSent.length'), 1, 'only one request in flight');
      await evaluate('window.__probeRelease.shift()()');
      await waitFor(() => evaluate('window.__probeSent.length === 2'), 'follow-up without animation-frame callback');
      assert.equal(await evaluate('window.__probeSent[1].controls.D01'), 5);
      assert.equal(await evaluate('controls.D01'), 5, 'intermediate response does not roll back controls');
      await evaluate('window.__probeRelease.shift()()'); await idle();
      assert.equal(await evaluate('lastFrame.controls.D01'), 5);
      assert.match(await evaluate(`document.getElementById('status').title`), /输入到绘图.*请求\/传输\/JSON.*后端/);
    } finally {
      await evaluate(`window.requestAnimationFrame=window.__probeRAF; window.fetch=window.__probeFetch;
        window.__probeRelease.splice(0).forEach(resolve=>resolve())`);
    }
  }
  await change('mode', 'free'); await click('zero');
  // Keep moving with the button held down. Delay responses to expose starvation
  // and accidental rollback even when inputs arrive faster than a frame returns.
  await evaluate(`(() => {
    window.__frames = []; window.__desiredD10 = 0; window.__inFlight = 0; window.__maxInFlight = 0;
    window.__originalFetch = window.fetch;
    window.fetch = window.__delayedFetch = async (...args) => {
      if (args[0] !== '/api/frame') return window.__originalFetch(...args);
      window.__maxInFlight = Math.max(window.__maxInFlight, ++window.__inFlight);
      try { const r = await window.__originalFetch(...args); await new Promise(resolve => setTimeout(resolve, 80)); return r; }
      finally { --window.__inFlight; }
    };
    const originalRender = render;
    render = (frame, image) => {
      originalRender(frame, image);
      window.__frames.push({value: frame.controls.D10, desired: window.__desiredD10,
        input: Number(document.getElementById('value-D10').value), width: frame.metrics.fwhm_mev,
        mode: frame.mode, uiMode: document.getElementById('mode').value});
    };
    document.getElementById('slide-D10').addEventListener('input', event => {window.__desiredD10 = Number(event.target.value);});
  })()`);
  const sliderBox = await evaluate(`(() => {const r=document.getElementById('slide-D10').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:r.width};})()`);
  await command('Input.dispatchMouseEvent', {type: 'mousePressed', x: sliderBox.x, y: sliderBox.y, button: 'left', clickCount: 1});
  for (let i = 1; i <= 36; i++) {
    await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: sliderBox.x+sliderBox.width*0.3*i/36, y: sliderBox.y, button: 'left', buttons: 1});
    await new Promise(resolve => setTimeout(resolve, 15));
  }
  const duringDrag = await evaluate('window.__frames');
  assert.ok(new Set(duringDrag.map(f => f.value)).size >= 3, `must render several distinct frames BEFORE mouse release, got ${duringDrag.length}`);
  assert.ok(duringDrag.some(f => f.width > baseline+1), 'FWHM updates while dragging');
  assert.ok(duringDrag.every(f => f.input === f.desired), 'intermediate frames must not roll back the live controls');
  await command('Input.dispatchMouseEvent', {type: 'mouseReleased', x: sliderBox.x+sliderBox.width*0.3, y: sliderBox.y, button: 'left', clickCount: 1});
  await idle();
  assert.equal(await evaluate('window.__maxInFlight'), 1, 'only one simulation request at a time');
  assert.equal(await evaluate('lastFrame.controls.D10 === controls.D10'), true, 'final frame catches up to final input');
  assert.ok(Math.abs(Number(await evaluate(`document.getElementById('value-D10').value`))) > 20, 'actual pointer drag changes slider');
  await evaluate('window.fetch = window.__originalFetch');
  await click('zero');
  // Screenshot order is presentation-only; powers and canonical export metadata
  // still agree by coefficient name, and the complete set of 20 is preserved.
  const displayOrder = ['D10','D01','D02','D20','D11','D30','D21','D12','D03',
    'D40','D31','D22','D13','D04','D50','D41','D32','D23','D14','D05'];
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('.coefficient'), el => el.id.slice(4))`), displayOrder);
  assert.deepEqual(await evaluate('names'), displayOrder);
  assert.deepEqual(await evaluate(`['D02','D20','D11'].map(n => document.querySelector('#row-'+n+' small').textContent)`), ['v²','u²','uv']);
  assert.deepEqual(await evaluate(`(() => {
    const style = id => getComputedStyle(document.getElementById(id));
    return {panel: getComputedStyle(document.querySelector('.tuning')).backgroundColor,
      scheme: getComputedStyle(document.documentElement).colorScheme,
      background: getComputedStyle(document.documentElement).backgroundColor,
      input: style('value-D10').backgroundColor, text: style('value-D10').color,
      warning: style('warnings').color, error: style('error').color,
      arrow: document.getElementById('wheel-toggle-D10').textContent,
      panels: Array.from(document.querySelectorAll('.panel')).every(p => getComputedStyle(p).backgroundColor==='rgb(25, 28, 32)')};
  })()`), {panel:'rgb(25, 28, 32)', scheme:'dark', background:'rgb(16, 18, 20)',
    input:'rgb(16, 18, 21)', text:'rgb(240, 241, 243)', warning:'rgb(244, 196, 126)',
    error:'rgb(255, 172, 165)', arrow:'↔', panels:true});
  // Real keyboard input: selection never modifies values, including when a
  // native coefficient number/range/step editor previously had focus.
  await pointerClick('wheel-toggle-D10');
  const selectionBefore = await evaluate('JSON.stringify(controls)');
  const selectionRequests = requests.filter(url => url.endsWith('/api/frame')).length;
  await key('ArrowUp'); assert.equal(await evaluate('selectedTerm'), 'D10');
  for (const name of displayOrder.slice(1, 9)) {
    await key('ArrowDown'); assert.equal(await evaluate('selectedTerm'), name);
  }
  await key('ArrowDown'); assert.equal(await evaluate('selectedTerm'), 'D03', 'page boundary does not jump to hidden high orders');
  await key('ArrowUp'); assert.equal(await evaluate('selectedTerm'), 'D12');
  for (const id of ['value-D01','slide-D01','wheel-step-D01']) {
    await evaluate(`document.getElementById('${id}').focus()`);
    await key('ArrowDown'); assert.equal(await evaluate('selectedTerm'), 'D02');
  }
  assert.equal(await evaluate('JSON.stringify(controls)'), selectionBefore);
  assert.equal(requests.filter(url => url.endsWith('/api/frame')).length, selectionRequests, 'selection is display-only');
  await key('Enter'); assert.equal(await evaluate('wheelTarget'), 'D02');
  await key('Enter', {autoRepeat:true}); assert.equal(await evaluate('wheelTarget'), 'D02', 'held Enter cannot immediately confirm');
  const stepRequests = requests.filter(url => url.endsWith('/api/frame')).length;
  await key('ArrowUp');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D02').value`), '10');
  await key('ArrowDown');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D02').value`), '1');
  for (let i=0;i<5;i++) await key('ArrowDown');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D02').value`), '0.01');
  for (let i=0;i<7;i++) await key('ArrowUp');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D02').value`), '300');
  assert.equal(await evaluate('selectedTerm'), 'D02', 'step keys never switch the active parameter');
  assert.equal(await evaluate('JSON.stringify(controls)'), selectionBefore);
  assert.equal(requests.filter(url => url.endsWith('/api/frame')).length, stepRequests, 'step keys do not simulate');
  await wheelAt('spot', -120); assert.equal(await evaluate('controls.D02'), 300);
  await key('Enter'); assert.equal(await evaluate('wheelTarget'), null);
  await key('Enter', {autoRepeat:true}); assert.equal(await evaluate('wheelTarget'), null, 'held confirmation cannot restart');
  await escape(); assert.equal(await evaluate('controls.D02'), 300, 'Enter commits');
  await key('Enter'); await wheelAt('spot', 120); await escape();
  assert.equal(await evaluate('controls.D02'), 300, 'Escape restores keyboard-start snapshot');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D02').value`), '300', 'Escape does not undo step settings');
  await change('wheel-step-D02', 0.1, 'input');
  await doubleClick('wheel-toggle-D02');
  await doubleClick('wheel-toggle-D02');
  assert.equal(await evaluate('wheelTarget'), null, 'confirming double-click does not accidentally re-enter');
  await evaluate(`document.getElementById('scene-settings').open=true;document.getElementById('noise-seed').focus()`);
  await key('ArrowUp'); assert.equal(await evaluate(`document.getElementById('noise-seed').value`), '18', 'setup editor retains native arrows');
  assert.equal(await evaluate('selectedTerm'), 'D02');
  await key('Enter'); assert.equal(await evaluate('wheelTarget'), null, 'setup Enter does not activate tuning');
  await change('noise-seed', 17); await click('zero');
  // Left/right keys share the wheel's current step and transaction; outside a
  // session they do not become global coefficient shortcuts.
  await change('value-D10', 7.5, 'input'); await change('value-D01', 2.25, 'input');
  await evaluate(`document.getElementById('row-D10').focus()`);
  const keyboardState = `JSON.stringify({controls,image:lastFrame.image_png,spectrum:lastFrame.spectrum,metrics:lastFrame.metrics})`;
  const keyboardStart = await evaluate(keyboardState);
  await key('ArrowLeft'); await key('ArrowRight');
  assert.equal(await evaluate(keyboardState), keyboardStart, 'normal row focus does not activate left/right tuning');
  await key('Enter');
  const keyboardScroll = await evaluate('JSON.stringify([scrollX,scrollY])');
  await key('ArrowRight'); assert.equal(await evaluate('controls.D10'), 8.5, 'default keyboard step is 1');
  assert.equal(await evaluate(`Number(document.getElementById('slide-D10').value) === 8.5 && Number(document.getElementById('value-D10').value) === 8.5 && lastFrame.controls.D10 === 8.5`), true, 'left/right synchronizes controls and final frame');
  await key('ArrowLeft'); assert.equal(await evaluate(keyboardState), keyboardStart, 'one left step reverses one right step exactly');
  await key('ArrowUp'); await key('ArrowRight');
  assert.equal(await evaluate('controls.D10'), 17.5, 'right uses the step just changed by Up');
  await key('ArrowDown'); await key('ArrowLeft');
  assert.equal(await evaluate('controls.D10'), 16.5, 'left uses the step just changed by Down');
  assert.equal(await evaluate('wheelTarget'), 'D10');
  assert.equal(await evaluate('selectedTerm'), 'D10');
  assert.equal(await evaluate('controls.D01'), 2.25, 'keyboard only changes the active coefficient');
  assert.equal(await evaluate('JSON.stringify([scrollX,scrollY])'), keyboardScroll, 'left/right never scroll during tuning');
  await escape(); assert.equal(await evaluate(keyboardState), keyboardStart, 'Escape restores mixed step/key transaction');
  await change('wheel-step-D10', 0.25, 'input'); await key('Enter');
  await key('ArrowRight'); await wheelAt('spot', -120); await key('ArrowLeft');
  assert.equal(await evaluate('controls.D10'), 7.75, 'custom keyboard and wheel steps share one transaction');
  await key('Enter'); await escape(); assert.equal(await evaluate('controls.D10'), 7.75, 'Enter confirms keyboard adjustment');
  const keyboardCommitted = await evaluate(keyboardState);
  await key('Enter');
  for (const invalid of [0, -1, '', 0.015]) {
    await change('wheel-step-D10', invalid, 'input');
    await key('ArrowRight'); await key('ArrowLeft');
    assert.equal(await evaluate('controls.D10'), 7.75, 'invalid step rejects both keyboard directions');
  }
  await change('wheel-step-D10', 0.25, 'input');
  for (const modifiers of [1,2,4,8]) {
    await key('ArrowRight', {modifiers}); await key('ArrowLeft', {modifiers});
    assert.equal(await evaluate('controls.D10'), 7.75, 'modified arrows do not change coefficients');
  }
  await evaluate('window.fetch=window.__delayedFetch');
  await command('Input.dispatchKeyEvent', {type:'keyDown',key:'ArrowRight',code:'ArrowRight'});
  await command('Input.dispatchKeyEvent', {type:'keyUp',key:'ArrowRight',code:'ArrowRight'});
  await waitFor(() => evaluate('running && window.__inFlight > 0'), 'slow keyboard tuning frame in flight');
  const framesBeforeKeyboardUndo = await evaluate('window.__frames.length');
  await escape(); assert.equal(await evaluate(keyboardState), keyboardCommitted);
  assert.equal(await evaluate(`window.__frames.slice(${framesBeforeKeyboardUndo}).every(f => f.value===7.75)`), true, 'late keyboard frame cannot overwrite undo');
  await evaluate('window.fetch=window.__originalFetch');
  await key('Enter'); await key('ArrowRight'); await pointerClick('zero');
  assert.equal(await evaluate('controls.D10'), 8, 'single-click confirms keyboard adjustment without triggering zero');
  assert.equal(await evaluate('wheelTarget'), null);
  for (const [start, arrow, bound] of [[299.99,'ArrowRight',300],[-299.99,'ArrowLeft',-300]]) {
    await change('value-D10', start, 'input'); await evaluate(`document.getElementById('row-D10').focus()`); await key('Enter');
    await key(arrow); await key(arrow, {autoRepeat:true});
    assert.equal(await evaluate('controls.D10'), bound, 'keyboard step clamps at the same wheel limit');
    await escape(); assert.equal(await evaluate('controls.D10'), start);
  }
  await change('value-D10', 0, 'input'); await change('wheel-step-D10', 0.01, 'input');
  await key('Enter'); await key('ArrowRight'); await key('ArrowRight', {autoRepeat:true});
  assert.equal(await evaluate('controls.D10'), 0.02, 'each repeat event advances one minimum step without drift');
  await escape(); await change('wheel-step-D10', 0.1, 'input'); await click('zero');
  // Double-click activation starts a transaction: global wheel capture, left-click
  // commits, Escape restores the activation snapshot (not zero or last frame).
  await command('Emulation.setDeviceMetricsOverride', {width: 1600, height: 900, deviceScaleFactor: 1, mobile: false});
  // Expand ancillary content to make page scrolling possible even when the
  // compact workbench itself now fits entirely in this tall viewport.
  await evaluate(`document.getElementById('scene-settings').open=true;document.getElementById('value-D10').focus()`);
  const pageScroll = await wheelAt('value-D10', 120);
  assert.equal(await evaluate('controls.D10'), 0, 'inactive focused number must not spin natively');
  assert.ok(pageScroll.after > pageScroll.before, 'inactive wheel still scrolls the page');
  await doubleClick('value-D10');
  assert.equal(await evaluate('wheelTarget'), null, 'double-clicking a number is not double-clicking the arrows');
  await change('value-D10', 7.5, 'input');
  await change('value-D01', 2.25, 'input');
  await pointerClick('wheel-toggle-D10');
  assert.equal(await evaluate('wheelTarget'), null, 'single click selects only');
  await doubleClick('wheel-toggle-D10');
  assert.equal(await evaluate('wheelTarget'), 'D10', 'double arrow double-click starts exactly one session');
  assert.equal(await evaluate(`document.getElementById('wheel-session').hidden`), false);
  assert.equal(await evaluate(`document.getElementById('wheel-toggle-D10').getAttribute('aria-pressed')`), 'true');
  for (const target of ['spot', 'value-D01', 'wheel-step-D01']) {
    const heldScroll = await wheelAt(target, -120);
    assert.equal(heldScroll.after, heldScroll.before, `wheel over ${target} does not scroll the page`);
  }
  assert.equal(await evaluate('controls.D10'), 7.8, 'three configured 0.1 wheel steps change only the selected coefficient');
  assert.equal(await evaluate('controls.D01'), 2.25, 'hovering another coefficient must not change it');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D01').value`), '1', 'native step editor cannot spin during global tuning');
  const modifiedWheel = await evaluate(`(() => {
    const ctrl = new WheelEvent('wheel',{deltaY:-120,ctrlKey:true,bubbles:true,cancelable:true});
    const horizontal = new WheelEvent('wheel',{deltaX:120,bubbles:true,cancelable:true});
    document.getElementById('spot').dispatchEvent(ctrl);document.getElementById('spot').dispatchEvent(horizontal);
    return {ctrl:ctrl.defaultPrevented,horizontal:horizontal.defaultPrevented,value:controls.D10};
  })()`);
  assert.deepEqual(modifiedWheel, {ctrl: true, horizontal: true, value: 7.8}, 'active session blocks scrolling/zoom without turning horizontal/modified gestures into steps');
  const committed = await evaluate('JSON.stringify(controls)');
  await pointerClick('zero'); // This stopping click must NOT also zero the coefficients.
  assert.equal(await evaluate('wheelTarget'), null);
  assert.equal(await evaluate('JSON.stringify(controls)'), committed, 'left-click commits without activating the clicked control');
  await escape();
  assert.equal(await evaluate('JSON.stringify(controls)'), committed, 'Escape outside a session cannot undo a previous commit');

  await change('wheel-step-D10', 0.25, 'input');
  const stateExpression = `JSON.stringify({controls,spectrum:lastFrame.spectrum,image:lastFrame.image_png,metrics:lastFrame.metrics})`;
  const beforeUndo = await evaluate(stateExpression);
  await doubleClick('wheel-toggle-D10');
  await wheelAt('spectrum', -120); await wheelAt('spectrum', -120); await wheelAt('spectrum', 120);
  assert.equal(await evaluate('controls.D10'), 8.05, 'custom step and reverse direction');
  await escape();
  assert.equal(await evaluate('wheelTarget'), null);
  assert.equal(await evaluate(stateExpression), beforeUndo, 'Escape restores the latest activation snapshot and its image/spectrum/metrics exactly');
  assert.equal(await evaluate('controls.D10'), 7.8, 'undo is relative to this session, not application startup');

  // Escape with a slow tuning frame in flight must not flash the undone value.
  await doubleClick('wheel-toggle-D10');
  await evaluate('window.fetch=window.__delayedFetch');
  const slowWheel = await centre('spot');
  await command('Input.dispatchMouseEvent', {type: 'mouseWheel', x: slowWheel.x, y: slowWheel.y, deltaX: 0, deltaY: -120});
  await waitFor(() => evaluate('running && window.__inFlight > 0'), 'slow tuning frame in flight');
  const framesBeforeUndo = await evaluate('window.__frames.length');
  await escape();
  assert.equal(await evaluate(stateExpression), beforeUndo);
  assert.equal(await evaluate(`window.__frames.slice(${framesBeforeUndo}).every(f => f.value === 7.8)`), true, 'late tuning responses cannot overwrite rollback');
  await evaluate('window.fetch=window.__originalFetch');

  for (const invalid of [0, -1, '', 0.015]) {
    await change('wheel-step-D10', invalid, 'input');
    await doubleClick('wheel-toggle-D10');
    assert.equal(await evaluate('wheelTarget'), null, `invalid step ${invalid} must not start a session`);
    assert.equal(await evaluate('controls.D10'), 7.8);
    assert.match(await evaluate(`document.getElementById('wheel-note-D10').textContent`), /不执行/);
  }
  await change('wheel-step-D10', 0.25, 'input');
  await doubleClick('wheel-toggle-D10');
  await change('wheel-step-D10', 0, 'input'); // Simulate invalid keyboard editing during tuning.
  const invalidScroll = await wheelAt('spot', -120);
  assert.equal(invalidScroll.before, invalidScroll.after);
  assert.equal(await evaluate('controls.D10'), 7.8);
  await escape();
  await change('wheel-step-D10', 0.25, 'input');
  for (const [start, deltaY, limit] of [[299.99, -120, 300], [-299.99, 120, -300]]) {
    await change('value-D10', start, 'input'); await doubleClick('wheel-toggle-D10');
    await wheelAt('spot', deltaY);
    assert.equal(await evaluate('controls.D10'), limit, 'coefficient bound');
    await escape(); assert.equal(await evaluate('controls.D10'), start, 'undo at bound');
  }
  await change('value-D10', 0, 'input');
  await doubleClick('wheel-toggle-D01');
  assert.equal(await evaluate(`document.querySelectorAll('.wheel-active').length`), 1);
  await wheelAt('value-D10', -120);
  assert.equal(await evaluate('controls.D01'), 3.25, 'default wheel step is 1');
  assert.equal(await evaluate('controls.D10'), 0);
  await pointerClick('wheel-toggle-D10');
  assert.equal(await evaluate('wheelTarget'), null, 'first left-click stops instead of switching targets');
  await pointerClick('wheel-toggle-D10');
  assert.equal(await evaluate('wheelTarget'), null, 'next single click selects but does not activate');
  await key('Enter');
  assert.equal(await evaluate('wheelTarget'), 'D10');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D10').value`), '0.25', 'per-row step retained');
  await wheelAt('spot', -120);
  await pointerClick('wheel-toggle-D10');
  assert.equal(await evaluate('wheelTarget'), null, 'clicking the active button stops without reactivating');
  assert.equal(await evaluate('controls.D10'), 0.25);
  await doubleClick('wheel-toggle-D10'); await wheelAt('spot', -120);
  await evaluate(`window.dispatchEvent(new Event('blur'))`);
  assert.equal(await evaluate('wheelTarget'), null, 'window blur safely ends capture');
  assert.equal(await evaluate('controls.D10'), 0.5, 'blur preserves current adjustment');
  await pointerClick('zero');
  await evaluate(`document.getElementById('scene-settings').open=false;window.scrollTo(0,0)`);
  // A scene/mode boundary still discards an obsolete in-flight frame.
  await evaluate(`window.fetch=window.__delayedFetch;const el=document.getElementById('slide-D10');el.value=30;el.dispatchEvent(new Event('input',{bubbles:true}));`);
  await waitFor(() => evaluate('running'), 'request in flight before switching mode');
  await change('mode', 'practice');
  assert.equal(await evaluate('window.__frames.every(f => f.mode === f.uiMode)'), true, 'do not render old free-mode frames in practice');
  await evaluate('window.fetch=window.__originalFetch');
  assert.equal(await evaluate(`document.getElementById('feedback').hidden`), true);
  assert.equal(await evaluate(`'feedback' in lastFrame`), false);
  // Practice stopwatch is local UI state, independent of simulation frames.
  const timerText = `document.getElementById('practice-time').textContent`;
  async function assertTimerReset() {
    assert.equal(await evaluate(timerText), '00:00:00.0');
    assert.equal(await evaluate('practiceStartedAt === null && practiceInterval === null'), true);
    assert.equal(await evaluate(`document.getElementById('timer-stop').disabled`), true);
  }
  await assertTimerReset();
  const timerFrame = await evaluate('JSON.stringify(lastFrame)');
  const timerRequests = requests.filter(url => url.endsWith('/api/frame')).length;
  await pointerClick('timer-start');
  assert.equal(await evaluate(`document.getElementById('timer-start').disabled && !document.getElementById('timer-stop').disabled`), true);
  const firstStart = await evaluate('practiceStartedAt');
  await click('timer-start');
  assert.equal(await evaluate('practiceStartedAt'), firstStart, 'repeated start is ignored');
  await waitFor(async () => (await evaluate(timerText)) !== '00:00:00.0', 'real stopwatch ticks');
  await pointerClick('timer-stop');
  const stoppedTime = await evaluate(timerText);
  await new Promise(resolve => setTimeout(resolve, 250));
  assert.equal(await evaluate(timerText), stoppedTime, 'stop freezes elapsed display');
  assert.equal(await evaluate('practiceInterval'), null, 'stop releases interval');
  assert.equal(await evaluate('JSON.stringify(lastFrame)'), timerFrame, 'start/stop do not alter question, controls or plots');
  assert.equal(requests.filter(url => url.endsWith('/api/frame')).length, timerRequests, 'timer sends no simulation requests');
  // Deterministic elapsed clock jump stands in for a delayed background paint.
  await evaluate(`window.__timerNow=1000;Object.defineProperty(performance,'now',{configurable:true,value:()=>window.__timerNow})`);
  await pointerClick('timer-start');
  assert.equal(await evaluate(timerText), '00:00:00.0', 'restart begins at zero, not a resume');
  await evaluate('window.__timerNow += 3661123; renderPracticeTimer()');
  assert.equal(await evaluate(timerText), '01:01:01.1', 'hours/minutes roll over using elapsed time, not callback count');
  const preservedStart = await evaluate('practiceStartedAt');
  await click('reveal'); await click('reveal'); await click('zero');
  await change('difficulty', 'easy'); await change('difficulty', 'medium');
  assert.equal(await evaluate('practiceStartedAt'), preservedStart, 'answers, zero and draft settings do not reset timer');
  await doubleClick('wheel-toggle-D11');
  await pointerClick('timer-stop');
  assert.equal(await evaluate('wheelTarget'), null);
  assert.equal(await evaluate('practiceStartedAt'), preservedStart, 'first tuning click confirms only, without stopping timer');
  await pointerClick('timer-stop');
  assert.equal(await evaluate(timerText), '01:01:01.1');
  for (const action of ['retry','new-question','random-question']) {
    await pointerClick('timer-start');
    await evaluate('window.__timerNow += 1500; renderPracticeTimer()');
    await pointerClick(action); await assertTimerReset();
  }
  await change('seed', 42); await click('new-question');
  await pointerClick('timer-start'); await change('mode', 'free'); await assertTimerReset();
  assert.equal(await evaluate(`document.getElementById('practice').hidden && document.getElementById('timer-start').disabled`), true);
  await change('mode', 'practice'); await assertTimerReset();
  await evaluate('delete performance.now');
  await click('reveal');
  assert.equal(await evaluate(`document.getElementById('feedback').hidden`), false);
  assert.equal(await evaluate(`document.querySelectorAll('#answer-rows tr').length`), 9);
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('#answer-rows tr'), r => r.cells[0].textContent)`), displayOrder.slice(0,9));
  const practiceState = `JSON.stringify({controls,image:lastFrame.image_png,spectrum:lastFrame.spectrum,metrics:lastFrame.metrics,question:lastFrame.question,feedback:lastFrame.feedback})`;
  const practiceBefore = await evaluate(practiceState);
  await doubleClick('wheel-toggle-D11'); await wheelAt('spot', -120); await key('ArrowRight'); await escape();
  assert.equal(await evaluate(practiceState), practiceBefore, 'practice rollback preserves question, reveal state and coefficient residuals');
  await evaluate(`document.querySelectorAll('#answer-rows tr').forEach(row => {const el=document.getElementById('value-'+row.cells[0].textContent);el.value=Number(row.cells[3].textContent);el.dispatchEvent(new Event('input', {bubbles:true}));})`);
  await idle();
  assert.equal(await evaluate(`lastFrame.feedback.normalized_rms`), 0);
  assert.equal(Number(await evaluate(`document.getElementById('fwhm').textContent`)), baseline);
  await click('retry');
  assert.equal(await evaluate(`document.getElementById('feedback').hidden`), true);
  assert.equal(await evaluate(`Object.values(controls).every(v => v === 0)`), true);
  await change('difficulty', 'hard'); // Does not change the active question until new.
  await click('new-question'); await click('reveal');
  // Revealed answers and expanded setup must not push the tuning controls down.
  await evaluate(`document.getElementById('scene-settings').open=true;document.getElementById('display-info').open=true`);
  await mkdir(join(root, artifactDirectory), {recursive: true});
  const layoutSizes = [[3072,1728],[2560,1440],[1920,1080],[1600,900],[1366,768],[1280,660],[1280,600]];
  const readableLayouts = [];
  async function assertReadableLayout(width, height, dpr) {
    const sizes = await evaluate(`(() => {
      const root = parseFloat(getComputedStyle(document.documentElement).fontSize);
      const input = document.getElementById('value-D10'), row = document.getElementById('row-D10');
      return {root, input:parseFloat(getComputedStyle(input).fontSize), inputHeight:input.getBoundingClientRect().height,
        label:parseFloat(getComputedStyle(row.querySelector('label')).fontSize), rowHeight:row.getBoundingClientRect().height,
        canvasFont:parseFloat(document.getElementById('spectrum').getContext('2d').font),
        zoom:getComputedStyle(document.documentElement).zoom, dpr:devicePixelRatio};
    })()`);
    assert.ok(sizes.root >= 12 && sizes.root <= 20, 'bounded fluid type, never shrink compact controls');
    if (width >= 1920 && height >= 1000) {
      assert.ok(sizes.root >= 18 && sizes.input >= 18 && sizes.label >= 16,
        `large-screen controls must be readable, not fixed 9–12px: ${JSON.stringify(sizes)}`);
      assert.ok(sizes.inputHeight >= 28 && sizes.rowHeight >= 45, 'control hit areas grow with type');
      assert.ok(sizes.canvasFont >= 18, 'plot tick labels must grow too');
    }
    if (width === 1280 && height === 600) assert.equal(sizes.root, 12, 'keep short-laptop compact baseline');
    assert.ok(['1','normal'].includes(sizes.zoom), 'no CSS zoom workaround');
    assert.equal(sizes.dpr, dpr);
    readableLayouts.push({width,height,...sizes});
  }
  const beforeResize = await evaluate(stateExpression);
  const frameRequestCount = () => requests.filter(url => url.endsWith('/api/frame')).length;
  const requestsBeforeResize = frameRequestCount();
  for (const [width, height] of layoutSizes) {
    await command('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
    await evaluate('window.scrollTo(0,0);new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    await assertWorkbenchVisible('desktop practice with answers and scene expanded');
    await assertReadableLayout(width, height, 1);
    assert.equal(await evaluate(`[document.getElementById('spot'),document.getElementById('spectrum')].every(c => c.width === Math.round(c.clientWidth*devicePixelRatio) && c.height === Math.round(c.clientHeight*devicePixelRatio) && c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((v,i) => i%4!==3 && v>0))`), true, 'resize redraws both canvases at the displayed resolution');
    const shot = await command('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
    await writeFile(join(root, artifactDirectory, `layout-${width}x${height}.png`), Buffer.from(shot.data, 'base64'));
  }
  // Representative large Windows viewport at 150% pixel density, not an
  // inferred exact replay of the owner's screenshot/browser zoom settings.
  await command('Emulation.setDeviceMetricsOverride', {width: 1984, height: 1066, deviceScaleFactor: 1.5, mobile: false});
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  await assertWorkbenchVisible('large Windows-like high-DPI desktop');
  await assertReadableLayout(1984, 1066, 1.5);
  assert.equal(await evaluate(`[document.getElementById('spot'),document.getElementById('spectrum')].every(c => c.width === Math.round(c.clientWidth*1.5) && c.height === Math.round(c.clientHeight*1.5))`), true, 'fractional-DPI buffers follow CSS dimensions');
  const largeShot = await command('Page.captureScreenshot', {format:'png',captureBeyondViewport:false});
  await writeFile(join(root, artifactDirectory, 'layout-1984x1066-dpr1.5.png'), Buffer.from(largeShot.data,'base64'));
  await command('Emulation.setDeviceMetricsOverride', {width: 1366, height: 768, deviceScaleFactor: 2, mobile: false});
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  await assertWorkbenchVisible('high-DPI desktop');
  assert.equal(await evaluate(`[document.getElementById('spot'),document.getElementById('spectrum')].every(c => c.width === Math.round(c.clientWidth*2) && c.height === Math.round(c.clientHeight*2))`), true, 'high-DPI backing buffers follow the CSS layout');
  await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 600, deviceScaleFactor: 1, mobile: false});
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  assert.equal(await evaluate(stateExpression), beforeResize, 'resizing does not alter simulation, controls or metrics');
  assert.equal(frameRequestCount(), requestsBeforeResize, 'resizing does not request a new simulation');
  // Actually tune the last coefficient without scrolling at laptop size.
  await doubleClick('wheel-toggle-D03');
  const lastRowScroll = await wheelAt('spot', -120);
  assert.equal(await evaluate('controls.D03'), 1);
  assert.equal(lastRowScroll.before, 0);
  assert.equal(lastRowScroll.after, 0);
  await assertWorkbenchVisible('last coefficient active, no scrolling');
  const screenshot = await command('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
  await writeFile(join(root, artifactDirectory, 'browser-desktop.png'), Buffer.from(screenshot.data, 'base64'));
  await escape();
  // Smaller windows may need control scrolling; both plots remain pinned while
  // the entire D03 row is brought into view, rather than disappearing above it.
  for (const [width,height] of [[1024,768],[720,720],[390,844]]) {
    await command('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
    await evaluate(`document.getElementById('row-D03').scrollIntoView({block:'end'});new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
    await assertWorkbenchVisible('narrow all nine rows and sticky plots');
    await doubleClick('wheel-toggle-D03');
    const held = await wheelAt('spot', -120);
    assert.equal(held.after, held.before);
    assert.equal(await evaluate('controls.D03'), 1);
    await assertWorkbenchVisible('narrow active all nine rows and sticky plots');
    await key('ArrowUp');
    assert.equal(await evaluate('selectedTerm'), 'D03');
    assert.equal(await evaluate(`document.getElementById('wheel-step-D03').value`), '10');
    await key('ArrowDown'); await key('ArrowLeft');
    assert.equal(await evaluate('controls.D03'), 0);
    await key('ArrowRight'); assert.equal(await evaluate('controls.D03'), 1);
    await assertWorkbenchVisible('narrow keyboard single-step tuning remains same-screen');
    const shot = await command('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
    await writeFile(join(root, artifactDirectory, width === 390 ? 'browser-narrow.png' : `layout-${width}x${height}.png`), Buffer.from(shot.data, 'base64'));
    await escape();
  }
  // Fourth/fifth-order pages retain all coefficients and steps. Changing the
  // displayed page must not request a simulation or deactivate off-page terms.
  await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 600, deviceScaleFactor: 1, mobile: false});
  await change('mode', 'free'); await evaluate('window.scrollTo(0,0)');
  await change('value-D01', 2.5, 'input');
  await pointerClick('page-4');
  assert.equal(await evaluate('currentPage'), 4);
  assert.equal(await evaluate('selectedTerm'), 'D40');
  await key('ArrowDown'); assert.equal(await evaluate('selectedTerm'), 'D31', 'paging leaves keyboard navigation ready');
  await key('Enter'); assert.equal(await evaluate('wheelTarget'), 'D31');
  await wheelAt('spot', -120); await escape();
  assert.equal(await evaluate('controls.D31'), 0);
  const fourth = ['D40','D31','D22','D13','D04'], fifth = ['D50','D41','D32','D23','D14','D05'];
  assert.deepEqual(await evaluate(`names.filter(n => !document.getElementById('row-'+n).hidden)`), fourth);
  await change('value-D40', 5, 'input'); await change('value-D22', -3, 'input'); await change('value-D04', 4, 'input');
  await assertWorkbenchVisible('fourth-order free page', fourth);
  const beforePage = await evaluate(stateExpression), requestsBeforePage = frameRequestCount();
  await pointerClick('page-5');
  assert.equal(await evaluate('selectedTerm'), 'D50');
  await key('ArrowDown'); assert.equal(await evaluate('selectedTerm'), 'D41');
  assert.equal(await evaluate(stateExpression), beforePage, 'paging alone preserves all simulation data');
  assert.equal(frameRequestCount(), requestsBeforePage, 'paging makes no frame request');
  assert.deepEqual(await evaluate(`names.filter(n => !document.getElementById('row-'+n).hidden)`), fifth);
  await change('value-D05', 7, 'input');
  assert.equal(await evaluate('lastFrame.controls.D01'), 2.5);
  assert.equal(await evaluate('lastFrame.controls.D22'), -3, 'off-page fourth-order term stays active');
  assert.notEqual(await evaluate('lastFrame.image_png'), JSON.parse(beforePage).image, 'fifth-order term changes the image');
  await assertWorkbenchVisible('fifth-order free page', fifth);
  // Page switch while a fifth-order frame is still in flight must preserve it.
  await evaluate(`window.fetch=window.__delayedFetch;document.getElementById('value-D05').value=8;document.getElementById('value-D05').dispatchEvent(new Event('input',{bubbles:true}))`);
  await waitFor(() => evaluate('running'), 'high-order request in flight');
  await pointerClick('page-4');
  assert.equal(await evaluate('currentPage'), 4);
  assert.equal(await evaluate('controls.D05'), 8);
  assert.equal(await evaluate('lastFrame.controls.D05'), 8);
  await evaluate('window.fetch=window.__originalFetch');
  await pointerClick('page-5'); await change('wheel-step-D05', 0.25, 'input');
  await doubleClick('wheel-toggle-D05'); await wheelAt('spot', -120);
  await pointerClick('page-4');
  assert.equal(await evaluate('currentPage'), 5, 'stopping click cannot also change the page');
  assert.equal(await evaluate('controls.D05'), 8.25);
  await pointerClick('page-4'); await pointerClick('page-5');
  assert.equal(await evaluate(`document.getElementById('wheel-step-D05').value`), '0.25');
  const highBeforeUndo = await evaluate(stateExpression);
  await doubleClick('wheel-toggle-D05'); await wheelAt('spectrum', -120); await key('ArrowRight'); await key('ArrowLeft'); await escape();
  assert.equal(await evaluate(stateExpression), highBeforeUndo, 'high-order undo preserves previously adjusted terms on every page');
  await pointerClick('zero');
  assert.equal(await evaluate('Object.values(controls).every(v => v === 0)'), true, 'zero clears every page');
  assert.equal(Number(await evaluate(`document.getElementById('fwhm').textContent`)), baseline);
  // New maximum-order settings are drafts until a new question is requested.
  await change('max-order', 5); await change('term-count', 20); await change('mode', 'practice');
  assert.equal(await evaluate('lastFrame.question.max_order'), 5);
  assert.equal(await evaluate('lastFrame.question.term_count'), 20);
  assert.equal(await evaluate(`'feedback' in lastFrame`), false);
  assert.equal(await evaluate(`document.querySelectorAll('.coefficient-pages .has-values').length`), 0, 'page badges must not reveal hidden initial terms');
  await pointerClick('page-5');
  const beforeDraft = await evaluate(practiceState);
  await change('max-order', 1);
  assert.equal(await evaluate(practiceState), beforeDraft);
  assert.equal(await evaluate(`document.getElementById('page-5').disabled`), false, 'draft lower order does not change the current question');
  await click('retry');
  assert.equal(await evaluate('lastFrame.question.max_order'), 5);
  assert.equal(await evaluate('lastFrame.question.term_count'), 20);
  await click('new-question');
  assert.equal(await evaluate('lastFrame.question.max_order'), 1);
  assert.equal(await evaluate('currentPage'), 3);
  assert.equal(await evaluate(`document.getElementById('page-4').disabled && document.getElementById('page-5').disabled`), true);
  assert.equal(await evaluate(`document.querySelectorAll('.coefficient:not([hidden])').length`), 2);
  await pointerClick('wheel-toggle-D01'); await key('ArrowDown');
  assert.equal(await evaluate('selectedTerm'), 'D01', 'selection skips every unavailable term in one-order exercise');
  await key('Enter'); assert.equal(await evaluate('wheelTarget'), 'D01'); await escape();
  // Each maximum admits only its own candidate terms; reveal and compensation
  // span every eligible page, while retry preserves the question and its order.
  for (const [order,count] of [[1,2],[2,5],[3,9],[4,14],[5,20]]) {
    await change('max-order', order); await change('term-count', count); await click('new-question');
    assert.equal(await evaluate('lastFrame.question.max_order'), order);
    assert.equal(await evaluate(`names.filter(n => orders[n]>${order}).every(n => document.getElementById('value-'+n).disabled && controls[n]===0)`), true, 'out-of-scope controls are disabled and zero');
    assert.equal(await evaluate(`'feedback' in lastFrame`), false);
    await click('reveal');
    assert.equal(await evaluate(`document.querySelectorAll('#answer-rows tr').length`), count);
    assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('#answer-rows tr'), r => r.cells[0].textContent)`), displayOrder.slice(0,count));
    assert.equal(await evaluate(`Object.values(lastFrame.feedback.initial).filter(v => v!==0).length`), count);
    assert.equal(await evaluate(`names.filter(n => orders[n]>${order}).every(n => lastFrame.feedback.initial[n]===0)`), true);
    const questionImage = await evaluate('lastFrame.image_png');
    if (order >= 4) {
      await pointerClick(`page-${order}`); await evaluate('window.scrollTo(0,0)');
      const term = order === 4 ? 'D04' : 'D05', terms = order === 4 ? fourth : fifth;
      await doubleClick(`wheel-toggle-${term}`);
      const scroll = await wheelAt('spot', -120);
      assert.equal(scroll.before, 0); assert.equal(scroll.after, 0);
      await assertWorkbenchVisible(`order ${order} practice tuning, laptop viewport`, terms);
      const shot = await command('Page.captureScreenshot', {format:'png',captureBeyondViewport:false});
      await writeFile(join(root, artifactDirectory, `browser-order-${order}.png`), Buffer.from(shot.data,'base64'));
      await escape();
      assert.equal(await evaluate('lastFrame.image_png'), questionImage);
    }
    await evaluate(`document.querySelectorAll('#answer-rows tr').forEach(row => {const el=document.getElementById('value-'+row.cells[0].textContent);el.value=Number(row.cells[3].textContent);el.dispatchEvent(new Event('input',{bubbles:true}));})`);
    await idle();
    assert.equal(await evaluate('lastFrame.feedback.normalized_rms'), 0);
    assert.equal(Number(await evaluate(`document.getElementById('fwhm').textContent`)), baseline);
    await click('retry');
    assert.equal(await evaluate('lastFrame.question.max_order'), order);
    assert.equal(await evaluate('lastFrame.image_png'), questionImage);
    assert.equal(await evaluate('Object.values(controls).every(v=>v===0)'), true);
  }
  for (const [width,height] of [[1024,768],[390,844]]) {
    await command('Emulation.setDeviceMetricsOverride', {width,height,deviceScaleFactor:1,mobile:false});
    for (const [page,terms] of [[4,fourth],[5,fifth]]) {
      await pointerClick(`page-${page}`);
      await assertWorkbenchVisible(`narrow high-order page ${page}`, terms);
      const term = terms.at(-1);
      await doubleClick(`wheel-toggle-${term}`);
      const scroll = await wheelAt('spot', -120);
      assert.equal(scroll.before, scroll.after);
      await assertWorkbenchVisible(`narrow active high-order page ${page}`, terms);
      const shot = await command('Page.captureScreenshot', {format:'png',captureBeyondViewport:false});
      await writeFile(join(root, artifactDirectory, `order-${page}-${width}x${height}.png`), Buffer.from(shot.data,'base64'));
      await escape();
    }
  }
  // Every one of twenty active terms gets the selected amplitude range.
  await command('Emulation.setDeviceMetricsOverride', {width:1366,height:768,deviceScaleFactor:1,mobile:false});
  await evaluate('window.scrollTo(0,0)');
  for (const [level,low,high] of [['easy',7,20],['medium',15.75,45],['hell',105,300],['hard',31.5,90]]) {
    await change('difficulty', level); await click('new-question'); await click('reveal');
    assert.equal(await evaluate('lastFrame.question.generator_version'), 'eels-exercise-per-term-2');
    assert.equal(await evaluate(`Object.values(lastFrame.feedback.initial).every(v => Math.abs(v)>=${low} && Math.abs(v)<=${high})`), true, 'no shared budget dilutes twenty-term strength');
    if (level === 'medium') {
      assert.ok(await evaluate('lastFrame.metrics.rms_mev > 20'), 'seed 42 twenty-term medium is no longer near baseline');
      const shot = await command('Page.captureScreenshot', {format:'png',captureBeyondViewport:false});
      await writeFile(join(root, artifactDirectory, 'difficulty-medium-20.png'), Buffer.from(shot.data,'base64'));
    }
  }
  const strongQuestion = await evaluate('JSON.stringify({question:lastFrame.question,feedback:lastFrame.feedback})');
  await change('field', 40);
  assert.ok(await evaluate('lastFrame.clipped_fraction > 0.001'));
  assert.equal(await evaluate('lastFrame.metrics.fwhm_mev'), null);
  assert.match(await evaluate(`document.getElementById('warnings').textContent`), /扩大能量视野/);
  await change('field', 240);
  assert.equal(await evaluate('JSON.stringify({question:lastFrame.question,feedback:lastFrame.feedback})'), strongQuestion, 'widening the field does not change question, answer or score');
  assert.ok(await evaluate('lastFrame.clipped_fraction < 0.001'));
  assert.doesNotMatch(await evaluate(`document.getElementById('warnings').textContent`), /扩大能量视野/);
  // Custom amplitude is a draft until new; invalid drafts cannot block an
  // active question, reset tuning/timer on failed new, or leak into retry.
  assert.deepEqual(await evaluate(`Array.from(document.getElementById('difficulty').options, o => o.textContent)`), ['初级','中级','高级','地狱难度','自定义难度']);
  assert.equal(await evaluate(`document.getElementById('custom-difficulty').hidden`), true);
  const beforeCustomDraft = await evaluate(practiceState);
  const beforeCustomRequests = frameRequestCount();
  await change('difficulty', 'custom'); await change('custom-amplitude', 123.45, 'input');
  assert.equal(await evaluate(`document.getElementById('custom-difficulty').hidden`), false);
  assert.equal(await evaluate(practiceState), beforeCustomDraft);
  assert.equal(frameRequestCount(), beforeCustomRequests);
  for (const amplitude of [123.45, 300, 0.1]) {
    await change('custom-amplitude', amplitude, 'input'); await click('new-question');
    assert.equal(await evaluate('lastFrame.question.amplitude'), amplitude);
    assert.equal(await evaluate('lastFrame.question.difficulty'), 'custom');
    assert.equal(await evaluate('Boolean(lastFrame.feedback)'), false);
    assert.match(await evaluate(`document.getElementById('question-info').textContent`), /自定义难度/);
    await click('reveal');
    assert.equal(await evaluate(`Object.values(lastFrame.feedback.initial).every(v => Math.abs(v)>=${Math.round(0.35*amplitude*100)/100} && Math.abs(v)<=${amplitude})`), true);
    const customQuestion = await evaluate('JSON.stringify(lastFrame.question)');
    const customInitial = await evaluate('JSON.stringify(lastFrame.feedback.initial)');
    await evaluate(`document.querySelectorAll('#answer-rows tr').forEach(row => {const el=document.getElementById('value-'+row.cells[0].textContent);el.value=Number(row.cells[3].textContent);el.dispatchEvent(new Event('input', {bubbles:true}));})`);
    await idle(); assert.equal(await evaluate('lastFrame.feedback.normalized_rms'), 0);
    assert.ok(Math.abs(await evaluate('lastFrame.metrics.fwhm_mev')-8)<0.2);
    await click('timer-start');
    const startedAt = await evaluate('practiceStartedAt');
    const solvedCustom = await evaluate(practiceState);
    for (const invalid of ['', 0, -1, 300.01, 0.015]) {
      await change('custom-amplitude', invalid, 'input');
      const beforeInvalid = frameRequestCount();
      await evaluate(`document.getElementById('new-question').click()`);
      assert.match(await evaluate(`document.getElementById('error').textContent`), /请检查设置/);
      assert.equal(frameRequestCount(), beforeInvalid);
      assert.equal(await evaluate(practiceState), solvedCustom);
      assert.equal(await evaluate('practiceStartedAt'), startedAt);
      // Existing question operations still work despite the invalid draft.
      await click('reveal'); await click('reveal');
    }
    await click('retry'); await assertTimerReset(); await click('reveal');
    assert.equal(await evaluate('JSON.stringify(lastFrame.question)'), customQuestion);
    assert.equal(await evaluate('JSON.stringify(lastFrame.feedback.initial)'), customInitial);
    await change('custom-amplitude', amplitude, 'input');
  }
  // Custom editor and the original nine controls remain usable on short and
  // narrow screens. Capture the actual new option/editor, not just DOM labels.
  await pointerClick('page-3');
  for (const [width,height] of [[1280,600],[390,844]]) {
    await command('Emulation.setDeviceMetricsOverride', {width,height,deviceScaleFactor:1,mobile:false});
    await evaluate(`document.querySelector('.workbench').scrollIntoView({block:'start'})`);
    await assertWorkbenchVisible('custom difficulty layout');
    await evaluate('window.scrollTo(0,0)');
    assert.equal(await evaluate(`(() => {const r=document.getElementById('custom-amplitude').getBoundingClientRect();return r.width>0 && r.top>=0 && r.bottom<=innerHeight && document.documentElement.scrollWidth<=innerWidth;})()`), true);
  }
  await command('Emulation.setDeviceMetricsOverride', {width:1366,height:768,deviceScaleFactor:1,mobile:false});
  await evaluate('window.scrollTo(0,0)');
  const customShot = await command('Page.captureScreenshot', {format:'png',captureBeyondViewport:false});
  await writeFile(join(root, artifactDirectory, 'difficulty-custom.png'), Buffer.from(customShot.data,'base64'));
  await change('difficulty', 'hell'); await click('new-question'); await click('reveal');
  assert.match(await evaluate(`document.getElementById('question-info').textContent`), /地狱难度/);
  assert.equal(await evaluate(`document.getElementById('custom-difficulty').hidden`), true);
  await evaluate(`document.querySelectorAll('#answer-rows tr').forEach(row => {const el=document.getElementById('value-'+row.cells[0].textContent);el.value=Number(row.cells[3].textContent);el.dispatchEvent(new Event('input', {bubbles:true}));})`);
  await idle(); assert.equal(await evaluate('lastFrame.feedback.normalized_rms'), 0);
  // Refresh clears page-local stopwatch and restores every coefficient step.
  await pointerClick('timer-start');
  await command('Page.navigate', {url:`http://127.0.0.1:${port}/`}); await idle();
  await assertTimerReset();
  assert.deepEqual(await evaluate(`names.map(n => document.getElementById('wheel-step-'+n).value)`), Array(20).fill('1'));
  // A refreshed frontend must reject both nine-term and twenty-term backends
  // still using the old shared-budget generator, with an actionable message.
  for (const legacyKind of ['nine-term', 'shared-budget', 'per-term-1', 'old-limit']) {
    const beforeOldBackend = frameRequestCount();
    const oldMeta = await command('Page.addScriptToEvaluateOnNewDocument', {source: `
      const nativeFetch = window.fetch;
      window.fetch = async (...args) => {
        const response = await nativeFetch(...args);
        if (args[0] !== '/api/meta') return response;
        const meta = await response.json();
        if (${JSON.stringify(legacyKind)} === 'old-limit') meta.control_limit=120;
        else if (${JSON.stringify(legacyKind)} === 'per-term-1') meta.generator_version='eels-exercise-per-term-1';
        else delete meta.generator_version;
        if (${JSON.stringify(legacyKind)} === 'nine-term') {
          meta.terms = meta.terms.slice(0,9);
          delete meta.max_order; delete meta.powers; delete meta.default_practice_order;
        }
        return new Response(JSON.stringify(meta), {headers:{'Content-Type':'application/json'}});
      };`});
    await command('Page.navigate', {url:`http://127.0.0.1:${port}/`});
    await waitFor(() => evaluate(`document.getElementById('error')?.textContent.includes('后端版本过旧')`), 'old backend compatibility message');
    assert.match(await evaluate(`document.getElementById('error').textContent`), /python3 run.py/);
    assert.equal(frameRequestCount(), beforeOldBackend, 'incompatible backend receives no frame requests');
    await command('Page.removeScriptToEvaluateOnNewDocument', {identifier:oldMeta.identifier});
  }
  assert.deepEqual(exceptions, []);
  const external = requests.filter(url => !url.startsWith(`http://127.0.0.1:${port}/`) && !url.startsWith('data:'));
  assert.deepEqual(external, [], 'UI does not fetch external resources');
  console.log(JSON.stringify({status: 'PASS', baseline_fwhm_mev: baseline, browser: (await command('Browser.getVersion', {}, null)).product,
    drag_frames_before_release: duringDrag.length, desktop_layout_sizes: layoutSizes, readable_layouts: readableLayouts, narrow_layout_sizes: [[1024,768],[720,720],[390,844]],
    checks: ['network starts and follows latest input without animation-frame gating in both modes', 'synchronous input coalescing with one in-flight request', 'full-path timing tooltip', 'all twenty control/step limits are 300', 'hell and custom difficulty bounds and exact compensation', 'custom drafts and invalid new preserve question, controls and timer', 'custom short/narrow layouts', 'old 120-limit backend rejected', 'all twenty initial steps are 1 meV', 'practice timer start/stop/restart and duplicate start', 'elapsed clock jump and hour/minute formatting', 'timer reset on new/retry/mode/refresh', 'timer does not simulate or alter question', 'timer respects tuning confirmation click', 'per-term difficulty bounds for all twenty terms', 'clipping guidance and widening the field preserves answers', 'old shared-budget generator gives restart instruction', '20 controls with nine on the default page', 'fourth and fifth order pages retain cross-page superposition', 'paging without simulation requests', 'in-flight high-order frame survives page switch', 'page button stopping click does not click through', 'high-order wheel steps and snapshot undo', 'all-page zero', 'practice maximum orders 1 through 5', 'order drafts and retry preserve current question', '14 and 20 term exact compensation', 'high-order page visibility while tuning on desktop and narrow screens', 'old backend metadata gives restart instruction without frame request', 'slider and numeric updates', 'continuous pointer drag renders before release', 'single in-flight request', 'no control rollback', 'mode boundary ignores old frames', 'screenshot ordering with restored original dark palette', 'keyboard selection without coefficient edits', 'Enter or double-arrow double-click activation', 'arrow step scaling and limits without simulation', 'left/right single-step tuning with current step and shared wheel transaction', 'keyboard bounds, invalid steps, modifiers and repeats', 'keyboard confirms, snapshot undo and late-frame protection', 'Enter commits and Escape restores keyboard-start snapshot', 'repeat Enter and confirming double-click do not re-enter', 'scene editors retain native keys', 'answer table follows display order', 'global wheel capture without page scroll', 'only selected coefficient changes', 'per-row wheel step', 'wheel direction and bounds', 'invalid wheel step rejected', 'inactive wheel preserves page scroll', 'left-click commits without click-through', 'Escape restores current session snapshot', 'late frame cannot overwrite rollback', 'practice rollback preserves question and feedback', 'blur ends capture preserving values', 'superposition', 'gamma preserves spectrum', 'zero baseline', 'hidden exercise', 'reveal', 'exact compensation', 'retry', 'new question', 'nine controls and both plots in desktop viewport', 'expanded settings and feedback do not displace controls', 'responsive canvas redraw without simulation', 'high-DPI canvas backing buffers', 'D03 tuning without scrolling on laptop', 'all nine controls with sticky plots in tested narrow viewports', 'keyboard navigation after page change and lower-order selection boundaries', 'narrow layout', 'no JS exceptions', 'no external UI requests'],
    screenshots: [`${artifactDirectory}/difficulty-custom.png`, `${artifactDirectory}/difficulty-medium-20.png`, `${artifactDirectory}/browser-desktop.png`, `${artifactDirectory}/browser-narrow.png`, `${artifactDirectory}/browser-order-4.png`, `${artifactDirectory}/browser-order-5.png`, `${artifactDirectory}/order-4-390x844.png`, `${artifactDirectory}/order-5-390x844.png`], temporary_profile: profile}, null, 2));
} finally {
  if (socket) socket.close();
  for (const child of [browser, service]) {
    if (child && child.exitCode === null) { child.kill('SIGTERM'); await Promise.race([once(child, 'exit'), new Promise(r => setTimeout(r, 3000))]); }
  }
}
