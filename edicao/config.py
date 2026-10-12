"""Configuração em duas camadas.

- `config.toml` na pasta do programa: valores padrão. Uma atualização substitui este arquivo.
- `config.toml` na pasta do usuário (fora da pasta do programa): o que vale só neste computador,
  como a identidade de marca. Atualizar o programa não mexe nela.

Cada chave da pasta do usuário substitui a do padrão; o resto continua vindo do padrão.
"""

import os
import platform
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "config.toml"


def pasta_usuario() -> Path:
    """Onde ficam a configuração deste computador e as fontes da marca."""
    if os.environ.get("EDICAO_PASTA"):
        return Path(os.environ["EDICAO_PASTA"])
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "edicao-videos"
    return Path.home() / ".config" / "edicao-videos"


def config_usuario() -> Path:
    return pasta_usuario() / "config.toml"


def _ler(caminho: Path) -> dict:
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def _mesclar(base: dict, por_cima: dict) -> dict:
    resultado = dict(base)
    for chave, valor in por_cima.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        else:
            resultado[chave] = valor
    return resultado


def carregar(caminho: Path | None = None) -> dict:
    """Padrão + configuração deste computador + `caminho` (se dado), nessa ordem."""
    cfg = _ler(CONFIG_PADRAO)
    if config_usuario().exists():
        cfg = _mesclar(cfg, _ler(config_usuario()))
    if caminho:
        cfg = _mesclar(cfg, _ler(caminho))
    return cfg


def salvar_usuario(secao: str, valores: dict) -> Path:
    """Grava `valores` na seção `secao` da configuração deste computador, mantendo o resto."""
    caminho = config_usuario()
    atual = _ler(caminho) if caminho.exists() else {}
    atual[secao] = {**atual.get(secao, {}), **valores}
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linhas = ["# Configuração deste computador (substitui o config.toml do programa).",
              "# Para a identidade de marca, prefira o comando: edicao marca", ""]
    for nome, conteudo in atual.items():
        linhas.append(f"[{nome}]")
        linhas += [f"{chave} = {_toml(valor)}" for chave, valor in conteudo.items()]
        linhas.append("")
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def _toml(valor) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return repr(valor)
    if isinstance(valor, list):
        return "[" + ", ".join(_toml(v) for v in valor) + "]"
    texto = str(valor).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{texto}"'
