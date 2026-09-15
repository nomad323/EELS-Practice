"use strict";
const $ = id => document.getElementById(id);
let names = [], monomials = [], orders = {};
let meta, session, controls = {};
let currentPage = 3, activeOrder = 5, selectedTerm = null;
const pageSelection = {};
// The TuneUp reference takes precedence where the two screenshots disagree.
// Presentation order only: preserve the model/export basis and seeded exercises.
const tuneUpOrder = ['D10', 'D01', 'D02', 'D20', 'D11'];
const tuneUpLabels = {D10: 'FX', D01: 'FY', D02: 'C', D20: 'D', D11: 'SY'};
const difficultyLabels = {easy: '初级', medium: '中级', hard: '高级', hell: '地狱难度', custom: '自定义难度'};
let lastFrame = null, lastImage = null, running = false, dirty = false, pendingAction = "update";
let revision = 0, contextRevision = 0, timer = null, lockedVmax = null, failed = false;
let wheelTarget = null, wheelStartControls = null, consumeLeftClick = false, suppressDoubleClick = false;
let practiceStartedAt = null, practiceElapsed = 0, practiceInterval = null;

function renderPracticeTimer() {
  // Measure elapsed time, not interval ticks: background throttling must not
  // turn a delayed repaint into lost practice time.
  const elapsed = practiceStartedAt === null ? practiceElapsed : performance.now() - practiceStartedAt;
  const tenths = Math.floor(Math.max(0, elapsed) / 100);
  const pad = value => String(value).padStart(2, "0");
  $("practice-time").textContent = `${pad(Math.floor(tenths / 36000))}:${pad(Math.floor(tenths / 600) % 60)}:${pad(Math.floor(tenths / 10) % 60)}.${tenths % 10}`;
}
function resetPracticeTimer() {
  clearInterval(practiceInterval); practiceInterval = null;
  practiceStartedAt = null; practiceElapsed = 0;
  renderPracticeTimer(); buttonState();
}
function startPracticeTimer() {
  if ($("mode").value !== "practice" || practiceStartedAt !== null || $("timer-start").disabled) return;
  practiceElapsed = 0; practiceStartedAt = performance.now();
  practiceInterval = setInterval(renderPracticeTimer, 100);
  renderPracticeTimer(); buttonState();
}
function stopPracticeTimer() {
  if (practiceStartedAt === null) return;
  practiceElapsed = performance.now() - practiceStartedAt; practiceStartedAt = null;
  clearInterval(practiceInterval); practiceInterval = null;
  renderPracticeTimer(); buttonState();
}

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
  updatePageBadges();
}
function pageTerms(page) {
  return names.filter(n => orders[n] <= activeOrder && (page === 3 ? orders[n] <= 3 : orders[n] === page));
}
function updatePageBadges() {
  [3, 4, 5].forEach(page => {
    const count = pageTerms(page).filter(n => controls[n] !== 0).length;
    const button = $(`page-${page}`);
    button.classList.toggle("has-values", count > 0);
    button.title = `${count} 项当前系数非零；翻页保留数值，所有已调项共同叠加`;
  });
}
function updatePages() {
  if (!pageTerms(currentPage).length) currentPage = 3;
  const visible = pageTerms(currentPage);
  names.forEach(n => {
    $(`row-${n}`).hidden = !visible.includes(n);
    $(`row-${n}`).querySelectorAll("input,button").forEach(el => el.disabled = orders[n] > activeOrder);
  });
  [3, 4, 5].forEach(page => {
    $(`page-${page}`).disabled = !pageTerms(page).length;
    $(`page-${page}`).setAttribute("aria-pressed", String(page === currentPage));
  });
  $("page-3").textContent = activeOrder === 1 ? "一阶" : activeOrder === 2 ? "一～二阶" : "一～三阶";
  selectTerm(visible.includes(pageSelection[currentPage]) ? pageSelection[currentPage] : visible[0]);
  updatePageBadges();
}
function selectTerm(name, focus = false) {
  if (!pageTerms(currentPage).includes(name) || (wheelTarget && wheelTarget !== name)) return;
  selectedTerm = name; pageSelection[currentPage] = name;
  names.forEach(n => {
    const row = $(`row-${n}`);
    row.classList.toggle('selected', n === name);
    row.tabIndex = n === name ? 0 : -1;
    if (n === name) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
  });
  if (focus) {
    const row = $(`row-${name}`);
    row.focus({preventScroll: true});
    // On small windows keep the selected row below the pinned plots.
    const top = matchMedia('(max-width:1100px)').matches
      ? document.querySelector('.monitor').getBoundingClientRect().bottom
      : document.querySelector('header').getBoundingClientRect().bottom;
    const box = row.getBoundingClientRect();
    if (box.top < top || box.bottom > innerHeight) row.scrollIntoView({block: 'end'});
  }
}
function setPage(page) {
  if (!pageTerms(page).length) return;
  finishWheel(); currentPage = page; updatePages();
  // Paging is display-only, even if a simulation is still in flight.
  if (matchMedia("(max-width:1100px)").matches) document.querySelector(".workbench").scrollIntoView({block: "start"});
  selectTerm(selectedTerm, true);
}
function updateTermChoices() {
  const order = number("max-order"), total = order*(order+3)/2;
  const previous = Number($("term-count").value);
  const choices = [...new Set([1, 3, 9, 14, 20, total])].filter(n => n <= total).sort((a,b) => a-b);
  $("term-count").replaceChildren(...choices.map(n => new Option(n === total ? `全部 ${n} 项` : `${n} 项`, String(n))));
  $("term-count").value = String(choices.includes(previous) ? previous : total);
}
function customAmplitude() {
  return $("difficulty").value === "custom" ? number("custom-amplitude") : undefined;
}
function updateDifficulty() {
  $("custom-difficulty").hidden = $("difficulty").value !== "custom";
}
function newQuestion() {
  // Reject invalid draft settings before clearing the current tuning/timer.
  try { customAmplitude(); }
  catch (error) { $("error").textContent = error.message; return; }
  finishWheel(); activeOrder = number("max-order"); resetPracticeTimer(); updatePages(); zeroControls(); request("new");
}
function zeroControls() { controls = Object.fromEntries(names.map(n => [n, 0])); syncControls(); }
function updateWheelBanner() {
  $("wheel-session").hidden = wheelTarget === null;
  if (wheelTarget) $("wheel-session").textContent = `${wheelTarget} = ${controls[wheelTarget].toFixed(2)} · 步长 ${$(`wheel-step-${wheelTarget}`).value} · ↑↓ 步长 · ←→ 单步 · Enter / 单击确认 · Esc 撤销`;
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
  if (!name || wheelTarget || !pageTerms(currentPage).includes(name) || !wheelNote(name)) return;
  selectTerm(name, true);
  wheelTarget = name;
  // Snapshot the current controls, not a possibly older rendered frame. A wheel
  // session changes only one coefficient; Escape restores this transaction.
  wheelStartControls = {...controls};
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
  const text = valid ? "双击双箭头或 Enter 开始；滚轮或 ←/→ 调系数（左减、右增一步），↑ 步长 ×10，↓ 步长 ÷10；Enter / 单击确认，Esc 撤销。" : `步长须为 0.01～${meta.control_limit} 的数值，精度 0.01；当前不执行滚轮调节。`;
  $(`wheel-note-${name}`).textContent = valid && wheelTarget !== name ? "" : text;
  $(`wheel-toggle-${name}`).title = text;
  step.title = text;
  return valid;
}
function adjustWheelStep(direction) {
  const step = $(`wheel-step-${wheelTarget}`);
  // Integer hundredths avoid floating point drift; an invalid editor remains
  // invalid until explicitly corrected, rather than silently changing its value.
  if (!wheelNote(wheelTarget)) return;
  const units = Math.round(Number(step.value)*100);
  step.value = String(Math.max(1, Math.min(meta.control_limit*100,
    direction > 0 ? units*10 : Math.round(units/10)))/100);
  wheelNote(wheelTarget); updateWheelBanner();
}
function nudgeCoefficient(direction) {
  // Wheel and keyboard share the same step validation, rounding, bounds and
  // transaction/pipeline. Only the currently active coefficient can change.
  if (!wheelTarget || !wheelNote(wheelTarget)) return;
  const name = wheelTarget, step = Number($(`wheel-step-${name}`).value);
  const units = Math.round(controls[name]*100) + direction*Math.round(step*100);
  const next = Math.max(-meta.control_limit*100, Math.min(meta.control_limit*100, units))/100;
  if (next === controls[name]) return;
  controls[name] = next; syncControls(); updateWheelBanner(); schedule();
}
function buildControls() {
  names.forEach((name, i) => {
    const row = document.createElement("div"); row.className = "coefficient"; row.id = `row-${name}`;
    row.title = "↑↓ 选择参数；双击双箭头或 Enter 开始滚轮调节";
    row.setAttribute('role', 'group'); row.setAttribute('aria-label', `${name} · ${monomials[i]}`);
    row.addEventListener('pointerdown', () => selectTerm(name));
    row.addEventListener('focusin', () => selectTerm(name));
    const label = document.createElement("label"); label.htmlFor = `slide-${name}`;
    label.append(tuneUpLabels[name] ? `${tuneUpLabels[name]} (${name})` : name);
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
    toggle.textContent = "↔"; toggle.setAttribute("aria-label", `双击或 Enter 启用 ${name} 滚轮调节`); toggle.setAttribute("aria-pressed", "false");
    toggle.addEventListener('click', () => selectTerm(name));
    toggle.addEventListener('dblclick', event => {
      event.preventDefault();
      if (!suppressDoubleClick) startWheel(name);
      suppressDoubleClick = false;
    });
    const stepLabel = document.createElement("label"); stepLabel.htmlFor = `wheel-step-${name}`; stepLabel.textContent = "步长";
    const step = document.createElement("input"); step.type = "number"; step.id = `wheel-step-${name}`;
    step.min = "0.01"; step.max = String(meta.control_limit); step.step = "0.01"; step.value = "1";
    step.setAttribute("aria-label", `${name} 滚轮步长 / meV`); stepLabel.append(step);
    const note = document.createElement("span"); note.id = `wheel-note-${name}`; note.className = "wheel-note"; note.setAttribute("aria-live", "polite");
    step.setAttribute("aria-describedby", note.id);
    step.addEventListener("input", () => { wheelNote(name); updateWheelBanner(); });
    settings.append(stepLabel, toggle, note);
    row.append(label, slider, input, reset, settings); $("sliders").append(row);
  });
  updatePages();
}
function schedule() {
  revision++; dirty = true; updatePageBadges();
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
  $("timer-start").disabled = $("mode").value !== "practice" || practiceStartedAt !== null || running || dirty || failed || !lastFrame?.question;
  $("timer-stop").disabled = practiceStartedAt === null;
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
        seed: number("seed"), difficulty: $("difficulty").value, term_count: number("term-count"), max_order: number("max-order"),
        gamma: number("gamma"), vmax: $("lock-intensity").checked ? lockedVmax : null};
      // Difficulty editors are drafts. Invalid custom input must not block
      // tuning/reveal/retry of an existing question, or free exploration.
      if (data.mode === "practice" && (action === "new" || !lastFrame?.question)) data.custom_amplitude = customAmplitude();
      const response = await post("/api/frame", data);
      const image = new Image(); image.src = `data:image/png;base64,${response.image_png}`; await image.decode();
      // A completed intermediate frame is useful while dragging. Only a new
      // mode/question/scene/action invalidates its context. Never write an older
      // snapshot back into controls that the user has already moved further.
      if (context === contextRevision) {
        if (version === revision) { controls = response.controls; syncControls(); }
        lastFrame = response; lastImage = image;
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
function redrawPlots() {
  // Layout changes reuse the last completed frame; no simulation or new labels.
  if (lastFrame && lastImage) { drawSpot(lastFrame, lastImage); drawSpectrum(lastFrame); }
}
function setupCanvas(canvas) {
  const w = Math.max(1, canvas.clientWidth), h = Math.max(1, canvas.clientHeight);
  // CSS rem sizing also applies to plot text/margins, independently of DPR.
  // Only redraw the existing frame: no resampling or simulation changes.
  const scale = parseFloat(getComputedStyle(document.documentElement).fontSize) / 12;
  const ratio = window.devicePixelRatio || 1, compact = w < 260 * scale;
  canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
  const c = canvas.getContext("2d"); c.setTransform(ratio, 0, 0, ratio, 0, 0);
  c.fillStyle = "#000"; c.fillRect(0, 0, w, h); c.font = `${(compact ? 9 : 12) * scale}px system-ui`;
  return {c, w, h, compact, scale, l: (compact ? 46 : 58) * scale,
    r: w - 12 * scale, t: 14 * scale, b: h - (compact ? 34 : 42) * scale};
}
function axis(p, xmin, xmax, ymin, ymax, ylabel, decimals = 0) {
  const {c, l, r, t, b, scale} = p;
  c.strokeStyle = "#89919b"; c.lineWidth = 1; c.beginPath(); c.moveTo(l, t); c.lineTo(l, b); c.lineTo(r, b); c.stroke();
  c.fillStyle = "#cbd1d8"; c.textAlign = "center";
  for (let i = 0; i <= 4; i++) {
    const x = l + i * (r-l)/4;
    c.fillText((xmin+i*(xmax-xmin)/4).toFixed(0), x, b+(p.compact ? 13 : 17)*scale);
  }
  c.fillText("E / meV", (l+r)/2, b+(p.compact ? 28 : 35)*scale);
  c.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const value = ymin+i*(ymax-ymin)/4;
    c.fillText(Math.abs(value) >= 10000 ? value.toExponential(1).replace("e+", "e") : value.toFixed(decimals), l-6*scale, b-i*(b-t)/4+4*scale);
  }
  c.save(); c.translate((p.compact ? 10 : 14)*scale, (t+b)/2); c.rotate(-Math.PI/2); c.textAlign = "center"; c.fillText(ylabel, 0, 0); c.restore();
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
  const warnings = [...frame.metrics.warnings];
  if (frame.clipped_fraction > 0.001) warnings.push("可在“场景与采样”扩大能量视野（±240 / ±480 meV）；不会改变本题系数或答案。");
  $("warnings").replaceChildren(...warnings.map(text => { const p = document.createElement("p"); p.textContent = text; return p; }));
  $("feedback").hidden = !frame.feedback;
  if (!frame.feedback) { $("answer-rows").replaceChildren(); $("score").textContent = ""; }
  $("reveal").textContent = frame.feedback ? "隐藏答案" : "查看答案 / 差距";
  if (frame.question) {
    const q = frame.question;
    $("question-info").textContent = `本题：最高 ${q.max_order} 阶 · ${q.term_count} 项 · 种子 ${q.seed} · ${difficultyLabels[q.difficulty]} · 单项上限 ${q.amplitude} meV。更改设置后需重新出题。`;
    if (activeOrder !== frame.question.max_order) { activeOrder = frame.question.max_order; updatePages(); }
  }
  if (frame.feedback) {
    $("score").textContent = `本题 ${frame.feedback.eligible_terms.length} 个可调项，按 ±${meta.control_limit} meV 量程归一化的残差 RMS：${(frame.feedback.normalized_rms*100).toFixed(3)}%`;
    $("answer-rows").replaceChildren(...names.filter(name => frame.feedback.eligible_terms.includes(name)).map(name => {
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
    if (event.ctrlKey || event.metaKey || event.deltaY === 0) return;
    nudgeCoefficient(-Math.sign(event.deltaY));
  }, {capture: true, passive: false});
  document.addEventListener("keydown", event => {
    if (event.isComposing) return;
    if (wheelTarget) {
      if (['Escape', 'Enter', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab'].includes(event.key)) {
        swallow(event);
        if (event.key === 'Escape') finishWheel(true);
        else if (event.key === 'Enter' && !event.repeat) finishWheel();
        else if (event.key === 'ArrowUp') adjustWheelStep(1);
        else if (event.key === 'ArrowDown') adjustWheelStep(-1);
        else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') &&
                 !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) {
          nudgeCoefficient(event.key === 'ArrowRight' ? 1 : -1);
        }
      } else if (event.target.matches?.('input,select')) swallow(event);
      return;
    }
    // Keep scene editors, selects and ordinary action buttons' native keys.
    // Within the coefficient panel, arrows select instead of spinning values.
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    const row = event.target.closest?.('.coefficient');
    if (!row && event.target.closest?.('input,select,[contenteditable]')) return;
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      swallow(event);
      const visible = pageTerms(currentPage), index = visible.indexOf(selectedTerm);
      selectTerm(visible[Math.max(0, Math.min(visible.length-1, index + (event.key === 'ArrowUp' ? -1 : 1)))], true);
    } else if (event.key === 'Enter' && !event.target.closest?.('button:not(.wheel-toggle),summary,a')) {
      swallow(event);
      if (!event.repeat) startWheel(selectedTerm);
    }
  }, true);
  document.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    consumeLeftClick = Boolean(wheelTarget);
    if (consumeLeftClick) { suppressDoubleClick = true; swallow(event); finishWheel(); }
  }, true);
  document.addEventListener("pointerup", event => {
    if (consumeLeftClick && event.button === 0) swallow(event);
  }, true);
  document.addEventListener("click", event => {
    if (event.button === 0 && (consumeLeftClick || wheelTarget)) {
      // The stopping click only confirms; it must not also reset a coefficient,
      // activate another button or immediately re-enter the same wheel session.
      swallow(event); consumeLeftClick = false; suppressDoubleClick = true; finishWheel();
    } else if (event.detail < 2) suppressDoubleClick = false;
  }, true);
  window.addEventListener("blur", () => finishWheel());
  [3, 4, 5].forEach(page => $(`page-${page}`).addEventListener("click", () => setPage(page)));
  $("max-order").addEventListener("change", () => { finishWheel(); updateTermChoices(); });
  $("difficulty").addEventListener("change", updateDifficulty);
  $("timer-start").addEventListener("click", startPracticeTimer);
  $("timer-stop").addEventListener("click", stopPracticeTimer);
  $("mode").addEventListener("change", () => {
    finishWheel(); resetPracticeTimer();
    const practice = $("mode").value === "practice";
    $("practice").hidden = !practice; $("reveal").hidden = !practice; $("feedback").hidden = true;
    $("mode-help").textContent = practice ? "滑块是补偿量 c；隐藏像差 a 与它相加。重试只清零补偿，不换题。最高阶设置在重新出题后生效。" : "一至五阶共 20 项，跨页任意叠加。系数单位：meV / 归一化角度幂。";
    activeOrder = practice ? number("max-order") : meta.max_order;
    currentPage = 3; updatePages(); zeroControls(); pendingAction = practice ? "new" : "update"; request();
  });
  $("zero").addEventListener("click", () => { zeroControls(); request(); });
  $("new-question").addEventListener("click", newQuestion);
  $("random-question").addEventListener("click", () => { $("seed").value = crypto.getRandomValues(new Uint32Array(1))[0]; newQuestion(); });
  $("retry").addEventListener("click", () => { resetPracticeTimer(); zeroControls(); request("retry"); });
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
    meta = await response.json();
    if (meta.max_order !== 5 || meta.terms?.length !== 20 || meta.powers?.length !== 20 || meta.generator_version !== "eels-exercise-per-term-2" || meta.control_limit !== 300 || meta.difficulties?.hell !== 300 || meta.custom_amplitude_min !== 0.1) throw new Error("后端版本过旧：请在终端停止并重新运行 python3 run.py，然后强制刷新页面。");
    names = [...tuneUpOrder, ...meta.terms.filter(n => !tuneUpOrder.includes(n))];
    const powers = Object.fromEntries(meta.terms.map((n, i) => [n, meta.powers[i]]));
    const superscript = ["", "", "²", "³", "⁴", "⁵"];
    monomials = names.map(n => {
      const [i, j] = powers[n];
      return (i ? "u"+superscript[i] : "") + (j ? "v"+superscript[j] : "");
    });
    orders = Object.fromEntries(names.map(n => [n, powers[n][0]+powers[n][1]]));
    controls = Object.fromEntries(names.map(n => [n, 0]));
    activeOrder = meta.max_order; $("max-order").value = String(meta.default_practice_order); updateTermChoices();
    session = (await post("/api/session", {})).session;
    $("custom-amplitude").min = String(meta.custom_amplitude_min);
    $("custom-amplitude").max = String(meta.control_limit);
    buildControls(); bind(); updateDifficulty();
    const plotObserver = new ResizeObserver(redrawPlots);
    [$("spot"), $("spectrum")].forEach(canvas => plotObserver.observe(canvas));
    window.addEventListener("resize", redrawPlots);
    $("version").textContent = `模型版本：${meta.model_version} · 出题版本：${meta.generator_version} · NumPy 核心 + 本地 Canvas · 无外部网络请求`;
    request();
  } catch (error) { $("error").textContent = `启动失败：${error.message}`; $("status").textContent = "启动失败"; }
}
init();
