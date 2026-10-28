# edicao-videos

Pipeline que edita sozinho os vídeos curtos (Reels) que o usuário grava no iPhone, substituindo a
edição semi-automática que ele fazia no app Edits (Meta). Visão geral e detalhes técnicos no README;
guia para quem usa no MANUAL-DE-USO.md (mantenha-o atualizado quando a instalação ou o uso mudarem).

## Decisões já tomadas (não reabrir sem o usuário pedir)

- Roda no computador do usuário, não na nuvem: Mac Mini Intel e MacBook M2.
- Entrada e saída pelo Fotos do iCloud: álbum "Para editar" (vídeo principal marcado como
  favorito + material de apoio) → álbum "Editados". Ainda não implementado.
- Transcrição local nos dois Macs: faster-whisper (Intel) e mlx-whisper (M2), escolha automática.
- Decisão de edição pelo Claude via assinatura (`claude -p` com `--json-schema`), sem chave de API.
  A API fica como opção em `config.toml`. Se o Claude falhar, o vídeo sai só com corte de silêncios.
- Só são cortadas as frases que o Claude manda remover; áudio não transcrito permanece.
- Zoom de 1,0 a 1,4 acompanhando os olhos, a 42% da altura (um pouco acima do centro);
  o zoom diminui se algum olho fosse sair da margem.
- Três modalidades de zoom, escolhidas pelo Claude por frase: seco (salto na emenda, natural
  depois de cortes), suave (cinematográfico, ao longo da frase) e rápido suavizado (0,4 s).
- Material de apoio: o Claude encaixa prints e imagens pelo conteúdo (marca falada opcional);
  depoimento em vídeo em tela dividida com o vídeo do autor congelado; desfoque de nomes e
  fotos de perfil ligado por padrão. Ainda não implementado.
- Legenda (26/10/2026): uma palavra por vez, na cor `cor_texto` (NICE: dourado da marca
  #C1A752, Poppins), com pop; destaques 25% maiores. Modo de blocos continua com
  `palavras_por_linha` > 1.
- Zoom no ritmo dos Reels (26/10): troca a cada corte e a cada ~3 s de fala contínua; o Claude
  dá zoom de ênfase na maioria das frases. Zoom máximo 1,4 também em 1080p (o usuário aceitou a
  perda de nitidez: "não limite o zoom"). Animação quadro a quadro em Python (OpenCV), não no ffmpeg.
- HDR mantido (26/10): saída HEVC 10 bits HLG quando o original é HDR. Qualidade SDR: CRF 17, slow.
- Elementos gráficos (26/10): título do Reels no início e cartões (número, frase, check, alerta)
  bem fluidos, no ASS quadro a quadro. Sem logo, sem barra de progresso e sem nome/titulação.
- O Claude também corrige termos mal transcritos (a legenda de uma palavra deixa erro à mostra).
- Postagem continua manual.
- Vídeos em 4K ou 1080p (o usuário vai gravar parte em 1080p para poupar espaço). HDR do iPhone
  (HLG, inclusive modo Cinema) é mantido (ver acima); com `hdr` diferente de "manter" no
  `config.toml`, é convertido para SDR BT.709.
- Roda em vários computadores, com contas diferentes do Claude (a do Claude Code logado em
  cada um) e sem depender de conta no GitHub para usar.
- Configuração em duas camadas: `config.toml` do programa (padrão, substituído ao atualizar) e
  `config.toml` do computador em `~/Library/Application Support/edicao-videos/` (`EDICAO_PASTA`
  sobrepõe; os testes usam isso). Identidade de marca na seção `[marca]`, via `edicao marca`:
  perguntas, leitura do manual pelo Claude (`claude_json` com a ferramenta Read) ou arquivo de
  fonte copiado para `fontes/`. Paleta guardada para o material de apoio.
- Repositório público, para instalar sem conta no GitHub. Instalação e atualização pela linha
  `/bin/bash -c "$(curl -fsSL .../main/instalar.command)"`: sem pasta do programa ao lado, o
  `instalar.command` baixa o tarball do main para `~/edicao-videos` (fora de Documentos/Mesa, por
  causa do iCloud), troca o código mantendo `.venv` e se executa de lá. Cria o app "Editar vídeo"
  na Mesa, no qual se arrastam os vídeos. Não pôr segredos nem dados pessoais no repositório.
- Mac Intel sem Homebrew (o instalador do Homebrew recusa Intel desde 2026): `bin/` do programa
  com `uv` (Python 3.12), link para o ffmpeg estático do pacote `imageio-ffmpeg` (tem libass e
  zimg; o evermeet.cx saiu do ar com erro 410) e `fonts.conf` para o fontconfig embutido; `cli._completar_path` põe `bin/` na frente do PATH e define `FONTCONFIG_FILE`.
  Apple Silicon continua com Homebrew; Intel que já tem Homebrew também.

## Próximos passos

1. Testar nos dois Macs (4K e 1080p, modo Cinema com HDR); relatar tempos e qualidade. Mac Mini
   Intel: instalado em 25/10/2026 pelo Termius (SSH via Tailscale), marca configurada com o manual
   da NICE (Google Drive da contato@); falta editar os vídeos de teste. O usuário prefere a conta
   lauro.al@ para as edições (Drive e/ou Claude; outra sessão está configurando o Mac Mini).
   MacBook M2: falta instalar.
2. Álbum do Fotos (osxphotos): ler "Para editar", importar o resultado em "Editados".
3. Material de apoio: encaixe pelo Claude, tela dividida, desfoque.
4. Inspiração em conta de referência (ideia em aberto, ver Pendências): perfil de estilo gerado a partir
   de vídeos de referência fornecidos pelo usuário, sem baixar das plataformas automaticamente.

## Pendências

A lista oficial é a database do Notion 📌 Pendências conhecidas (chaves `nota:edicao-video-*`).
Sessão com acesso ao Notion: atualize lá (marque Concluído e Concluída em). Sessão sem Notion
(a do Mac Mini): registre no Manual do Claude do Mac Mini (memória `pendencia-editor-videos`,
etapas "Lauro:/Claude:") e nesta seção; uma sessão com Notion repassa depois.
Abertas em 28/10/2026 (já no Notion):
- `nota:edicao-video-automatica`: teste em 4K com HDR real e modo Cinema; instalar no MacBook M2.
- `nota:edicao-video-microfone-lapela`: teste com microfone de lapela (tratamento de voz).
- `nota:edicao-video-album-fotos`: entrada e saída pelo álbum do Fotos (código).
- `nota:edicao-video-material-apoio`: material de apoio (código).
- `nota:edicao-video-inspiracao`: inspiração em conta de referência (decisão em aberto).
Registradas pela sessão do Mac Mini (sem Notion), a repassar:
- 28/10: IMG_4038 refeito com as correções de corte, sincronia e HDR (commit d42e8dd); aguarda a
  avaliação do usuário. Pedido em aberto da mesma conversa: usar esse vídeo (lapela) para a
  amostra de tratamento de voz mais leve (a anterior soou abafada).

## Cuidados técnicos

- Corte (desde 28/10/2026, IMG_4038 saiu com erros e repetições): o que fica é a fala das palavras
  mantidas (`plano.aplicar_decisao`), não o complemento dos silêncios. O detector de silêncio só
  dá o fim do vídeo; recortar a fala por ele cortava o começo de palavras ditas baixo (lapela a
  -28 LUFS). Whisper com `condition_on_previous_text=False`: com contexto ele pulava a tentativa
  repetida. Palavra > 1 s = fala não transcrita escondida; só o fim (0,45 s) vale, no corte e na
  legenda. `cortes_parciais` do Claude tiram a tentativa errada de dentro de uma frase.
- Sincronia: `plano.alinhar_quadros` leva os trechos à grade de quadros e cada pedaço de vídeo é
  forçado à duração exata (`fps`, `tpad`, `trim=duration`). Antes, cada emenda ganhava até um
  quadro, o concat completava o áudio, e a legenda (tempo planejado) se adiantava 0,4 s no fim.
- HDR: a camada de gráficos tem o alfa separado (`alphaextract`/`alphamerge`); o `zscale` com
  `r=tv` comprimia o alfa para a faixa limitada (véu preto de 6% no vídeo todo, gráficos 92%).

- `pyproject.toml`: `av>=14,<16` — PyAV 16+ quebra o faster-whisper 1.2.1 (`metadata_errors`).
- `render._zerar_rotacao`: o ffmpeg 7.1 copiava a rotação -90 do iPhone para a saída já girada
  (vídeo de lado); remux com `-display_rotation 0 -c copy` (e `-tag:v hvc1` no HEVC).
- O filtro `perspective` do ffmpeg (que faria zoom com fração de pixel) só trabalha em 8 bits e
  estragaria o HDR; por isso o zoom animado é feito no Python (`render.animar`).
- Gráficos: o libass alinha desenhos pelo contorno; `Camada.caixa` fixa o contorno com pontos
  minúsculos nos cantos. Eventos quadro a quadro têm bordas no meio entre quadros
  ((n ± ½)/fps), para o arredondamento em centésimos não repetir nem pular quadro.
- O tamanho de fonte do ASS é a altura "win" (ascendente + descendente): na Poppins o "em" é
  ~71% do tamanho. `graficos.largura_texto` mede com o arquivo da fonte (fontTools).

- O crop do ffmpeg guarda o tamanho do primeiro quadro (`in_w`/`in_h`); no zoom animado a
  posição do corte é calculada a partir da largura ampliada (ver `render._animacao`).
- Expressões de suavização entram sempre entre parênteses na fórmula do ffmpeg.
- Conversão HDR para SDR (`render._para_sdr`, só quando `hdr` não é "manter"): roda depois do corte e da escala, em 1080x1920; mobius
  com param 0,6 manteve tons médios e saturação num HLG simulado. Ainda não conferida em vídeo
  real do iPhone, nem o comportamento dos realces.
- Modo Cinema: falta confirmar se o desfoque de fundo vem aplicado no arquivo exportado
  (no álbum, exportar a versão renderizada, não o original com dados de profundidade).
- Fonte da legenda: o libass acha a fonte pela família (nameID 16/1) com negrito/itálico do
  estilo; o nome completo ("Inter Display Medium Italic") não foi reconhecido no teste. Por isso
  `marca.ler_fonte` grava família + `negrito` (peso ≥ 600) + `italico`.
- Sem ffprobe: duração, dimensões com rotação e curva HDR vêm do PyAV (`midia.py`), que já vem
  com o faster-whisper; o pacote imageio-ffmpeg só traz o ffmpeg. O instalador testa os filtros
  `subtitles` e `zscale` do ffmpeg e avisa se faltar.
- Testes: `.venv/bin/pytest`. O teste de zoom animado compara o primeiro e o último quadro com os
  enquadramentos esperados.
