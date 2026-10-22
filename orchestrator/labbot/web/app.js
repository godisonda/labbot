/* LabBot — клиентская логика */

const $ = (sel) => document.querySelector(sel);

const STEPS = [
  { key: "extract", label: "Чтение" },
  { key: "outline", label: "Структура" },
  { key: "code", label: "Код" },
  { key: "scripts", label: "Графики" },
  { key: "sections", label: "Разделы" },
  { key: "assemble", label: "Сборка" },
];

const PROVIDERS = {
  deepseek: { base_url: "https://api.deepseek.com", model: "deepseek-chat" },
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  openrouter: { base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  ollama: { base_url: "http://localhost:11434/v1", model: "llama3.1" },
  custom: null,
};

const STATUS = {
  done: "готово",
  partial: "не завершено",
  ready: "ещё не запускалось",
  empty: "нет задания",
};

const state = {
  labs: [],
  current: null,
  details: null,
  busy: false,
  es: null,
  runId: null,
  active: -1,
  done: new Set(),
  error: false,
  clock: null,
  started: 0,
  settings: null,
  promptKey: "system",
  profileDirty: false,
};

/* ---------- мелочи ---------- */

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (typeof opts.body === "string" && !opts.headers) {
    opts.headers = { "Content-Type": "application/json" };
  }
  const response = await fetch(path, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}

let toastTimer = null;
function toast(message, kind = "") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 3500);
}

/* ---------- список работ ---------- */

async function loadState() {
  const data = await api("/api/state");
  state.labs = data.labs || [];

  const key = $("#envInfo");
  key.textContent = data.has_api_key ? "ключ сохранён" : "ключ не задан";
  key.className = `key ${data.has_api_key ? "ok" : ""}`;

  fillProfile(data.profile || {});
  renderLabs();

  if (state.current) await selectLab(state.current);
  else if (state.labs.length) await selectLab(state.labs[0].id);
  else {
    $("#workspace").classList.add("hidden");
    $("#deleteLabTop").classList.add("hidden");
  }
}

function fillProfile(profile) {
  if (state.profileDirty) return;
  for (const key of ["student", "group", "teacher"]) {
    const input = $(`#${key}`);
    if (input && !input.value) input.value = profile[key] || "";
  }
}

function renderLabs() {
  const query = $("#search").value.trim().toLowerCase();
  const list = state.labs.filter((lab) => {
    if (!query) return true;
    return `${lab.id} ${lab.task || ""} ${lab.meta.title || ""}`.toLowerCase().includes(query);
  });

  if (!list.length) {
    $("#labs").innerHTML = `<p class="empty small">Ничего не найдено</p>`;
    return;
  }

  $("#labs").innerHTML = list.map((lab) => `
    <button class="work ${lab.id === state.current ? "active" : ""} ${lab.status === "empty" ? "empty" : ""}"
            data-id="${esc(lab.id)}" type="button">
      <span class="work-name">${esc(lab.id)}</span>
      <span class="work-topic">${esc(lab.meta.title || lab.task || "нет документов")}</span>
    </button>`).join("");

  for (const item of document.querySelectorAll(".work")) {
    item.addEventListener("click", () => selectLab(item.dataset.id));
  }
}

/* ---------- выбранная работа ---------- */

async function selectLab(id) {
  if (state.busy && id !== state.current) {
    toast("Идёт генерация — дождитесь окончания", "warn");
    return;
  }
  try {
    const data = await api(`/api/lab?lab=${encodeURIComponent(id)}`);
    state.current = id;
    state.details = data;
    if (!state.busy) {
      state.done = new Set();
      state.active = -1;
      state.error = false;
    }
    renderLabs();
    renderLab();
    replayReveal();
    $("#workspace").classList.remove("hidden");
  } catch (error) {
    toast(error.message, "err");
  }
}

function replayReveal() {
  document.querySelectorAll(".block").forEach((block, index) => {
    block.style.setProperty("--i", index);
    block.classList.remove("reveal");
    void block.offsetWidth;
    block.classList.add("reveal");
  });
}

function renderLab() {
  const lab = state.details;
  if (!lab) return;

  const meta = lab.meta || {};
  $("#labTitle").textContent = lab.id;
  $("#labEyebrow").textContent = meta.work_type
    ? `${meta.work_type}${meta.number ? ` №${meta.number}` : ""}`
    : "Работа";
  $("#labSubtitle").textContent = meta.title || lab.task || "Документы ещё не загружены";
  $("#statusText").textContent = STATUS[lab.status] || "";
  $("#deleteLabTop").classList.remove("hidden");

  renderDocs(lab);
  renderResults(lab);
  if (!state.busy) renderSteps(lab.steps || {});

  if (!state.busy) {
    let saved = "";
    try { saved = localStorage.getItem(`labbot.variant.${lab.id}`) || ""; } catch (error) { saved = ""; }
    $("#variant").value = saved;
  }
  applyMode();
}

/* ---------- документы ---------- */

function renderDocs(lab) {
  const refs = lab.refs || [];
  const task = lab.task;

  const taskRow = task
    ? `<div class="doc-row filled" data-kind="task">
         <span class="doc-tag">Задание</span>
         <span class="doc-name" title="${esc(task)}">${esc(task)}</span>
         <label class="doc-add">заменить<input type="file" accept=".pdf,.docx,.txt,.md" hidden></label>
       </div>`
    : `<div class="doc-row empty-drop" data-kind="task">
         <span class="doc-plus">+</span>
         <span class="doc-empty-text">
           <b>Перетащите задание</b>
           <span class="note">методичка или ТЗ — PDF, DOCX, TXT</span>
         </span>
         <label class="doc-add">выбрать<input type="file" accept=".pdf,.docx,.txt,.md" hidden></label>
       </div>`;

  $("#docs").innerHTML = `
    ${taskRow}
    <div class="doc-row ${refs.length ? "filled" : ""}" data-kind="refs">
      <span class="doc-tag">Образец</span>
      ${refs.length
        ? `<span class="doc-list">${refs.map((name) => `<span title="${esc(name)}">${esc(name)}</span>`).join("")}</span>`
        : `<span class="doc-name none">необязательно</span>`}
      <label class="doc-add">добавить<input type="file" multiple accept=".pdf,.docx,.txt,.md" hidden></label>
    </div>`;

  for (const row of document.querySelectorAll(".doc-row")) {
    const input = row.querySelector('input[type="file"]');
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      row.classList.add("drag");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag"));
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      row.classList.remove("drag");
      uploadFiles(row.dataset.kind, event.dataTransfer.files);
    });
    input.addEventListener("change", () => {
      uploadFiles(row.dataset.kind, input.files);
      input.value = "";
    });
  }
}

async function uploadFiles(kind, files) {
  if (!files || !files.length || !state.current) return;
  if (state.busy) return toast("Идёт генерация — файлы добавим после", "warn");

  try {
    for (const file of files) {
      const url = `/api/upload?lab=${encodeURIComponent(state.current)}&kind=${kind}&name=${encodeURIComponent(file.name)}`;
      const response = await fetch(url, { method: "POST", body: file });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `Не удалось загрузить ${file.name}`);
    }
    toast(files.length > 1 ? "Файлы добавлены" : "Файл добавлен");
    await selectLab(state.current);
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ---------- результаты ---------- */

function renderResults(lab) {
  const files = lab.files || [];
  if (!files.length) {
    $("#results").innerHTML = `<p class="empty">Пока пусто — запустите генерацию.</p>`;
    return;
  }

  $("#results").innerHTML = files.map((file, index) => {
    const download = ["docx", "cpp", "py", "tex"].includes(file.kind) ? "&download=1" : "";
    const href = `/api/file?lab=${encodeURIComponent(lab.id)}&path=${encodeURIComponent(file.path)}${download}`;
    const ext = (file.kind || "").slice(0, 4).toUpperCase();
    return `
      <a class="result" style="--i:${index}" href="${href}" target="_blank" rel="noopener">
        <span class="ext">${esc(ext)}</span>
        <span class="result-name">${esc(file.name)}</span>
        <span class="result-size">${fmtSize(file.size)}</span>
        <span class="result-arrow">→</span>
      </a>`;
  }).join("");
}

/* ---------- шаги ---------- */

function renderSteps(completed = {}) {
  const done = new Set(state.done);
  for (const step of STEPS) {
    if (completed[step.key]) done.add(step.key);
  }

  const percent = Math.round((done.size / STEPS.length) * 100);
  $("#progressBar").style.width = `${percent}%`;

  $("#steps").innerHTML = STEPS.map((step, index) => {
    const finished = done.has(step.key);
    const active = state.busy && index === state.active;
    const classes = [
      finished ? "done" : "",
      active ? "active" : "",
      active && state.error ? "error" : "",
      active && !state.error ? "running" : "",
    ].filter(Boolean).join(" ");
    return `<li class="${classes}">${step.label}</li>`;
  }).join("");
}

function advanceTo(index) {
  state.active = index;
  for (let i = 0; i < index; i += 1) state.done.add(STEPS[i].key);
  renderSteps({});
}

/* ---------- журнал ---------- */

function appendLog(line) {
  const log = $("#log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
  const row = document.createElement("div");
  const cls = /Traceback|Error|ошибка|Ошибка/.test(line)
    ? "err"
    : /готов|успешно|завершена|собран/.test(line)
      ? "ok"
      : "";
  row.className = `log-line ${cls}`;
  row.textContent = line;
  log.appendChild(row);
  while (log.childElementCount > 2000) log.removeChild(log.firstElementChild);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function trackLine(line) {
  const step = line.match(/\[(\d)\/5\]/);
  if (step) advanceTo(Number(step[1]));

  const cost = line.match(/Стоимость: \$([\d.]+)/);
  if (cost) $("#cost").textContent = `$${cost[1]}`;

  const tokens = line.match(/Токенов: prompt=(\d+), completion=(\d+)/);
  if (tokens) $("#cost").textContent = `${Number(tokens[1]) + Number(tokens[2])} токенов`;

  if (/Traceback|DeepSeekAPIError|Недостаточно средств/.test(line)) {
    state.error = true;
    renderSteps({});
  }
}

/* ---------- запуск ---------- */

function setBusy(busy) {
  state.busy = busy;
  $("#start").disabled = busy;
  $("#stop").disabled = !busy;
  $("#mode").disabled = busy;
  $("#fromStage").disabled = busy || $("#mode").value !== "report";
  document.body.classList.toggle("running", busy);
}

function applyMode() {
  const report = $("#mode").value === "report";
  $("#fromStage").disabled = state.busy || !report;
  $("#variant").disabled = state.busy || !report;
}

function startClock() {
  state.started = Date.now();
  clearInterval(state.clock);
  state.clock = setInterval(() => {
    const total = Math.floor((Date.now() - state.started) / 1000);
    const mm = String(Math.floor(total / 60)).padStart(2, "0");
    const ss = String(total % 60).padStart(2, "0");
    if (state.busy) $("#statusText").textContent = `генерация · ${mm}:${ss}`;
  }, 1000);
}

function stopClock() {
  clearInterval(state.clock);
  state.clock = null;
}

async function startRun() {
  if (state.busy || !state.current) return;

  const payload = {
    lab: state.current,
    mode: $("#mode").value,
    variant: $("#variant").value.trim(),
    student: $("#student").value.trim(),
    group: $("#group").value.trim(),
    teacher: $("#teacher").value.trim(),
    remember: $("#remember").checked,
    from_stage: $("#fromStage").value,
  };

  if (payload.variant) {
    try { localStorage.setItem(`labbot.variant.${state.current}`, payload.variant); } catch (error) { /* приватный режим */ }
  }

  state.runId = null;
  state.active = -1;
  state.done = new Set();
  state.error = false;

  $("#log").innerHTML = "";
  $("#cost").textContent = "";
  $("#logBox").open = true;
  setBusy(true);
  renderSteps({});
  advanceTo(0);
  startClock();

  try {
    const data = await api("/api/run", { method: "POST", body: JSON.stringify(payload) });
    state.runId = data.id;

    const source = new EventSource(`/api/log/${data.id}`);
    state.es = source;

    source.onmessage = (event) => {
      const item = JSON.parse(event.data);
      appendLog(item.line);
      trackLine(item.line);
    };

    source.addEventListener("done", (event) => {
      const result = JSON.parse(event.data);
      source.close();
      state.es = null;
      finishRun(result.returncode);
    });
  } catch (error) {
    stopClock();
    setBusy(false);
    $("#statusText").textContent = "ошибка запуска";
    toast(error.message, "err");
    await selectLab(state.current);
  }
}

async function finishRun(code) {
  stopClock();
  setBusy(false);

  if (code === 0) {
    for (const step of STEPS) state.done.add(step.key);
    state.active = -1;
    renderSteps({});
    toast("Отчёт готов", "");
    setTimeout(() => {
      const results = document.querySelector("#results");
      if (results) results.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 300);
  } else if ([130, -15, 143].includes(code)) {
    toast("Остановлено", "warn");
  } else {
    state.error = true;
    renderSteps({});
    toast(`Не получилось (код ${code}) — смотрите журнал`, "err");
  }

  await selectLab(state.current);
}

async function stopRun() {
  if (!state.runId) return;
  try {
    await api("/api/cancel", { method: "POST", body: JSON.stringify({ id: state.runId }) });
    toast("Останавливаю…", "warn");
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ---------- настройки ---------- */

async function openSettings() {
  try {
    const data = await api("/api/settings");
    state.settings = data;

    $("#setApiKey").value = "";
    $("#setApiKey").placeholder = data.api_key_set ? `сохранён: ${data.api_key_masked}` : "sk-...";
    $("#keyStatus").textContent = data.api_key_set ? "Ключ сохранён в .env" : "Ключ не задан";

    $("#setProvider").value = data.llm.provider || "deepseek";
    $("#setModel").value = data.llm.model;
    $("#setBaseUrl").value = data.llm.base_url;
    $("#setTemperature").value = data.llm.temperature;
    $("#setMaxTokens").value = data.llm.max_tokens;
    $("#setTimeout").value = data.llm.timeout;
    $("#setRetries").value = data.llm.max_retries;
    $("#setCostLimit").value = data.llm.max_cost_limit_usd;

    $("#setStudent").value = data.profile.student || "";
    $("#setGroup").value = data.profile.group || "";
    $("#setTeacher").value = data.profile.teacher || "";
    $("#setFaculty").value = data.profile.faculty || "";
    $("#setDepartment").value = data.profile.department || "";
    $("#setYear").value = data.report.year || "";

    const select = $("#promptSelect");
    select.innerHTML = Object.entries(data.prompt_labels)
      .map(([key, label]) => `<option value="${key}">${esc(label)}</option>`)
      .join("");
    state.promptKey = select.options.length ? select.options[0].value : "system";
    select.value = state.promptKey;
    $("#promptText").value = data.prompts[state.promptKey] || "";
    updatePromptHints();

    $("#settingsPath").textContent = data.settings_file;
    $("#settingsModal").classList.remove("hidden");
  } catch (error) {
    toast(error.message, "err");
  }
}

function closeSettings() {
  $("#settingsModal").classList.add("hidden");
}

function updatePromptHints() {
  const list = (state.settings && state.settings.prompt_placeholders[state.promptKey]) || [];
  $("#promptHints").textContent = list.length
    ? `Подстановки: ${list.map((name) => `<<${name}>>`).join(", ")}`
    : "В этом промпте нет подстановок.";
}

function collectPromptEdits() {
  if (state.settings) state.settings.prompts[state.promptKey] = $("#promptText").value;
}

async function saveSettings() {
  if (!state.settings) return;
  collectPromptEdits();

  const payload = {
    api_key: $("#setApiKey").value.trim(),
    llm: {
      provider: $("#setProvider").value,
      model: $("#setModel").value.trim(),
      base_url: $("#setBaseUrl").value.trim(),
      temperature: Number($("#setTemperature").value),
      max_tokens: Number($("#setMaxTokens").value),
      timeout: Number($("#setTimeout").value),
      max_retries: Number($("#setRetries").value),
      max_cost_limit_usd: Number($("#setCostLimit").value),
    },
    report: { year: $("#setYear").value.trim() },
    profile: {
      student: $("#setStudent").value.trim(),
      group: $("#setGroup").value.trim(),
      teacher: $("#setTeacher").value.trim(),
      faculty: $("#setFaculty").value.trim(),
      department: $("#setDepartment").value.trim(),
    },
    prompts: state.settings.prompts,
  };

  try {
    const saved = await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    toast("Настройки сохранены");
    closeSettings();

    for (const key of ["student", "group", "teacher"]) {
      const value = saved.profile[key] || "";
      if (value) $(`#${key}`).value = value;
    }
    await loadState();
  } catch (error) {
    toast(error.message, "err");
  }
}

async function testApiKey() {
  try {
    const data = await api("/api/settings/test", {
      method: "POST",
      body: JSON.stringify({ api_key: $("#setApiKey").value.trim() }),
    });
    toast(`Ключ работает (HTTP ${data.status})`);
  } catch (error) {
    toast(error.message, "err");
  }
}

async function resetPrompt() {
  if (!state.settings) return;
  try {
    const data = await api("/api/settings/reset", {
      method: "POST",
      body: JSON.stringify({ name: state.promptKey }),
    });
    state.settings = data;
    $("#promptText").value = data.prompts[state.promptKey] || "";
    toast("Промпт сброшен");
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ---------- прочее ---------- */

function openNewLab() {
  $("#newName").value = "";
  $("#newFile").value = "";
  $("#newHint").textContent = "";
  $("#newHint").className = "note";
  $("#newModal").classList.remove("hidden");
  setTimeout(() => $("#newName").focus(), 40);
}

function closeNewLab() {
  $("#newModal").classList.add("hidden");
}

async function createLab() {
  if (state.busy) return toast("Идёт генерация", "warn");

  const name = $("#newName").value.trim();
  if (!name) {
    $("#newHint").textContent = "Введите название работы";
    $("#newHint").className = "note err-text";
    return;
  }

  const file = $("#newFile").files[0];
  try {
    const data = await api("/api/new", { method: "POST", body: JSON.stringify({ name }) });
    if (file) {
      const url = `/api/upload?lab=${encodeURIComponent(data.id)}&kind=task&name=${encodeURIComponent(file.name)}`;
      const response = await fetch(url, { method: "POST", body: file });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Работа создана, но файл не загрузился");
    }
    closeNewLab();
    await loadState();
    await selectLab(data.id);
    toast(`Создана «${data.id}»`);
  } catch (error) {
    $("#newHint").textContent = error.message;
    $("#newHint").className = "note err-text";
  }
}

async function cleanLab() {
  if (!state.current) return;
  if (state.busy) return toast("Сначала остановите генерацию", "warn");
  const ok = confirm(`Очистить build/, scripts/ и src/ у ${state.current}?`);
  if (!ok) return;
  try {
    await api("/api/clean", { method: "POST", body: JSON.stringify({ lab: state.current }) });
    toast("Кэш очищен");
    await selectLab(state.current);
  } catch (error) {
    toast(error.message, "err");
  }
}

function openDelete() {
  if (!state.current) return;
  $("#deleteName").textContent = state.current;
  $("#deleteModal").classList.remove("hidden");
}

function closeDelete() {
  $("#deleteModal").classList.add("hidden");
}

async function deleteLab() {
  if (state.busy) return toast("Сначала остановите генерацию", "warn");
  const name = state.current;
  try {
    await api("/api/delete", { method: "POST", body: JSON.stringify({ lab: name }) });
    closeDelete();
    toast(`«${name}» удалена`);
    state.current = null;
    await loadState();
  } catch (error) {
    toast(error.message, "err");
  }
}

async function revealLab() {
  if (!state.current) return;
  try {
    await api("/api/reveal", { method: "POST", body: JSON.stringify({ lab: state.current }) });
  } catch (error) {
    toast(error.message, "err");
  }
}

/* ---------- запуск интерфейса ---------- */

function bind() {
  $("#search").addEventListener("input", renderLabs);

  $("#refresh").addEventListener("click", () => loadState());
  $("#newLab").addEventListener("click", openNewLab);
  $("#start").addEventListener("click", startRun);
  $("#stop").addEventListener("click", stopRun);
  $("#cleanLab").addEventListener("click", cleanLab);
  $("#deleteLab").addEventListener("click", openDelete);
  $("#deleteLabTop").addEventListener("click", openDelete);
  $("#deleteCancel").addEventListener("click", closeDelete);
  $("#deleteClose").addEventListener("click", closeDelete);
  $("#deleteConfirm").addEventListener("click", deleteLab);
  $("#deleteModal").addEventListener("click", (event) => {
    if (event.target === $("#deleteModal")) closeDelete();
  });
  $("#setProvider").addEventListener("change", () => {
    const preset = PROVIDERS[$("#setProvider").value];
    if (preset) {
      $("#setBaseUrl").value = preset.base_url;
      $("#setModel").value = preset.model;
    }
  });
  $("#reveal").addEventListener("click", revealLab);
  $("#mode").addEventListener("change", applyMode);

  $("#openSettings").addEventListener("click", openSettings);
  $("#settingsClose").addEventListener("click", closeSettings);
  $("#settingsCancel").addEventListener("click", closeSettings);
  $("#settingsSave").addEventListener("click", saveSettings);
  $("#testKey").addEventListener("click", testApiKey);
  $("#promptReset").addEventListener("click", resetPrompt);

  $("#newCreate").addEventListener("click", createLab);
  $("#newCancel").addEventListener("click", closeNewLab);
  $("#newClose").addEventListener("click", closeNewLab);
  $("#newModal").addEventListener("click", (event) => {
    if (event.target === $("#newModal")) closeNewLab();
  });
  $("#newName").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      createLab();
    }
  });

  $("#promptSelect").addEventListener("change", () => {
    collectPromptEdits();
    state.promptKey = $("#promptSelect").value;
    $("#promptText").value = (state.settings && state.settings.prompts[state.promptKey]) || "";
    updatePromptHints();
  });

  $("#settingsModal").addEventListener("click", (event) => {
    if (event.target === $("#settingsModal")) closeSettings();
  });

  for (const key of ["student", "group", "teacher"]) {
    $(`#${key}`).addEventListener("input", () => { state.profileDirty = true; });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!$("#settingsModal").classList.contains("hidden")) closeSettings();
      if (!$("#newModal").classList.contains("hidden")) closeNewLab();
      if (!$("#deleteModal").classList.contains("hidden")) closeDelete();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      startRun();
    }
  });
}

bind();
loadState().catch((error) => toast(error.message, "err"));
