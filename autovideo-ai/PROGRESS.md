# AutoVideo AI — progresso e retomada

Atualização: 16/11/2026. Projeto: `C:/Users/ruana/OneDrive/Documentos/Videos ia/autovideo-ai`.

## Concluído

1. FastAPI, SQLite WAL, interface e fila persistente.
2. Pipeline real SVG/Pillow + Piper + legendas ASS/SRT + MP4 exato de 80 segundos.
3. PT/EN: vozes instaladas/alinhadas, sincronização visual, publicação atômica dos dois idiomas. Dois vídeos reais validados em `output/acceptance/` na versão anterior à etapa 6.
4. Ollama portátil 0.40.16 + qwen3:1.7b Q4_K_M; ideias, roteiros, adaptação EN, medição e reescrita de falas. `scripts/validate_ai.py` passou com modelo real; relatório em `tests/artifacts/ai-generation-validation.json`.
5. Lotes de 1–20 histórias, transação atômica, controles do grupo, recuperação e processamento sequencial.
6. Biblioteca SVG/PNG/JPEG, proteção de arquivos e exclusão em uso; membros articulados, boca/piscar; transições crossfade/cut/wipe/slide; música/efeitos procedurais com ducking. NVENC passou em codificação real 1080×1920 nesta GTX 1650; fallback CPU disponível.

## Validação atual

- `python -m pytest -q`: **66 passaram**, um aviso de depreciação do TestClient/httpx.
- `pip check`: sem incompatibilidades.
- `node --check` em app.js, automation.js, library.js: passou.
- `scripts/browser_check.py`: passou no Edge, 13 verificações, seis larguras (320–1440 px), teclado, editor, fila, configurações, biblioteca, modo lote e player real PT/EN. Relatório/capturas em `tests/artifacts/`.
- Etapa 7 **ainda em execução**: lote automático de duas histórias para gerar quatro vídeos na versão final com música/efeitos/NVENC. Não considerar concluído antes desse resultado.
- Estado conservado em `tests/artifacts/full-validation-state.json`, apontando banco isolado em `%LOCALAPPDATA%/AutoVideoAI/autovideo-acceptance-...`. Não apagar; permite retomar sem recriar trabalhos.
- Sessão atual de aceitação: **92773**. Sessões 16143/20035/47223 falharam por repetição do modelo 1,7B. Padrão substituído por **qwen3:4b-instruct-2507-q4_K_M**: GGUF oficial verificado e importado. Benchmark real: 2.344.636.907 bytes de VRAM, contexto 4096 e 15,93 tokens/s; descarregado ao terminar. `tests/artifacts/ai-hardware.json`.
- Roteiros PT/EN da história de Marte (`dec0556b-a547-46b5-8e04-190b58cb5616`) foram gerados/medidos e o PT final foi validado: NVENC, 156,27s de processamento, 2400 quadros, música/efeitos. Inspeção de quadro mostrou Terra no lugar de Marte; corrigido com SVG próprio `mars` e substituição nos dois roteiros do banco ISOLADO. Par pausado e reenviado para renderização correta, sem regenerar falas/roteiros com IA. Biblioteca agora tem 11 SVGs.
- Segundo trabalho (`5bf10151-df81-4da0-a477-efa75af31845`): tema aprovado sobre desaparecimento de insetos polinizadores; está gerando roteiro na mesma sessão 92773.
- Gerador de temas agora propõe ao menos três opções por pedido e varia áreas. Revisão antiga confundia impossibilidade física com hipótese inválida; corrigido prompt e decisão categórica, mantendo rejeição de condição já verdadeira/ambiguidade/duplicata. Logs guardam candidatos e motivos.
- Driver conserva e valida trabalhos concluídos mesmo que outro falhe; grava relatório `passed:false` nesse caso e pode retomar. Ainda exige todos os trabalhos aprovados para terminar com sucesso.
- `scripts/inspect_videos.py` criado para validar movimento, energia de áudio, pixels de destaque de legendas e gerar contact sheet; executar somente após relatório final atualizado.
- Revisão manual dos textos IA detectou contradições reais (abelha sobrevivente após sumiço de todas; rios de Marte; efeitos incorretos da gravidade). Os dois trabalhos foram pausados e **reenviados para geração com os MESMOS temas** na sessão 92773. Ainda não são demonstrações finais aprovadas.
- Adicionado `services/editorial.py`: referências locais com links NASA/FAO, checagem de premissa/contradições, reparos por cena, limite de três revisões e bloqueio se persistirem problemas; 2 testes novos passaram. `generate_job` agora faz PT → revisão editorial → medição/ajuste PT → adaptação EN do PT final → revisão EN → medição EN. As referências também entram no primeiro prompt. Evidências vão em `generation.json`.
- **Estado mais recente**: os dois jobs estão gerando novamente por Ollama 4B com a revisão editorial automática nova. Aguardar/fixar o necessário antes de publicar/concluir. Não usar os roteiros antigos como demonstrações finais.

## Próximas ações

1. Acompanhar sessão 92773. Se falhar, consultar os logs do banco isolado indicado no estado, corrigir a causa e executar `scripts/validate_full.py --resume`.
2. Não afrouxar a duração, número de quadros, idiomas, alinhamento ou integridade para fazer o teste passar.
3. Após os quatro vídeos finais, inspecionar quadros, confirmar arquivos/relatórios e repetir player no Edge com os novos MP4.
4. Atualizar `VALIDACAO.md` e este arquivo com resultados finais e limitações reais. Resumo curto ao usuário.

## Restrições

- Autonomia, sem confirmação entre etapas. Não usar agentes delegados.
- GTX 1650 4 GB / 12 GB RAM: um trabalho por vez, contexto 4096, Ollama descarregado antes de voz/mídia, dois threads CPU, limite de mídia 1600 MB.
- Dados reais fora do OneDrive. Não alterar projetos do usuário para testar. Migrações com backup.
- Pausa/retomada reinicia a etapa, preservando roteiros e história. Não retoma quadro intermediário.
- Modelo local requer revisão editorial; validação técnica não garante veracidade científica. Não houve vídeo de referência anexado.
- Download nativo Ollama travou no IPv6/CDN. Instalador Windows usa importação oficial direta com SHA-256 e resolução IPv4 restrita ao próprio processo. Modelo padrão qwen3:4b-instruct-2507-q4_K_M; 1,7B produziu repetições e não é o padrão final.

## Comandos (PowerShell nesta pasta)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\install_media.py
.\.venv\Scripts\python.exe scripts\install_ai.py --direct-model
.\.venv\Scripts\python.exe scripts\validate_ai.py
.\.venv\Scripts\python.exe scripts\validate_full.py --automatic --count 2
.\.venv\Scripts\python.exe scripts\validate_full.py --resume
.\.venv\Scripts\python.exe scripts\browser_check.py
.\start.bat
```

Leia este arquivo primeiro ao retomar. Consulte apenas módulos alterados e relatórios necessários. Não refazer etapas concluídas.
