"""Elementos gráficos animados: o título do Reels no início e cartões ao longo da fala.

Tudo vira eventos ASS desenhados pelo libass, no mesmo arquivo da legenda. A animação é feita
quadro a quadro: para cada quadro do vídeo há um evento com posição, escala, opacidade e forma
calculadas por curvas de aceleração (inclusive mola com ultrapassagem). O libass posiciona com
fração de pixel, então o movimento sai liso, sem os degraus do crop do ffmpeg.

Os elementos usam a fonte e as cores da marca ([marca] e [graficos] da configuração).
"""

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

TIPOS = ("numero", "frase", "check", "alerta")


@dataclass
class Elemento:
    tipo: str          # "titulo", "pergunta" ou um de TIPOS
    texto: str
    detalhe: str
    inicio: float      # segundos, na linha do tempo do vídeo editado
    fim: float


# Curvas (p de 0 a 1)

def _limitar(p: float) -> float:
    return min(1.0, max(0.0, p))


def _saida_cubica(p: float) -> float:
    return 1 - (1 - _limitar(p)) ** 3


def _mola(p: float, ultrapassa: float = 1.70158) -> float:
    """Chega ao destino passando um pouco dele e voltando (easeOutBack)."""
    p = _limitar(p) - 1
    return 1 + (ultrapassa + 1) * p ** 3 + ultrapassa * p ** 2


def _fase(t: float, ini: float, dur: float) -> float:
    return _limitar((t - ini) / dur)


# Medida do texto, para dimensionar os cartões

@lru_cache(maxsize=8)
def _metricas(arquivo: str):
    from fontTools.ttLib import TTFont
    fonte = TTFont(arquivo, lazy=True)
    os2 = fonte["OS/2"]
    altura = os2.usWinAscent + os2.usWinDescent        # o libass usa a altura "win" como tamanho
    return fonte.getBestCmap(), fonte["hmtx"].metrics, altura


def _arquivo_peso(arquivo_fonte: str, peso: int) -> str | None:
    """Arquivo da mesma família com o peso pedido, se estiver na mesma pasta."""
    if not arquivo_fonte or not Path(arquivo_fonte).exists():
        return None
    nomes = {800: ("ExtraBold", "Heavy", "Black"), 700: ("Bold",), 600: ("SemiBold", "DemiBold")}
    pasta = Path(arquivo_fonte).parent
    familia = Path(arquivo_fonte).stem.split("-")[0]
    for sufixo in nomes.get(peso, ()):
        for ext in (".ttf", ".otf"):
            candidato = pasta / f"{familia}-{sufixo}{ext}"
            if candidato.exists():
                return str(candidato)
    return arquivo_fonte


def largura_texto(texto: str, tamanho: float, arquivo_fonte: str = "", peso: int = 700) -> float:
    arquivo = _arquivo_peso(arquivo_fonte, peso)
    if not arquivo:
        return len(texto) * tamanho * 0.42           # estimativa para fontes sem arquivo
    cmap, avancos, altura = _metricas(arquivo)
    unidades = sum(avancos.get(cmap.get(ord(c), ".notdef"), (altura * 0.3, 0))[0] for c in texto)
    return unidades * tamanho / altura


def quebrar(texto: str, tamanho: float, largura_max: float, arquivo_fonte: str, peso: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if atual and largura_texto(tentativa, tamanho, arquivo_fonte, peso) > largura_max:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    return linhas + ([atual] if atual else [])


# Formas (desenho ASS em pixels, origem no canto superior esquerdo da forma)

def _retangulo(w: float, h: float, r: float) -> str:
    r = min(r, w / 2, h / 2)
    k = r * 0.4477                                       # aproximação de quarto de círculo por Bézier
    return (f"m {r:.1f} 0 l {w - r:.1f} 0 b {w - k:.1f} 0 {w:.1f} {k:.1f} {w:.1f} {r:.1f} "
            f"l {w:.1f} {h - r:.1f} b {w:.1f} {h - k:.1f} {w - k:.1f} {h:.1f} {w - r:.1f} {h:.1f} "
            f"l {r:.1f} {h:.1f} b {k:.1f} {h:.1f} 0 {h - k:.1f} 0 {h - r:.1f} "
            f"l 0 {r:.1f} b 0 {k:.1f} {k:.1f} 0 {r:.1f} 0")


def _retangulo_topo(w: float, h: float, r: float) -> str:
    """Retângulo com só os cantos de cima arredondados."""
    r = min(r, w / 2, h)
    k = r * 0.4477
    return (f"m {r:.1f} 0 l {w - r:.1f} 0 b {w - k:.1f} 0 {w:.1f} {k:.1f} {w:.1f} {r:.1f} "
            f"l {w:.1f} {h:.1f} l 0 {h:.1f} l 0 {r:.1f} b 0 {k:.1f} {k:.1f} 0 {r:.1f} 0")


def _circulo(d: float) -> str:
    return _retangulo(d, d, d / 2)


def _triangulo(lado: float) -> str:
    h = lado * 0.866
    return f"m {lado / 2:.1f} 0 l {lado:.1f} {h:.1f} l 0 {h:.1f}"


def _traco(pontos: list[tuple[float, float]], espessura: float, fracao: float) -> str:
    """Linha grossa que se desenha aos poucos (fracao de 0 a 1 do comprimento)."""
    segmentos = list(zip(pontos, pontos[1:]))
    total = sum(math.dist(a, b) for a, b in segmentos)
    resta = total * _limitar(fracao)
    partes = []
    for (ax, ay), (bx, by) in segmentos:
        comp = math.dist((ax, ay), (bx, by))
        if resta <= 0.5:
            break
        f = min(1.0, resta / comp)
        bx, by = ax + (bx - ax) * f, ay + (by - ay) * f
        resta -= comp
        nx, ny = -(by - ay), bx - ax
        n = math.hypot(nx, ny) or 1
        nx, ny = nx / n * espessura / 2, ny / n * espessura / 2
        partes.append(f"m {ax + nx:.1f} {ay + ny:.1f} l {bx + nx:.1f} {by + ny:.1f} "
                      f"l {bx - nx:.1f} {by - ny:.1f} l {ax - nx:.1f} {ay - ny:.1f}")
        # junta arredondada entre os segmentos
        partes.append(" ".join(_circulo_em(bx, by, espessura / 2)))
    return " ".join(partes)


def _circulo_em(cx: float, cy: float, r: float) -> list[str]:
    k = r * 0.5523
    return [f"m {cx:.1f} {cy - r:.1f} b {cx + k:.1f} {cy - r:.1f} {cx + r:.1f} {cy - k:.1f} {cx + r:.1f} {cy:.1f}",
            f"b {cx + r:.1f} {cy + k:.1f} {cx + k:.1f} {cy + r:.1f} {cx:.1f} {cy + r:.1f}",
            f"b {cx - k:.1f} {cy + r:.1f} {cx - r:.1f} {cy + k:.1f} {cx - r:.1f} {cy:.1f}",
            f"b {cx - r:.1f} {cy - k:.1f} {cx - k:.1f} {cy - r:.1f} {cx:.1f} {cy - r:.1f}"]


# Camadas e emissão quadro a quadro

def _cor(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _alfa(opacidade: float) -> str:
    return f"&H{255 - round(255 * _limitar(opacidade)):02X}&"


@dataclass
class Camada:
    """Uma forma ou texto centrado em (dx, dy) relativo ao centro do grupo."""
    dx: float
    dy: float
    cor: str
    opacidade: float = 1.0
    desenho: str = ""        # forma ASS; vazio = texto
    texto: str = ""
    tamanho: float = 0
    peso: int = 700
    escala: float = 1.0      # escala própria (além da do grupo)
    giro: float = 0.0
    camada: int = 1
    # Tamanho da área do desenho (largura, altura): posiciona pelo canto, e não pelo contorno
    # do desenho (que muda enquanto um traço é desenhado aos poucos).
    caixa: tuple[float, float] | None = None
    fonte: str = ""          # família da fonte; vazio = a da marca (estilo Grafico)


def _linha(c: Camada, cx: float, cy: float, escala_grupo: float, opacidade_grupo: float) -> str:
    e = escala_grupo * c.escala
    x, y = cx + c.dx * escala_grupo, cy + c.dy * escala_grupo
    if c.caixa:
        ancora = f"\\an7\\pos({x - c.caixa[0] / 2 * e:.2f},{y - c.caixa[1] / 2 * e:.2f})"
    else:
        ancora = f"\\an5\\pos({x:.2f},{y:.2f})"
    tags = (f"{ancora}\\fscx{e * 100:.2f}\\fscy{e * 100:.2f}"
            f"\\bord0\\shad0\\1c{c.cor}\\alpha{_alfa(c.opacidade * opacidade_grupo)}")
    if c.giro:
        tags += f"\\org({x:.2f},{y:.2f})\\frz{c.giro:.2f}"
    if c.desenho:
        desenho = c.desenho
        if c.caixa:
            # O libass alinha pelo contorno do desenho: dois pontos minúsculos nos cantos
            # fixam o contorno no tamanho da caixa.
            w, h = c.caixa
            desenho = (f"m 0 0 l 0.01 0 l 0 0.01 m {w:.1f} {h:.1f} l {w - 0.01:.2f} {h:.1f} "
                       f"l {w:.1f} {h - 0.01:.2f} {desenho}")
        return f"{{{tags}\\p1}}{desenho}{{\\p0}}"
    fonte = f"\\fn{c.fonte}" if c.fonte else ""
    return f"{{{tags}{fonte}\\fs{c.tamanho:.0f}\\b{c.peso}}}{c.texto}"


def _tempo(t: float) -> str:
    cs = round(max(0.0, t) * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class Desenhista:
    def __init__(self, cfg: dict, marca: dict, largura: int, altura: int, fps: Fraction):
        self.cfg, self.marca, self.fps = cfg, marca, fps
        self.W, self.H = largura, altura
        self.fonte = marca.get("arquivo_fonte", "")
        self.cartao = _cor(marca.get("cor_cartao", "#FFFFFF"))
        self.texto_cartao = _cor(marca.get("cor_texto_cartao", "#111111"))
        self.escuro = _cor(marca.get("cor_cartao_escuro", "#111111"))
        self.texto_escuro = _cor(marca.get("cor_texto_escuro", "#FFFFFF"))
        self.acento = _cor(marca.get("cor_acento", marca.get("cor_destaque", "#FFD400")))

    def eventos(self, el: Elemento) -> list[str]:
        montar = getattr(self, f"_{el.tipo}")
        estado = montar(el)
        y = {"titulo": self.cfg["altura_titulo"],
             "pergunta": self.cfg.get("altura_pergunta", 520)}.get(el.tipo, self.cfg["altura_elementos"])
        cx = self.W / 2
        linhas = []
        primeiro = math.ceil(el.inicio * self.fps)
        ultimo = math.ceil(el.fim * self.fps)            # exclusivo: o próximo pode começar ali
        for n in range(primeiro, ultimo):
            t = float(n / self.fps)
            rel, dur = t - el.inicio, el.fim - el.inicio
            camadas, dx, dy, escala, opac = estado(rel, dur)
            ini, fim = float((n - Fraction(1, 2)) / self.fps), float((n + Fraction(1, 2)) / self.fps)
            for c in camadas:
                linhas.append(f"Dialogue: {c.camada + 10},{_tempo(ini)},{_tempo(fim)},Grafico,,0,0,0,,"
                              + _linha(c, cx + dx, y + dy, escala, opac))
        return linhas

    # Entrada, flutuação leve e saída, comuns a todos

    def _grupo(self, rel: float, dur: float, de_lado: bool = False):
        entrada = _fase(rel, 0, 0.5)
        saida = _fase(rel, dur - 0.32, 0.32)
        escala = 0.72 + 0.28 * _mola(entrada) - 0.06 * _saida_cubica(saida)
        opac = _saida_cubica(entrada / 0.6) * (1 - _saida_cubica(saida))
        flutua = 5 * math.sin(2 * math.pi * rel / 3.2) * entrada
        desloc = (1 - _saida_cubica(entrada)) * 70
        dx = -desloc if de_lado else 0
        dy = (0 if de_lado else desloc) + flutua - 28 * _saida_cubica(saida)
        return dx, dy, escala, opac

    def _titulo(self, el: Elemento):
        tam, pad_x, pad_y = self.cfg["tamanho_titulo"], 54, 34
        linhas = quebrar(el.texto, tam, self.W * 0.78, self.fonte, 800)
        larg = max(largura_texto(l, tam, self.fonte, 800) for l in linhas) + 2 * pad_x
        alt = len(linhas) * tam + 2 * pad_y + 14
        fundo = _retangulo(larg, alt, 30)

        def estado(rel, dur):
            dx, dy, escala, opac = self._grupo(rel, dur)
            barra = _saida_cubica(_fase(rel, 0.25, 0.55)) * (larg - 2 * pad_x)
            camadas = [
                Camada(0, 0, self.cartao, 0.97, desenho=fundo, camada=0),
                Camada(0, -7, self.texto_cartao, texto="\\N".join(linhas), tamanho=tam, peso=800),
            ]
            if barra > 1:
                camadas.append(Camada(0, alt / 2 - pad_y / 2 - 6, self.acento, desenho=_retangulo(barra, 8, 4)))
            return camadas, dx, dy, escala, opac
        return estado

    def _pergunta(self, el: Elemento):
        """Caixinha de pergunta do Instagram, só texto em preto e branco: faixa com o convite e a
        pergunta digitada. Na fonte do Instagram (a do sistema do iPhone; no Mac, a Helvetica Neue
        é a mais próxima que o libass acha), não na da marca. A quebra de linha usa a medida da fonte
        da marca, mais larga, e por isso nunca estoura a caixa."""
        fonte = self.cfg.get("fonte_pergunta", "Helvetica Neue")
        larg, raio, tam_c, tam = self.W * 0.8, 44, 50, 76
        faixa, pad = 120, 52
        linhas = quebrar(el.texto, tam, larg - 2 * pad, self.fonte, 700)
        corpo = len(linhas) * tam * 1.12 + 2 * pad
        alt = faixa + corpo
        topo = -alt / 2
        convite = el.detalhe or "Faça uma pergunta"
        total = sum(len(l) for l in linhas)
        branco, preto = _cor("#FFFFFF"), _cor("#000000")

        def digitada(n):
            """Letras ainda não digitadas ficam transparentes, para o centro não se mexer."""
            texto = "\\N".join(linhas)
            i, contadas = 0, 0
            while i < len(texto) and contadas < n:
                i += 2 if texto.startswith("\\N", i) else 1
                contadas += 0 if texto[i - 2:i] == "\\N" else 1
            return texto if i >= len(texto) else texto[:i] + "{\\1a&HFF&}" + texto[i:]

        def estado(rel, dur):
            dx, dy, escala, opac = self._grupo(rel, dur)
            letras = round(total * _limitar((rel - 0.55) / max(0.6, total * 0.035)))
            camadas = [
                Camada(0, 6, preto, 0.18, desenho=_retangulo(larg, alt, raio), camada=0),
                Camada(0, 0, branco, desenho=_retangulo(larg, alt, raio), camada=1),
                Camada(0, topo + faixa / 2, preto, desenho=_retangulo_topo(larg, faixa, raio), camada=2),
                Camada(0, topo + faixa / 2, branco, texto=convite, tamanho=tam_c, peso=600, camada=3,
                       fonte=fonte),
                Camada(0, topo + faixa + corpo / 2, preto, texto=digitada(letras), tamanho=tam, peso=700,
                       camada=3, fonte=fonte),
            ]
            return camadas, dx, dy, escala, opac
        return estado

    def _numero(self, el: Elemento):
        tam, tam_d, pad = 190, 66, 46
        linhas_d = quebrar(el.detalhe, tam_d, self.W * 0.72, self.fonte, 600) if el.detalhe else []
        larg_n = largura_texto(el.texto, tam, self.fonte, 800)
        larg = max([larg_n, *(largura_texto(l, tam_d, self.fonte, 600) for l in linhas_d)]) + 2 * pad
        alt = tam * 0.95 + len(linhas_d) * tam_d * 1.05 + 2 * pad
        fundo = _retangulo(larg, alt, 36)
        m = re.match(r"^(\D*?)(\d+(?:[.,]\d+)?)(.*)$", el.texto)

        def contagem(rel):
            if not m:
                return el.texto
            antes, numero, depois = m.groups()
            separador = "," if "," in numero else "."
            casas = len(numero.split(separador)[1]) if separador in numero else 0
            valor = float(numero.replace(",", ".")) * _saida_cubica(_fase(rel, 0.1, 0.8))
            texto = f"{valor:.{casas}f}".replace(".", separador)
            return f"{antes}{texto}{depois}"

        def estado(rel, dur):
            dx, dy, escala, opac = self._grupo(rel, dur)
            topo = -alt / 2 + pad
            camadas = [
                Camada(0, 0, self.escuro, 0.93, desenho=fundo, camada=0),
                Camada(0, topo + tam * 0.45, self.acento, texto=contagem(rel), tamanho=tam, peso=800),
            ]
            if linhas_d:
                surge = _saida_cubica(_fase(rel, 0.3, 0.4))
                camadas.append(Camada(0, topo + tam * 0.95 + len(linhas_d) * tam_d * 0.5 + (1 - surge) * 16,
                                      self.texto_escuro, surge, texto="\\N".join(linhas_d),
                                      tamanho=tam_d, peso=600))
            return camadas, dx, dy, escala, opac
        return estado

    def _frase(self, el: Elemento):
        tam, pad_x, pad_y, barra_l = 76, 50, 34, 14
        linhas = quebrar(el.texto, tam, self.W * 0.74, self.fonte, 700)
        larg = max(largura_texto(l, tam, self.fonte, 700) for l in linhas) + 2 * pad_x + barra_l
        alt = len(linhas) * tam + 2 * pad_y
        fundo = _retangulo(larg, alt, 26)

        def estado(rel, dur):
            dx, dy, escala, opac = self._grupo(rel, dur, de_lado=True)
            h = _saida_cubica(_fase(rel, 0.2, 0.45)) * (alt - 24)
            camadas = [
                Camada(0, 0, self.cartao, 0.97, desenho=fundo, camada=0),
                Camada(barra_l / 2, 0, self.texto_cartao, texto="\\N".join(linhas), tamanho=tam, peso=700),
            ]
            if h > 1:
                camadas.append(Camada(-larg / 2 + 22, 0, self.acento, desenho=_retangulo(barra_l, h, 6)))
            return camadas, dx, dy, escala, opac
        return estado

    def _icone_e_texto(self, el: Elemento, desenhar_icone):
        tam, pad, icone = 70, 36, 120
        linhas = quebrar(el.texto, tam, self.W * 0.58, self.fonte, 700)
        larg_t = max(largura_texto(l, tam, self.fonte, 700) for l in linhas)
        larg = icone + 26 + larg_t + 2 * pad
        alt = max(icone, len(linhas) * tam) + 2 * pad
        fundo = _retangulo(larg, alt, alt / 2 if len(linhas) == 1 else 34)
        x_icone = -larg / 2 + pad + icone / 2
        x_texto = x_icone + icone / 2 + 26 + larg_t / 2

        def estado(rel, dur):
            dx, dy, escala, opac = self._grupo(rel, dur)
            surge = _saida_cubica(_fase(rel, 0.2, 0.4))
            camadas = [Camada(0, 0, self.escuro, 0.93, desenho=fundo, camada=0),
                       *desenhar_icone(rel, x_icone, icone),
                       Camada(x_texto + (1 - surge) * 30, 0, self.texto_escuro, surge,
                              texto="\\N".join(linhas), tamanho=tam, peso=700)]
            return camadas, dx, dy, escala, opac
        return estado

    def _check(self, el: Elemento):
        def icone(rel, x, d):
            pop = _mola(_fase(rel, 0.05, 0.4), 1.8)
            pontos = [(d * 0.27, d * 0.52), (d * 0.44, d * 0.68), (d * 0.74, d * 0.36)]
            traco = _traco(pontos, d * 0.11, _saida_cubica(_fase(rel, 0.3, 0.35)))
            camadas = [Camada(x, 0, self.acento, desenho=_circulo(d), escala=max(0.01, pop),
                              caixa=(d, d), camada=1)]
            if traco:
                camadas.append(Camada(x, 0, self.escuro, desenho=traco, escala=max(0.01, pop),
                                      caixa=(d, d), camada=2))
            return camadas
        return self._icone_e_texto(el, icone)

    def _alerta(self, el: Elemento):
        def icone(rel, x, d):
            pop = _mola(_fase(rel, 0.05, 0.4), 1.8)
            balanco = 9 * math.sin(rel * 22) * math.exp(-rel * 4) if rel > 0.2 else 0
            lado = d * 1.05
            camadas = [Camada(x, 0, self.acento, desenho=_triangulo(lado), escala=max(0.01, pop),
                              giro=balanco, caixa=(lado, lado * 0.866), camada=1),
                       Camada(x, d * 0.08, self.escuro, texto="!", tamanho=d * 0.62, peso=800,
                              escala=max(0.01, pop), giro=balanco, camada=2)]
            return camadas
        return self._icone_e_texto(el, icone)


def estilo(marca: dict) -> str:
    return (f"Style: Grafico,{marca['fonte']},60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1")


def limpar(texto: str) -> str:
    """Texto seguro para o ASS (chaves e barras viram comandos)."""
    return re.sub(r"\s+", " ", texto.replace("\\", " ").replace("{", "(").replace("}", ")")).strip()


def gerar(elementos: list[Elemento], cfg: dict, marca: dict, largura: int, altura: int,
          fps: Fraction) -> list[str]:
    d = Desenhista(cfg, marca, largura, altura, fps)
    linhas = []
    for el in elementos:
        linhas += d.eventos(el)
    return linhas


def programar(titulo: str, pedidos: list[tuple[str, str, str, float, float]], cfg: dict,
              duracao_video: float, pergunta: str = "") -> list[Elemento]:
    """Monta a lista final: título no início e os elementos sem se sobrepor.

    pedidos: (tipo, texto, detalhe, início e fim das palavras em que o assunto é dito), já na
    linha do tempo editada. Cada elemento entra 0,15 s antes dessas palavras e dura entre
    `duracao_minima` e `duracao_maxima`; um que cairia sobre o anterior é atrasado até 1 s ou
    descartado (cartão fora do momento da fala parece desconectado). `pergunta` abre o vídeo com a caixinha de
    pergunta do Instagram no lugar do título.
    """
    resultado = []
    livre = 0.0
    if pergunta:
        fim = min(cfg.get("duracao_pergunta", 4.5), duracao_video)
        resultado.append(Elemento("pergunta", pergunta, "", 0.0, fim))
        livre = fim + 0.4
    elif titulo and cfg.get("titulo", True):
        fim = min(cfg["duracao_titulo"], duracao_video)
        resultado.append(Elemento("titulo", titulo, "", 0.0, fim))
        livre = fim + 0.4
    if not cfg.get("elementos", True):
        return resultado
    for tipo, texto, detalhe, dito, fim_dito in sorted(pedidos, key=lambda p: p[3]):
        # Entra um pouco antes da palavra (o olho chega antes do ouvido) e fica até depois dela.
        ini = max(dito - 0.15, livre, 0.0)
        if ini - dito > 1.0:            # atrasado demais: fora de contexto, melhor não mostrar
            continue
        fim = min(max(fim_dito + 1.5, ini + cfg["duracao_minima"]), ini + cfg["duracao_maxima"],
                  duracao_video)
        if fim - ini < cfg["duracao_minima"] * 0.8:
            continue
        resultado.append(Elemento(tipo, texto, detalhe, ini, fim))
        livre = fim + cfg["intervalo_minimo"]
    return resultado
