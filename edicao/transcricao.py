"""Transcrição local com timestamps por palavra.

Dois backends, escolhidos pela configuração:
- mlx: mlx-whisper, usa a GPU do Apple Silicon (M1, M2, ...).
- faster-whisper: roda na CPU, funciona no Mac Intel e no Apple Silicon.
"""

import json
import platform
import sys
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
