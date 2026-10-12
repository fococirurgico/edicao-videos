"""Decisão de edição pelo Claude: quais frases ficam, o que destacar e onde dar zoom.

O Claude recebe a transcrição dividida em frases numeradas e devolve só IDs e palavras;
os tempos vêm sempre da transcrição, nunca da resposta do modelo.

Backends:
- assinatura: chama o Claude Code instalado no Mac (`claude -p`), usando a assinatura.
- api: chama a API da Anthropic (precisa de ANTHROPIC_API_KEY e do pacote `anthropic`).
- nenhum: mantém tudo, sem destaques nem zoom.
"""

import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field

from .transcricao import Palavra


@dataclass
class Frase:
    id: int
    texto: str
    inicio: float
    fim: float
    palavras: list[Palavra] = field(repr=False)


@dataclass
class Decisao:
    manter: list[int]
    destaques: list[str]
    zoom: dict[int, float]


ESQUEMA = {
    "type": "object",
    "properties": {
        "manter": {"type": "array", "items": {"type": "integer"},
                   "description": "IDs das frases que ficam no vídeo, em ordem."},
        "destaques": {"type": "array", "items": {"type": "string"},
                      "description": "Palavras a destacar na legenda, escritas como na transcrição."},
        "zoom": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frase": {"type": "integer"}, "nivel": {"type": "number"}},
                "required": ["frase", "nivel"],
                "additionalProperties": False,
            },
            "description": "Frases com zoom de ênfase e o nível (1.0 a 1.2).",
        },
    },
    "required": ["manter", "destaques", "zoom"],
    "additionalProperties": False,
}

INSTRUCOES = """Você é o editor de um vídeo curto vertical (Reels) gravado no celular por um médico.
Abaixo está a transcrição, dividida em frases numeradas com o tempo de cada uma.

Decida a edição:

1. manter: os IDs das frases que ficam no vídeo final.
   - Quando o autor regrava um trecho (repete a mesma ideia), mantenha só a ÚLTIMA versão completa.
   - Remova frases abandonadas no meio, falsos começos e marcas faladas de corte
     ("corta", "de novo", "vou repetir", "ops").
   - Não remova conteúdo só para encurtar: na dúvida, mantenha.
2. destaques: palavras-chave que merecem cor na legenda (números, termos técnicos, a ideia central).
   No máximo uma a cada 5 segundos. Escreva exatamente como aparecem na transcrição.
3. zoom: frases de ênfase (início do vídeo, frase de impacto, chamada para ação) que ganham
   aproximação, com nível entre 1.08 e 1.15. Evite zoom em muitas frases seguidas; cerca de
   uma frase a cada três é um bom ritmo.

Transcrição:
"""


def dividir_em_frases(palavras: list[Palavra], pausa: float = 0.6) -> list[Frase]:
    """Nova frase após pontuação final ou pausa maior que `pausa` segundos."""
    frases: list[Frase] = []
    atual: list[Palavra] = []
    for p in palavras:
        if atual and (re.search(r"[.?!…]$", atual[-1].texto) or p.inicio - atual[-1].fim > pausa):
            frases.append(_frase(len(frases) + 1, atual))
            atual = []
        atual.append(p)
    if atual:
        frases.append(_frase(len(frases) + 1, atual))
    return frases


def _frase(id_: int, palavras: list[Palavra]) -> Frase:
    return Frase(id_, " ".join(p.texto for p in palavras), palavras[0].inicio, palavras[-1].fim, palavras)


def montar_prompt(frases: list[Frase]) -> str:
    linhas = [f"[{f.id}] ({f.inicio:.1f}s–{f.fim:.1f}s) {f.texto}" for f in frases]
    return INSTRUCOES + "\n".join(linhas)


def validar(bruto: dict, frases: list[Frase]) -> Decisao:
    """Descarta IDs e palavras inexistentes; nunca devolve um vídeo vazio."""
    ids = {f.id for f in frases}
    manter = sorted({i for i in bruto.get("manter", []) if i in ids}) or sorted(ids)

    def norm(t: str) -> str:
        return re.sub(r"[^\w]", "", t.lower())

    mantidas = {norm(p.texto) for f in frases if f.id in manter for p in f.palavras}
    destaques = [d for d in bruto.get("destaques", []) if norm(d) and norm(d) in mantidas]
    zoom = {
        z["frase"]: min(1.2, max(1.0, float(z["nivel"])))
        for z in bruto.get("zoom", [])
        if z.get("frase") in manter and "nivel" in z
    }
    return Decisao(manter, destaques, zoom)


def decidir(frases: list[Frase], cfg: dict) -> Decisao:
    """Pede a decisão ao Claude. Se falhar, segue sem decisão (mantém tudo) e avisa."""
    backend = cfg["backend"]
    if backend == "nenhum" or not frases:
        return Decisao([f.id for f in frases], [], {})
    prompt = montar_prompt(frases)
    try:
        if backend == "assinatura":
            bruto = _via_assinatura(prompt, cfg)
        elif backend == "api":
            bruto = _via_api(prompt, cfg)
        else:
            raise ValueError(f"backend de decisão desconhecido: {backend}")
    except Exception as e:  # o vídeo sai mesmo assim, só sem a edição do Claude
        print(f"    aviso: decisão do Claude falhou ({e}); mantendo todas as frases")
        return Decisao([f.id for f in frases], [], {})
    return validar(bruto, frases)


def _via_assinatura(prompt: str, cfg: dict) -> dict:
    cmd = [
        "claude", "-p", "--output-format", "json",
        "--json-schema", json.dumps(ESQUEMA),
        "--max-turns", "3", "--no-session-persistence", "--tools", "",
    ]
    if cfg.get("modelo"):
        cmd += ["--model", cfg["modelo"]]
    # Roda numa pasta vazia para não carregar CLAUDE.md nem configurações de projeto.
    with tempfile.TemporaryDirectory() as pasta:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=cfg.get("timeout", 300), cwd=pasta)
    if r.returncode != 0:
        raise RuntimeError(f"claude saiu com código {r.returncode}: {r.stderr.strip()[:300]}")
    saida = json.loads(r.stdout)
    if saida.get("is_error") or saida.get("subtype") != "success":
        raise RuntimeError(f"claude retornou erro: {str(saida.get('result'))[:300]}")
    return saida.get("structured_output") or json.loads(saida["result"])


def _via_api(prompt: str, cfg: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    resposta = client.beta.messages.create(
        model=cfg.get("modelo_api", "claude-opus-5-5"),
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": ESQUEMA},
        },
        messages=[{"role": "user", "content": prompt}],
    )
    if resposta.stop_reason == "refusal":
        raise RuntimeError("a API recusou o pedido")
    texto = next(b.text for b in resposta.content if b.type == "text")
    return json.loads(texto)


def salvar(decisao: Decisao, frases: list[Frase], caminho) -> None:
    caminho.write_text(json.dumps({
        "frases": [{"id": f.id, "texto": f.texto, "inicio": f.inicio, "fim": f.fim} for f in frases],
        "decisao": asdict(decisao),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
