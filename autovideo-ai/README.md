# AutoVideo AI

Fábrica local de vídeos animados em português e inglês. Cada versão tem **80 segundos, 2400 quadros, 30 fps, 1080×1920, H.264 e AAC**. Ollama cria ideias e roteiros; Piper narra; SVG/Pillow animam; FFmpeg compõe áudio e legendas. Sem API comercial obrigatória.

## Usar neste computador

1. Abra `start.bat` e acesse http://127.0.0.1:8000. Se uma versão anterior estiver aberta, encerre sua janela com Ctrl+C e reinicie.
2. Informe um tema ou clique em **Gerar tema automaticamente**.
3. Marque **Gerar roteiros e vídeos PT/EN automaticamente** e escolha a quantidade (1–20). Tema vazio permite criar ideias novas; em lote, o tema serve como inspiração.
4. Acompanhe a fila e os lotes. Em **Ver detalhes**, reproduza e baixe PT, EN ou SRT.

Para revisão antes de renderizar: cadastre um tema sem a opção automática, use **Gerar roteiros com IA**, abra o editor e revise os dois idiomas. O exemplo do Sol fornece roteiros editoriais prontos. Salvar e gerar usa os idiomas já salvos; o endpoint `/render` sem corpo mantém compatibilidade e gera somente PT.

A aceitação usa um banco separado dos seus projetos. Vídeos exportados ficam em `output/acceptance/`; o estado para retomada está em `tests/artifacts/full-validation-state.json`.

## Instalar em outro Windows

Requisitos: Windows 64 bits, Python 3.13 com launcher `py`, espaço para modelos/ferramentas. Execute `instalar_midia.bat`, depois `instalar_ia.bat`. A instalação usa internet; a produção funciona localmente com os modelos instalados. Abra `start.bat`.

Instalação manual no PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\install_media.py
.\.venv\Scripts\python.exe scripts\install_ai.py --direct-model
.\.venv\Scripts\python.exe scripts\run.py
```

O instalador verifica SHA-256 e conserva licenças/model cards. As vozes são `pt_BR-faber-medium` e `en_US-ljspeech-high`, com cópias alinhadas para obter os tempos reais dos fonemas. As ferramentas ficam em `%LOCALAPPDATA%\AutoVideoAI`, sem alterar o PATH. O padrão é Ollama portátil com [qwen3:4b-instruct-2507-q4_K_M](https://ollama.com/library/qwen3%3A4b-instruct-2507-q4_K_M), GGUF de cerca de 2,5 GB. O importador direto baixa GGUF e metadados oficiais, verifica SHA e usa `ollama create`; no Windows, usa IPv4 somente no processo de instalação.

No VS Code, abra esta pasta e selecione `.venv/Scripts/python.exe`. Configure substituições em `.env`, seguindo `.env.example`. Vozes alternativas precisam corresponder ao idioma e conter os dados de alinhamento esperados pelo Piper.

## Recursos e edição

- Fila SQLite persistente, histórico, prevenção de temas duplicados, erros recuperáveis e controles por trabalho/lote.
- Temas e roteiros locais com JSON validado, adaptação EN e reescrita automática das falas que não couberem.
- Editor PT/EN de 5–20 cenas, 100–240 palavras e soma exata de 2400 quadros. Os tempos reais são medidos por voz.
- Personagens com braços/pernas articulados, boca ligada à atividade da voz, piscar e expressões; objetos, órbita, rotação, zoom e panorâmica.
- Biblioteca com dez SVGs próprios CC0 e importação PNG/JPEG de até 2 MB, 4096 px e 8 megapixels. Imagens são normalizadas para PNG de até 1024 px. Informe autoria/licença; recursos usados em roteiros não podem ser excluídos.
- Transições `crossfade`, `cut`, `wipe`, `slide`, configuradas por cena com `transition_frames` de 0–30.
- Música ambiente e efeitos de transição opcionais, sintetizados localmente. A trilha reduz o volume sob a fala; a mixagem é normalizada.
- Legendas grandes, contorno, destaque temporal por palavra, queima no vídeo, faixa mov_text e SRT.
- Verificação FFprobe e decodificação completa antes de publicar o par. Player e downloads com HTTP Range.

O plano visual PT é compartilhado com EN; títulos, falas e tempos continuam independentes. Lista `elements` vazia usa a composição do cenário. Exemplo de elemento no editor JSON:

```json
{"asset":"earth","x":0.5,"y":0.5,"scale":1.4,"motion":"spin","amplitude":0.025,"speed":0.2,"expression":"neutral"}
```

Movimentos: `none`, `bob`, `drift`, `orbit`, `spin`, `walk`. Expressões: `neutral`, `happy`, `worried`. `opacity_start` e `opacity_end` (0–1) animam aparecimento/desaparecimento. Posições normalizadas, até 12 elementos por cena. Para imagem importada, use o ID `asset_...` mostrado na biblioteca. Câmera: `zoom_start`, `zoom_end`, `pan_x`, `pan_y`. SVG externo, caminho arbitrário e comandos de voz/legenda são recusados.

A velocidade de ajuste fica entre 0,92 e 1,12 com pausas e preservação de tom. Nenhuma palavra é cortada. Escreva números por extenso. Se um roteiro manual não couber, encurte a fala ou redistribua quadros; a geração com IA tenta reescrever a cena.

## GTX 1650 4 GB / 12 GB RAM

Um trabalho por vez, dois threads de CPU por padrão e limite monitorado de 1600 MB para a árvore de processos de mídia. Ollama usa contexto 4096, um modelo carregado e `keep_alive=0`, liberando VRAM antes da voz/renderização. O modelo 4B mediu cerca de 2,34 GB de VRAM e 15,93 tokens/s neste computador, com descarregamento ao terminar. Relatório em `tests/artifacts/ai-hardware.json`; repetir com `scripts/benchmark_ai.py`.

A opção **Automática** testa NVENC com dois quadros reais em 1080×1920 e usa CPU caso indisponível. O teste passou nesta GTX 1650. A renderização de imagens e o Piper continuam em CPU. NVENC forçado informa erro quando não funciona. Feche programas pesados se faltar memória.

Pausa/cancelamento encerra a árvore de processos. **Retomar reinicia a etapa interrompida**, preservando roteiros e histórias; não continua do último quadro. Após queda, trabalhos ativos retornam à fila. A supervisão aplica limite de memória e tempo de 30 minutos por etapa; o limite é monitorado, não uma cota rígida do Windows.

## Dados e API

Dados em `%LOCALAPPDATA%\AutoVideoAI`: `database/`, `output/`, `temp/`, `assets/`, `logs/`, `tools/`, `voices/`, `ai_models/`. Banco fora do OneDrive. Migrações mantêm backup prévio. Execute uma instância por pasta de dados. Para backup manual, encerre o servidor e copie a pasta inteira.

Cada saída conserva MP4, WAVs, SRT/ASS, tempos de palavras, encaixe da narração, prévias, SVGs e validação. Arquivos finais não são excluídos automaticamente; temporários interrompidos são recuperados/limpos.

API documentada em `/docs`, `/redoc`, `/openapi.json`:

| Rotas | Função |
| --- | --- |
| `POST /api/videos` | Tema; `automatic:true` gera roteiro e par PT/EN |
| `POST /api/videos/batch` | `count`, `automatic`, inspiração `topic` ou lista explícita `topics` |
| `GET /api/batches`, `GET /api/batches/{id}` | Progresso agregado |
| `POST /api/batches/{id}/{pause,resume,cancel}` | Controle do grupo |
| `POST /api/topics/generate` | Retorna 202 + id de solicitação |
| `GET /api/topics/tasks/{id}` | Ideias, progresso ou erro |
| `POST /api/topics/tasks/{id}/cancel` | Cancela pedido de ideias |
| `GET /api/videos`, `GET /api/videos/{id}` | Lista, estado e eventos |
| `GET/PUT /api/videos/{id}/script` | Edição; GET aceita `?language=EN` |
| `POST /api/videos/{id}/generate-script` | Gera ambos os roteiros; `auto_render` opcional |
| `POST /api/videos/{id}/render` | `{"languages":["PT","EN"]}` |
| `POST /api/videos/{id}/{pause,resume,cancel}` | Controle individual |
| `GET /api/videos/{id}/download/{PT,EN}` | MP4 validado |
| `GET /api/videos/{id}/{preview,subtitles,validation}` | Aceita `?language=PT` ou EN |
| `GET/POST /api/assets`, `PUT/DELETE /api/assets/{id}` | Biblioteca; upload JSON base64 |
| `GET /api/assets/{id}/image` | Imagem local autorizada |
| `GET/PUT /api/settings`, `GET /api/health` | Configuração e diagnóstico |

O servidor usa loopback, mesma origem e valida caminhos. Não há publicação pública ou autenticação multiusuário. Os visualizadores OpenAPI usam CDN; o painel principal funciona sem CDN. A deduplicação normaliza temas e algumas reformulações, sem garantir equivalência semântica completa.

## Verificar e retomar

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_ai.py
.\.venv\Scripts\python.exe scripts\validate_full.py --automatic --count 2
.\.venv\Scripts\python.exe scripts\browser_check.py
```

`validate_full.py` usa dados isolados, conserva estado e copia os MP4 reais para `output/acceptance`. Para continuar uma aceitação interrompida, use `--resume`. O navegador usa Edge instalado, sem baixar outro browser. Leia `PROGRESS.md` antes de retomar desenvolvimento e `VALIDACAO.md` para os resultados.

Roteiros do modelo pequeno precisam de revisão editorial, especialmente afirmações científicas. Os controles verificam estrutura, repetições, tempos e integridade, sem garantir veracidade de toda hipótese. Sem vídeo de referência anexado, não foi avaliada fidelidade a um estilo específico. Teste responsivo em Edge não equivale a teste em aparelho físico.
