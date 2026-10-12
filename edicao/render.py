"""Renderização final com ffmpeg: cortes, enquadramento 9:16 e legendas."""

import subprocess
from pathlib import Path

from .plano import Trecho


def _escapar_caminho_filtro(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# Curvas de aceleração (p vai de 0 a 1). Guardam p em st(0) para reaproveitar.
_SUAVIZACAO = {
    "suave": "st(0,{p})*ld(0)*(3-2*ld(0))",            # acelera e desacelera
    "rapido": "1-pow(1-st(0,{p}),3)",                   # sai rápido e assenta devagar
}


def _para_sdr(transferencia: str) -> str:
    """Converte HDR (BT.2020, HLG ou PQ) para SDR BT.709 sem deixar a imagem lavada.

    Mobius mantém os tons médios (pele) praticamente iguais e só comprime os realces.
    Roda depois do corte e da escala, em 1080x1920, para custar menos.
    """
    return (
        f"setparams=color_primaries=bt2020:color_trc={transferencia}:colorspace=bt2020nc,"
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=mobius:param=0.6:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def _animacao(t: Trecho, larg: int, alt: int, W: int, H: int) -> str:
    """Zoom animado: amplia a imagem quadro a quadro e corta a janela que segue os olhos."""
    x0, y0, w0, _ = t.quadro_inicial
    x1, y1, w1, _ = t.quadro
    p = f"clip((t+{t.anim_decorrido:.3f})/{max(t.anim_duracao, 0.01):.3f},0,1)"
    e = "(" + _SUAVIZACAO[t.tipo].format(p=p) + ")"
    largura_janela = f"({w0}+({w1 - w0})*{e})"
    # Largura e altura da imagem ampliada, calculadas aqui: o crop guarda o tamanho do
    # primeiro quadro em in_w/in_h e não acompanha a escala que muda a cada quadro.
    largura_ampliada = f"(trunc({W}*{larg}/{largura_janela}/2)*2)"
    altura_ampliada = f"({largura_ampliada}*{H}/{W})"
    return (
        f"scale=w='{largura_ampliada}':h=-2:eval=frame:flags=lanczos,"
        f"crop=w={larg}:h={alt}:"
        f"x='clip(({x0}+({x1 - x0})*{e})*{largura_ampliada}/{W},0,{largura_ampliada}-{larg})':"
        f"y='clip(({y0}+({y1 - y0})*{e})*{altura_ampliada}/{H},0,{altura_ampliada}-{alt}-2)'"
    )


def renderizar(
    video: Path, trechos: list[Trecho], legendas_ass: Path | None, saida: Path,
    cfg_video: dict, fade_audio: float, dimensoes: tuple[int, int] | None = None,
    hdr: str | None = None,
) -> None:
    """hdr: curva de transferência do original (ver midia.transferencia_hdr); None se SDR."""
    larg, alt = cfg_video["largura"], cfg_video["altura"]
    cor = f",{_para_sdr(hdr)}" if hdr else ""
    filtros = []
    for i, t in enumerate(trechos):
        fade = min(fade_audio, t.duracao / 2)
        if t.quadro and t.quadro_inicial and t.tipo in _SUAVIZACAO and dimensoes:
            enquadramento = _animacao(t, larg, alt, *dimensoes)
        elif t.quadro:
            # Corte seco: janela fixa calculada a partir dos olhos (ver rosto.enquadrar).
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
            f"{enquadramento}{cor},setsar=1[v{i}]"
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
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(saida)],
        check=True,
    )
