"""Transcrição local com timestamps por palavra.

Dois backends, escolhidos pela configuração:
- mlx: mlx-whisper, usa a GPU do Apple Silicon (M1, M2, ...).
- faster-whisper: roda na CPU, funciona no Mac Intel e no Apple Silicon.
"""

import json
import platform
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Palavra:
    texto: str
    inicio: float
    fim: float


def _mlx_disponivel() -> bool:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def escolher_backend(backend: str) -> str:
    if backend == "auto":
        return "mlx" if _mlx_disponivel() else "faster-whisper"
    return backend


def transcrever(video: Path, cfg: dict) -> list[Palavra]:
    backend = escolher_backend(cfg["backend"])
    if backend == "mlx":
        return _transcrever_mlx(video, cfg["modelo"], cfg["idioma"])
    if backend == "faster-whisper":
        return _transcrever_faster_whisper(video, cfg["modelo"], cfg["idioma"])
    raise ValueError(f"backend de transcrição desconhecido: {backend}")


def trechos_suspeitos(palavras: list[Palavra], limite: float = 1.5,
                      antes: float = 4.0, depois: float = 1.0) -> list[tuple[int, int]]:
    """Faixas de índices [i0, i1] em volta de palavras com duração anormal.

    O modelo pequeno às vezes engole uma tentativa abandonada esticando UMA palavra por
    vários segundos ("foi" com 3 s). Sem as palavras da tentativa, o Claude não vê a
    repetição e a edição emenda a tomada errada na certa. A faixa vai de `antes` segundos
    antes da palavra até `depois` segundos depois, em limites de palavra.
    """
    faixas: list[tuple[int, int]] = []
    for k, p in enumerate(palavras):
        if p.fim - p.inicio <= limite:
            continue
        i0 = next(i for i in range(k + 1) if palavras[i].inicio >= p.inicio - antes)
        i1 = max(i for i in range(k, len(palavras)) if palavras[i].fim <= p.fim + depois or i == k)
        if faixas and i0 <= faixas[-1][1] + 1:
            faixas[-1] = (faixas[-1][0], max(i1, faixas[-1][1]))
        else:
            faixas.append((i0, i1))
    return faixas


def revisar_tomadas(video: Path, palavras: list[Palavra], cfg: dict) -> tuple[list[Palavra], int]:
    """Retranscreve com `modelo_revisao` os trechos com palavra de duração anormal.

    Devolve as palavras corrigidas e quantos trechos foram revistos. Sem `modelo_revisao`
    (ou igual ao modelo principal), não faz nada.
    """
    modelo = cfg.get("modelo_revisao", "")
    if not modelo or modelo == cfg["modelo"]:
        return palavras, 0
    faixas = trechos_suspeitos(palavras, cfg.get("limite_palavra_longa", 1.5))
    if not faixas:
        return palavras, 0
    resultado = list(palavras)
    with tempfile.TemporaryDirectory() as pasta:
        for i0, i1 in reversed(faixas):  # de trás para frente: os índices anteriores não mudam
            anterior = resultado[i0 - 1].fim if i0 > 0 else 0.0
            seguinte = resultado[i1 + 1].inicio if i1 + 1 < len(resultado) else resultado[i1].fim + 0.3
            ini = max(anterior, resultado[i0].inicio - 0.3)
            fim = min(seguinte, resultado[i1].fim + 0.3)
            audio = Path(pasta) / f"trecho_{i0}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-i", str(video),
                            "-t", f"{fim - ini:.3f}", "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                           check=True)
            novas = transcrever(audio, {**cfg, "modelo": modelo})
            novas = [Palavra(n.texto, round(n.inicio + ini, 3), round(n.fim + ini, 3)) for n in novas]
            novas = [n for n in novas if ini <= (n.inicio + n.fim) / 2 <= fim]
            if not novas:
                continue
            # o áudio cortado termina "no meio" da fala: o modelo põe reticências que não existem
            if not re.search(r"[.?!…]$", resultado[i1].texto):
                novas[-1].texto = re.sub(r"[.…]+$", "", novas[-1].texto) or novas[-1].texto
            resultado[i0:i1 + 1] = novas
    return resultado, len(faixas)


def _transcrever_mlx(video: Path, modelo: str, idioma: str) -> list[Palavra]:
    import mlx_whisper

    resultado = mlx_whisper.transcribe(
        str(video),
        path_or_hf_repo=f"mlx-community/whisper-{modelo}-mlx",
        language=idioma,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    return [
        Palavra(p["word"].strip(), float(p["start"]), float(p["end"]))
        for seg in resultado["segments"]
        for p in seg.get("words", [])
        if p["word"].strip()
    ]


def _transcrever_faster_whisper(video: Path, modelo: str, idioma: str) -> list[Palavra]:
    from faster_whisper import WhisperModel

    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    # Sem o texto anterior como contexto: com ele, o Whisper tende a pular a fala repetida
    # (a tentativa errada e a refeita viram uma só), e o erro fica no vídeo sem ser visto.
    segmentos, _ = m.transcribe(str(video), language=idioma, word_timestamps=True,
                                condition_on_previous_text=False)
    return [
        Palavra(p.word.strip(), float(p.start), float(p.end))
        for seg in segmentos
        for p in (seg.words or [])
        if p.word.strip()
    ]


def salvar(palavras: list[Palavra], caminho: Path) -> None:
    caminho.write_text(
        json.dumps([asdict(p) for p in palavras], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def carregar(caminho: Path) -> list[Palavra]:
    return [Palavra(**p) for p in json.loads(caminho.read_text(encoding="utf-8"))]
