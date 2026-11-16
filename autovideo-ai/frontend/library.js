"use strict";
const effectsSettings = element("div","effects-settings");
for (const [id,label] of [["music-enabled","Música ambiente suave"],["sfx-enabled","Efeitos sonoros nas transições"]]) {
  const row = element("label","checkbox-label");
  const checkbox = element("input"); checkbox.type="checkbox"; checkbox.id=id;
  row.append(checkbox,document.createTextNode(label)); effectsSettings.append(row);
}
const encoderLabel = element("label","","Codificação do vídeo"); encoderLabel.htmlFor="encoder";
const encoderSelect = element("select"); encoderSelect.id="encoder";
for (const [value,label] of [["auto","Automática (testa GPU e usa CPU se necessário)"],["cpu","CPU — menor uso de GPU"],["nvenc","NVIDIA NVENC"]]) {
  const option = element("option","",label); option.value=value; encoderSelect.append(option);
}
effectsSettings.append(encoderLabel,encoderSelect);
$("#settings-form button").before(effectsSettings);

const library = element("section","panel visual-library"); library.id="library";
library.append(element("h2","","Biblioteca visual"),element("p","muted","Recursos incluídos em CC0. Importe PNG ou JPEG de até 2 MB com licença de uso. Use o ID no campo elements do roteiro JSON."));
const uploadForm = element("form","asset-upload");
const assetName = element("input"); assetName.placeholder="Nome do recurso"; assetName.required=true; assetName.maxLength=80; assetName.setAttribute("aria-label","Nome do recurso");
const assetLicense = element("input"); assetLicense.placeholder="Licença ou autoria (ex.: próprio, CC0)"; assetLicense.required=true; assetLicense.minLength=3; assetLicense.maxLength=200; assetLicense.setAttribute("aria-label","Licença do recurso");
const assetFile = element("input"); assetFile.type="file"; assetFile.accept="image/png,image/jpeg"; assetFile.required=true; assetFile.setAttribute("aria-label","Arquivo de imagem");
const uploadButton = element("button","button secondary","Importar imagem"); uploadButton.type="submit";
const libraryStatus = element("p","form-status"); libraryStatus.setAttribute("role","status");
const assetGrid = element("div","asset-grid");
uploadForm.append(assetName,assetLicense,assetFile,uploadButton); library.append(uploadForm,libraryStatus,assetGrid);
$("#settings").before(library);
async function loadAssets() {
  try {
    const data = await api("/api/assets");
    assetGrid.replaceChildren(...data.items.map((asset) => {
      const card = element("article","asset-card");
      const thumbnail = element("img"); thumbnail.src=asset.image_url; thumbnail.alt=asset.name; thumbnail.loading="lazy"; thumbnail.width=100; thumbnail.height=100;
      card.append(thumbnail,element("strong","",asset.name),element("code","",asset.id),element("small","muted",asset.license));
      card.append(actionButton("Copiar ID",async () => { try { await navigator.clipboard.writeText(asset.id); libraryStatus.textContent="ID copiado. Adicione-o aos elementos no editor JSON."; } catch { libraryStatus.textContent=asset.id; } }));
      if (!asset.builtin) {
        card.append(actionButton("Excluir",async () => { try { await api(`/api/assets/${asset.id}`,{method:"DELETE"}); await loadAssets(); } catch(error) { libraryStatus.textContent=error.message; } }));
      }
      return card;
    }));
  } catch(error) { libraryStatus.textContent=error.message; }
}
uploadForm.addEventListener("submit",async (event) => {
  event.preventDefault(); uploadButton.disabled=true;
  try {
    const file=assetFile.files[0];
    if (!file || file.size>2000000) throw new Error("Selecione PNG/JPEG de até 2 MB.");
    const image_base64=await new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(reader.result.split(",")[1]); reader.onerror=()=>reject(new Error("Não foi possível ler a imagem.")); reader.readAsDataURL(file); });
    await api("/api/assets",{method:"POST",body:JSON.stringify({name:assetName.value,license:assetLicense.value,image_base64})});
    uploadForm.reset(); libraryStatus.textContent="Imagem importada e disponível para os roteiros."; await loadAssets();
  } catch(error) { libraryStatus.textContent=error.message; }
  finally { uploadButton.disabled=false; }
});
loadAssets();
