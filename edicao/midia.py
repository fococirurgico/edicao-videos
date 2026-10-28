"""Leitura dos vídeos (PyAV) e chamadas ao ffmpeg.

As informações do arquivo vêm do PyAV, que já vem com o Whisper, e não do ffprobe: no Mac Intel
sem Homebrew só há o ffmpeg (do pacote imageio-ffmpeg), sem ffprobe.
"""

import re
import subprocess
from fractions import Fraction
from pathlib import Path

import av


def duracao(video: Path) -> float:
    with av.open(str(video)) as c:
        return c.duration / av.time_base


def dimensoes(video: Path) -> tuple[int, int]:
    """Largura e altura de exibição (vídeos do iPhone guardam a rotação como metadado)."""
    with av.open(str(video)) as c:
        s = c.streams.video[0]
        rotacao = next(c.decode(s)).rotation
        w, h = s.codec_context.width, s.codec_context.height
    return (h, w) if abs(rotacao) % 180 == 90 else (w, h)


def fps(video: Path) -> Fraction:
    """Taxa de quadros média (o iPhone grava a uma taxa constante: 30, 60 ou 24)."""
    with av.open(str(video)) as c:
        taxa = c.streams.video[0].average_rate
    return Fraction(taxa) if taxa else Fraction(30)


# Curvas de transferência HDR: HLG (padrão do iPhone, inclusive no modo Cinema) e PQ, com o
# número do FFmpeg (AVColorTransferCharacteristic) e o nome que o filtro setparams usa.
TRANSFERENCIAS_HDR = {18: "arib-std-b67", 16: "smpte2084"}


def transferencia_hdr(video: Path) -> str | None:
    """Curva de transferência do vídeo se ele for HDR; None se for SDR."""
    with av.open(str(video)) as c:
        trc = c.streams.video[0].codec_context.color_trc
    return TRANSFERENCIAS_HDR.get(int(trc))


def tem_filtro(nome: str) -> bool:
    saida = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(linha.split()[1:2] == [nome] for linha in saida.splitlines())


def volume_integrado(video: Path) -> float | None:
    """Volume percebido do áudio inteiro, em LUFS (EBU R128); None se não houver áudio."""
    stderr = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    achados = re.findall(r"I:\s+(-?[\d.]+) LUFS", stderr)
    return float(achados[-1]) if achados else None


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
