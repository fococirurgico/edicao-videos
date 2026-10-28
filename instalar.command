#!/bin/bash
# Instalador do edicao-videos para macOS (Mac Intel ou Apple Silicon).
#
# Uso: abra o Terminal, cole a linha abaixo e tecle Enter. A mesma linha atualiza o programa.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/fococirurgico/edicao-videos/main/instalar.command)"
#
# Rodado assim, primeiro baixa o programa para ~/edicao-videos e continua a partir de lá.
# Também funciona de dentro da pasta do programa: bash instalar.command.
#
# O que faz: Homebrew e Python; ffmpeg; ambiente do projeto com o Whisper certo para este Mac;
# Claude Code com login na sua conta; baixa o modelo de transcrição; e cria na Mesa o app
# "Editar vídeo", no qual você arrasta os vídeos para editar.
set -euo pipefail

etapa() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
aviso() { printf '\033[33m%s\033[0m\n' "$1"; }

eh_pasta_do_programa() { [ -f "$1/pyproject.toml" ] && [ -d "$1/edicao" ]; }

ORIGEM="${BASH_SOURCE[0]:-}"
if [ -n "$ORIGEM" ] && [ -f "$ORIGEM" ] && eh_pasta_do_programa "$(dirname "$ORIGEM")"; then
  PASTA="$(cd "$(dirname "$ORIGEM")" && pwd)"
else
  # Rodado pela linha do curl: baixa (ou atualiza) o programa e roda o instalador de lá.
  # Fora de Documentos e da Mesa, que o iCloud pode sincronizar e esvaziar.
  DESTINO="${EDICAO_INSTALAR_EM:-$HOME/edicao-videos}"
  FONTE_URL="${EDICAO_FONTE_URL:-https://codeload.github.com/fococirurgico/edicao-videos/tar.gz/refs/heads/main}"
  etapa "Baixando o programa para $DESTINO"
  if [ -e "$DESTINO" ] && ! eh_pasta_do_programa "$DESTINO"; then
    aviso "Já existe $DESTINO e não é a pasta do programa. Renomeie ou apague essa pasta e rode de novo."
    exit 1
  fi
  BAIXADO="$(mktemp -d)"
  curl -fsSL "$FONTE_URL" | tar -xz -C "$BAIXADO" --strip-components 1
  mkdir -p "$DESTINO"
  # Troca o código e mantém o ambiente já instalado (.venv).
  rm -rf "$DESTINO/edicao" "$DESTINO/tests"
  cp -R "$BAIXADO/." "$DESTINO/"
  rm -rf "$BAIXADO"
  chmod +x "$DESTINO/instalar.command"
  echo "ok: programa em $DESTINO"
  exec /bin/bash "$DESTINO/instalar.command"
fi
cd "$PASTA"

carregar_brew() {
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then
      eval "$("$b" shellenv)"
      return 0
    fi
  done
  return 1
}

etapa "1/7 Homebrew"
# O Homebrew não instala mais em Mac Intel. Nele, sem Homebrew já instalado, o Python vem pronto
# para a pasta bin/ do programa (uv), sem pedir senha.
SEM_BREW=0
if command -v brew >/dev/null 2>&1 || carregar_brew; then
  :
elif [ "$(uname -m)" = "arm64" ]; then
  echo "Instalando o Homebrew. Ele vai pedir a senha do Mac (ao digitar, nada aparece; é normal)."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  carregar_brew
else
  SEM_BREW=1
fi
if [ "$SEM_BREW" = "1" ]; then
  echo "ok: Mac Intel sem Homebrew; o Python vai para $PASTA/bin"
else
  BREW="$(command -v brew)"
  if ! grep -qs "$BREW shellenv" "$HOME/.zprofile"; then
    echo "eval \"\$($BREW shellenv)\"" >> "$HOME/.zprofile"
  fi
  echo "ok: $BREW"
fi

etapa "2/7 Python e ffmpeg"
# O ffmpeg vem na etapa 3, pelo pacote imageio-ffmpeg, em todos os Macs: o do Homebrew (9.x)
# veio sem libass e sem zscale (sem legenda e sem conversão HDR).
if [ "$SEM_BREW" = "1" ]; then
  mkdir -p bin
  if [ ! -x bin/uv ]; then
    curl -fsSL https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-apple-darwin.tar.gz \
      | tar -xz -C bin --strip-components 1
  fi
  bin/uv python install 3.12
else
  brew install python@3.12
  PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
fi

etapa "3/7 Ambiente do projeto"
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
  if [ "$(uname -m)" = "arm64" ]; then
    EXTRA="mx"
  else
    aviso "Mac Apple Silicon rodando o Terminal em modo Intel (Rosetta): a transcrição vai usar o modo Intel, mais lento."
    EXTRA="intel"
  fi
else
  EXTRA="intel"
fi
if [ ! -d .venv ]; then
  if [ "$SEM_BREW" = "1" ]; then
    bin/uv venv --python 3.12 --seed .venv
  else
    "$PYTHON" -m venv .venv
  fi
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[$EXTRA]"
echo "ok: transcrição no modo $EXTRA"
mkdir -p bin
.venv/bin/pip install --quiet imageio-ffmpeg
FFMPEG="$(ls "$PASTA"/.venv/lib/python3.*/site-packages/imageio_ffmpeg/binaries/ffmpeg-* 2>/dev/null | head -1)"
if [ -z "$FFMPEG" ] || ! "$FFMPEG" -version >/dev/null 2>&1; then
  aviso "Não consegui instalar o ffmpeg (pacote imageio-ffmpeg). Mande esta mensagem para o suporte."
  exit 1
fi
ln -sf "$FFMPEG" bin/ffmpeg
# O fontconfig embutido nesse ffmpeg não sabe onde ficam as fontes do Mac.
cat > bin/fonts.conf <<'XML'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/System/Library/Fonts</dir>
  <dir>/Library/Fonts</dir>
  <dir>~/Library/Fonts</dir>
  <cachedir>~/Library/Caches/edicao-videos/fontconfig</cachedir>
</fontconfig>
XML
export PATH="$PASTA/bin:$PATH"
export FONTCONFIG_FILE="$PASTA/bin/fonts.conf"
FILTROS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
if ! grep -q " subtitles " <<<"$FILTROS"; then
  aviso "Este ffmpeg não tem legendas (libass): os vídeos vão sair sem legenda. Mande esta mensagem para o suporte."
elif ! grep -q " zscale " <<<"$FILTROS"; then
  aviso "Este ffmpeg não converte HDR (zscale): vídeos em HDR podem sair com cores lavadas."
else
  echo "ok: $(command -v ffmpeg) com legendas e conversão HDR"
fi

etapa "4/7 Claude Code"
export PATH="$PATH:$HOME/.local/bin"
if ! command -v claude >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
TESTE="$(mktemp -d)"
if (cd "$TESTE" && claude -p "Responda apenas: ok" --max-turns 1 --tools "" >/dev/null 2>&1); then
  echo "ok: Claude Code com login feito"
else
  echo "Falta fazer login no Claude Code. Ele vai abrir agora: siga as instruções para entrar"
  echo "com a sua conta e, quando aparecer a caixa de mensagem, digite /exit e tecle Enter."
  read -r -p "Tecle Enter para continuar… "
  (cd "$TESTE" && claude) || true
  if (cd "$TESTE" && claude -p "Responda apenas: ok" --max-turns 1 --tools "" >/dev/null 2>&1); then
    echo "ok: Claude Code com login feito"
  else
    aviso "O Claude Code ainda não respondeu. Os vídeos saem só com corte de silêncios até o login funcionar; rode este instalador de novo depois."
  fi
fi
rm -rf "$TESTE"

etapa "5/7 Modelo de transcrição (download único)"
.venv/bin/python - "$EXTRA" <<'PY' || aviso "Não consegui baixar o modelo agora; ele será baixado no primeiro vídeo."
import sys
from edicao import config
modelo = config.carregar()["transcricao"]["modelo"]
if sys.argv[1] == "mx":
    from huggingface_hub import snapshot_download
    snapshot_download(f"mlx-community/whisper-{modelo}-mlx")
else:
    from faster_whisper import WhisperModel
    WhisperModel(modelo, device="cpu", compute_type="int8")
print(f"ok: modelo {modelo}")
PY

etapa "6/7 Identidade de marca"
if .venv/bin/python -c "from edicao import config; raise SystemExit(0 if config.config_usuario().exists() else 1)"; then
  echo "Este computador já tem uma identidade de marca configurada:"
  .venv/bin/edicao marca --mostrar
  PERGUNTA="Quer reconfigurar agora? (s/N) "
else
  echo "Fonte e cores da legenda, nome da marca e quem fala nos vídeos ficam guardados neste"
  echo "computador e não se perdem ao atualizar o programa."
  PERGUNTA="Quer configurar agora? (s/N) "
fi
read -r -p "$PERGUNTA" RESPOSTA
if [ "$RESPOSTA" = "s" ] || [ "$RESPOSTA" = "S" ]; then
  echo "Se tiver o manual de marca (PDF ou imagem), arraste o arquivo para esta janela e tecle"
  read -r -p "Enter. Sem manual, só tecle Enter para responder às perguntas: " MANUAL
  MANUAL="${MANUAL%"${MANUAL##*[![:space:]]}"}"
  MANUAL="${MANUAL//\\ / }"
  MANUAL="${MANUAL#[\'\"]}"
  MANUAL="${MANUAL%[\'\"]}"
  # Com manual: o Claude lê o manual e as perguntas já vêm preenchidas com o que ele achou.
  if [ -n "$MANUAL" ] && .venv/bin/edicao marca --manual "$MANUAL"; then
    :
  else
    [ -n "$MANUAL" ] && aviso "Não consegui ler o manual; seguindo só com as perguntas."
    .venv/bin/edicao marca || aviso "A identidade não foi salva. Depois, rode: .venv/bin/edicao marca"
  fi
else
  echo "Pode configurar depois, na pasta do programa: .venv/bin/edicao marca"
fi

etapa "7/7 App \"Editar vídeo\" na Mesa"
PASTA_AS="${PASTA//\\/\\\\}"
PASTA_AS="${PASTA_AS//\"/\\\"}"
FONTE="$(mktemp -d)/editar.applescript"
cat > "$FONTE" <<APPLESCRIPT
property pasta : "$PASTA_AS"

on open arquivos
	set comando to ""
	repeat with f in arquivos
		set comando to comando & quoted form of (pasta & "/.venv/bin/edicao") & " processar " & quoted form of (POSIX path of f) & "; "
	end repeat
	tell application "Terminal"
		activate
		do script comando
	end tell
end open

on run
	display dialog "Arraste um ou mais vídeos para este ícone. O vídeo editado aparece ao lado do original, com _editado no nome." buttons {"OK"} default button 1 with title "Editar vídeo"
end run
APPLESCRIPT
rm -rf "$HOME/Desktop/Editar vídeo.app"
osacompile -o "$HOME/Desktop/Editar vídeo.app" "$FONTE"
echo "ok: app criado na Mesa"

etapa "Pronto"
echo "Arraste um vídeo (da Mesa ou do Finder) para o ícone \"Editar vídeo\" na Mesa."
echo "Na primeira vez, o Mac pergunta se o app pode controlar o Terminal: clique em OK."
