"use strict";

const $ = (selector) => document.querySelector(selector);
const labels = { queued: "Na fila", preparing: "Preparando", awaiting_renderer: "Aguardando roteiro ou geração", paused: "Pausado", cancelled: "Cancelado", failed: "Erro no processamento", render_queued: "Na fila de vídeo", synthesizing: "Gerando narração", rendering: "Renderizando", validating: "Validando vídeo", completed: "Vídeo concluído" };
const activeStates = ["queued", "preparing", "render_queued", "synthesizing", "rendering", "validating"];
const dateFormat = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const pageSize = 10;
let offset = 0;
let loadingQueue = false;
let queueSignature = "";
let lastFocus = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    throw new Error("Não foi possível acessar o servidor local. Verifique se start.bat está aberto.");
  }
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : (Array.isArray(data.detail) ? data.detail.map((item) => item.msg.replace(/^Value error,\s*/, "")).join(" ") : "Confira os campos informados e tente novamente.");
    throw new Error(detail);
  }
  return data;
}

function setConnected(connected) {
  $("#connection").textContent = connected ? "● Servidor local conectado" : "● Sem conexão com o servidor";
  $("#connection").classList.toggle("offline", !connected);
}

async function showDetails(id, source) {
  try {
    const job = await api(`/api/videos/${id}`);
    $("#detail-topic").textContent = job.topic;
    const info = $("#detail-info");
    info.replaceChildren();
    for (const [name, value] of [
      ["Identificador", job.id], ["Estado", labels[job.status]],
      ["Preparação", job.preparation_complete ? "JSON do projeto salvo" : "Pendente"],
      ["Renderização", job.video_available ? "Validada: 80 segundos / 2400 quadros" : `${job.progress}% · ${labels[job.status]}`],
      ["Tentativas de processamento", String(job.attempts)],
      ["Última atualização", dateFormat.format(new Date(job.updated_at))],
    ]) info.append(element("dt", "", name), element("dd", "", value));
    $("#media-preview").replaceChildren();
    if (job.video_available) {
      const video = element("video", "video-player");
      video.controls = true;
      video.preload = "metadata";
      video.src = `/api/videos/${job.id}/preview?language=${job.video_languages?.[0] || 'PT'}`;
      video.setAttribute("aria-label", "Vídeo narrado em português, com legendas");
      const links = element("div", "editor-actions");
      for (const language of (job.video_languages || ["PT"])) {
        links.append(actionButton(`Assistir ${language}`, () => { video.pause(); video.src = `/api/videos/${job.id}/preview?language=${language}`; }));
        for (const [label, route] of [[`Baixar MP4 ${language}`, `download/${language}`], [`Legendas ${language}`, `subtitles?language=${language}`], [`Validação ${language}`, `validation?language=${language}`]]) {
        const link = element("a", "button secondary", label);
        link.href = `/api/videos/${job.id}/${route}`;
        if (route.startsWith("validation")) { link.target = "_blank"; link.rel = "noreferrer"; }
        links.append(link);
        }
      }
      $("#media-preview").append(video, links);
    }
    $("#event-list").replaceChildren(...job.events.map((event) => {
      const row = element("li", "", event.message);
      const time = element("time", "", dateFormat.format(new Date(event.created_at)));
      time.dateTime = event.created_at;
      row.append(time);
      return row;
    }));
    lastFocus = source;
    $("#job-dialog").showModal();
  } catch (error) { $("#queue-error").textContent = error.message; }
}

function actionButton(label, handler) {
  const button = element("button", "button secondary", label);
  button.type = "button";
  button.addEventListener("click", () => handler(button));
  return button;
}

async function controlJob(job, action, button) {
  button.disabled = true;
  try {
    await api(`/api/videos/${job.id}/${action}`, { method: "POST", ...(action === "render" ? { body: JSON.stringify({languages: job.script_languages || ["PT"]}) } : {}) });
    queueSignature = "";
    await loadQueue(true);
    const updatedRow = [...$("#jobs").children].find((row) => row.dataset.jobId === job.id);
    updatedRow?.querySelector("button")?.focus({ preventScroll: true });
  } catch (error) { $("#queue-error").textContent = error.message; }
  finally { button.disabled = false; }
}

function jobRow(job) {
  const row = element("article", "job-row");
  row.dataset.jobId = job.id;
  const content = element("div");
  content.append(element("h3", "job-topic", job.topic));
  const meta = element("div", "job-meta");
  meta.append(element("span", `status-badge ${job.status}`, labels[job.status]));
  const time = element("time", "", dateFormat.format(new Date(job.created_at)));
  time.dateTime = job.created_at;
  meta.append(time, element("span", "", job.preparation_complete ? "Projeto JSON salvo" : "Preparação pendente"));
  content.append(meta, element("p", "job-message", job.error || job.message));
  if (activeStates.includes(job.status)) {
    const progress = element("progress");
    progress.setAttribute("aria-label", job.task === "render" ? `Renderização: ${job.progress}%` : "Preparação em andamento");
    if (job.task === "render") { progress.max = 100; progress.value = job.progress; }
    content.append(progress);
  }
  const actions = element("div", "job-actions");
  actions.append(actionButton("Ver detalhes", (button) => showDetails(job.id, button)));
  if (job.preparation_complete && ["awaiting_renderer", "paused", "failed", "completed"].includes(job.status)) actions.append(actionButton("Editar roteiro", () => openEditor(job)));
  if (job.preparation_complete && ["awaiting_renderer", "paused", "failed"].includes(job.status)) actions.append(actionButton("Gerar roteiros com IA", async (button) => {
    button.disabled = true;
    try { await api(`/api/videos/${job.id}/generate-script`, {method:"POST",body:JSON.stringify({auto_render:false})}); await loadQueue(true); }
    catch (error) { $("#queue-error").textContent = error.message; }
    finally { button.disabled = false; }
  }));
  if (job.script_available && ["awaiting_renderer", "failed", "paused"].includes(job.status)) actions.append(actionButton(job.script_languages?.length === 2 ? "Gerar PT e EN" : "Gerar vídeo PT", (button) => controlJob(job, "render", button)));
  if (activeStates.includes(job.status)) actions.append(actionButton("Pausar trabalho", (button) => controlJob(job, "pause", button)));
  if (["paused", "failed"].includes(job.status)) actions.append(actionButton("Retomar trabalho", (button) => controlJob(job, "resume", button)));
  if (!["cancelled", "completed"].includes(job.status)) actions.append(actionButton("Cancelar trabalho", (button) => controlJob(job, "cancel", button)));
  row.append(content, actions);
  return row;
}

async function loadQueue(force = false) {
  if (loadingQueue) return;
  loadingQueue = true;
  try {
    const filter = $("#status-filter").value;
    const data = await api(`/api/videos?limit=${pageSize}&offset=${offset}${filter ? `&status=${filter}` : ""}`);
    setConnected(true);
    $("#queue-error").textContent = "";
    const all = Object.values(data.counts).reduce((sum, value) => sum + value, 0);
    $("#total-count").textContent = String(all);
    $("#nav-count").textContent = String(activeStates.reduce((sum, state) => sum+(data.counts[state] || 0), 0));
    $("#queue-summary").textContent = `${data.counts.completed || 0} concluídos · ${data.counts.paused || 0} pausados`;
    const signature = JSON.stringify(data.items);
    // Preserve the focused action while still showing live render progress.
    if (signature !== queueSignature || force) {
      const focused = $("#jobs").contains(document.activeElement) ? document.activeElement : null;
      const focusedJob = focused?.closest(".job-row")?.dataset.jobId;
      const focusedLabel = focused?.textContent;
      if (data.items.length) $("#jobs").replaceChildren(...data.items.map(jobRow));
      else {
        const empty = element("div", "empty-state");
        empty.append(element("span", "empty-icon", "≡"), element("h3", "", filter ? "Nenhum trabalho neste estado" : "Sua próxima história começa aqui"), element("p", "", filter ? "Escolha outro filtro para consultar a fila." : "Informe um tema para preparar o primeiro projeto."));
        $("#jobs").replaceChildren(empty);
      }
      queueSignature = signature;
      if (focusedJob) {
        const row = [...$("#jobs").children].find((item) => item.dataset.jobId === focusedJob);
        const buttons = [...(row?.querySelectorAll("button") || [])];
        (buttons.find((button) => button.textContent === focusedLabel) || buttons[0])?.focus({ preventScroll: true });
      }
    }
    $("#previous-page").disabled = offset === 0;
    $("#next-page").disabled = offset + pageSize >= data.total;
    $("#page-label").textContent = `Página ${Math.floor(offset / pageSize) + 1}`;
  } catch (error) {
    setConnected(false);
    $("#queue-error").textContent = error.message;
    if (!queueSignature) {
      const empty = element("div", "empty-state");
      empty.append(element("h3", "", "Fila indisponível"), element("p", "", "Abra start.bat e use Atualizar fila para reconectar."));
      $("#jobs").replaceChildren(empty);
    }
  } finally { loadingQueue = false; }
}

$("#topic").addEventListener("input", () => {
  $("#char-count").textContent = `${$("#topic").value.length} / 300`;
  $("#topic").removeAttribute("aria-invalid");
});
$("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#topic-error").textContent = "";
  const button = $("#submit-button");
  button.disabled = true;
  $("#create-status").textContent = "Salvando tema na fila local…";
  try {
    const quantity = Number($("#quantity")?.value || 1);
    const automatic = Boolean($("#automatic")?.checked);
    if (quantity > 1 || !$("#topic").value.trim()) {
      await api("/api/videos/batch", {method:"POST",body:JSON.stringify({count:quantity,automatic:true,topic:$("#topic").value})});
    } else {
      await api("/api/videos", { method: "POST", body: JSON.stringify({ topic: $("#topic").value, automatic }) });
    }
    $("#topic").value = "";
    $("#char-count").textContent = "0 / 300";
    $("#create-status").textContent = "Projeto adicionado à fila. Acompanhe a preparação abaixo.";
    $("#status-filter").value = "";
    offset = 0;
    await loadQueue(true);
  } catch (error) {
    $("#topic-error").textContent = error.message;
    $("#topic").setAttribute("aria-invalid", "true");
    $("#topic").focus();
    $("#create-status").textContent = "O tema informado foi mantido para nova tentativa.";
  } finally { button.disabled = false; }
});
$("#refresh").addEventListener("click", () => loadQueue(true));
$("#status-filter").addEventListener("change", () => { offset = 0; loadQueue(true); });
$("#previous-page").addEventListener("click", () => { offset = Math.max(0, offset - pageSize); loadQueue(true); });
$("#next-page").addEventListener("click", () => { offset += pageSize; loadQueue(true); });
$("#close-dialog").addEventListener("click", () => $("#job-dialog").close());
$("#job-dialog").addEventListener("close", () => { $("#media-preview video")?.pause(); if (lastFocus?.isConnected) lastFocus.focus(); });

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ worker_poll_seconds: Number($("#poll-seconds").value), max_concurrent_jobs: 1, cpu_threads: Number($("#cpu-threads").value), render_memory_mb: Number($("#memory-limit").value), subtitle_font_size: Number($("#subtitle-size").value), music_enabled:$("#music-enabled").checked, sfx_enabled:$("#sfx-enabled").checked, encoder:$("#encoder").value }) });
    $("#settings-status").textContent = "Configurações salvas no SQLite.";
  } catch (error) { $("#settings-status").textContent = error.message; }
  finally { button.disabled = false; }
});

async function loadEnvironment() {
  try {
    const [settings, info] = await Promise.all([api("/api/settings"), api("/api/health")]);
    if (document.activeElement !== $("#poll-seconds")) $("#poll-seconds").value = settings.queue.worker_poll_seconds;
    $("#cpu-threads").value = settings.queue.cpu_threads;
    $("#memory-limit").value = settings.queue.render_memory_mb;
    $("#subtitle-size").value = settings.queue.subtitle_font_size;
    $("#music-enabled").checked = settings.queue.music_enabled;
    $("#sfx-enabled").checked = settings.queue.sfx_enabled;
    $("#encoder").value = settings.queue.encoder;
    $("#data-dir").textContent = settings.data_dir;
    $("#health-tag").textContent = info.status === "ok" ? "Sistema operacional" : "Verificar worker";
    $("#media-status").textContent = info.media.ready ? `Vozes PT/EN disponíveis. IA local: ${info.ai.available ? "conectada" : "execute instalar_ia.bat"}.` : "Execute instalar_midia.bat para instalar as dependências gratuitas de voz e vídeo.";
    const rows = [
      ["Python", info.system.python], ["Banco de dados", "SQLite conectado"],
      ["RAM disponível", `${info.system.memory_available_gb} GB`], ["Worker", info.worker.running ? "Em execução" : "Desativado"],
    ];
    const nodes = rows.map(([label, value]) => {
      const row = element("div");
      row.append(element("span", "muted", label), element("span", "", value));
      return row;
    });
    for (const [name, dependency] of Object.entries(info.dependencies)) {
      const row = element("div");
      row.append(element("span", "muted", name), element("span", dependency.available ? "dependency-present" : "dependency-absent", dependency.available ? "Disponível" : "Não encontrado"));
      nodes.push(row);
    }
    $("#environment").replaceChildren(...nodes);
  } catch (error) { $("#health-tag").textContent = "Diagnóstico indisponível"; $("#settings-status").textContent = error.message; }
}

loadQueue();
loadEnvironment();
setInterval(() => { if (!document.hidden && !$("#job-dialog").open && !$("#script-dialog").open) loadQueue(); }, 2000);

let editorJob = null;
let editorScript = null;
let editorLanguage = "PT";
let editorDrafts = {};
const languageLabel = element("label", "", "Idioma do roteiro");
languageLabel.htmlFor = "editor-language";
const languageSelect = element("select");
languageSelect.id = "editor-language";
for (const [value, label] of [["PT", "Português brasileiro"], ["EN", "English"]]) { const option = element("option", "", label); option.value = value; languageSelect.append(option); }
$("#script-form").before(languageLabel, languageSelect);
languageSelect.addEventListener("change", async () => {
  editorDrafts[editorLanguage] = structuredClone(editorScript);
  editorLanguage = languageSelect.value;
  const saved = editorDrafts[editorLanguage] || (await api(`/api/videos/${editorJob.id}/script?language=${editorLanguage}`)).script;
  editorScript = saved || { language: editorLanguage, scenes: editorDrafts.PT.scenes.map((scene) => ({...structuredClone(scene), title: "", narration: ""})) };
  renderEditor();
});
function updateTotals() {
  const frames = editorScript.scenes.reduce((sum, scene) => sum+scene.frames, 0);
  const words = editorScript.scenes.reduce((sum, scene) => sum+scene.narration.trim().split(/\s+/).filter(Boolean).length, 0);
  $("#script-totals").textContent = `${(frames/30).toFixed(2)} / 80 segundos · ${frames} / 2400 quadros · ${words} palavras`;
  $("#script-totals").classList.toggle("field-error", frames !== 2400);
  $("#script-json").value = JSON.stringify(editorScript, null, 2);
}

function renderEditor() {
  const backgrounds = { space: "Espaço", city: "Cidade", ocean: "Oceano", snow: "Neve", dusk: "Entardecer", studio: "Estúdio" };
  $("#scene-editor").replaceChildren(...editorScript.scenes.map((scene, index) => {
    const section = element("fieldset", "scene-fields");
    section.append(element("legend", "", `Cena ${index+1}`));
    function field(label, type, value, key) {
      const wrapper = element("div");
      const id = `scene-${index}-${key}`;
      const input = element(type === "textarea" ? "textarea" : "input");
      input.id = id;
      input.value = value;
      input.required = true;
      if (type === "number") { input.type = "number"; input.step = "0.1"; input.min = "1"; input.max = "30"; }
      else { input.maxLength = key === "title" ? 70 : 550; }
      if (type === "textarea") input.rows = 3;
      const name = element("label", "", label);
      name.htmlFor = id;
      input.addEventListener("input", () => { scene[key] = key === "frames" ? Math.round(Number(input.value)*30) : input.value; updateTotals(); });
      wrapper.append(name, input);
      return wrapper;
    }
    const row = element("div", "scene-row");
    row.append(field("Duração (segundos)", "number", scene.frames/30, "frames"));
    const visual = element("div");
    const label = element("label", "", "Cenário");
    label.htmlFor = `scene-${index}-background`;
    const select = element("select");
    select.id = label.htmlFor;
    for (const [value, title] of Object.entries(backgrounds)) { const option = element("option", "", title); option.value = value; select.append(option); }
    select.value = scene.background;
    select.addEventListener("change", () => { scene.background = select.value; scene.elements = []; updateTotals(); });
    visual.append(label, select);
    row.append(visual);
    section.append(row, field("Texto visual", "text", scene.title, "title"), field("Narração", "textarea", scene.narration, "narration"));
    return section;
  }));
  updateTotals();
}

async function openEditor(job) {
  try {
    const result = await api(`/api/videos/${job.id}/script`);
    editorJob = job;
    editorLanguage = "PT";
    languageSelect.value = "PT";
    editorDrafts = {};
    editorScript = result.script || { language: "PT", scenes: [5,7,8,9,9,9,8,10,10,5].map((seconds) => ({ frames: seconds*30, title: "", narration: "", background: "space", elements: [] })) };
    $("#script-topic").textContent = job.topic;
    $("#script-error").textContent = "";
    $("#script-status").textContent = "";
    renderEditor();
    $("#script-dialog").showModal();
  } catch (error) { $("#queue-error").textContent = error.message; }
}

$("#close-editor").addEventListener("click", () => $("#script-dialog").close());
const exampleInEditor = actionButton("Carregar roteiro do Sol", async () => {
  try {
    editorScript = (await api("/api/examples/sun")).scripts[editorLanguage];
    renderEditor();
    $("#script-status").textContent = "Exemplo sobre o Sol carregado no editor. Revise antes de salvar.";
  } catch (error) { $("#script-error").textContent = error.message; }
});
exampleInEditor.classList.add("example-button");
$("#script-form").before(exampleInEditor);
$("#apply-json").addEventListener("click", () => {
  try {
    const parsed = JSON.parse($("#script-json").value);
    if (!Array.isArray(parsed.scenes) || parsed.scenes.length < 5 || parsed.scenes.length > 20) throw new Error("Informe de 5 a 20 cenas.");
    if (!["PT", "EN"].includes(parsed.language) || parsed.scenes.some((scene) => !Number.isInteger(scene.frames) || typeof scene.narration !== "string" || typeof scene.title !== "string" || !["space", "city", "ocean", "snow", "dusk", "studio"].includes(scene.background))) throw new Error("Use idioma PT/EN e cenas com frames inteiros, title, narration e background válidos.");
    editorScript = parsed;
    editorLanguage = parsed.language;
    languageSelect.value = editorLanguage;
    renderEditor();
    $("#script-error").textContent = "";
  } catch (error) { $("#script-error").textContent = `Estrutura inválida: ${error.message}`; }
});

async function saveEditor(render = false) {
  if (!$("#script-form").reportValidity()) return;
  const jobId = editorJob.id;
  const payload = JSON.stringify(editorScript);
  const buttons = [...$("#script-form").querySelectorAll("button")];
  buttons.forEach((button) => { button.disabled = true; });
  $("#script-error").textContent = "";
  try {
    await api(`/api/videos/${jobId}/script`, { method: "PUT", body: payload });
    $("#script-status").textContent = "Roteiro salvo. O encaixe da voz será verificado ao gerar.";
    if (render) {
      const languages = [...new Set([...(editorJob.script_languages || ["PT"]), editorScript.language])];
      await api(`/api/videos/${jobId}/render`, { method: "POST", body: JSON.stringify({languages}) });
      $("#script-dialog").close();
    }
    await loadQueue(true);
  } catch (error) { $("#script-error").textContent = error.message; }
  finally { buttons.forEach((button) => { button.disabled = false; }); }
}
$("#script-form").addEventListener("submit", (event) => { event.preventDefault(); saveEditor(); });
$("#save-render").addEventListener("click", () => saveEditor(true));

$("#create-example").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const example = await api("/api/examples/sun");
    const job = await api("/api/videos", { method: "POST", body: JSON.stringify({ topic: example.topic }) });
    let prepared = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      const current = await api(`/api/videos/${job.id}`);
      if (current.status === "awaiting_renderer") { prepared = true; break; }
      if (current.status === "failed") throw new Error(current.error);
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!prepared) throw new Error("O projeto foi criado e ainda está na fila. Aguarde a preparação para editar o roteiro.");
    for (const language of ["PT", "EN"]) await api(`/api/videos/${job.id}/script`, { method: "PUT", body: JSON.stringify(example.scripts[language]) });
    $("#create-status").textContent = "Exemplo PT/EN salvo. Revise os roteiros ou clique em Gerar PT e EN na fila.";
    offset = 0;
    $("#status-filter").value = "";
    await loadQueue(true);
  } catch (error) { $("#topic-error").textContent = error.message; }
  finally { button.disabled = false; }
});
