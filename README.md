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
4. **Decisão de edição (Claude API):** recebe frases numeradas com tempos e devolve só os IDs das frases a manter, as palavras a destacar e os pontos de zoom. Para retakes: quando duas frases forem parecidas, mantém a última. O código valida o JSON e corta pelos tempos reais.
5. **Renderização (FFmpeg):** cortes com folga de 60–120 ms e crossfade de áudio de ~20 ms; zoom 1,0–1,15 a cada 3–5 s, centrado no rosto; legendas em ASS com destaque palavra por palavra.
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
- **Vídeo de depoimento:** tela cheia com o áudio do depoimento e legenda própria; sua fala pausa ou fica em volume baixo.
- **Privacidade (opcional):** desfocar nomes e fotos de perfil nos prints.

## Decisões em aberto

| Decisão | Recomendação |
|---|---|
| ~~Onde roda~~ | **Decidido: no computador (Mac), não na nuvem** |
| ~~Entrada~~ | **Decidido: álbum do Fotos do iCloud (Para editar → Editados)** |
| Transcrição | API, escolhida pela precisão do timestamp por palavra |
| Postagem | Só entregar o arquivo |
| Estilo | Padrão inicial em arquivo de configuração, ajustado após o primeiro resultado |

## Alternativas consideradas

- **B:** igual à A, renderizando com Remotion (legendas e zoom mais elaborados). Verificar licença.
- **C:** serviço pronto (Submagic, Captions, Shotstack, Creatomate). Pouco código, mas trata mal retakes e prende o estilo.
- **Espelhamento do iPhone no Mac com o Claude operando o Edits:** possível em teoria, mas lento, impreciso e frágil.

## Status

Planejamento. Pendência registrada no Notion (📌 Pendências conhecidas, chave `nota:edicao-video-automatica`).
