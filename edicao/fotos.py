"""Saída no Fotos do Mac (e, com o Fotos do iCloud ligado, no iPhone).

Usa o AppleScript do app Fotos. Na primeira vez o macOS pede para autorizar o controle do Fotos
(Ajustes do Sistema › Privacidade e Segurança › Automação); a janela aparece na tela do Mac, então
não dá para aprovar por SSH.
"""

import subprocess
from pathlib import Path

_SCRIPT = """
on run argv
    set caminho to item 1 of argv
    set nomeAlbum to item 2 of argv
    tell application "Photos"
        if not (exists album nomeAlbum) then make new album named nomeAlbum
        set destino to album nomeAlbum
        set itens to import {POSIX file caminho} into destino skip check duplicates true
        return count of itens
    end tell
end run
"""


def importar(video: Path, album: str, espera: int = 600) -> int:
    """Importa o vídeo para o álbum (criado se não existir). Devolve quantos itens entraram."""
    r = subprocess.run(["osascript", "-e", _SCRIPT, str(Path(video).resolve()), album],
                       capture_output=True, text=True, timeout=espera)
    if r.returncode != 0:
        raise RuntimeError(f"o Fotos recusou a importação: {r.stderr.strip()}")
    return int(r.stdout.strip() or 0)
