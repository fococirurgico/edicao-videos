# edicao-videos

Pipeline que edita sozinho os vídeos curtos (Reels) que o usuário grava no iPhone, substituindo a
edição semi-automática que ele fazia no app Edits (Meta). Visão geral e detalhes técnicos no README;
guia para quem usa no MANUAL-DE-USO.md (mantenha-o atualizado quando a instalação ou o uso mudarem).

## Decisões já tomadas (não reabrir sem o usuário pedir)

- Roda no computador do usuário, não na nuvem: Mac Mini Intel e MacBook M2.
- Entrada e saída pelo Fotos do iCloud. Saída pronta (28/10/2026): `--album` ou `[saida] album`
  importa o editado pelo AppleScript do Fotos (`edicao/fotos.py`); no Mac Mini o álbum é
  "Vídeos editados", ao lado do "Vídeos para editar" que o usuário já tinha. O controle do Fotos
  foi autorizado na tela do Mac Mini em 28/10. Entrada pelo álbum (vídeo principal marcado como
  favorito + material de apoio) ainda não implementada; o original pode estar só na nuvem
  (biblioteca otimizada), então a leitura precisa baixá-lo (osxphotos).
- Transcrição local nos dois Macs: faster-whisper (Intel) e mlx-whisper (M2), escolha automática.
- Decisão de edição pelo Claude via assinatura (`claude -p` com `--json-schema`), sem chave de API.
  A API fica como opção em `config.toml`. Se o Claude falhar, o vídeo sai só com corte de silêncios.
- Fica no vídeo só a fala das palavras que o Claude manteve (28/10/2026, muda a regra antiga
  "áudio não transcrito permanece"): com a regra antiga, as tentativas erradas que o Whisper
  pulava ficavam no vídeo. Na dúvida sobre uma frase, o Claude mantém; fala não transcrita sai.
- Tomada escondida (06/11/2026, IMG_4521): o modelo small às vezes engole a tentativa abandonada
  esticando UMA palavra ("foi" com 3 s); sem as palavras, o Claude não via a repetição e a edição
  emendava a tomada errada na certa. Palavra acima de `limite_palavra_longa` (1,5 s) faz o trecho
  em volta (4 s antes, 1 s depois) ser retranscrito com `modelo_revisao` (large-v3), só ali:
  ~15 s a mais no M2. Fala normal não passa de ~1,4 s.
- Zoom de 1,0 a 1,4 acompanhando os olhos, a 42% da altura (um pouco acima do centro);
  o zoom diminui se algum olho fosse sair da margem.
- Três modalidades de zoom, escolhidas pelo Claude por frase: seco (salto na emenda, natural
  depois de cortes), suave (cinematográfico, ao longo da frase) e rápido suavizado (0,4 s).
- Material de apoio: o Claude encaixa prints e imagens pelo conteúdo (marca falada opcional);
  depoimento em vídeo em tela dividida com o vídeo do autor congelado; desfoque de nomes e
  fotos de perfil ligado por padrão. Imagens implementadas em 06/11/2026 (`--apoio`,
  `edicao/apoio.py`): o print da dúvida de seguidor é o gancho e abre o vídeo no lugar do título;
  o desfoque é pelo Vision do macOS (OCR + rostos em blocos), não por caixas do modelo. Depoimento
  em vídeo e entrada automática pelo álbum ainda não.
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
- Caixinha de pergunta do Instagram no início (`--pergunta "..."`, 28/10), no lugar do título:
  preto e branco, só texto ("Faça uma pergunta" + a pergunta digitada letra a letra). A versão
  com avatar e cores da marca foi recusada pelo usuário. Fonte do Instagram, não a da marca (pedido de 28/10):
  `[graficos] fonte_pergunta`, padrão "Helvetica Neue". A San Francisco do sistema (".SF NS") o
  libass não acha (o CoreText devolve Times); com a SF Pro instalada a partir do pacote oficial da
  Apple, "SF Pro Display" funciona. Os dois Macs usam assim desde 29/10, na config do computador
  (fontes extraídas do pkg assinado com `pkgutil --expand-full` para ~/Library/Fonts, sem senha).
  Um Mac novo sem a SF Pro volta à Helvetica Neue. A quebra de linha mede com a fonte da
  caixinha (`graficos.arquivo_sistema`).
  Em HDR a caixinha é uma camada à parte com o branco a `[graficos] nits_pergunta` (600 nits,
  sinal HLG 0,92): com o branco de referência (203 nits, 0,75), o da legenda e dos cartões, ela
  saiu cinza no iPhone, quase do tom da parede (IMG_4038 postado assim, 28/10).
  Legenda e cartões em HDR: branco a `[graficos] nits_graficos` = 400 (05/11, escolha do usuário).
  Com 203 o creme (Y10 692) e o dourado (574) ficavam abaixo das partes claras da cena (780–826 no
  IMG_2764) e pareciam apagados; com 400, 788 e 678. Custo: o marinho clareia (296 → 372) e, numa
  tela comum, as cores saem um pouco mais claras que as da marca. `render.renderizar` mantém 203
  como padrão (testes de cor da marca); quem passa 400 é o `cli`.
- Áudio (28/10): tratamento de voz ligado por padrão (`[audio] tratamento = "voz"`,
  `render.tratamento_voz`), a amostra "C" escolhida pelo usuário com o vídeo de lapela:
  `highpass 70, afftdn nr=10 nf=-50, +2 dB em 4 kHz, acompressor 2:1 a -24 dB, loudnorm -14 LUFS`.
  Rejeitada antes por soar abafada: `afftdn nr=40` + deesser + corte de 2 dB em 250 Hz.
  `tratamento = "nenhum"` volta ao ganho fixo com limitador.
- Fluxo de teste atual (28/10): o usuário põe o vídeo em Meu Drive/Vídeos (conta lauro.al@); o
  editado vai para o álbum "Vídeos editados" do Fotos (o usuário achou o iCloud mais prático que
  o Drive) e também para Meu Drive/Vídeos/Vídeos Editados. Processamento em ~/edicao-teste.
- Rosto "partido" no celular (28/10): era um QUARTO da imagem (bordas na metade da largura e da
  altura) repetido do quadro anterior por alguns quadros. Causa: o arquivo temporário do zoom
  animado em FFV1 level 3 (4 fatias); de vez em quando uma fatia saía corrompida (aviso
  `bytestream end mismatching`) e o decodificador repetia o pedaço anterior. Não é falha
  determinística: arquivos refeitos isoladamente decodificavam sem erro. Agora FFV1 level 1 (sem
  fatias) e cada temporário é conferido com `-err_detect explode` antes do uso; a ferramenta de
  conferência procura quartos congelados. O GOP fechado no x265 (`open-gop=0`) ficou por segurança.
- Cartões no momento da fala (28/10): o usuário notou cartões desconectados do que estava sendo
  dito. Eles entravam no começo da frase (frases de até 10 s; uma caía na tentativa cortada). O
  Claude agora dá a `ancora` (palavras exatas em que o assunto é dito) e o cartão entra 0,15 s
  antes delas; se o anterior o atrasaria mais de 1 s, ele não aparece.
- Silêncio no começo das frases (28/10): o Whisper marca o início da 1ª palavra até 0,8 s antes;
  `plano.aparar_silencio` apara as bordas dos cortes pelo volume do áudio (25 dB abaixo da fala,
  nunca abaixo do ruído de fundo + 6 dB).
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
- ffmpeg em todos os Macs: link em `bin/` do programa para o ffmpeg estático 7.1 do pacote
  `imageio-ffmpeg` (tem libass e zimg; o evermeet.cx saiu do ar com erro 410), mais `fonts.conf`
  para o fontconfig embutido; `cli._completar_path` põe `bin/` na frente do PATH e define
  `FONTCONFIG_FILE`. Desde 28/10/2026 vale também para o Apple Silicon: o ffmpeg 9 do Homebrew
  veio sem libass e sem zscale (instalação no MacBook M2 saía sem legenda). Uma versão só nos dois
  Macs também evita diferenças de comportamento entre versões do ffmpeg.
- Python: Homebrew (`python@3.12`) no Apple Silicon e no Intel que já tem Homebrew; Mac Intel sem
  Homebrew (o instalador do Homebrew recusa Intel desde 2026) usa `uv` em `bin/`.

## Próximos passos

1. Testar nos dois Macs (4K e 1080p, modo Cinema com HDR); relatar tempos e qualidade. Mac Mini
   Intel: instalado em 25/10/2026; testado com IMG_3878 (iPhone, 1080p SDR, aprovado na 0.7),
   dois vídeos de Samsung e IMG_4038 (iPhone HLG + Dolby Vision, lapela, 28/10). Falta 4K.
   O usuário prefere a conta lauro.al@ para as edições. MacBook M2: falta instalar.
2. Álbum do Fotos (osxphotos): ler "Para editar", importar o resultado em "Editados".
3. Material de apoio: imagens feitas (06/11); falta depoimento em vídeo em tela dividida.
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
- 28/10: IMG_4038: o usuário achou a edição "muito melhor" e apontou, em duas rodadas, quadros
  com o rosto "partido" (FFV1 em fatias), pausa longa no começo das frases (`aparar_silencio`) e
  cartões fora do momento da fala (`ancora`). Versão com tudo corrigido e voz C em renderização
  no fim do dia 28/10; aguarda avaliação. No álbum "Vídeos editados" ficaram versões anteriores do
  mesmo vídeo: o usuário apaga (o Claude não apaga itens do Fotos).
- 28/10: `nota:edicao-video-album-fotos` andou: a SAÍDA no álbum do Fotos está pronta e ligada no
  Mac Mini (álbum "Vídeos editados"). Falta a ENTRADA pelo álbum "Vídeos para editar".
- 28/10: `nota:edicao-video-microfone-lapela` CONCLUÍDA: o usuário escolheu a amostra C, que
  virou o padrão (ver Decisões).

- Lixo colorido em rajadas de ~0,3 s (28/10, IMG_4038 no modo Cinema): o bicúbico do zoom animado
  passava de 1023 junto do reflexo nos óculos e o FFV1 de 10 bits transbordava. `animar` limita a
  1023. Conferir rajadas com a energia de bordas quadro a quadro (o ffmpeg decodifica sem erro).
- Memória (28/10): cada pedaço de vídeo é uma entrada própria com `-ss`; com todos em `[0:v]` o
  ffmpeg chegou a 13 GB e travou o MacBook de 8 GB.

## Fluxo sem retrabalho (09/11/2026, pedido do usuário)

Cada ajuste depois do render final custava ~10 min (vídeo de 1:16 em HDR no M2), e quase todo o
retrabalho vinha de erro de corte que só aparecia no vídeo pronto. O fluxo agora é:
1. `edicao planejar VIDEO [--apoio ...] [--pergunta ...]`: transcreve, decide, encaixa as imagens,
   confere os cortes (`edicao/checagem.py`) e mostra o plano (frases ✔/✘ com o tempo no editado,
   cartões, correções). Nada é renderizado. Mostre o plano e as suspeitas ao usuário e ajuste o
   `*.decisao.json` antes de seguir.
2. `edicao processar VIDEO --previa`: 540x960, zoom parado no enquadramento final, áudio sem
   tratamento, HEVC pelo chip (HDR mantido: a conversão para SDR deixava a pele alaranjada); vai
   para `[saida] album_previas` ("Prévias" nos dois Macs). ~45 s para 50 s de vídeo.
3. `edicao processar VIDEO`: o final, com tudo. Sem render de novo para cada ajuste.
O processar e o planejar reaproveitam a transcrição, a decisão e o encaixe salvos com o nome do
vídeo final (`*_editado.transcricao.json` etc.); `--refazer` decide de novo. A decisão só é
reaproveitada junto com a transcrição dela. Os olhos ficam em `VIDEO.olhos.json`.
A checagem avisa: voz sem palavra (tomada refeita que o Whisper engoliu sem esticar palavra,
IMG_4539 em 1:57; a suspeita é retranscrita sozinha, e isolada a 2ª tentativa aparece), palavra
cortada (borda de corte dentro de palavra ou com voz depois) e palavra longa demais.

## Como conferir uma edição (antes de entregar)

Em 28/10 o usuário achou, assistindo no celular, três defeitos que as conferências da época não
pegaram (legenda adiantada, quarto da imagem congelado, cartões fora de hora). Cada um virou uma
verificação da ferramenta abaixo ou uma regra do código; ao achar um defeito novo, faça o mesmo.

Olhar quadros soltos não basta: o IMG_4038 (28/10) parecia certo numa grade de quadros e saiu com
legenda adiantada, tentativas erradas no meio e véu escuro no HDR. Antes de entregar:
- `ferramentas/conferir_edicao.py ORIGINAL EDITADO`: durações (plano = vídeo = áudio), volume,
  texto que ficou (procure repetições e "não, não"), cortes e desvio do áudio em relação ao plano.
- Ler a decisão (`*.decisao.json`): `manter`, `cortes_parciais` e `correcoes`. A decisão do Claude
  varia de uma rodada para outra; depois de revisada, refaça só o vídeo com `--decisao-json` (e
  `--transcricao-json`), sem pedir de novo.
- Quadros de HDR para olhar em SDR: `zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,
  tonemap=mobius:param=0.6,zscale=t=bt709:m=bt709:r=tv,format=yuv420p`.
- Qualidade: VMAF contra o original. O iPhone grava em taxa variável; para parear os quadros,
  codifique com `-fps_mode passthrough` e use `setpts=N/30/TB` nos dois lados (sem isso a nota sai
  defasada; o próprio original sem perda dava PSNR 33). IMG_3878: antiga 5,2 Mbps VMAF 96,2;
  CRF 17 slow 7,8 Mbps VMAF 97,8. A perda de nitidez que o usuário notou vem do zoom em 1080p.
- Testes com tolerância larga escondem defeito: o de HDR aceitava 14 níveis e deixou passar o
  véu (9 níveis). Compare com o original, não com um valor absoluto.

## O que já se viu nos vídeos do usuário

- iPhone selfie: os olhos ocupam ~22% da largura do quadro (IMG_3878, IMG_4038); os cartões no
  alto encostam no cabelo e a legenda dourada perde contraste sobre roupa clara (terno azul-claro,
  camisa branca). Possíveis ajustes, ainda não pedidos: cartões menores, contorno mais grosso ou
  faixa escura atrás da palavra.
- iPhone HDR (IMG_4038): HLG com Dolby Vision perfil 8.4. A saída é HLG puro (o RPU do Dolby
  Vision se perde), então no iPhone o original pode parecer um pouco mais brilhante.
- Lapela (IMG_4038): gravou a -28 LUFS; por isso o volume final passou a ser normalizado.
- Samsung (Android, 27/10): 1080x2336 (19,5:9), SDR, HEVC, pessoa longe e pequena no quadro, eco
  de sala; o fundo (-35 a -41 dB) fica acima do limiar de silêncio (-35 dB) e nenhum silêncio é
  detectado. O corte pelas palavras (28/10) não depende disso.
- libx265 com CRF 18 deu só 2,8 Mbps em 1080x1920 HLG (original 13,5 Mbps); CRF 15 dá ~4,6 Mbps.
- Tempo no Mac Mini 2011: ~6 min para 30 s em SDR; ~30 min para 80 s em HDR com 17 trechos
  animados.
- Fotos por AppleScript: na primeira chamada o `osascript` fica parado, sem erro nem saída,
  esperando a aprovação na tela do Mac (Privacidade › Automação); por SSH não dá para aprovar.
  No Mac Mini não há `timeout`: use `perl -e 'alarm 40; exec @ARGV' osascript ...`. A biblioteca
  do Mac Mini é a do iCloud do usuário (~15 mil itens, álbuns "Vídeos para editar" e "Reels").
  Há álbuns com nome repetido; o editor procura e cria o álbum pelo nome exato.
- Taxa de quadros da saída (28/10): a saída do concat tem base de tempo de 1 µs; sem `-r`, o
  x264/x265 deduziam uma taxa absurda (nível 6.2, recusado pelo iPhone) e, com o nível fixo, o x265
  recusava abrir ("frame rate is out of range for specified level"). `_codificacao` passa o fps ao x265. Os
  testes sintéticos (taxa fixa, base 1/30) não reproduziam: teste com trechos do vídeo real.
- `afftdn` atrasa o som em 1200 amostras a 48 kHz (25 ms); `tratamento_voz` compensa (corta o
  início e completa o fim). Medir atraso de filtro com impulso, não com correlação contra o
  original cru (a compressão e a redução de ruído deixam a correlação ambígua em trechos quietos).
- Avisos inofensivos: `ffv1 ... bytestream end mismatching` ao ler os trechos animados e
  `non monotonically increasing dts` do muxer null ao decodificar a saída.

- 09/11 (IMG_4539 caixinha + print da ATA; IMG_4544 comentário de seguidora):
  - Tomada refeita escondida SEM palavra esticada: o small (vídeo inteiro) e o large-v3 juntaram
    as duas tentativas numa frase com os tempos da 1ª; a 2ª ficou como 3 s de voz sem palavra e o
    editor manteve a abandonada. Isolado (só o trecho), o small separou as duas. Hoje a checagem
    acusa "voz sem palavra"; a correção ainda é à mão (palavras da 2ª tentativa na transcrição e
    `manter` trocado na decisão).
  - Avatar em desenho (não foto) não é achado pelo Vision: desfocar à mão no print antes de
    editar. O usuário quer nome de usuário E foto de perfil desfocados.
  - Print atrás da pessoa (pedido do usuário, gostou): o print no quadrante superior direito,
    coberto em parte pela cabeça, até o fim da explicação. Feito fora do editor: render A (sem o
    cartão) e B (com o cartão), máscara de pessoa do Vision quadro a quadro
    (`VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)`; `init()` é
    NS_UNAVAILABLE) sobre quadros tonemapeados, e `alphamerge` de A sobre B só na janela, com o
    encoder de `_codificacao`. Ainda não é opção do editor.
  - Ele fala pausado: cortar silêncios leva 2:18 a 1:16 sem perder conteúdo; não é erro.
  - Mantém a posição padrão da caixinha e o zoom dinâmico padrão (pediu para não mexer).

- 11/11 (IMG_4555 caixinha + print da OPAS; IMG_4557 título + print do ENT Today):
  - Grade do perfil do Instagram: mostra o recorte 3:4 do meio do vídeo 9:16 (y 240 a 1680 em
    1080x1920). O título e a caixinha agora descem o necessário para caber inteiros nele
    (`graficos.dentro_da_grade`, `margem_grade = 40`), o título passou a 130 e quebra em linhas
    equilibradas (`quebrar_equilibrado`: "Tirei a tireoide / de um menino", não uma palavra solta
    na 2ª linha). A capa do Reels é um quadro com o título/caixinha já completos (a caixinha vai
    sendo digitada: escolher depois de ~3,5 s).
  - Correção que alonga palavra cortava o começo: "com de mais úsculo" → "com D maiúsculo" deu
    1,01 s a "maiúsculo", e a regra da palavra longa (só os últimos 0,45 s valem) cortou "D mai".
    Agora a substituta só é tratada como longa se o trecho original tinha palavra longa
    (`Palavra.longa`, `plano._e_longa`; teste `test_correcao_que_alonga_palavra_nao_corta_o_comeco`).
    Também: correção que já traz pontuação não ganha a da original ("CONVENCIONAL,.").
  - O encaixe do Claude trocou os dois prints entre os vídeos (cada vídeo recebeu os dois);
    conferir e editar o `*.apoio.json` à mão quando houver prints de vídeos diferentes no álbum.
  - Corte parcial errado: o Claude cortou "não é o mais convencional" como tentativa repetida, mas
    era aposto ("um câncer que não é o mais convencional, não é o mais comum"). Começo abandonado
    antes de pausa longa ("por a doença" + 10 s) passou: virou corte parcial à mão. Ler os
    `cortes_parciais` no plano procurando os dois casos.
  - Print atrás + pessoa deslocada para o lado (pedido do usuário): na janela do print, o
    enquadramento leva os olhos para ~0,37 da largura (`rosto.enquadrar` e `plano.alinhar_quadros`
    remendados no script do render A/B, dividindo o trecho no início do print). Limite: zoom máximo
    1,35. Com 1,6 ele fica maior e a cabeça cobre o print do mesmo jeito. Quando ele grava à direita
    do centro (IMG_4557), o deslocamento é pequeno (olhos em ~0,46); a solução é gravar um pouco à
    esquerda. Ainda não é opção do editor (junto com o print atrás, candidata a `--apoio-atras`).
- 12/11 (IMG_4563, vídeo do Foco Cirúrgico, outra marca): estilo pedido e aprovado, diferente dos
  Reels do consultório. Configuração à parte usada com `edicao --config foco.toml` (mesclada por
  cima da do computador): só legenda, no azul do manual (#283F51), contorno branco de 2 px, sem
  sombra, uma palavra por vez, SF Pro Display Regular (negrito=false), tamanho 92 e
  `[legendas] maiusculas = false` (opção nova; o padrão continua em maiúsculas); sem título
  (`--sem-titulo`), sem cartões (`--sem-graficos`) e sem zoom (`zoom_maximo = 1.0`,
  `salto_nos_cortes = 0`, `plano_maximo = 0`). Monograma f::c em marca d'água no vídeo todo com
  `ferramentas/marca_dagua.py`, depois do render (prévia e final). Manual de marca do Foco: cores
  #283f51, #e2a81b, #c5242f, #ce5e20, #457e7b; fonte de comunicação Josefin Sans (o usuário
  preferiu SF Pro).
  - "neurocirurgiões" saiu sem o "neuro" no começo de frase depois de um corte: o Whisper marcou
    a palavra 0,48 s depois do começo da voz. `aparar_silencio` agora volta o início do trecho até
    a voz começar (até 0,6 s, `ESTENDER_INICIO`), sem passar da palavra anterior, e a legenda
    acompanha. A checagem não acusou: palavra cortada no começo, por atraso do Whisper, ainda não
    é suspeita da checagem.
  - Legenda azul-escura sem contorno some na camisa e na parede: o contorno branco fino é
    necessário. A marca d'água branca a 35% fica discreta sobre parede clara (aprovada assim,
    aumentada de 150 para 210 px).

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
