"""Identidade de marca deste computador: quem fala, fonte e cores da legenda, paleta.

Três caminhos, combináveis: perguntas no Terminal, leitura do manual de marca pelo Claude
(PDF ou imagens) e arquivo de fonte (.ttf/.otf) da marca. O resultado vai para a configuração
deste computador (ver config.salvar_usuario) e gera uma prévia da legenda em PNG.
"""

import platform
import re
import shutil
import subprocess
from pathlib import Path

from . import config, decisao, legendas
from .transcricao import Palavra

CAMPOS_COR = (
    ("cor_texto", "Cor do texto da legenda"),
    ("cor_palavra_atual", "Cor da palavra sendo falada"),
    ("cor_destaque", "Cor das palavras de destaque"),
    ("cor_contorno", "Cor do contorno das letras"),
)
FORMATOS_MANUAL = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

ESQUEMA_MANUAL = {
    "type": "object",
    "properties": {
        "nome": {"type": "string", "description": "Nome da marca."},
        "publico": {"type": "string", "description": "Público-alvo, numa frase curta; vazio se o manual não diz."},
        "tom": {"type": "string", "description": "Tom de voz da marca, numa frase curta; vazio se o manual não diz."},
        "fontes": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "uso": {"type": "string"}},
            "required": ["nome", "uso"], "additionalProperties": False}},
        "cores": {"type": "array", "items": {"type": "object", "properties": {
            "hex": {"type": "string"}, "nome": {"type": "string"}, "uso": {"type": "string"}},
            "required": ["hex", "nome", "uso"], "additionalProperties": False}},
        "legenda": {"type": "object", "properties": {
            "fonte": {"type": "string"},
            "cor_texto": {"type": "string"},
            "cor_palavra_atual": {"type": "string"},
            "cor_destaque": {"type": "string"},
            "cor_contorno": {"type": "string"}},
            "required": ["fonte", "cor_texto", "cor_palavra_atual", "cor_destaque", "cor_contorno"],
            "additionalProperties": False},
        "observacoes": {"type": "string", "description": "Avisos curtos para quem vai configurar."},
    },
    "required": ["nome", "publico", "tom", "fontes", "cores", "legenda", "observacoes"],
    "additionalProperties": False,
}

INSTRUCOES_MANUAL = """Leia o manual de marca nos arquivos {arquivos} (use a ferramenta Read; num PDF longo,
leia por páginas). Extraia o nome da marca, o público, o tom de voz, as fontes e as cores (em
#RRGGBB; converta de RGB ou CMYK se preciso).

Depois proponha o estilo da legenda de vídeos verticais (Reels): texto em caixa alta, em negrito,
sobre o vídeo, com contorno grosso para ler em qualquer fundo. A palavra sendo falada e as palavras
de destaque ganham cor própria.
- Priorize a legibilidade: o texto e o contorno precisam de alto contraste entre si (em geral texto
  claro e contorno escuro).
- Use cores da marca na palavra atual e nos destaques, distintas entre si e do texto, e que se
  destaquem sobre o contorno.
- Fonte: use a fonte da marca se for legível em negrito em tamanho grande; senão, a mais legível
  do manual. Escreva o nome da família como no manual.
Em observacoes, avise o que o usuário precisa saber (por exemplo, instalar a fonte no Mac).
"""


def normalizar_cor(texto: str) -> str | None:
    """'#abc', 'ABC', '#a1b2c3' → '#AABBCC' / '#A1B2C3'; None se não for uma cor válida."""
    t = texto.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", t):
        t = "".join(c * 2 for c in t)
    return f"#{t.upper()}" if re.fullmatch(r"[0-9a-fA-F]{6}", t) else None


def limpar_caminho(texto: str) -> str:
    """Caminho arrastado para o Terminal: tira aspas e as barras antes de espaços."""
    return texto.strip().strip("'\"").replace("\\ ", " ")


def ler_fonte(arquivo: Path) -> dict:
    """Família, negrito e itálico do arquivo de fonte.

    A legenda encontra a fonte pela família (ex.: 'Montserrat') com o peso e a inclinação
    pedidos; o nome completo ('Montserrat ExtraBold Italic') nem sempre é reconhecido.
    """
    from fontTools.ttLib import TTFont

    fonte = TTFont(arquivo, fontNumber=0, lazy=True)
    nomes = fonte["name"]
    familia = nomes.getDebugName(16) or nomes.getDebugName(1) or arquivo.stem
    os2 = fonte["OS/2"] if "OS/2" in fonte else None
    peso = os2.usWeightClass if os2 else 700
    italico = bool(os2.fsSelection & 1) if os2 else False
    return {"fonte": familia, "negrito": peso >= 600, "italico": italico}


def copiar_fonte(arquivo: Path) -> dict:
    """Copia a fonte para a pasta deste computador; devolve os campos da marca para ela."""
    if arquivo.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        raise ValueError("a fonte precisa ser um arquivo .ttf, .otf ou .ttc")
    destino = config.pasta_usuario() / "fontes" / arquivo.name
    destino.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.resolve() != destino.resolve():
        shutil.copy(arquivo, destino)
    return {**ler_fonte(destino), "arquivo_fonte": str(destino)}


def ler_manual(arquivos: list[Path], cfg_decisao: dict) -> dict:
    """Pede ao Claude (assinatura) para ler o manual e propor a identidade. Valida as cores."""
    for a in arquivos:
        if a.suffix.lower() not in FORMATOS_MANUAL:
            raise ValueError(f"{a.name}: use PDF ou imagem (PNG, JPG)")
    nomes = ", ".join(a.name for a in arquivos)
    bruto = decisao.claude_json(INSTRUCOES_MANUAL.format(arquivos=nomes), ESQUEMA_MANUAL,
                                cfg_decisao, tuple(arquivos))
    return validar_manual(bruto)


def validar_manual(bruto: dict) -> dict:
    cores = []
    for c in bruto.get("cores", []):
        hexa = normalizar_cor(c.get("hex", ""))
        if hexa:
            cores.append({**c, "hex": hexa})
    legenda = {}
    for chave, valor in bruto.get("legenda", {}).items():
        if chave == "fonte":
            if valor.strip():
                legenda["fonte"] = valor.strip()
        elif normalizar_cor(valor):
            legenda[chave] = normalizar_cor(valor)
    return {**bruto, "cores": cores, "legenda": legenda}


def aplicar_manual(marca: dict, proposta: dict) -> dict:
    """Junta a proposta do manual à marca atual (o que o manual não traz continua igual)."""
    novo = dict(marca)
    for chave in ("nome", "publico", "tom"):
        if proposta.get(chave):
            novo[chave] = proposta[chave]
    if proposta["cores"]:
        novo["cores"] = [c["hex"] for c in proposta["cores"]]
    if proposta["legenda"].get("fonte") and proposta["legenda"]["fonte"] != marca.get("fonte"):
        novo.update(arquivo_fonte="", negrito=True, italico=False)
    novo.update(proposta["legenda"])
    return novo


def resumo_manual(proposta: dict) -> str:
    linhas = [f"Marca: {proposta.get('nome') or '(sem nome)'}"]
    for f in proposta.get("fontes", []):
        linhas.append(f"  fonte {f['nome']}: {f['uso']}")
    for c in proposta["cores"]:
        linhas.append(f"  cor {c['hex']} {c['nome']}: {c['uso']}")
    if proposta.get("observacoes"):
        linhas.append(f"Observações: {proposta['observacoes']}")
    return "\n".join(linhas)


def perguntar(marca: dict, entrada=input) -> dict:
    """Pergunta cada campo no Terminal; Enter mantém o valor entre colchetes."""
    novo = dict(marca)
    print("Tecle Enter para manter o valor entre colchetes.\n")
    for chave, rotulo in (("nome", "Nome da marca"),
                          ("autor", "Quem fala nos vídeos (ex.: um médico cirurgião)"),
                          ("publico", "Para quem são os vídeos"),
                          ("tom", "Tom da comunicação (ex.: didático e acolhedor)")):
        resposta = entrada(f"{rotulo} [{novo.get(chave, '')}]: ").strip()
        if resposta:
            novo[chave] = resposta

    resposta = limpar_caminho(entrada(
        f"Fonte da legenda: nome de uma fonte instalada no Mac, ou arraste aqui um arquivo "
        f".ttf/.otf [{novo['fonte']}]: "))
    if resposta:
        if Path(resposta).expanduser().is_file():
            novo.update(copiar_fonte(Path(resposta).expanduser()))
            print(f"    fonte copiada: {novo['fonte']}")
        else:
            novo.update(fonte=resposta, arquivo_fonte="", negrito=True, italico=False)

    for chave, rotulo in CAMPOS_COR:
        while True:
            resposta = entrada(f"{rotulo}, em hex [{novo[chave]}]: ").strip()
            if not resposta:
                break
            if normalizar_cor(resposta):
                novo[chave] = normalizar_cor(resposta)
                break
            print("    use o formato #RRGGBB, por exemplo #FFD400")

    while True:
        atuais = ", ".join(novo.get("cores", []))
        resposta = entrada(f"Paleta da marca, cores em hex separadas por vírgula [{atuais}]: ").strip()
        if not resposta:
            break
        cores = [normalizar_cor(c) for c in resposta.split(",") if c.strip()]
        if all(cores):
            novo["cores"] = cores
            break
        print("    alguma cor não está no formato #RRGGBB")
    return novo


def previa(cfg: dict, saida: Path) -> Path:
    """Imagem da legenda com a fonte e as cores da marca sobre um fundo neutro."""
    v, marca = cfg["video"], cfg["marca"]
    ass = saida.with_suffix(".ass")
    palavras = [Palavra("Assim", 0, 1), Palavra("fica", 1, 2), Palavra("a", 2, 3),
                Palavra("legenda", 3, 4), Palavra("da", 4, 5), Palavra("marca", 5, 6)]
    texto = legendas.gerar_ass(palavras, {**cfg["legendas"], "palavras_por_linha": 6}, marca,
                               v["largura"], v["altura"], {"marca"})
    ass.write_text(texto, encoding="utf-8")
    filtro = f"subtitles=filename='{_escapar(ass)}'"
    if marca.get("arquivo_fonte"):
        filtro += f":fontsdir='{_escapar(Path(marca['arquivo_fonte']).parent)}'"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"gradients=s={v['largura']}x{v['altura']}:c0=0x6B7B8C:c1=0xD9CBB8:seed=1:d=4",
         "-vf", filtro, "-ss", "3.5", "-frames:v", "1", str(saida)],
        check=True,
    )
    ass.unlink()
    return saida


def _escapar(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def configurar(cfg: dict, manual: list[Path] | None, fonte: Path | None, interativo: bool) -> None:
    marca = dict(cfg["marca"])
    if manual:
        print("Lendo o manual de marca com o Claude…")
        proposta = ler_manual(manual, cfg["decisao"])
        print(resumo_manual(proposta) + "\n")
        marca = aplicar_manual(marca, proposta)
    if fonte:
        marca.update(copiar_fonte(fonte))
        print(f"Fonte da legenda: {marca['fonte']}")
    if interativo:
        marca = perguntar(marca)
    caminho = config.salvar_usuario("marca", marca)
    print(f"\nIdentidade salva em {caminho}")

    imagem = previa({**cfg, "marca": marca}, config.pasta_usuario() / "previa-legenda.png")
    print(f"Prévia da legenda: {imagem}")
    print("Se a fonte da prévia não for a da marca, instale a fonte no Mac (clique duas vezes "
          "no arquivo) ou use: edicao marca --fonte ARQUIVO")
    if platform.system() == "Darwin":
        subprocess.run(["open", str(imagem)], check=False)


def mostrar(cfg: dict) -> None:
    print(f"Configuração deste computador: {config.config_usuario()}")
    for chave, valor in cfg["marca"].items():
        print(f"  {chave} = {valor}")
