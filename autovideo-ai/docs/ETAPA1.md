# Registro da entrega da etapa 1

Documentação histórica. Para a versão atual, consulte o README.md na raiz do projeto.

Estúdio local para organizar a produção de vídeos curtos. **Etapa 1 implementada:** FastAPI, SQLite com SQLAlchemy, interface em português e worker de preparação de projetos. Funciona sem API comercial, conta externa ou GPU.

## Abrir no Windows

Requisito: **Python 3.13 de 64 bits**, com o launcher `py` (já encontrado neste computador).

1. Abra a pasta `autovideo-ai` no VS Code.
2. Dê dois cliques em `start.bat` ou execute `.\start.bat` no PowerShell.
3. Na primeira execução, o script instala os pacotes gratuitos no ambiente `.venv`. É necessário acesso à internet para instalar dependências.
4. O navegador abre em **http://127.0.0.1:8000**. Mantenha o terminal aberto.
5. Informe um tema e clique em **Adicionar à fila**. O worker prepara o projeto automaticamente.

Para encerrar, pressione `Ctrl+C`. Nas próximas execuções, dependências já instaladas são reaproveitadas. Se necessário, instale Python em https://www.python.org/downloads/windows/ e marque o launcher `py` no instalador.

Instalação manual no terminal PowerShell, a partir da pasta do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run.py
```

Não é necessário ativar o ambiente virtual nem alterar a política de execução do PowerShell. Se a porta 8000 estiver ocupada, encerre a outra instância. Para usar outra porta manualmente:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --workers 1
```

Nesse caso, abra http://127.0.0.1:8001 no navegador. Execute sempre **um processo servidor**; a trava da pasta de dados impede duas instâncias de assumirem o mesmo banco. Não use `--workers 2`.

## O que funciona agora

- Criação e listagem de projetos, com paginação e filtro por estado.
- Temas salvos no SQLite; duplicatas com variações de maiúsculas, acentos, espaços e pontuação são recusadas, inclusive após cancelamento. Similaridade semântica depende da etapa 4.
- Fila FIFO persistente, processada por um único worker local.
- Preparação real: grava `output/<story_id>/project.json` na pasta de dados, com tema, identificadores e especificações finais previstas.
- Pausa e retomada da preparação, cancelamento e histórico de eventos persistidos.
- Recuperação de trabalhos interrompidos durante a preparação, preservando pausas e cancelamentos.
- Erros de preparação registrados no banco e no log; um trabalho com erro pode ser retomado.
- Configurações da fila persistidas e diagnóstico de RAM, Python, banco e dependências.
- Documentação OpenAPI em `/docs`, `/redoc` e `/openapi.json`.

A preparação é curta. Normalmente você verá diretamente **Aguardando etapa 2**; pausar só se aplica aos estados Na fila e Preparando. Um projeto preparado pode ser cancelado. O cancelamento preserva o histórico e o JSON já criado. Não há exclusão automática de projetos.

**Esta etapa não gera roteiros, narração, legendas, animações, MP4, prévias, downloads ou lotes.** A interface não simula essas saídas. `progress` permanece em zero porque nenhuma renderização foi iniciada; `preparation_complete` e o estado da fila informam o trabalho realmente executado. Os roteiros e as cenas do manifesto ficam vazios.

As especificações no JSON são um contrato futuro: 80 segundos, 30 fps, 2400 quadros, 1080 × 1920, H.264/AAC e idiomas PT/EN. Não significam que um arquivo tenha sido renderizado ou validado com FFprobe.

## Dados e configurações

Por padrão, os dados são gravados em **`%LOCALAPPDATA%\AutoVideoAI`**, fora do OneDrive. Isso evita sincronizar arquivos SQLite enquanto estão em uso. A interface mostra o caminho exato em Configurações → Ver pasta de dados.

```text
%LOCALAPPDATA%/AutoVideoAI/
  database/autovideo.sqlite3
  database/server.lock
  output/<story_id>/project.json
  temp/
  logs/autovideo.log
```

Os logs têm rotação em 2 MB, com três cópias. A trava é liberada pelo sistema operacional quando o processo encerra, mesmo após uma queda; o arquivo `server.lock` pode permanecer sem indicar um servidor ativo. Temporários próprios incompletos são removidos na recuperação. Os diretórios `output/` e `temp/` do código são reservados; os dados reais usam a pasta acima.

Para alterar a pasta de dados, copie `.env.example` para `.env`, configure `AUTOVIDEO_DATA_DIR` e reinicie o servidor. A mudança seleciona outro banco e não move os dados existentes. `AUTOVIDEO_WORKER_ENABLED=false` permite manter a fila parada, por exemplo para testar pausa e retomada; retorne para `true` e reinicie para processar.

Configurações da API:

```json
{"worker_poll_seconds": 1.0, "max_concurrent_jobs": 1}
```

O intervalo aceita 0,2 a 10 segundos e entra em vigor no próximo ciclo do worker. A concorrência nesta etapa é fixada em 1. Limites de CPU/memória do futuro renderizador serão adicionados junto com esse componente; não há controle de renderização fictício nesta versão.

Para backup, encerre o servidor e copie a pasta de dados inteira. O SQLite usa WAL: não copie apenas o arquivo principal com a aplicação aberta. Não coloque o banco em unidade de rede. Atualizações futuras do esquema precisarão de migrações; `create_all` nesta etapa cria bancos novos, não altera tabelas existentes.

## API

| Método e rota | Comportamento nesta etapa |
| --- | --- |
| `POST /api/videos` | Recebe `{"topic":"E se o Sol desaparecesse?"}` e retorna 202 com o trabalho |
| `GET /api/videos` | Lista trabalhos; parâmetros `limit`, `offset`, `status` |
| `GET /api/videos/{id}` | Consulta trabalho e histórico |
| `POST /api/videos/{id}/pause` | Pausa preparação pendente ou em andamento |
| `POST /api/videos/{id}/resume` | Retoma um trabalho pausado ou com erro |
| `POST /api/videos/{id}/cancel` | Cancela trabalho ainda não cancelado |
| `GET /api/videos/{id}/download/{PT\|EN}` | Retorna 409: arquivo ainda não existe |
| `POST /api/videos/batch` | Retorna 501: etapa 5 |
| `POST /api/topics/generate` | Retorna 501: etapa 4 |
| `GET /api/settings` | Configurações, contrato do vídeo e pasta de dados |
| `PUT /api/settings` | Atualiza configurações da fila |
| `GET /api/health` | Estado real dos componentes e dependências encontradas no PATH |

Os identificadores das rotas são os IDs dos **trabalhos**, retornados na criação. Há um `story_id` separado no mesmo objeto. Erros de validação retornam 422; tema repetido ou transição incompatível, 409; ID desconhecido, 404. Envie JSON com `Content-Type: application/json`.

O servidor fica vinculado ao loopback e bloqueia hosts externos e mutações originadas de outra página. Não há autenticação multiusuário nem suporte a publicação pública nesta etapa. Tópicos são tratados como texto, nunca como caminhos ou comandos. Pastas de dados e logs não são servidas por HTTP. A interface e os arquivos estáticos funcionam sem CDN; os visualizadores Swagger/ReDoc padrão usam CDN e precisam de internet para carregar seus componentes.

## Diagnóstico deste computador

Verificado em 16/11/2026:

| Componente | Encontrado |
| --- | --- |
| Sistema | Windows 11 Home Single Language, 64 bits |
| Python | 3.13.17 |
| CPU | Intel Core i5-11300H, 4 núcleos / 8 threads |
| RAM | Aproximadamente 11,79 GiB utilizáveis (12 GB nominais) |
| RAM livre na verificação inicial | Aproximadamente 1 GiB, variável conforme os programas abertos |
| GPU dedicada | NVIDIA GeForce GTX 1650, 4096 MiB de VRAM |
| GPU integrada | Intel Iris Xe |
| FFmpeg / FFprobe / Ollama / Piper | Não encontrados no PATH |

Interface, SQLite e fila podem funcionar nesse equipamento. Renderização SVG/FFmpeg e voz local são candidatas para CPU na etapa 2, com um vídeo por vez; o desempenho precisa ser medido com a implementação real. A RAM livre atual é pequena para carregar modelos locais. Um modelo de linguagem pequeno e quantizado pode ser avaliado na etapa 4 após liberar memória. ComfyUI não é necessário e não foi instalado. Compatibilidade CUDA, modelo e velocidade da GPU ainda não foram validados; a etapa 1 não precisa de CUDA.

Execute novamente o diagnóstico quando necessário:

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
```

Dependências futuras, todas com caminhos gratuitos de instalação:

- **FFmpeg e FFprobe:** obtenha um build Windows indicado em https://ffmpeg.org/download.html#build-windows e adicione sua pasta `bin` ao PATH. Abra outro terminal e execute `ffmpeg -version` e `ffprobe -version`.
- **Ollama:** instalador Windows em https://ollama.com/download/windows. O modelo local será escolhido e integrado na etapa 4; não é necessário baixar agora.
- **Piper:** o mecanismo de voz local será integrado na etapa 2. Consulte https://github.com/OHF-Voice/piper1-gpl e verifique os requisitos da versão e a licença de cada voz PT-BR/EN antes de baixar. Não é necessário para iniciar esta versão.
- **faster-whisper:** alinhamento/transcrição será avaliado junto com a etapa de legendas, sem instalação obrigatória agora.

Não foram baixados modelos de IA ou pacotes de mídia grandes para a etapa 1. O diagnóstico detecta executáveis no PATH; ele não comprova que modelos ou vozes tenham sido instalados nem que um serviço Ollama esteja ativo.

## Verificações

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\browser_check.py
```

Os testes da API e fila usam diretórios temporários separados dos seus dados. Cobrem duplicação de temas, validação, estados, reivindicação concorrente sem trabalho duplicado, escrita real de JSON, falha de disco, pausa/cancelamento antes do processamento, retomada após reinício, trava exclusiva, persistência e proteção de arquivos. A verificação de navegador usa o Microsoft Edge instalado, inicia um servidor isolado e testa criação, detalhes, duplicação, filtros, configurações e larguras de 320 a 1440 pixels. Capturas ficam em `tests/artifacts/`.

Nenhum teste desta etapa afirma duração, integridade, áudio ou legendas de um vídeo inexistente. Esses critérios entram nas etapas de mídia.

## Estrutura e próximas etapas

```text
backend/    FastAPI, configuração, ciclo de vida e proteção local
frontend/   HTML, CSS e JavaScript sem build ou CDN
services/   Fila, worker, diagnóstico e trava de processo
models/     Oito tabelas SQLAlchemy e contratos Pydantic
database/   Conexões SQLite, WAL e transações curtas
animation/  Ponto de integração futuro, sem renderizador nesta etapa
assets/     Recursos visuais futuros
output/     Reservado; dados reais fora do OneDrive
temp/       Reservado; temporários reais fora do OneDrive
tests/      Testes automatizados e capturas de validação
scripts/    Inicialização, diagnóstico e verificação no navegador
```

Etapa 2: SVG animado, voz local, legendas e validação real de 80 segundos. Etapa 3: versões PT/EN. Etapa 4: Ollama e roteiros. Etapa 5: lotes. Etapa 6: biblioteca visual e efeitos. Etapa 7: validação completa e vídeos de demonstração. O avanço depende da validação da etapa anterior.
