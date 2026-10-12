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


def dimensoes(video: Path) -> tuple[int, int]:
    """Largura e altura de exibição (vídeos do iPhone guardam a rotação como metadado)."""
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    s = json.loads(saida)["streams"][0]
    rotacao = int(s.get("tags", {}).get("rotate", 0))
    for d in s.get("side_data_list", []):
        rotacao = int(d.get("rotation", rotacao))
    w, h = s["width"], s["height"]
    return (h, w) if abs(rotacao) % 180 == 90 else (w, h)


# Curvas de transferência HDR: HLG (padrão do iPhone, inclusive no modo Cinema) e PQ.
TRANSFERENCIAS_HDR = ("arib-std-b67", "smpte2084")


def transferencia_hdr(video: Path) -> str | None:
    """Curva de transferência do vídeo se ele for HDR; None se for SDR."""
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=color_transfer", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    trc = json.loads(saida)["streams"][0].get("color_transfer")
    return trc if trc in TRANSFERENCIAS_HDR else None


def tem_filtro(nome: str) -> bool:
    saida = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(linha.split()[1:2] == [nome] for linha in saida.splitlines())


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
