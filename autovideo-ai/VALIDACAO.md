# Validação do AutoVideo AI

Windows, Python 3.13.17, GTX 1650 4 GB e 12 GB RAM. Execução em 16/11/2026.

## Resultados confirmados

- 62 testes automatizados passaram; `pip check` sem incompatibilidades e JavaScript passou em `node --check`.
- API, migrações com backup, fila, recuperação, controles, lotes atômicos, caminhos seguros, edição bilíngue, validação temporal, legendas, alinhamento de fonemas, animação, biblioteca e mixagem testados.
- Ollama real produziu ideias e roteiros PT/EN, medidos pelo Piper e corrigidos sem cortes. Relatório: `tests/artifacts/ai-generation-validation.json`.
- Vozes reais: pt_BR-faber-medium e en_US-ljspeech-high. Modelos e ferramentas locais instalados.
- NVENC codificou dois quadros reais de 1080×1920 nesta GPU. Seleção automática conserva fallback CPU.
- Edge passou em 13 verificações e seis larguras, de 320 a 1440 px, sem erros JavaScript, rolagem horizontal ou colisões nos componentes verificados. Inclui teclado, foco, editor, fila, importação/exclusão de imagem e configurações persistidas.
- Player reproduziu os MP4 reais PT e EN anteriores à etapa 6: 80 segundos e 1080×1920. Relatório: `tests/artifacts/browser-report.json`.

## Aceitação final em andamento

`scripts/validate_full.py --automatic --count 2` cria duas histórias com ideias e roteiros gerados localmente, produzindo quatro vídeos com música/efeitos e seleção automática de encoder. O estado persiste em `tests/artifacts/full-validation-state.json`; `--resume` recupera trabalhos em vez de recriá-los.

A primeira execução recusou roteiros repetitivos do modelo. A recuperação passou a tentar JSON simples e geração por cena; essa falha não foi ocultada nem substituída por conteúdo simulado. Consulte `PROGRESS.md` para a execução ativa.

Os arquivos de `output/acceptance/` e `tests/artifacts/full-validation.json` só devem ser apresentados como validação da versão final depois de atualizados pela execução atual.

## Verificações dos MP4

Cada vídeo só é publicado quando FFprobe confirma 80,000 segundos no contêiner/vídeo, 2400 quadros, 30/1 fps, 1080×1920, H.264, AAC e faixa mov_text. O idioma de áudio é por/eng conforme roteiro e voz. Há destaque de palavras queimado e SRT. Todos os quadros e o áudio são decodificados com FFmpeg antes de liberar download; a API testa Range 206.

## Limites

A voz foi sintetizada e os tempos medidos, sem avaliação humana externa de naturalidade. Idioma é validado por roteiro/voz e marcação, sem classificador independente. O modelo pequeno precisa de revisão científica/editorial. Não houve referência visual anexada, teste em telefone físico ou publicação pública. A memória é monitorada, sem cota rígida do Windows. O aviso de depreciação TestClient/httpx não causa falha; o gate anterior para páginas de marketing não é apresentado como aprovado.
