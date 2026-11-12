"""Põe um logo translúcido (marca d'água) no vídeo inteiro, depois do render (fora do editor).

    PATH=~/edicao-videos/bin:$PATH .venv/bin/python ferramentas/marca_dagua.py \
        ENTRADA SAIDA LOGO.png [--previa] [--opacidade 0.35] [--largura 210] [--x 56] [--y 250]

LOGO: PNG com transparência (o monograma do Foco em branco foi feito do PNG preto com
`format=gray,negate` como alfa). Posição e largura em pixels de um vídeo 1080x1920 (escalam com a
resolução, para servir também à prévia de 540x960). Primeiro uso: vídeo do Foco Cirúrgico de
12/11/2026 (monograma f::c branco, 35%, 210 px, canto superior esquerdo, abaixo da faixa dos
ícones do Instagram e dentro do recorte 3:4 da grade). Em HDR o branco vai a ~80% do sinal HLG
para não estourar. Recodifica com `render._codificacao`, a mesma do editor.
"""
import argparse
import subprocess
from pathlib import Path

from edicao import config, midia, render

ap = argparse.ArgumentParser()
ap.add_argument("entrada", type=Path)
ap.add_argument("saida", type=Path)
ap.add_argument("logo", type=Path)
ap.add_argument("--previa", action="store_true", help="codifica pelo chip, como a prévia")
ap.add_argument("--opacidade", type=float, default=0.35)
ap.add_argument("--largura", type=int, default=210)
ap.add_argument("--x", type=int, default=56)
ap.add_argument("--y", type=int, default=250)
a = ap.parse_args()

largura_video, _ = midia.dimensoes(a.entrada)
k = largura_video / 1080
hdr = midia.transferencia_hdr(a.entrada)
cv = dict(config.carregar()["video"])
if a.previa:
    cv.update(codec_hdr="hevc_videotoolbox", taxa_videotoolbox="6M")
cod = render._codificacao(cv, hdr, midia.fps(a.entrada))
brilho = 0.8 if hdr else 1.0
f = (f"[1:v]scale={round(a.largura * k / 2) * 2}:-1,format=rgba,"
     f"colorchannelmixer=rr={brilho}:gg={brilho}:bb={brilho}:aa={a.opacidade}[m];"
     f"[0:v][m]overlay={round(a.x * k)}:{round(a.y * k)}:format={'yuv420p10' if hdr else 'yuv420'}[v]")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(a.entrada), "-i", str(a.logo),
                "-filter_complex", f, "-map", "[v]", "-map", "0:a", "-c:a", "copy", *cod,
                "-movflags", "+faststart", str(a.saida)], check=True)
print("pronto:", a.saida)
