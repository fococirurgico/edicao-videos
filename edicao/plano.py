"""Plano de cortes: quais trechos do vídeo original ficam no vídeo final."""

from dataclasses import dataclass

from .transcricao import Palavra


@dataclass
class Trecho:
    inicio: float
    fim: float
    zoom: float = 1.0

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
                    resultado.append(Trecho(x, y, _zoom_em((x + y) / 2, frases, decisao)))
    return resultado


def _zoom_em(t: float, frases, decisao) -> float:
    for i, f in enumerate(frases):
        ini = (frases[i - 1].fim + f.inicio) / 2 if i > 0 else float("-inf")
        fim = (f.fim + frases[i + 1].inicio) / 2 if i + 1 < len(frases) else float("inf")
        if ini <= t < fim:
            return decisao.zoom.get(f.id, 1.0)
    return 1.0


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
