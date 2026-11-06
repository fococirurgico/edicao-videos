"""Material de apoio: prints e imagens que aparecem sobre o vídeo.

O Claude lê as imagens e a transcrição já decidida e diz, para cada imagem:
- se ela é o gancho (a dúvida do seguidor que motiva o vídeo): abre o vídeo, no lugar do título;
- senão, em que frase e em que palavras o assunto dela é dito (a imagem entra nesse instante);
- que textos identificam pessoas comuns (nome de usuário, nome de quem comentou), para desfocar.

O desfoque é feito aqui, não pelo modelo: o texto é localizado pelo OCR do macOS (Vision) e os
rostos (foto de perfil) pelo detector de rostos do Vision. Nome e foto de perfil saem desfocados
por padrão; autores de artigos publicados e instituições não.

Cada imagem vira um cartão PNG com transparência (cantos arredondados e sombra), sobreposto pelo
render com entrada deslizando e esmaecendo.
"""

import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from . import decisao

FORMATOS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}


@dataclass
class Pedido:
    arquivo: str            # nome do arquivo (sem pasta)
    gancho: bool
    frase: int              # 0 = sem frase (gancho)
    ancora: str
    ocultar: list[str]


@dataclass
class Cartao:
    png: Path
    inicio: float           # segundos, na linha do tempo do vídeo editado
    fim: float
    x: int                  # canto superior esquerdo do PNG no quadro
    y: int


ESQUEMA = {
    "type": "object",
    "properties": {
        "imagens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "arquivo": {"type": "string"},
                    "gancho": {"type": "boolean"},
                    "frase": {"type": "integer"},
                    "ancora": {"type": "string"},
                    "ocultar": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["arquivo", "gancho", "frase", "ancora", "ocultar"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["imagens"],
    "additionalProperties": False,
}

INSTRUCOES = """Você está editando um vídeo curto vertical (Reels){autor}. O autor mandou imagens de
apoio para aparecer sobre o vídeo: {arquivos}. Leia cada imagem (ferramenta Read) e a transcrição
abaixo (só as frases que ficaram no vídeo) e decida, para cada imagem:

- gancho: true se a imagem é a dúvida ou o comentário de um seguidor que motiva o vídeo (ela abre
  o vídeo, no lugar do título). No máximo uma imagem é gancho. Para o gancho, frase = 0 e ancora "".
- frase e ancora (se não for gancho): o ID da frase em que o assunto da imagem é dito e as
  palavras dessa frase, copiadas exatamente e em sequência (2 a 5 palavras), em que a imagem deve
  aparecer (ex.: um artigo entra quando o autor fala "um estudo americano"). Se o assunto nunca
  é dito, escolha a frase mais próxima do tema.
- ocultar: os textos da imagem que identificam pessoas comuns, copiados exatamente como aparecem
  na imagem: nome de usuário ("@fulana123" ou "fulana123"), nome de quem comentou ou mandou a
  mensagem, telefone, e-mail pessoal. NÃO inclua autores de artigos científicos, revistas,
  instituições, nem o próprio autor do vídeo. Lista vazia se não houver.

Transcrição:
"""


def montar_prompt(frases: list[decisao.Frase], manter: list[int], arquivos: list[str],
                  marca: dict | None = None) -> str:
    autor, _ = decisao._contexto_marca(marca or {})
    linhas = [f"[{f.id}] {f.texto}" for f in frases if f.id in manter]
    return (INSTRUCOES.format(autor=autor, arquivos=", ".join(arquivos)) + "\n".join(linhas))


def validar(bruto: dict, frases: list[decisao.Frase], manter: list[int], arquivos: list[str]) -> list[Pedido]:
    """Uma entrada por arquivo enviado, na ordem; o que o Claude não respondeu entra no fim do vídeo
    sem desfoque de texto (os rostos são desfocados mesmo assim)."""
    textos = {f.id: decisao.norm_frase(f) for f in frases}
    respostas = {}
    for r in bruto.get("imagens", []):
        nome = Path(str(r.get("arquivo", ""))).name
        if nome in arquivos and nome not in respostas:
            respostas[nome] = r
    pedidos, tem_gancho = [], False
    for nome in arquivos:
        r = respostas.get(nome, {})
        gancho = bool(r.get("gancho")) and not tem_gancho
        tem_gancho |= gancho
        frase = r.get("frase") if r.get("frase") in manter else 0
        ancora = " ".join(str(r.get("ancora", "")).split())
        alvo = decisao._tokens(ancora)
        if not frase or not alvo or decisao._achar(textos[frase], alvo) is None:
            ancora = ""
        if not gancho and not frase:
            frase = manter[-1] if manter else 0
        ocultar = [" ".join(str(o).split()) for o in r.get("ocultar", []) if str(o).strip()]
        pedidos.append(Pedido(nome, gancho, 0 if gancho else frase, "" if gancho else ancora, ocultar))
    return pedidos


def decidir(frases: list[decisao.Frase], manter: list[int], imagens: list[Path], cfg: dict,
            marca: dict | None = None) -> list[Pedido]:
    arquivos = [p.name for p in imagens]
    if cfg["backend"] == "nenhum":
        return validar({}, frases, manter, arquivos)
    prompt = montar_prompt(frases, manter, arquivos, marca)
    try:
        bruto = decisao.claude_json(prompt, ESQUEMA, {**cfg, "timeout": max(cfg.get("timeout", 300), 300)},
                                    anexos=tuple(imagens))
    except Exception as e:
        print(f"    aviso: o Claude não encaixou as imagens ({e}); entram no fim, com rostos desfocados")
        bruto = {}
    return validar(bruto, frases, manter, arquivos)


def salvar(pedidos: list[Pedido], caminho: Path) -> None:
    caminho.write_text(json.dumps([asdict(p) for p in pedidos], ensure_ascii=False, indent=2), encoding="utf-8")


def carregar(caminho: Path) -> list[Pedido]:
    return [Pedido(**p) for p in json.loads(caminho.read_text(encoding="utf-8"))]


# Desfoque

def _ler(caminho: Path) -> np.ndarray:
    img = cv2.imread(str(caminho), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"{caminho.name}: não consegui abrir a imagem")
    return img


def _pedido_vision(img: np.ndarray, pedidos: list):
    import Foundation
    import Vision
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = Path(pasta) / "img.png"
        cv2.imwrite(str(arquivo), img)
        url = Foundation.NSURL.fileURLWithPath_(str(arquivo))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        ok, erro = handler.performRequests_error_(pedidos, None)
        if not ok:
            raise RuntimeError(f"Vision falhou: {erro}")


def _texto(img: np.ndarray) -> list:
    """Linhas de texto da imagem (candidatos do Vision, com caixa por trecho)."""
    import Vision
    pedido = Vision.VNRecognizeTextRequest.alloc().init()
    pedido.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    pedido.setRecognitionLanguages_(["pt-BR", "en-US"])
    pedido.setUsesLanguageCorrection_(False)
    _pedido_vision(img, [pedido])
    return [obs.topCandidates_(1)[0] for obs in (pedido.results() or []) if obs.topCandidates_(1)]


def _rostos(img: np.ndarray, lado: int = 400) -> list[tuple[int, int, int, int]]:
    """Rostos em pixels (x0, y0, x1, y1). A imagem é varrida em blocos que se sobrepõem: numa
    print inteira, a foto de perfil é pequena demais e o Vision não a acha (testado em 06/11)."""
    import Vision
    alt, larg = img.shape[:2]
    passo = lado // 2
    achados = []
    for y in range(0, max(1, alt - passo), passo):
        for x in range(0, max(1, larg - passo), passo):
            bloco = img[y:y + lado, x:x + lado]
            h, w = bloco.shape[:2]
            if h < 40 or w < 40:
                continue
            pedido = Vision.VNDetectFaceRectanglesRequest.alloc().init()
            _pedido_vision(bloco, [pedido])
            for obs in pedido.results() or []:
                x0, y0, x1, y1 = _px(obs.boundingBox(), w, h)
                achados.append((x + x0, y + y0, x + x1, y + y1))
    return achados


def _px(caixa, largura: int, altura: int) -> tuple[int, int, int, int]:
    """Caixa normalizada do Vision (origem embaixo à esquerda) → x0, y0, x1, y1 em pixels."""
    (x, y), (w, h) = caixa.origin, caixa.size
    return (round(x * largura), round((1 - y - h) * altura), round((x + w) * largura), round((1 - y) * altura))


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower().lstrip("@")).strip()


def regioes_a_desfocar(img: np.ndarray, ocultar: list[str]) -> list[tuple[int, int, int, int, bool]]:
    """Caixas (x0, y0, x1, y1, redonda) dos textos a ocultar e das fotos de perfil (rostos)."""
    import Foundation
    alt, larg = img.shape[:2]
    linhas = _texto(img)
    regioes = []
    alvos = [_norm(o) for o in ocultar if _norm(o)]
    for cand in linhas:
        texto = str(cand.string())
        baixo = texto.lower()
        for alvo in alvos:
            # Procura também sem o "@" e com espaços variáveis.
            padrao = re.compile(r"@?" + r"\s*".join(re.escape(c) for c in alvo.replace(" ", "")), re.I)
            for m in padrao.finditer(baixo):
                caixa, _ = cand.boundingBoxForRange_error_(Foundation.NSMakeRange(m.start(), m.end() - m.start()), None)
                if caixa is None:
                    continue
                x0, y0, x1, y1 = _px(caixa.boundingBox(), larg, alt)
                folga = max(4, round((y1 - y0) * 0.25))
                regioes.append((x0 - folga, y0 - folga, x1 + folga, y1 + folga, False))
    for x0, y0, x1, y1 in _rostos(img):
        # A foto de perfil é um círculo bem maior que o rosto detectado nela.
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 1.1
        regioes.append((round(cx - r), round(cy - r), round(cx + r), round(cy + r), True))
    return [(max(0, a), max(0, b), min(larg, c), min(alt, d), redonda)
            for a, b, c, d, redonda in regioes if c > a and d > b]


def desfocar(img: np.ndarray, regioes: list[tuple[int, int, int, int, bool]]) -> np.ndarray:
    """Pixeliza e desfoca: ilegível, mas sem tarja preta chamando atenção. Regiões redondas (foto
    de perfil) só dentro do círculo, para o anel do avatar continuar com a forma de avatar."""
    saida = img.copy()
    for x0, y0, x1, y1, redonda in regioes:
        trecho = saida[y0:y1, x0:x1]
        h, w = trecho.shape[:2]
        if h < 2 or w < 2:
            continue
        bloco = max(6, round(min(h, w) / 3))
        pequeno = cv2.resize(trecho, (max(1, w // bloco), max(1, h // bloco)), interpolation=cv2.INTER_AREA)
        trecho = cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_LINEAR)
        k = max(3, (min(h, w) // 4) | 1)
        trecho = cv2.GaussianBlur(trecho, (k, k), 0)
        if redonda:
            mascara = np.zeros((h, w), np.uint8)
            cv2.circle(mascara, (w // 2, h // 2), min(h, w) // 2, 255, -1, cv2.LINE_AA)
            a = (mascara.astype(np.float32) / 255)[..., None]
            trecho = (trecho * a + saida[y0:y1, x0:x1] * (1 - a)).astype(img.dtype)
        saida[y0:y1, x0:x1] = trecho
    return saida


# Cartão

def montar_cartao(img: np.ndarray, largura_max: int, altura_max: int, raio: int = 34,
                  sombra: int = 28) -> np.ndarray:
    """Imagem reduzida para caber, com cantos arredondados e sombra suave; BGRA."""
    alt, larg = img.shape[:2]
    escala = min(largura_max / larg, altura_max / alt)
    w, h = max(1, round(larg * escala)), max(1, round(alt * escala))
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
    mascara = np.zeros((h, w), np.uint8)
    r = min(raio, w // 2, h // 2)
    cv2.rectangle(mascara, (r, 0), (w - 1 - r, h - 1), 255, -1, cv2.LINE_AA)
    cv2.rectangle(mascara, (0, r), (w - 1, h - 1 - r), 255, -1, cv2.LINE_AA)
    for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
        cv2.circle(mascara, (cx, cy), r, 255, -1, cv2.LINE_AA)
    W, H = w + 2 * sombra, h + 2 * sombra
    fundo = np.zeros((H, W), np.float32)
    fundo[sombra + sombra // 3:sombra + sombra // 3 + h, sombra:sombra + w] = mascara / 255.0
    fundo = cv2.GaussianBlur(fundo, (0, 0), sombra / 2.5) * 0.45
    cartao = np.zeros((H, W, 4), np.float32)
    a = mascara.astype(np.float32) / 255.0
    cartao[..., 3] = fundo
    regiao = cartao[sombra:sombra + h, sombra:sombra + w]
    alfa_final = a + regiao[..., 3] * (1 - a)
    for c in range(3):
        regiao[..., c] = np.where(alfa_final > 0, img[..., c] * a / np.maximum(alfa_final, 1e-6), 0)
    regiao[..., 3] = alfa_final
    cartao[..., 3] *= 255
    return np.clip(cartao, 0, 255).astype(np.uint8)


def preparar(imagem: Path, ocultar: list[str], saida: Path, largura_video: int, altura_video: int,
             cfg: dict) -> tuple[Path, int, int, int]:
    """Desfoca, monta o cartão e grava o PNG. Devolve (png, regiões desfocadas, largura, altura)."""
    img = _ler(imagem)
    regioes = regioes_a_desfocar(img, ocultar) if cfg.get("desfocar", True) else []
    img = desfocar(img, regioes)
    cartao = montar_cartao(img, round(largura_video * cfg.get("largura_apoio", 0.86)),
                           round(altura_video * cfg.get("altura_max_apoio", 0.42)))
    cv2.imwrite(str(saida), cartao)
    return saida, len(regioes), cartao.shape[1], cartao.shape[0]


def programar(janelas: list[tuple[bool, float, float]], cfg: dict, duracao_video: float,
              inicio_livre: float = 0.0) -> list[tuple[float, float] | None]:
    """Início e fim de cada imagem no vídeo editado (None = não coube).

    janelas: (gancho, início e fim das palavras da âncora), já no vídeo editado. O gancho abre o
    vídeo (depois da caixinha de pergunta, se houver: `inicio_livre`); as outras entram 0,15 s antes
    da âncora (ou assim que a anterior sai) e ficam entre `duracao_minima_apoio` e
    `duracao_maxima_apoio`, sem se sobrepor. Só fica de fora a que cairia no último segundo.
    """
    resultado: list[tuple[float, float] | None] = [None] * len(janelas)
    livre = inicio_livre
    for i, (gancho, _, _) in enumerate(janelas):
        if gancho:
            fim = min(inicio_livre + cfg.get("duracao_gancho", 4.0), duracao_video)
            resultado[i] = (inicio_livre, fim)
            livre = fim + 0.3
    minimo, maximo = cfg.get("duracao_minima_apoio", 3.0), cfg.get("duracao_maxima_apoio", 5.0)
    for i in sorted((i for i, j in enumerate(janelas) if not j[0]), key=lambda i: janelas[i][1]):
        _, dito, fim_dito = janelas[i]
        ini = max(dito - 0.15, livre)
        if ini >= duracao_video - 1.0:
            continue            # atrasada, a imagem ainda entra (o autor a escolheu); sem espaço, não
        fim = min(max(fim_dito + 2.0, ini + minimo), ini + maximo, duracao_video)
        resultado[i] = (ini, fim)
        livre = fim + 0.3
    return resultado
