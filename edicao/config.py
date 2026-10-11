import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "config.toml"


def carregar(caminho: Path | None = None) -> dict:
    with open(caminho or CONFIG_PADRAO, "rb") as f:
        return tomllib.load(f)
