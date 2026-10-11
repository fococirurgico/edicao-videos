"""Legendas em ASS com a palavra falada no momento destacada."""

import re

from .transcricao import Palavra


def _cor_ass(hex_rgb: str) -> str:
    r, g, b = hex_rgb.lstrip("#")[0:2], hex_rgb.lstrip("#")[2:4], hex_rgb.lstrip("#")[4:6]
    return f"&H00{b}{g}{r}".upper()


def _tempo(t: float) -> str:
    cs = round(max(0.0, t) * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _normalizar(texto: str) -> str:
    return re.sub(r"[^\w]", "", texto.lower())


def _escapar(texto: str) -> str:
    return texto.replace("\\", "").replace("{", "(").replace("}", ")")


def gerar_ass(
    palavras: list[Palavra], cfg: dict, largura: int, altura: int,
    destaques: set[str] | None = None,
) -> str:
    """Divide as palavras em blocos curtos e cria um evento por palavra falada.

    Em cada evento o bloco inteiro aparece, com a palavra atual em `cor_palavra_atual`.
    Palavras em `destaques` aparecem sempre em `cor_destaque`.
    """
    destaques = {_normalizar(d) for d in (destaques or set())}
    cor_atual = _cor_ass(cfg["cor_palavra_atual"])
    cor_destaque = _cor_ass(cfg["cor_destaque"])

    cabecalho = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Padrao,{cfg["fonte"]},{cfg["tamanho"]},{_cor_ass(cfg["cor"])},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{cfg["contorno"]},0,2,60,60,{cfg["margem_inferior"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = []
    n = cfg["palavras_por_linha"]
    for b in range(0, len(palavras), n):
        bloco = palavras[b:b + n]
        for i, atual in enumerate(bloco):
            fim = bloco[i + 1].inicio if i + 1 < len(bloco) else atual.fim
            partes = []
            for j, p in enumerate(bloco):
                texto = _escapar(p.texto.upper())
                if j == i:
                    partes.append(f"{{\\c{cor_atual}}}{texto}{{\\r}}")
                elif _normalizar(p.texto) in destaques:
                    partes.append(f"{{\\c{cor_destaque}}}{texto}{{\\r}}")
                else:
                    partes.append(texto)
            eventos.append(
                f"Dialogue: 0,{_tempo(atual.inicio)},{_tempo(max(fim, atual.inicio + 0.05))},"
                f"Padrao,,0,0,0,,{' '.join(partes)}"
            )
    return cabecalho + "\n".join(eventos) + "\n"
