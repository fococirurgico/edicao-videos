"""Plano de cortes: quais trechos do vídeo original ficam no vídeo final."""

from dataclasses import dataclass

from .transcricao import Palavra


@dataclass
class Trecho:
    inicio: float
    fim: float
    zoom: float = 1.0
    # Janela de corte (x, y, largura, altura) na imagem original; None = centralizado.
    quadro: tuple[int, int, int, int] | None = None
    # Modalidade do zoom: "seco", "suave" ou "rapido" (ver decisao.TIPOS_ZOOM).
    tipo: str = "seco"
    frase: int | None = None
    # Para "suave" e "rapido": janela no início da animação, quanto da animação já passou
    # quando o trecho começa e a duração total da animação (segundos).
    quadro_inicial: tuple[int, int, int, int] | None = None
    anim_decorrido: float = 0.0
    anim_duracao: float = 0.0
    # Nível de zoom de onde a animação parte (o do trecho anterior quando não há corte entre eles).
    zoom_inicial: float = 1.0

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


def trechos_mantidos(
    duracao_total: float, silencios: list[tuple[float, float]], folga: float
) -> list[Trecho]:
    """Complemento dos silêncios, com folga nas bordas e trechos sobrepostos unidos."""
    trechos: list[Trecho] = []
    cursor = 0.0
    for ini, fim in sorted(silencios):
        if ini > cursor:
            trechos.append(Trecho(cursor, ini))
        cursor = max(cursor, fim)
    if cursor < duracao_total:
        trechos.append(Trecho(cursor, duracao_total))

    unidos: list[Trecho] = []
    for t in trechos:
        t = Trecho(max(0.0, t.inicio - folga), min(duracao_total, t.fim + folga))
        if unidos and t.inicio <= unidos[-1].fim:
            unidos[-1].fim = max(unidos[-1].fim, t.fim)
        else:
            unidos.append(t)
    return [t for t in unidos if t.duracao > 0.05]


def aplicar_decisao(trechos: list[Trecho], frases, decisao, folga: float) -> list[Trecho]:
    """Corta as frases que o Claude mandou remover e aplica o zoom das frases escolhidas.

    Só sai o que foi explicitamente removido: áudio que a transcrição não captou continua no vídeo.
    """
    # 1. Intervalos a remover: cada frase descartada, estendida até perto das vizinhas.
    remover = []
    for i, f in enumerate(frases):
        if f.id in decisao.manter:
            continue
        ini = min(frases[i - 1].fim + folga, f.inicio) if i > 0 else f.inicio
        fim = max(frases[i + 1].inicio - folga, f.fim) if i + 1 < len(frases) else f.fim
        remover.append((ini, fim))

    # 2. Pontos de troca de zoom: fronteiras (meio da pausa) ao redor das frases com zoom.
    cortes = set()
    for i, f in enumerate(frases):
        if f.id in decisao.zoom:
            if i > 0:
                cortes.add((frases[i - 1].fim + f.inicio) / 2)
            if i + 1 < len(frases):
                cortes.add((f.fim + frases[i + 1].inicio) / 2)

    resultado: list[Trecho] = []
    for t in trechos:
        pedacos = [(t.inicio, t.fim)]
        for r_ini, r_fim in remover:
            pedacos = [p for a, b in pedacos
                       for p in ((a, min(b, r_ini)), (max(a, r_fim), b)) if p[1] - p[0] > 0.05]
        for a, b in pedacos:
            pontos = [a, *sorted(c for c in cortes if a < c < b), b]
            for x, y in zip(pontos, pontos[1:]):
                if y - x > 0.05:
                    fid = _frase_em((x + y) / 2, frases)
                    resultado.append(Trecho(
                        x, y, decisao.zoom.get(fid, 1.0),
                        tipo=decisao.tipo_zoom.get(fid, "seco") if fid in decisao.zoom else "seco",
                        frase=fid,
                    ))
    return resultado


def _frase_em(t: float, frases) -> int | None:
    for i, f in enumerate(frases):
        ini = (frases[i - 1].fim + f.inicio) / 2 if i > 0 else float("-inf")
        fim = (f.fim + frases[i + 1].inicio) / 2 if i + 1 < len(frases) else float("inf")
        if ini <= t < fim:
            return f.id
    return None


def aplicar_ritmo(trechos: list[Trecho], palavras: list[Palavra], plano_maximo: float,
                  variacao: float, zoom_maximo: float) -> list[Trecho]:
    """Padrão dos Reels: o enquadramento muda pelo menos a cada `plano_maximo` segundos.

    Trechos "seco" ou "rapido" mais longos que isso são divididos nos intervalos entre palavras
    mais próximos de cada `plano_maximo`; os pedaços seguintes alternam entre o nível do trecho
    e esse nível ± `variacao`, com aproximação rápida e suavizada (sem corte na fala, a troca
    é animada). O "suave" já se move a frase inteira e fica como está.
    """
    if plano_maximo <= 0 or variacao <= 0:
        return trechos
    resultado: list[Trecho] = []
    for t in trechos:
        if t.tipo == "suave" or t.duracao <= plano_maximo * 1.3:
            resultado.append(t)
            continue
        vaos = [(a.fim + b.inicio) / 2 for a, b in zip(palavras, palavras[1:])
                if t.inicio + 1.0 < (a.fim + b.inicio) / 2 < t.fim - 1.0]
        pontos, ultimo = [], t.inicio
        while ultimo + plano_maximo < t.fim - plano_maximo / 2:
            candidatos = [v for v in vaos if v > ultimo + 1.2]
            if not candidatos:
                break
            ultimo = min(candidatos, key=lambda v: abs(v - (ultimo + plano_maximo)))
            pontos.append(ultimo)
        limites = [t.inicio, *pontos, t.fim]
        alto = t.zoom + variacao if t.zoom + variacao <= zoom_maximo else max(1.0, t.zoom - variacao)
        for k, (a, b) in enumerate(zip(limites, limites[1:])):
            nivel = round(alto if k % 2 else t.zoom, 2)
            resultado.append(Trecho(a, b, nivel, tipo="rapido" if k else t.tipo, frase=t.frase))
    return resultado


def saltar_nos_cortes(trechos: list[Trecho], salto: float, zoom_maximo: float) -> None:
    """Quando um trecho "seco" começa logo após um corte e ficaria no mesmo nível do anterior,
    o nível muda em `salto` (sobe; se passar do máximo, desce): o corte vira um salto de
    enquadramento, como nos Reels, e não um tranco."""
    if salto <= 0:
        return
    for anterior, t in zip(trechos, trechos[1:]):
        houve_corte = t.inicio - anterior.fim > 0.05
        if houve_corte and t.tipo == anterior.tipo == "seco" and abs(t.zoom - anterior.zoom) < 0.01:
            subir = anterior.zoom + salto
            t.zoom = round(subir if subir <= zoom_maximo else max(1.0, anterior.zoom - salto), 2)


def planejar_movimento(trechos: list[Trecho], duracao_rapido: float,
                       salto_nos_cortes: float, zoom_maximo: float) -> None:
    """Prepara as animações e os saltos de enquadramento (altera os trechos no lugar).

    - Corte seco: ver saltar_nos_cortes (0 desliga, para quem já chamou antes do ritmo).
    - "suave": a animação atravessa a frase inteira, mesmo que ela tenha sido dividida
      por cortes de silêncio; cada pedaço continua de onde o anterior parou.
    - "rapido": a animação dura `duracao_rapido` segundos a partir do início da frase.
    - A animação parte do nível do trecho anterior se não houver corte entre eles (o
      movimento continua sem salto); depois de um corte, parte de 1,0.
    """
    saltar_nos_cortes(trechos, salto_nos_cortes, zoom_maximo)

    total: dict[int, float] = {}
    for t in trechos:
        if t.tipo == "suave":
            total[t.frase] = total.get(t.frase, 0.0) + t.duracao
    decorrido: dict[int, float] = {}
    partida: dict = {}
    for i, t in enumerate(trechos):
        if t.tipo not in ("suave", "rapido"):
            continue
        chave = (t.frase, t.tipo) if t.tipo == "suave" else id(t)
        if chave not in partida:
            anterior = trechos[i - 1] if i > 0 else None
            continuo = anterior is not None and t.inicio - anterior.fim <= 0.05
            partida[chave] = anterior.zoom if continuo else 1.0
        t.zoom_inicial = partida[chave]
        if t.tipo == "suave":
            t.anim_decorrido = decorrido.get(t.frase, 0.0)
            t.anim_duracao = total[t.frase]
            decorrido[t.frase] = t.anim_decorrido + t.duracao
        else:
            t.anim_duracao = duracao_rapido


def remapear_tempo(tempo: float, trechos: list[Trecho]) -> float | None:
    """Instante do vídeo original na linha do tempo do vídeo cortado; None se foi cortado."""
    deslocamento = 0.0
    for t in trechos:
        if t.inicio <= tempo <= t.fim:
            return tempo - t.inicio + deslocamento
        deslocamento += t.duracao
    return None


def remapear(palavras: list[Palavra], trechos: list[Trecho]) -> list[Palavra]:
    """Leva os tempos das palavras para a linha do tempo do vídeo cortado.

    Palavras cujo meio cai fora de todos os trechos mantidos são descartadas.
    """
    resultado = []
    for p in palavras:
        meio = (p.inicio + p.fim) / 2
        deslocamento = 0.0
        for t in trechos:
            if t.inicio <= meio <= t.fim:
                ini = max(p.inicio, t.inicio) - t.inicio + deslocamento
                fim = min(p.fim, t.fim) - t.inicio + deslocamento
                resultado.append(Palavra(p.texto, ini, fim))
                break
            deslocamento += t.duracao
    return resultado
