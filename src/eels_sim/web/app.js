"use strict";
const $ = id => document.getElementById(id);
const names = ["D10", "D01", "D20", "D11", "D02", "D30", "D21", "D12", "D03"];
const monomials = ["u", "v", "u²", "uv", "v²", "u³", "u²v", "uv²", "v³"];
let meta, session, controls = Object.fromEntries(names.map(n => [n, 0]));
let lastFrame = null, running = false, dirty = false, pendingAction = "update";
let revision = 0, contextRevision = 0, timer = null, lockedVmax = null, failed = false;
let wheelTarget = null, wheelStartControls = null, consumeLeftClick = false;

async function post(path, data, binary = false) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || `HTTP ${response.status}`);
  }
  return binary ? response.blob() : response.json();
}
function number(id) {
  const el = $(id);
  if (!el.checkValidity() || el.value.trim() === "") throw new Error(`请检查设置：${el.parentElement.textContent.trim()}`);
  return Number(el.value);
}
function scene() {
  const q = $("quality").value;
  return {...meta.defaults, pupil_x: number("pupil-x"), pupil_y: number("pupil-y"),
    angular_slit_half: number("angular-slit"), y_psf_sigma: number("y-psf"),
    extra_sigma_mev: number("extra-sigma"), expected_counts: number("counts"),
    background_per_pixel: number("background"), noise_seed: number("noise-seed"),
    poisson: $("poisson").checked, energy_half_range_mev: number("field"),
    n_rays: q === "preview" ? 16384 : q === "high" ? 262144 : 65536,
    energy_bins: q === "high" ? 1601 : 801};
}
function syncControls() {
  names.forEach(name => { $(`slide-${name}`).value = controls[name]; $(`value-${name}`).value = controls[name]; });
}
function zeroControls() { controls = Object.fromEntries(names.map(n => [n, 0])); syncControls(); }
function updateWheelBanner() {
  $("wheel-session").hidden = wheelTarget === null;
  if (wheelTarget) $("wheel-session").textContent = `${wheelTarget} = ${controls[wheelTarget].toFixed(2)} · 全页滚轮调节 · 左键保留并停止 · Esc 撤销本次调整`;
}
function updateWheelUI() {
  names.forEach(term => {
    $(`row-${term}`).classList.toggle("wheel-active", term === wheelTarget);
    $(`wheel-toggle-${term}`).setAttribute("aria-pressed", String(term === wheelTarget));
    wheelNote(term);
  });
  updateWheelBanner();
}
function startWheel(name) {
  if (wheelTarget || !wheelNote(name)) return;
  wheelTarget = name;
  // Snapshot the current controls, not a possibly older rendered frame. A wheel
  // session changes only one coefficient; Escape restores this transaction.
  wheelStartControls = {...controls};
  document.activeElement?.blur();
  updateWheelUI();
}
function finishWheel(rollback = false) {
  if (!wheelTarget) return;
  const initial = wheelStartControls;
  wheelTarget = null; wheelStartControls = null;
  if (rollback) { controls = {...initial}; syncControls(); }
  updateWheelUI();
  // Invalidate any in-flight tuning frame before restoring the plot/spectrum.
  // Ordinary confirmation keeps the latest inputs and lets the pipeline finish.
  if (rollback) request();
}
function wheelNote(name) {
  const step = $(`wheel-step-${name}`);
  const valid = step.value !== "" && step.checkValidity();
  const text = valid ? "先设置步长，再点击滚轮调节。启用后全页滚轮只调此项；左键保留并停止，Esc 撤销。" : "步长须为 0.01～120 的数值，精度 0.01；当前不执行滚轮调节。";
  $(`wheel-note-${name}`).textContent = valid && wheelTarget !== name ? "" : text;
  $(`wheel-toggle-${name}`).textContent = valid ? (wheelTarget === name ? "调节中" : "滚轮调节") : "步长无效";
  step.title = text;
  return valid;
}
function buildControls() {
  names.forEach((name, i) => {
    const row = document.createElement("div"); row.className = "coefficient"; row.id = `row-${name}`;
    row.title = "点击本行的滚轮调节按钮启用；左键保留并停止，Esc 撤销本次调整";
    const label = document.createElement("label"); label.htmlFor = `slide-${name}`; label.append(name);
    const small = document.createElement("small"); small.textContent = monomials[i]; label.append(small);
    const slider = document.createElement("input"); slider.type = "range"; slider.id = `slide-${name}`;
    const input = document.createElement("input"); input.type = "number"; input.id = `value-${name}`; input.setAttribute("aria-label", `${name} 数值`);
    [slider, input].forEach(el => { el.min = -meta.control_limit; el.max = meta.control_limit; el.step = "0.01"; el.value = "0"; });
    const reset = document.createElement("button"); reset.textContent = "↺"; reset.title = `归零 ${name}`; reset.setAttribute("aria-label", reset.title);
    slider.addEventListener("input", () => { controls[name] = Number(slider.value); input.value = slider.value; schedule(); });
    input.addEventListener("input", () => {
      if (input.checkValidity() && input.value !== "") { controls[name] = Number(input.value); slider.value = input.value; schedule(); }
    });
    reset.addEventListener("click", () => { controls[name] = 0; syncControls(); request(); });
    // Keep step editors and activation buttons in stable positions.
    const settings = document.createElement("div"); settings.className = "wheel-settings"; settings.id = `wheel-settings-${name}`;
    const toggle = document.createElement("button"); toggle.id = `wheel-toggle-${name}`; toggle.className = "wheel-toggle";
    toggle.textContent = "滚轮调节"; toggle.setAttribute("aria-label", `启用 ${name} 滚轮调节`); toggle.setAttribute("aria-pressed", "false");
    toggle.addEventListener("click", () => startWheel(name));
    const stepLabel = document.createElement("label"); stepLabel.htmlFor = `wheel-step-${name}`; stepLabel.textContent = "步长";
    const step = document.createElement("input"); step.type = "number"; step.id = `wheel-step-${name}`;
    step.min = "0.01"; step.max = String(meta.control_limit); step.step = "0.01"; step.value = "0.1";
    step.setAttribute("aria-label", `${name} 滚轮步长 / meV`); stepLabel.append(step);
    const note = document.createElement("span"); note.id = `wheel-note-${name}`; note.className = "wheel-note"; note.setAttribute("aria-live", "polite");
    step.setAttribute("aria-describedby", note.id);
    step.addEventListener("input", () => wheelNote(name));
    settings.append(toggle, stepLabel, note);
    row.append(label, slider, input, reset, settings); $("sliders").append(row);
  });
}
function schedule() {
  revision++; dirty = true;
  $("status").textContent = "实时更新中…";
  buttonState();
  // Coalesce only within a browser frame; continuous input never restarts a
  // trailing debounce. An in-flight request will pick up the latest values.
  if (!running && timer === null) timer = requestAnimationFrame(() => { timer = null; pump(); });
}
function request(action = "update") {
  // Explicit mode/scene/actions end tuning before changing its context.
  finishWheel();
  if (timer !== null) { cancelAnimationFrame(timer); timer = null; }
  revision++; contextRevision++; dirty = true;
  if (action !== "update") pendingAction = action;
  pump();
}
function buttonState() {
  ["new-question", "random-question", "retry", "reveal"].forEach(id => $(id).disabled = running);
  ["export", "save-png"].forEach(id => $(id).disabled = running || dirty || failed || !lastFrame);
}
async function pump() {
  if (running || !dirty || !session) return;
  running = true; buttonState();
  while (dirty) {
    dirty = false;
    const version = revision, context = contextRevision, action = pendingAction; pendingAction = "update";
    $("status").textContent = lastFrame ? "实时更新中…" : "计算中…";
    try {
      const data = {session, mode: $("mode").value, action, controls: {...controls}, config: scene(),
        seed: number("seed"), difficulty: $("difficulty").value, term_count: number("term-count"),
        gamma: number("gamma"), vmax: $("lock-intensity").checked ? lockedVmax : null};
      const response = await post("/api/frame", data);
      const image = new Image(); image.src = `data:image/png;base64,${response.image_png}`; await image.decode();
      // A completed intermediate frame is useful while dragging. Only a new
      // mode/question/scene/action invalidates its context. Never write an older
      // snapshot back into controls that the user has already moved further.
      if (context === contextRevision) {
        if (version === revision) { controls = response.controls; syncControls(); }
        lastFrame = response;
        if ($("lock-intensity").checked && lockedVmax === null) lockedVmax = response.display_vmax;
        render(response, image); failed = false; $("error").textContent = "";
        if (version !== revision) $("status").textContent += " · 跟随调节中";
        document.body.dataset.ready = "true";
      }
    } catch (error) {
      if (context === contextRevision) {
        failed = true; $("error").textContent = error.message;
        $("status").textContent = "未更新 · 如有图像则为上一帧";
      }
    }
    // Let the browser paint, then compute one latest snapshot, not a backlog of
    // mouse events. The image, spectrum, width and feedback always share a frame.
    if (dirty) await new Promise(resolve => requestAnimationFrame(resolve));
  }
  running = false; buttonState();
}
function setupCanvas(canvas) {
  const c = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  c.fillStyle = "#000"; c.fillRect(0, 0, w, h); c.font = "17px system-ui";
  return {c, w, h, l: 78, r: w - 24, t: 30, b: h - 62};
}
function axis(p, xmin, xmax, ymin, ymax, ylabel, decimals = 0) {
  const {c, l, r, t, b} = p;
  c.strokeStyle = "#89919b"; c.lineWidth = 1; c.beginPath(); c.moveTo(l, t); c.lineTo(l, b); c.lineTo(r, b); c.stroke();
  c.fillStyle = "#cbd1d8"; c.textAlign = "center";
  for (let i = 0; i <= 4; i++) {
    const x = l + i * (r-l)/4;
    c.fillText((xmin+i*(xmax-xmin)/4).toFixed(0), x, b+25);
  }
  c.fillText("E / meV", (l+r)/2, b+51);
  c.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const value = ymin+i*(ymax-ymin)/4;
    c.fillText(Math.abs(value) >= 10000 ? value.toExponential(1) : value.toFixed(decimals), l-10, b-i*(b-t)/4+6);
  }
  c.save(); c.translate(20, (t+b)/2); c.rotate(-Math.PI/2); c.textAlign = "center"; c.fillText(ylabel, 0, 0); c.restore();
}
function drawSpot(frame, image) {
  const p = setupCanvas($("spot")), {c, l, r, t, b} = p;
  c.imageSmoothingEnabled = false; c.drawImage(image, l, t, r-l, b-t);
  const e = frame.energy_mev;
  axis(p, e[0], e[e.length-1], frame.y_range[0], frame.y_range[1], "归一化角度 v", 1);
}
function drawSpectrum(frame) {
  const p = setupCanvas($("spectrum")), {c, l, r, t, b} = p;
  const e = frame.energy_mev, spectrum = frame.spectrum;
  const xmin = e[0], xmax = e[e.length-1], ymax = Math.max(...spectrum, 1)*1.1;
  const sx = x => l+(x-xmin)/(xmax-xmin)*(r-l), sy = y => b-y/ymax*(b-t);
  axis(p, xmin, xmax, 0, ymax, "积分计数");
  c.save(); c.beginPath(); c.rect(l, t, r-l, b-t); c.clip();
  c.strokeStyle = "#fff"; c.lineWidth = 2; c.beginPath();
  e.forEach((x, i) => { if (i) c.lineTo(sx(x), sy(spectrum[i])); else c.moveTo(sx(x), sy(spectrum[i])); }); c.stroke();
  const m = frame.metrics;
  if (m.half_height !== null) {
    c.strokeStyle = "#999"; c.lineWidth = 1; c.setLineDash([6, 7]);
    c.beginPath(); c.moveTo(l, sy(m.half_height)); c.lineTo(r, sy(m.half_height)); c.stroke();
    if (m.left_mev !== null) {
      [m.left_mev, m.right_mev].forEach(x => { c.beginPath(); c.moveTo(sx(x), b); c.lineTo(sx(x), sy(m.half_height)); c.stroke(); });
    }
  }
  c.restore();
}
function fmt(value, digits = 3) { return value === null || value === undefined ? "—" : Number(value).toFixed(digits); }
function render(frame, image) {
  drawSpot(frame, image); drawSpectrum(frame);
  ["fwhm", "centroid", "rms"].forEach((id, i) => $(id).textContent = fmt(frame.metrics[["fwhm_mev", "centroid_mev", "rms_mev"][i]]));
  $("status").textContent = `${frame.elapsed_ms.toFixed(0)} ms · ${frame.shape[1]} × ${frame.shape[0]}`;
  $("diagnostics").textContent = `角窗口通过率 ${(100*frame.transmission).toFixed(2)}% · 通过后信号视野损失 ${(100*frame.clipped_fraction).toFixed(3)}% · 能量采样 ${frame.pixel_mev.toFixed(3)} meV/像素 · 灰度上限 ${fmt(frame.display_vmax, 2)} 计数`;
  $("warnings").replaceChildren(...frame.metrics.warnings.map(text => { const p = document.createElement("p"); p.textContent = text; return p; }));
  $("feedback").hidden = !frame.feedback;
  if (!frame.feedback) { $("answer-rows").replaceChildren(); $("score").textContent = ""; }
  $("reveal").textContent = frame.feedback ? "隐藏答案" : "查看答案 / 差距";
  if (frame.question) $("question-info").textContent = `本题：种子 ${frame.question.seed} · ${frame.question.term_count} 项 · ${frame.question.difficulty}。更改难度/种子后需重新出题。`;
  if (frame.feedback) {
    $("score").textContent = `按 ±${meta.control_limit} meV 量程归一化的残差 RMS：${(frame.feedback.normalized_rms*100).toFixed(3)}%`;
    $("answer-rows").replaceChildren(...names.map(name => {
      const row = document.createElement("tr");
      [name, ...["initial", "controls", "answer", "residual"].map(k => fmt(frame.feedback[k][name], 4))].forEach(value => {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }); return row;
    }));
  }
}
function download(url, name) { const a = document.createElement("a"); a.href = url; a.download = name; a.click(); }
function bind() {
  const swallow = event => { event.preventDefault(); event.stopImmediatePropagation(); };
  document.addEventListener("wheel", event => {
    if (!wheelTarget) {
      // Prevent native spinning of inactive coefficient number inputs while
      // leaving normal page scrolling available outside a tuning session.
      if (event.target.matches?.('.coefficient > input[type="number"]')) event.target.blur();
      return;
    }
    // Capture everywhere, including plots, other coefficients and step editors.
    // No page/native-input scrolling or zoom can leak through while tuning.
    swallow(event);
    if (event.ctrlKey || event.metaKey || event.deltaY === 0 || !wheelNote(wheelTarget)) return;
    const name = wheelTarget, step = Number($(`wheel-step-${name}`).value);
    const units = Math.round(controls[name]*100) - Math.sign(event.deltaY)*Math.round(step*100);
    const next = Math.max(-meta.control_limit*100, Math.min(meta.control_limit*100, units))/100;
    if (next === controls[name]) return;
    controls[name] = next; syncControls(); updateWheelBanner(); schedule();
  }, {capture: true, passive: false});
  document.addEventListener("keydown", event => {
    if (wheelTarget && event.key === "Escape") { swallow(event); finishWheel(true); }
  }, true);
  document.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    consumeLeftClick = Boolean(wheelTarget);
    if (consumeLeftClick) { swallow(event); finishWheel(); }
  }, true);
  document.addEventListener("pointerup", event => {
    if (consumeLeftClick && event.button === 0) swallow(event);
  }, true);
  document.addEventListener("click", event => {
    if (event.button === 0 && (consumeLeftClick || wheelTarget)) {
      // The stopping click only confirms; it must not also reset a coefficient,
      // activate another button or immediately re-enter the same wheel session.
      swallow(event); consumeLeftClick = false; finishWheel();
    }
  }, true);
  window.addEventListener("blur", () => finishWheel());
  $("mode").addEventListener("change", () => {
    finishWheel();
    const practice = $("mode").value === "practice";
    $("practice").hidden = !practice; $("reveal").hidden = !practice; $("feedback").hidden = true;
    $("mode-help").textContent = practice ? "滑块是补偿量 c；隐藏像差 a 与它相加。重试只清零补偿，不换题。" : "九项可任意叠加。系数单位：meV / 归一化角度幂。";
    zeroControls(); pendingAction = practice ? "new" : "update"; request();
  });
  $("zero").addEventListener("click", () => { zeroControls(); request(); });
  $("new-question").addEventListener("click", () => { zeroControls(); request("new"); });
  $("random-question").addEventListener("click", () => { $("seed").value = crypto.getRandomValues(new Uint32Array(1))[0]; zeroControls(); request("new"); });
  $("retry").addEventListener("click", () => { zeroControls(); request("retry"); });
  $("reveal").addEventListener("click", () => request(lastFrame?.feedback ? "hide" : "reveal"));
  ["pupil-x", "pupil-y", "angular-slit", "y-psf", "extra-sigma", "counts", "background", "noise-seed", "poisson", "field", "quality"].forEach(id => $(id).addEventListener("change", () => request()));
  $("gamma").addEventListener("input", () => { $("gamma-value").textContent = Number($("gamma").value).toFixed(2); schedule(); });
  $("lock-intensity").addEventListener("change", () => { lockedVmax = $("lock-intensity").checked ? lastFrame?.display_vmax ?? null : null; request(); });
  $("reset-scene").addEventListener("click", () => {
    const mapping = {"pupil-x": "pupil_x", "pupil-y": "pupil_y", "angular-slit": "angular_slit_half", "y-psf": "y_psf_sigma", "extra-sigma": "extra_sigma_mev", "counts": "expected_counts", "background": "background_per_pixel", "noise-seed": "noise_seed", "field": "energy_half_range_mev"};
    Object.entries(mapping).forEach(([id, key]) => $(id).value = meta.defaults[key]); $("poisson").checked = false; $("quality").value = "normal"; request();
  });
  $("save-png").addEventListener("click", () => { if (lastFrame) download(`data:image/png;base64,${lastFrame.image_png}`, "eels-grayscale.png"); });
  $("export").addEventListener("click", async () => {
    if ($("mode").value === "practice" && !confirm("NPZ 包含本题真实像差和理想补偿答案。确定导出？")) return;
    try {
      const blob = await post("/api/export", {session}, true); const url = URL.createObjectURL(blob);
      download(url, "eels-sample.npz"); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (error) { $("error").textContent = error.message; }
  });
}
async function init() {
  try {
    const response = await fetch("/api/meta"); if (!response.ok) throw new Error("无法加载本地模型配置");
    meta = await response.json(); session = (await post("/api/session", {})).session;
    buildControls(); bind(); $("version").textContent = `模型版本：${meta.model_version} · NumPy 核心 + 本地 Canvas · 无外部网络请求`;
    request();
  } catch (error) { $("error").textContent = `启动失败：${error.message}`; $("status").textContent = "启动失败"; }
}
init();
