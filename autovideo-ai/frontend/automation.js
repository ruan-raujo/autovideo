"use strict";
const autoLabel = element("label", "checkbox-label");
const automaticInput = element("input");
automaticInput.type = "checkbox";
automaticInput.id = "automatic";
autoLabel.append(automaticInput, document.createTextNode("Gerar roteiros e vídeos PT/EN automaticamente"));
$("#submit-button").before(autoLabel);
const quantityLabel = element("label", "", "Quantidade de histórias");
quantityLabel.htmlFor = "quantity";
const quantityInput = element("input");
quantityInput.type = "number";
quantityInput.id = "quantity";
quantityInput.min = "1";
quantityInput.max = "20";
quantityInput.value = "1";
quantityInput.required = true;
quantityInput.className = "quantity-input";
autoLabel.before(quantityLabel,quantityInput);
function updateAutomaticMode() {
  const batch = Number(quantityInput.value)>1;
  if (batch) automaticInput.checked = true;
  automaticInput.disabled = batch;
  $("#topic").required = !automaticInput.checked;
}
quantityInput.addEventListener("change",updateAutomaticMode);
automaticInput.addEventListener("change",updateAutomaticMode);
const ideasPanel = element("div", "ideas-panel");
const ideasStatus = element("p", "form-status");
ideasStatus.setAttribute("role", "status");
const ideasList = element("div", "ideas-list");
const ideasButton = actionButton("Gerar tema automaticamente", async (button) => {
  button.disabled = true;
  ideasStatus.textContent = "Pedido de ideias adicionado à fila local…";
  try {
    const task = await api("/api/topics/generate", {method:"POST",body:JSON.stringify({count:3,seed_topic:$("#topic").value})});
    const deadline = Date.now()+20*60*1000;
    while (Date.now() < deadline) {
      const current = await api(`/api/topics/tasks/${task.id}`);
      if (current.status === "failed") throw new Error(current.error);
      if (current.status === "completed") {
        ideasList.replaceChildren(...current.result.topics.map((topic) => actionButton(topic, () => { $("#topic").value = topic; $("#topic").dispatchEvent(new Event("input")); })));
        ideasStatus.textContent = "Escolha uma ideia para preencher o tema.";
        return;
      }
      ideasStatus.textContent = current.status === "queued" ? "Aguardando a vez na fila…" : "Ollama está criando ideias neste computador…";
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error("A solicitação continua salva, mas excedeu o tempo de acompanhamento da página.");
  } catch (error) { ideasStatus.textContent = error.message; }
  finally { button.disabled = false; }
});
ideasPanel.append(ideasButton, ideasStatus, ideasList);
$("#create-example").after(ideasPanel);

const batchesPanel = element("section", "batches-panel panel");
batchesPanel.append(element("h2", "", "Lotes de produção"));
const batchesList = element("div", "batches-list");
batchesPanel.append(batchesList);
$("#queue").append(batchesPanel);
async function loadBatches() {
  try {
    const data = await api("/api/batches");
    if (batchesList.contains(document.activeElement)) return;
    batchesList.replaceChildren(...data.items.map((batch) => {
      const row = element("article","batch-row");
      row.append(element("p","",`${batch.count} histórias · ${batch.counts.completed || 0} concluídas · lote ${batch.id.slice(0,8)}`));
      const actions = element("div","editor-actions");
      if (!["completed","cancelled"].includes(batch.status)) for (const [label,action] of [["Pausar lote","pause"],["Retomar lote","resume"],["Cancelar lote","cancel"]]) {
        actions.append(actionButton(label,async () => { try { await api(`/api/batches/${batch.id}/${action}`,{method:"POST"}); await loadBatches(); await loadQueue(true); } catch(error) { $("#queue-error").textContent = error.message; } }));
      }
      row.append(actions);
      return row;
    }));
    if (!data.items.length) batchesList.append(element("p","muted","Lotes criados aparecerão aqui. Os vídeos são processados um por vez."));
  } catch(error) { batchesList.textContent = error.message; }
}
loadBatches();
setInterval(() => { if (!document.hidden) loadBatches(); },5000);
