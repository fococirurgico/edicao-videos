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
- Postagem continua manual.
- Vídeos em 4K ou 1080p (o usuário vai gravar parte em 1080p para poupar espaço). HDR do iPhone
  (HLG, inclusive modo Cinema) é convertido para SDR na renderização; saída sempre BT.709.
- Roda em vários computadores, com contas diferentes do Claude (a do Claude Code logado em
  cada um) e sem depender de conta no GitHub para usar.
- Configuração em duas camadas: `config.toml` do programa (padrão, substituído ao atualizar) e
  `config.toml` do computador em `~/Library/Application Support/edicao-videos/` (`EDICAO_PASTA`
  sobrepõe; os testes usam isso). Identidade de marca na seção `[marca]`, via `edicao marca`:
  perguntas, leitura do manual pelo Claude (`claude_json` com a ferramenta Read) ou arquivo de
  fonte copiado para `fontes/`. Paleta guardada para o material de apoio.
- Instalação pelo `instalar.command` (o repositório é privado: o usuário baixa o ZIP e roda o
  script pelo Terminal); ele cria o app "Editar vídeo" na Mesa, no qual se arrastam os vídeos.

## Próximos passos

1. Usuário instalar com o `instalar.command` e testar nos dois Macs (4K e 1080p, modo Cinema com HDR); relatar tempos e qualidade.
2. Álbum do Fotos (osxphotos): ler "Para editar", importar o resultado em "Editados".
3. Material de apoio: encaixe pelo Claude, tela dividida, desfoque.

## Pendência no Notion

Database 📌 Pendências conhecidas. Atualize ao avançar (marque Concluído e Concluída em):
- `nota:edicao-video-automatica`: instalar e testar o protótipo (ação do usuário).
- `nota:edicao-video-album-fotos`: entrada e saída pelo álbum do Fotos (código).
- `nota:edicao-video-material-apoio`: material de apoio (código).
- `nota:edicao-video-zoom-1080p`: limite de zoom em 1080p, decidir depois do teste.

## Cuidados técnicos

- O crop do ffmpeg guarda o tamanho do primeiro quadro (`in_w`/`in_h`); no zoom animado a
  posição do corte é calculada a partir da largura ampliada (ver `render._animacao`).
- Expressões de suavização entram sempre entre parênteses na fórmula do ffmpeg.
- Conversão HDR (`render._para_sdr`): roda depois do corte e da escala, em 1080x1920; mobius
  com param 0,6 manteve tons médios e saturação num HLG simulado. Ainda não conferida em vídeo
  real do iPhone, nem o comportamento dos realces.
- Modo Cinema: falta confirmar se o desfoque de fundo vem aplicado no arquivo exportado
  (no álbum, exportar a versão renderizada, não o original com dados de profundidade).
- Fonte da legenda: o libass acha a fonte pela família (nameID 16/1) com negrito/itálico do
  estilo; o nome completo ("Inter Display Medium Italic") não foi reconhecido no teste. Por isso
  `marca.ler_fonte` grava família + `negrito` (peso ≥ 600) + `italico`.
- Testes: `.venv/bin/pytest`. O teste de zoom animado compara o primeiro e o último quadro com os
  enquadramentos esperados.
