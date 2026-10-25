# Manual de uso

Guia curto para instalar e usar a edição automática de vídeos num Mac. Detalhes técnicos no README.

## O que você precisa

- Um Mac (Intel ou Apple Silicon) com internet.
- Uma conta do Claude com Claude Code incluído (Pro, Max, Team ou Enterprise). Cada computador
  usa a conta em que estiver logado, e o uso conta no limite dessa conta. No plano gratuito, os
  vídeos saem só com corte de silêncios e legendas, sem cortes de erros, destaques nem zoom.
- Opcional: o manual de marca (PDF ou imagens) e o arquivo da fonte da marca (.otf ou .ttf).

## Instalar (uma vez por computador)

1. Abra o **Terminal** (em Aplicativos → Utilitários, ou busque "Terminal" no Spotlight).
2. Copie a linha abaixo, cole no Terminal e tecle Enter:

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/fococirurgico/edicao-videos/main/instalar.command)"
   ```

   Ela baixa o programa para a pasta `edicao-videos` da sua pasta de usuário (ao lado de
   Documentos e Mesa) e instala tudo. Não mude essa pasta de lugar: o app de editar aponta para ela.
   Não precisa de conta no GitHub. Vale para Mac Intel e Apple Silicon.
3. Siga as instruções na tela:
   - O Mac pede a senha uma vez. Ao digitar, nada aparece; é normal.
   - Na primeira vez, o Claude Code abre o navegador para você entrar na sua conta. Depois de
     entrar, digite `/exit` e tecle Enter para o instalador continuar.
   - O instalador pergunta se você quer configurar a identidade de marca (veja abaixo).
4. No fim, aparece na Mesa o app **Editar vídeo**.

Se você instalou antes pelo ZIP (pasta `edicao-videos-main` em Documentos), rode a linha acima e
depois apague a pasta antiga. A identidade de marca continua.

A instalação leva uns 15 minutos. Rodar o instalador de novo é seguro: ele só instala o que faltar.

## Configurar a identidade de marca

A identidade define a fonte e as cores da legenda e conta ao Claude quem fala nos vídeos, para
quem são e o tom da comunicação, o que ajuda a escolher cortes e destaques.

- **Com o manual de marca:** quando o instalador perguntar, arraste o PDF (ou a imagem) para a
  janela do Terminal e tecle Enter. O Claude lê o manual e propõe a legenda. Depois vêm as
  perguntas, já preenchidas, para você conferir.
- **Sem manual:** só tecle Enter e responda às perguntas.

Em cada pergunta, Enter mantém o valor entre colchetes. Responda a **"Quem fala nos vídeos"**
(por exemplo, "um médico cirurgião"). Na pergunta da fonte, você pode digitar o nome de uma fonte
instalada no Mac ou arrastar o arquivo .otf/.ttf da marca. Cores vão em hex, como `#FFD400`.

No fim abre uma imagem de prévia da legenda. Se a fonte não for a da marca, instale a fonte no Mac
(clique duas vezes no arquivo) ou arraste o arquivo da fonte na pergunta da fonte.

Para mudar depois, abra o Terminal na pasta do programa e use:

```bash
cd ~/edicao-videos
.venv/bin/edicao marca                       # refaz as perguntas
.venv/bin/edicao marca --manual manual.pdf   # lê outro manual de marca
.venv/bin/edicao marca --mostrar             # mostra a configuração atual
```

## Editar um vídeo

1. Grave no iPhone. 4K dá mais nitidez no zoom; 1080p também funciona. HDR e modo Cinema
   podem ficar ligados: as cores são convertidas automaticamente.
2. Passe o vídeo para o Mac (por exemplo, por AirDrop para a Mesa).
3. Arraste o vídeo (ou vários) para o ícone **Editar vídeo** na Mesa. Na primeira vez, o Mac
   pergunta se o app pode controlar o Terminal: clique em **OK**.
4. O Terminal mostra as etapas de 1/5 a 5/5. O vídeo editado aparece ao lado do original, com
   `_editado` no nome.
5. Mande o vídeo editado para o iPhone por AirDrop e poste.

Para errar menos na edição: ao errar uma frase, faça uma pausa e repita a frase inteira. O Claude
mantém a última versão e corta as anteriores, assim como "corta", "de novo" e "vou repetir".

## Atualizar o programa

Cole no Terminal a mesma linha da instalação. Ela baixa a versão nova e só instala o que faltar.
A identidade de marca e os ajustes do computador continuam.

## Se algo der errado

- **O vídeo saiu sem cortes de erros, sem destaques e sem zoom:** o Claude não respondeu.
  Confira o login (rode `claude` no Terminal) e se a conta tem plano com Claude Code ou se o limite
  de uso acabou.
- **A legenda saiu com outra fonte:** a fonte da marca não está instalada. Veja "Configurar a
  identidade de marca".
- **O app Editar vídeo não abre o Terminal:** em Ajustes do Sistema → Privacidade e Segurança →
  Automação, permita que "Editar vídeo" controle o Terminal.
- **Outro erro:** copie a mensagem do Terminal e envie para quem dá suporte, junto com os arquivos
  `*_editado.transcricao.json` e `*_editado.decisao.json` que ficam ao lado do vídeo.

Ainda não disponível: entrada e saída pelo álbum do Fotos e material de apoio (prints,
depoimentos e imagens).
