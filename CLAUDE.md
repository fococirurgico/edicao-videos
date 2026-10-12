# edicao-videos

Pipeline que edita sozinho os vídeos curtos (Reels) que o usuário grava no iPhone, substituindo a
edição semi-automática que ele fazia no app Edits (Meta). Visão geral e instruções de uso no README.

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

## Próximos passos

1. Usuário testar a versão atual nos dois Macs com um vídeo real em 4K e relatar tempos e qualidade.
2. Álbum do Fotos (osxphotos): ler "Para editar", importar o resultado em "Editados".
3. Material de apoio: encaixe pelo Claude, tela dividida, desfoque.

## Pendência no Notion

Database 📌 Pendências conhecidas, chave `nota:edicao-video-automatica`. Atualize-a ao avançar.

## Cuidados técnicos

- O crop do ffmpeg guarda o tamanho do primeiro quadro (`in_w`/`in_h`); no zoom animado a
  posição do corte é calculada a partir da largura ampliada (ver `render._animacao`).
- Expressões de suavização entram sempre entre parênteses na fórmula do ffmpeg.
- Testes: `.venv/bin/pytest`. O teste de zoom animado compara o primeiro e o último quadro com os
  enquadramentos esperados.
