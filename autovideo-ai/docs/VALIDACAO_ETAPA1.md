# Registro da validação da etapa 1

Executada no Windows do projeto, em 16/11/2026.

- Python 3.13.17; dependências instaladas em `.venv`, sem alterar os pacotes globais.
- `python -m pytest -q`: **25 testes aprovados**. Um aviso de depreciação do TestClient do Starlette informa a futura substituição de httpx por httpx2; não houve falhas.
- `python scripts/browser_check.py`: fluxo real aprovado no Microsoft Edge, com servidor e banco temporários, separados dos dados do usuário. O script encerra seu servidor ao finalizar.
- Navegador: criação, preparação por worker, detalhes/histórico, Escape para fechar diálogo, rejeição de duplicatas, texto longo e HTML tratados como texto, cancelamento, filtros, persistência das configurações após recarga e erro de conexão visível.
- Layout verificado em 1440×900, 1024×768, 820×1180, 768×1024, 390×844 e 320×800. Sem rolagem horizontal ou colisão de texto nos componentes inspecionados. Nenhum erro JavaScript de execução.
- `python -m pip check`: nenhuma dependência incompatível.
- `node --check frontend/app.js`: JavaScript válido.
- Verificação de texto do design: zero falhas. O aviso sobre uma sequência numérica foi mantido porque os números identificam as etapas especificadas no projeto.

O gate de composição da habilidade design-taste-frontend também foi executado. Ele **não aprovou** esta interface: exige navegação horizontal, imagens ou demonstrações em cada seção, efeitos e seções com altura de uma tela. Esses requisitos de página de apresentação não foram aplicados ao painel funcional solicitado. Seus alertas úteis de foco e composição móvel foram investigados: o deslocamento suave que atrasava a visibilidade do foco foi removido; o campo de tema foi compactado no celular. O aplicativo passou pelos testes funcionais e responsivos acima; isso não equivale à aprovação desse gate de marketing.

O relatório reproduzível do navegador e as capturas são gravados em `tests/artifacts/`. A verificação em larguras móveis usa emulação do Edge; não representa um teste em aparelho físico.

O teste de reinício preserva o banco, deixa uma preparação interrompida e abre uma nova instância com worker ativo. O projeto é recuperado e chega a `awaiting_renderer`. O teste de falha de escrita injeta `PermissionError`, verifica erro persistido e retoma com sucesso. O teste concorrente executa múltiplas reivindicações e confirma que cada trabalho é obtido uma única vez. Os testes verificam também as oito tabelas do esquema e a exclusividade de acesso por servidor.

Nenhum vídeo foi produzido, nenhuma voz ou modelo foi instalado, e não foram executados testes de duração/áudio/legendas. Essas verificações pertencem às próximas etapas. A GPU foi identificada com `nvidia-smi`; CUDA e inferência não foram validados.
