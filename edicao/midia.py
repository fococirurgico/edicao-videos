"""Chamadas ao ffmpeg/ffprobe."""

import json
import re
import subprocess
from pathlib import Path


def duracao(video: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(saida)["format"]["duration"])


def detectar_silencios(video: Path, limiar_db: float, minimo: float) -> list[tuple[float, float]]:
    """Intervalos (início, fim) em que o áudio fica abaixo do limiar por pelo menos `minimo` s."""
    stderr = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", f"silencedetect=noise={limiar_db}dB:d={minimo}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", stderr)]
    total = duracao(video)
    # Um silêncio que vai até o fim do arquivo não tem silence_end.
    fins += [total] * (len(inicios) - len(fins))
    return [(max(0.0, i), f) for i, f in zip(inicios, fins)]
