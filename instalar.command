#!/bin/bash
# Instalador do edicao-videos para macOS (Mac Intel ou Apple Silicon).
#
# Uso: abra o Terminal, digite "bash " (com espaço), arraste este arquivo para a janela e
# tecle Enter. Pode rodar de novo quando quiser: instala só o que faltar e atualiza o resto.
#
# O que faz: Homebrew, ffmpeg e Python; ambiente do projeto com o Whisper certo para este Mac;
# Claude Code com login na sua conta; baixa o modelo de transcrição; e cria na Mesa o app
# "Editar vídeo", no qual você arrasta os vídeos para editar.
set -euo pipefail

PASTA="$(cd "$(dirname "$0")" && pwd)"
cd "$PASTA"

etapa() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
aviso() { printf '\033[33m%s\033[0m\n' "$1"; }

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
if ! command -v brew >/dev/null 2>&1 && ! carregar_brew; then
  echo "Instalando o Homebrew. Ele vai pedir a senha do Mac (ao digitar, nada aparece; é normal)."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  carregar_brew
fi
BREW="$(command -v brew)"
if ! grep -qs "$BREW shellenv" "$HOME/.zprofile"; then
  echo "eval \"\$($BREW shellenv)\"" >> "$HOME/.zprofile"
fi
echo "ok: $BREW"

etapa "2/7 ffmpeg e Python"
brew install ffmpeg python@3.12
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"

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
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[$EXTRA]"
echo "ok: transcrição no modo $EXTRA"

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
