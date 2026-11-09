"""Checagem antes de renderizar: os erros de corte que só apareciam no vídeo pronto.

1. Voz sem palavra: trecho com voz no áudio e nenhuma palavra transcrita. É a tomada refeita
   que o Whisper engoliu (juntou as duas tentativas numa frase só, com os tempos da primeira):
   o editor fica com a tentativa abandonada e descarta a boa (IMG_4539, 09/11/2026).
2. Palavra cortada: um corte que cai no meio de uma palavra, ou depois do qual a voz continua
   (fim de palavra marcado cedo demais pelo Whisper: o "agora?" do IMG_4539).
3. Palavra longa demais para o tamanho dela: costuma esconder fala não transcrita; o editor
   fica só com o fim dela (o "hiper" de hipertireoidismo, IMG_4544).

As suspeitas de voz sem palavra são retranscritas sozinhas (com o modelo principal): isoladas
do resto, as duas tentativas costumam aparecer separadas.
"""

import subprocess
import tempfile
from itertools import groupby
from dataclasses import dataclass
from pathlib import Path

from . import plano


@dataclass
class Suspeita:
    tipo: str                 # "voz sem palavra", "palavra cortada", "palavra longa"
    inicio: float             # segundos no vídeo original
    fim: float
    saida: float | None       # segundos no vídeo editado (None = o trecho saiu do vídeo)
    detalhe: str = ""


def limiar_de_voz(envelope) -> float:
    """O mesmo limiar de aparar_silencio: 25 dB abaixo da fala, nunca abaixo do ruído de fundo."""
    import numpy as np

    fala = float(np.percentile(envelope, 90))
    fundo = float(np.percentile(envelope, 10))
    return max(fala - 25, fundo + 6)


def _blocos_de_voz(envelope, limiar: float, por_segundo: int, juntar: float) -> list[tuple[float, float]]:
    """Intervalos com voz; pausas menores que `juntar` (entre sílabas) não separam."""
    blocos: list[list[float]] = []
    for i, v in enumerate(envelope):
        if v <= limiar:
            continue
        t = i / por_segundo
        if blocos and t - blocos[-1][1] <= juntar:
            blocos[-1][1] = t + 1 / por_segundo
        else:
            blocos.append([t, t + 1 / por_segundo])
    return [(a, b) for a, b in blocos]


def voz_sem_palavra(palavras, envelope, por_segundo: int = 100, minimo: float = 0.8,
                    juntar: float = 0.25) -> list[tuple[float, float]]:
    """Blocos de voz de pelo menos `minimo` s em que as palavras cobrem menos de 30%."""
    limiar = limiar_de_voz(envelope)
    achados = []
    for a, b in _blocos_de_voz(envelope, limiar, por_segundo, juntar):
        if b - a < minimo:
            continue
        coberto = sum(max(0.0, min(b, p.fim) - max(a, p.inicio)) for p in palavras)
        if coberto < 0.3 * (b - a):
            achados.append((round(a, 2), round(b, 2)))
    return achados


def palavras_cortadas(trechos, palavras, envelope, por_segundo: int = 100,
                      folga: float = 0.05) -> list[tuple[float, str]]:
    """Bordas de corte (não as emendas contíguas) que caem dentro de uma palavra, ou depois das
    quais a voz continua sem que outra palavra comece. Devolve (tempo no original, palavra)."""
    import numpy as np

    limiar = limiar_de_voz(envelope)
    achados = []
    for i, t in enumerate(trechos):
        corte_antes = i == 0 or t.inicio - trechos[i - 1].fim > 0.02
        corte_depois = i + 1 == len(trechos) or trechos[i + 1].inicio - t.fim > 0.02
        for borda, e_corte in ((t.inicio, corte_antes), (t.fim, corte_depois)):
            if not e_corte:
                continue
            dentro = [p for p in palavras if p.inicio + folga < borda < p.fim - folga]
            if dentro:
                achados.append((round(borda, 2), dentro[0].texto))
        if corte_depois:
            # Voz logo depois do fim, sem palavra começando ali: o fim da palavra ficou de fora.
            a, b = int(t.fim * por_segundo), int((t.fim + 0.15) * por_segundo)
            janela = envelope[a:b]
            seguinte = any(t.fim - 0.02 <= p.inicio <= t.fim + 0.2 for p in palavras)
            if len(janela) and float(np.mean(janela > limiar)) > 0.6 and not seguinte:
                ultima = [p for p in palavras if p.fim <= t.fim + 0.05]
                achados.append((round(t.fim, 2), ultima[-1].texto if ultima else ""))
    vistos, unicos = set(), []
    for x in achados:
        if x[0] not in vistos:
            vistos.add(x[0])
            unicos.append(x)
    return unicos


def palavras_longas(palavras) -> list:
    return [p for p in palavras if p.fim - p.inicio > plano._limite_palavra(p.texto)]


def _retranscrever(video: Path, ini: float, fim: float, cfg_transcricao: dict) -> str:
    from . import transcricao

    with tempfile.TemporaryDirectory() as pasta:
        audio = Path(pasta) / "trecho.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-i", str(video),
                        "-t", f"{fim - ini:.3f}", "-vn", "-ac", "1", "-ar", "16000", str(audio)], check=True)
        try:
            texto = " ".join(p.texto for p in transcricao.transcrever(audio, cfg_transcricao))
        except Exception as e:                       # a checagem nunca impede a edição
            return f"(não foi possível retranscrever: {e})"
    return _limpar(texto)


def _limpar(texto: str) -> str:
    """Em ruído o Whisper repete uma sílaba sem fim ("P -p -p -p…"): vira um aviso curto."""
    tokens = texto.split()
    repetidos = max((sum(1 for _ in g) for _, g in groupby(t.lower().strip(".,-") for t in tokens)), default=0)
    if repetidos >= 5:
        return "(ruído, sem fala reconhecível)"
    return texto if len(texto) <= 160 else texto[:157] + "…"


def checar(video: Path, trechos, palavras, envelope, cfg_transcricao: dict | None = None,
           por_segundo: int = 100) -> list[Suspeita]:
    """Todas as suspeitas, em ordem de tempo. Com `cfg_transcricao`, as de voz sem palavra são
    retranscritas sozinhas (com 1,5 s de contexto de cada lado)."""
    suspeitas = []
    for a, b in voz_sem_palavra(palavras, envelope, por_segundo):
        texto = ""
        if cfg_transcricao:
            texto = _retranscrever(video, max(0.0, a - 1.5), b + 1.5, cfg_transcricao)
        suspeitas.append(Suspeita("voz sem palavra", a, b, plano.remapear_tempo(a, trechos),
                                  f"{b - a:.1f} s de voz sem transcrição" + (f"; isolado: \"{texto}\"" if texto else "")))
    for tempo, palavra in palavras_cortadas(trechos, palavras, envelope, por_segundo):
        saida = plano.remapear_tempo(tempo - 0.01, trechos)
        suspeitas.append(Suspeita("palavra cortada", tempo, tempo, saida, f"\"{palavra}\""))
    for p in palavras_longas(palavras):
        suspeitas.append(Suspeita("palavra longa", p.inicio, p.fim, plano.remapear_tempo(p.fim - 0.01, trechos),
                                  f"\"{p.texto}\" com {p.fim - p.inicio:.1f} s (só o fim entra no vídeo)"))
    return sorted(suspeitas, key=lambda s: s.inicio)


def _mmss(t: float | None) -> str:
    return "fora" if t is None else f"{int(t // 60)}:{t % 60:04.1f}"


def relatorio(suspeitas: list[Suspeita]) -> str:
    if not suspeitas:
        return "    checagem: nenhuma suspeita"
    linhas = [f"    checagem: {len(suspeitas)} suspeita(s) — conferir antes de renderizar"]
    for s in suspeitas:
        linhas.append(f"      ! {s.tipo} em {_mmss(s.inicio)} do original "
                      f"({_mmss(s.saida)} no editado): {s.detalhe}")
    return "\n".join(linhas)
