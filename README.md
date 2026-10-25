# edicao-videos

Pipeline automático de edição de vídeos curtos (Reels). Você grava no iPhone, envia o vídeo bruto e recebe de volta o vídeo editado, pronto para salvar no Fotos e postar.

Substitui a edição semi-automática feita hoje no app Edits (Meta), que não tem API pública.

## O que o pipeline faz

- Corta silêncios e erros/retakes
- Gera legendas com destaque das palavras relevantes
- Aplica variação suave de zoom para dar dinamismo
- Exporta MP4 vertical 9:16

## Arquitetura (A)

1. **Entrada e saída pelo Fotos do iCloud:** no iPhone, o vídeo (e o material de apoio) vai para o álbum **Para editar**. O Mac lê o álbum com `osxphotos`, processa e importa o resultado no álbum **Editados**, que sincroniza de volta para o iPhone.
2. **Silêncios:** detector de voz (VAD Silero ou `silencedetect` do FFmpeg).
3. **Transcrição:** Whisper via API ou WhisperX, com timestamp preciso por palavra.
4. **Decisão de edição (Claude, pela assinatura via Claude Code; API opcional):** recebe frases numeradas com tempos e devolve só os IDs das frases a manter, as palavras a destacar e os pontos de zoom. Para retakes: quando duas frases forem parecidas, mantém a última. O código valida o JSON e corta pelos tempos reais.
5. **Renderização (FFmpeg):** cortes com folga e fade de áudio nas emendas; zoom de 1,0 a 1,4 enquadrado pelos olhos (detector YuNet do OpenCV), com os olhos um pouco acima do centro; legendas em ASS com destaque palavra por palavra.
6. **Entrega:** o vídeo volta para o celular. A postagem continua manual.

Roda no computador do usuário (decidido em 2026-10-11), sem servidor na nuvem. O Mac precisa estar ligado para processar.

## Material de apoio (comentários, depoimentos, imagens)

**Como enviar:** no álbum **Para editar**, junto com o vídeo principal. O vídeo principal é marcado como favorito (coração); todo o resto do álbum é material de apoio daquele vídeo. Marcar o favorito é o sinal de "pode processar". Depois do processamento, os itens saem do álbum.

**Onde cada material entra:**
1. **Automático por conteúdo (padrão):** o Claude lê cada imagem (texto do print, o que a imagem mostra) e transcreve os vídeos de depoimento, e escolhe o trecho da fala em que cada um se encaixa.
2. **Marca falada (opcional, para forçar):** durante a gravação, uma frase combinada como "entra o depoimento" fixa o ponto exato; a frase é cortada do vídeo final.
3. **Ordem do álbum (desempate):** se o Claude não achar o encaixe, usa a ordem dos itens.

**Como aparece:**
- **Print de comentário ou imagem:** cartão sobre o vídeo (você continua falando), com leve zoom de entrada, pelo tempo da frase relacionada (mínimo de ~2,5 s).
- **Vídeo de depoimento:** tela dividida. O depoimento roda numa metade, com áudio e legenda próprios; na outra metade, o seu vídeo fica pausado (quadro congelado). Ao terminar o depoimento, o seu vídeo volta a rodar em tela cheia. A posição das metades é configurável.
- **Privacidade (ligada por padrão):** nomes e fotos de perfil nos prints são desfocados.

## Decisões em aberto

| Decisão | Recomendação |
|---|---|
| ~~Onde roda~~ | **Decidido: no computador (Mac), não na nuvem** |
| ~~Entrada~~ | **Decidido: álbum do Fotos do iCloud (Para editar → Editados)** |
| ~~Transcrição~~ | **Decidido: local nos dois Macs.** Mac Mini Intel com faster-whisper (CPU); MacBook M2 com mlx-whisper (GPU). Escolha automática. |
| Postagem | Só entregar o arquivo |
| Estilo | Padrão inicial em arquivo de configuração, ajustado após o primeiro resultado |

## Alternativas consideradas

- **B:** igual à A, renderizando com Remotion (legendas e zoom mais elaborados). Verificar licença.
- **C:** serviço pronto (Submagic, Captions, Shotstack, Creatomate). Pouco código, mas trata mal retakes e prende o estilo.
- **Espelhamento do iPhone no Mac com o Claude operando o Edits:** possível em teoria, mas lento, impreciso e frágil.

## Como usar (protótipo 0.6)

Guia passo a passo para quem vai usar: [MANUAL-DE-USO.md](MANUAL-DE-USO.md).

O que já funciona: corte de silêncios, transcrição local, decisão pelo Claude (corta retakes e marcas como "corta, vou repetir", escolhe palavras de destaque e frases com zoom) e legendas com a palavra atual destacada, exportando em 1080x1920. O zoom alterna três modalidades, escolhidas pelo Claude frase a frase:

- **Seco:** o enquadramento salta na emenda, sem animação. Usado sobretudo logo depois de cortes de fala ou de silêncio; quando um corte deixaria o mesmo enquadramento dos dois lados, o zoom muda sozinho (salto de 0,12) para o corte não parecer um tranco.
- **Suave (cinematográfico):** aproximação lenta e contínua ao longo da frase inteira, que continua de onde parou mesmo se a frase tiver um silêncio cortado no meio.
- **Rápido suavizado:** aproximação de 0,4 s no começo da frase, que sai rápido e assenta devagar, e depois fica parada.

O zoom vai de 1,0 a 1,4 e acompanha os olhos em todas as modalidades: eles ficam centralizados na horizontal e um pouco acima do centro (42% da altura), e se algum olho fosse sair do quadro o zoom daquele trecho diminui. Ainda não: álbum do Fotos e material de apoio.

Resolução: grave em 4K quando puder. Em 1080p funciona, mas no zoom de 1,4 a imagem é ampliada 1,4 vez e perde um pouco de nitidez (o mesmo que acontece no Edits).

HDR: o iPhone grava em HDR (HLG) por padrão, inclusive no modo Cinema. O pipeline detecta isso e converte para SDR na renderização, sem deixar a imagem lavada; não é preciso desligar o HDR. A saída é sempre SDR (BT.709), que o Instagram exibe de forma previsível.

A decisão usa a sua assinatura do Claude por meio do Claude Code instalado no Mac (`claude -p`), sem chave de API. Se o Claude Code falhar ou o limite de uso estourar, o vídeo sai mesmo assim, só com o corte de silêncios. A API fica como opção em `config.toml` (`[decisao] backend = "api"`).

Instalação no Mac (uma vez):

Abra o Terminal, cole a linha abaixo e tecle Enter (Mac Intel ou Apple Silicon, sem conta no GitHub):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/fococirurgico/edicao-videos/main/instalar.command)"
```

Ela baixa o programa para `~/edicao-videos` (fora de Documentos e da Mesa, que o iCloud pode sincronizar) e roda o `instalar.command` de lá. Quem já tem a pasta do programa pode rodar `bash instalar.command` dentro dela.

O instalador cuida de tudo: ffmpeg e Python (pelo Homebrew no Apple Silicon; no Mac Intel, onde o Homebrew não instala mais, Python pelo `uv` e ffmpeg do pacote `imageio-ffmpeg`, com link em `bin/` do programa); o Whisper certo para o Mac (Intel ou Apple Silicon); o Claude Code com login na sua conta; o download do modelo de transcrição; a identidade de marca (opcional); e o app **Editar vídeo** na Mesa. Para editar, arraste o vídeo para esse ícone. Rodar o instalador de novo é seguro: ele só instala o que faltar.

Uso pelo Terminal, dentro da pasta do projeto:

```bash
# Mede a velocidade da transcrição neste Mac (rode duas vezes: a 1ª baixa o modelo)
.venv/bin/edicao medir ~/Desktop/video.mov
.venv/bin/edicao medir ~/Desktop/video.mov --modelo medium

# Edita o vídeo; gera video_editado.mp4 ao lado do original
.venv/bin/edicao processar ~/Desktop/video.mov

# Sem a decisão do Claude (só corta silêncios e legenda)
.venv/bin/edicao processar ~/Desktop/video.mov --sem-claude
```

Ao lado do vídeo editado ficam `*.transcricao.json` (o texto com tempos) e `*.decisao.json` (o que o Claude decidiu manter, destacar e aproximar), úteis para conferir a edição.

Os ajustes (sensibilidade do silêncio, modelo, cores e tamanho da legenda) ficam em `config.toml`.

Testes: `.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest`.

## Identidade de marca

Fonte e cores da legenda, nome da marca, quem fala nos vídeos, público e tom. O nome, o autor, o público e o tom ajudam o Claude a decidir os cortes e os destaques. Tudo isso fica guardado no computador, fora da pasta do programa (`~/Library/Application Support/edicao-videos/`), e não se perde ao atualizar.

```bash
.venv/bin/edicao marca                              # perguntas no Terminal (Enter mantém o valor atual)
.venv/bin/edicao marca --manual ~/Desktop/manual.pdf  # o Claude lê o manual (PDF ou imagens) e preenche as respostas
.venv/bin/edicao marca --fonte ~/Desktop/Marca-Bold.otf  # usa o arquivo de fonte da marca sem instalar
.venv/bin/edicao marca --mostrar                    # mostra a configuração atual
```

Ao ler o manual, o Claude extrai fontes, cores (em hex) e tom de voz e propõe a legenda: texto e contorno com alto contraste, palavra falada e destaques nas cores da marca. Depois vêm as perguntas, já preenchidas, para você conferir. Ao final sai uma prévia da legenda em PNG. Se a fonte da prévia não for a da marca, instale a fonte no Mac ou use `--fonte`.

A paleta completa fica guardada para o material de apoio, que ainda não foi implementado.

## Vários computadores e contas

- **Claude:** cada computador usa a conta em que o Claude Code está logado (o instalador faz o login). O uso conta no limite dessa conta, que precisa ter o Claude Code incluído (Pro, Max, Team ou Enterprise). No plano gratuito, os vídeos saem só com corte de silêncios e legendas. Para trocar de conta, rode `claude` e digite `/login`.
- **GitHub:** o repositório é público e a linha de instalação baixa o código sem login; o uso não acessa o GitHub.
- **Atualizar:** rode a mesma linha da instalação. Ela troca o código em `~/edicao-videos`, mantém o ambiente (`.venv`) e só instala o que faltar. A identidade de marca e os ajustes deste computador continuam.
- **Outros ajustes por computador:** o arquivo `config.toml` em `~/Library/Application Support/edicao-videos/` aceita qualquer seção do `config.toml` do programa (por exemplo, `[legendas] tamanho = 80`); o que estiver lá vale só naquele computador.

## Status

Protótipo 0.6.3. Pendência registrada no Notion (📌 Pendências conhecidas, chave `nota:edicao-video-automatica`).
