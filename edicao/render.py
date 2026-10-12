"""Renderização final com ffmpeg: cortes, enquadramento 9:16 e legendas."""

import subprocess
from pathlib import Path

from .plano import Trecho


def _escapar_caminho_filtro(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def renderizar(
    video: Path, trechos: list[Trecho], legendas_ass: Path | None, saida: Path,
    cfg_video: dict, fade_audio: float,
) -> None:
    larg, alt = cfg_video["largura"], cfg_video["altura"]
    filtros = []
    for i, t in enumerate(trechos):
        fade = min(fade_audio, t.duracao / 2)
        if t.quadro:
            # Janela calculada a partir dos olhos (ver rosto.enquadrar).
            x, y, w, h = t.quadro
            enquadramento = f"crop={w}:{h}:{x}:{y},scale={larg}:{alt}:flags=lanczos"
        else:
            # Sem rastreamento: zoom centralizado, cortando o excesso para 9:16.
            z = t.zoom
            enquadramento = (
                f"scale={round(larg * z / 2) * 2}:{round(alt * z / 2) * 2}:force_original_aspect_ratio=increase,"
                f"crop={larg}:{alt}"
            )
        filtros.append(
            f"[0:v]trim=start={t.inicio:.3f}:end={t.fim:.3f},setpts=PTS-STARTPTS,"
            f"{enquadramento},setsar=1[v{i}]"
        )
        filtros.append(
            f"[0:a]atrim=start={t.inicio:.3f}:end={t.fim:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:d={fade:.3f},afade=t=out:st={t.duracao - fade:.3f}:d={fade:.3f}[a{i}]"
        )
    entradas = "".join(f"[v{i}][a{i}]" for i in range(len(trechos)))
    filtros.append(f"{entradas}concat=n={len(trechos)}:v=1:a=1[vc][ac]")

    final = "[vc]null"
    if legendas_ass:
        final += f",subtitles=filename='{_escapar_caminho_filtro(legendas_ass)}'"
    filtros.append(final + "[vout]")

    codec = cfg_video["codec"]
    qualidade = ["-crf", str(cfg_video["crf"])] if codec == "libx264" else ["-q:v", "65"]
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-filter_complex", ";".join(filtros), "-map", "[vout]", "-map", "[ac]",
         "-c:v", codec, *qualidade, "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(saida)],
        check=True,
    )
