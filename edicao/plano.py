"""Plano de cortes: quais trechos do vídeo original ficam no vídeo final."""

from dataclasses import dataclass

from .transcricao import Palavra


@dataclass
class Trecho:
    inicio: float
    fim: float

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
