# edicao-videos

Pipeline automático de edição de vídeos curtos (Reels). Você grava no iPhone, envia o vídeo bruto e recebe de volta o vídeo editado, pronto para salvar no Fotos e postar.

Substitui a edição semi-automática feita hoje no app Edits (Meta), que não tem API pública.

## O que o pipeline faz

- Corta silêncios e erros/retakes
- Gera legendas com destaque das palavras relevantes
- Aplica variação suave de zoom para dar dinamismo
- Exporta MP4 vertical 9:16

## Arquitetura (A)

1. **Upload:** Atalho do iOS (Compartilhar → enviar → aguardar → Salvar no Fotos). Página web como alternativa.
2. **Silêncios:** detector de voz (VAD Silero ou `silencedetect` do FFmpeg).
3. **Transcrição:** Whisper via API ou WhisperX, com timestamp preciso por palavra.
4. **Decisão de edição (Claude API):** recebe frases numeradas com tempos e devolve só os IDs das frases a manter, as palavras a destacar e os pontos de zoom. Para retakes: quando duas frases forem parecidas, mantém a última. O código valida o JSON e corta pelos tempos reais.
5. **Renderização (FFmpeg):** cortes com folga de 60–120 ms e crossfade de áudio de ~20 ms; zoom 1,0–1,15 a cada 3–5 s, centrado no rosto; legendas em ASS com destaque palavra por palavra.
6. **Entrega:** o vídeo volta para o celular. A postagem continua manual.

Custo estimado: menos de US$ 0,05 por vídeo de 1 minuto, mais o servidor (US$ 5–10/mês).

## Decisões em aberto

| Decisão | Recomendação |
|---|---|
| Onde roda | Nuvem (Railway ou Render) |
| Transcrição | API, escolhida pela precisão do timestamp por palavra |
| Postagem | Só entregar o arquivo |
| Estilo | Padrão inicial em arquivo de configuração, ajustado após o primeiro resultado |

## Alternativas consideradas

- **B:** igual à A, renderizando com Remotion (legendas e zoom mais elaborados). Verificar licença.
- **C:** serviço pronto (Submagic, Captions, Shotstack, Creatomate). Pouco código, mas trata mal retakes e prende o estilo.
- **Espelhamento do iPhone no Mac com o Claude operando o Edits:** possível em teoria, mas lento, impreciso e frágil.

## Status

Planejamento. Pendência registrada no Notion (📌 Pendências conhecidas, chave `nota:edicao-video-automatica`).
