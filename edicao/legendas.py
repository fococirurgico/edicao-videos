"""Legendas em ASS: uma palavra por vez (padrão) ou blocos com a palavra falada destacada."""

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
    palavras: list[Palavra], cfg: dict, marca: dict, largura: int, altura: int,
    destaques: set[str] | None = None, graficos: list[str] | None = None,
    estilos_extras: list[str] | None = None,
) -> str:
    """Cria um evento por palavra falada.

    cfg: seção [legendas] (tamanho e posição); marca: seção [marca] (fonte e cores).
    Com `palavras_por_linha` = 1, só a palavra dita aparece, em `cor_texto`, entrando com um
    "pop" (cresce um pouco além do tamanho e assenta); as de `destaques` ficam maiores.
    Com mais de 1, o bloco inteiro aparece, com a palavra atual em `cor_palavra_atual` e as
    de `destaques` em `cor_destaque`.
    graficos/estilos_extras: eventos e estilos dos elementos gráficos (ver graficos.py).
    """
    destaques = {_normalizar(d) for d in (destaques or set())}
    cor_atual = _cor_ass(marca["cor_palavra_atual"])
    cor_destaque = _cor_ass(marca["cor_destaque"])

    cabecalho = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Padrao,{marca["fonte"]},{cfg["tamanho"]},{_cor_ass(marca["cor_texto"])},&H000000FF,{_cor_ass(marca["cor_contorno"])},&H80000000,{-1 if marca.get("negrito", True) else 0},{-1 if marca.get("italico") else 0},0,0,100,100,0,0,1,{cfg["contorno"]},{cfg.get("sombra", 0)},2,60,60,{cfg["margem_inferior"]},1
{chr(10).join(estilos_extras or [])}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = list(graficos or [])
    n = cfg["palavras_por_linha"]
    if n <= 1:
        eventos += _uma_por_vez(palavras, destaques, cfg)
        return cabecalho + "\n".join(eventos) + "\n"
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


def _uma_por_vez(palavras: list[Palavra], destaques: set[str], cfg: dict) -> list[str]:
    """A palavra fica na tela até a próxima começar; numa pausa longa, some logo depois de dita."""
    eventos = []
    for i, p in enumerate(palavras):
        proxima = palavras[i + 1].inicio if i + 1 < len(palavras) else None
        fim = p.fim + 0.25
        if proxima is not None and (proxima - p.fim < 0.4 or fim > proxima):
            fim = proxima
        fim = max(fim, p.inicio + 0.08)
        final = cfg.get("escala_destaque", 125) if _normalizar(p.texto) in destaques else 100
        pop = ""
        if cfg.get("animacao", True):
            pop = (f"\\fscx{final * 0.72:.0f}\\fscy{final * 0.72:.0f}"
                   f"\\t(0,70,0.6,\\fscx{final * 1.08:.0f}\\fscy{final * 1.08:.0f})"
                   f"\\t(70,150,1.5,\\fscx{final}\\fscy{final})")
        elif final != 100:
            pop = f"\\fscx{final}\\fscy{final}"
        texto = _escapar(p.texto.upper())
        eventos.append(f"Dialogue: 0,{_tempo(p.inicio)},{_tempo(fim)},Padrao,,0,0,0,,"
                       + (f"{{{pop}}}" if pop else "") + texto)
    return eventos
