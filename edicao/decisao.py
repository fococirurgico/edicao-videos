"""Decisão de edição pelo Claude: quais frases ficam, o que destacar, onde dar zoom, o título,
os elementos gráficos e as correções da transcrição.

O Claude recebe a transcrição dividida em frases numeradas e devolve só IDs e palavras;
os tempos vêm sempre da transcrição, nunca da resposta do modelo.

Backends:
- assinatura: chama o Claude Code instalado no Mac (`claude -p`), usando a assinatura.
- api: chama a API da Anthropic (precisa de ANTHROPIC_API_KEY e do pacote `anthropic`).
- nenhum: mantém tudo, sem destaques nem zoom.
"""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    # Modalidade de cada zoom: "seco" (salto na emenda), "suave" (aproximação lenta ao longo
    # da frase) ou "rapido" (aproximação curta e suavizada no início da frase).
    tipo_zoom: dict[int, str] = field(default_factory=dict)
    titulo: str = ""
    # Elementos gráficos: {"frase", "tipo", "texto", "detalhe"} (tipos em graficos.TIPOS).
    elementos: list[dict] = field(default_factory=list)
    # Palavras mal transcritas: {"frase", "errado", "certo"}.
    correcoes: list[dict] = field(default_factory=list)
    # Partes de frases mantidas que saem (falso começo, trecho repetido): {"frase", "trecho"}.
    cortes_parciais: list[dict] = field(default_factory=list)


TIPOS_ZOOM = ("seco", "suave", "rapido")
TIPOS_ELEMENTO = ("numero", "frase", "check", "alerta")

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
                "properties": {
                    "frase": {"type": "integer"},
                    "nivel": {"type": "number"},
                    "tipo": {"type": "string", "enum": list(TIPOS_ZOOM)},
                },
                "required": ["frase", "nivel", "tipo"],
                "additionalProperties": False,
            },
            "description": "Frases com zoom, o nível (1.0 a 1.4) e a modalidade.",
        },
        "titulo": {"type": "string", "description": "Título curto do Reels, mostrado no início."},
        "elementos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase": {"type": "integer"},
                    "tipo": {"type": "string", "enum": list(TIPOS_ELEMENTO)},
                    "texto": {"type": "string"},
                    "detalhe": {"type": "string"},
                },
                "required": ["frase", "tipo", "texto", "detalhe"],
                "additionalProperties": False,
            },
            "description": "Elementos gráficos que aparecem durante a frase.",
        },
        "correcoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase": {"type": "integer"},
                    "errado": {"type": "string"},
                    "certo": {"type": "string"},
                },
                "required": ["frase", "errado", "certo"],
                "additionalProperties": False,
            },
            "description": "Trechos mal transcritos e a forma correta.",
        },
        "cortes_parciais": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase": {"type": "integer"},
                    "trecho": {"type": "string"},
                },
                "required": ["frase", "trecho"],
                "additionalProperties": False,
            },
            "description": "Pedaços de frases mantidas que devem sair (falso começo, repetição).",
        },
    },
    "required": ["manter", "destaques", "zoom", "titulo", "elementos", "correcoes", "cortes_parciais"],
    "additionalProperties": False,
}

INSTRUCOES = """Você é o editor de um vídeo curto vertical (Reels) gravado no celular{autor}.
{contexto}Abaixo está a transcrição, dividida em frases numeradas com o tempo de cada uma.

Decida a edição:

1. manter: os IDs das frases que ficam no vídeo final.
   - Quando o autor regrava um trecho (repete a mesma ideia), mantenha só a ÚLTIMA versão completa.
   - Remova frases abandonadas no meio, falsos começos e marcas faladas de corte
     ("corta", "de novo", "vou repetir", "ops").
   - A transcrição às vezes junta a tentativa errada e a refeita na mesma frase, ou deixa
     palavras soltas de uma tentativa abandonada ("não, não", "ou melhor"). Leia com atenção:
     se uma frase repete um pedaço ("já tive alguns pacientes assim, já tive alguns pacientes
     assim e certamente..."), mantenha a frase e use cortes_parciais para tirar a parte repetida.
   - Não remova conteúdo só para encurtar: na dúvida, mantenha.
2. destaques: palavras-chave que merecem cor na legenda (números, termos técnicos, a ideia central).
   No máximo uma a cada 5 segundos. Escreva exatamente como aparecem na transcrição.
3. zoom: frases que ganham aproximação, com nível entre 1.0 e {zoom_maximo} e uma modalidade (tipo).
   O enquadramento acompanha os olhos automaticamente. O programa já troca o enquadramento a
   cada corte e a cada ~3 s de fala contínua (padrão dos Reels); o seu zoom é o de ênfase, por
   cima disso. Alterne as três modalidades:
   - "seco": o enquadramento salta para o nível na emenda, sem animação. É a escolha natural
     para frases marcadas com ✂ (logo depois de um corte de fala ou de silêncio), porque o salto
     disfarça o corte. Níveis de 1.15 a 1.3.
   - "suave": aproximação lenta e contínua ao longo da frase inteira, cinematográfica. Para
     frases reflexivas, de explicação ou de emoção, de preferência com mais de 3 segundos.
     Níveis de 1.15 a 1.3.
   - "rapido": aproximação curta e suavizada no começo da frase, que depois fica parada.
     Para impacto: gancho inicial, número forte, frase de efeito, chamada para ação.
     Níveis de 1.25 a {zoom_maximo}.
   Evite a mesma modalidade e o mesmo nível em frases seguidas. Dê zoom na maioria das frases:
   mais da metade delas, e sempre na primeira (gancho) e na última (fechamento).
4. titulo: o título do Reels, mostrado num cartão nos primeiros segundos. Curto (até 6 palavras,
   no máximo 40 caracteres), claro para leigos, no tom da marca; pode ser uma pergunta. Sem
   emoji, sem hashtag e sem ponto final.
5. elementos: cartões gráficos animados que reforçam a fala, em frases-chave. Tipos:
   - "numero": um número ou porcentagem dito na frase (texto: "90%", "3 cm", "1 em 10");
     detalhe: o que o número significa, em até 5 palavras.
   - "frase": a ideia central da frase em até 6 palavras (texto); detalhe vazio.
   - "check": algo positivo, um benefício ou uma resposta "sim" (texto em até 5 palavras).
   - "alerta": um cuidado, risco ou "não faça" (texto em até 5 palavras).
   Use de 1 a 4 elementos, só onde reforçam a mensagem, separados por pelo menos 6 segundos e
   nunca na primeira frase (o título aparece nela). Use só o que foi dito: não invente números.
6. correcoes: palavras que a transcrição automática errou, com a forma correta pelo contexto
   (ex.: termos médicos: errado "ar de frequência", certo "radiofrequência"; errado "nódo",
   certo "nódulo"). "errado" deve aparecer exatamente na frase indicada. Só corrija o que tem
   certeza; não reescreva o estilo da fala.
7. cortes_parciais: dentro de uma frase mantida, o pedaço que sai, copiado exatamente da frase
   (palavras seguidas). Use para a primeira tentativa de um trecho repetido (fica a última),
   para um falso começo no início da frase e para marcas de erro ("não, não", "peraí", "ops").
   Lista vazia se não houver.

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


def _contexto_marca(marca: dict) -> tuple[str, str]:
    """Trecho sobre o autor e linhas de contexto da marca (vazios se não configurados)."""
    autor = f" por {marca['autor']}" if marca.get("autor") else ""
    itens = [(rotulo, marca.get(chave, "")) for rotulo, chave in
             (("Marca", "nome"), ("Público", "publico"), ("Tom da comunicação", "tom"))]
    linhas = [f"{rotulo}: {valor}" for rotulo, valor in itens if valor]
    contexto = "\n".join(linhas) + "\n\n" if linhas else ""
    return autor, contexto


def montar_prompt(frases: list[Frase], zoom_maximo: float = 1.4, pausa_corte: float = 0.5,
                  marca: dict | None = None) -> str:
    """Uma linha por frase; ✂ marca frases precedidas de pausa longa (o silêncio será cortado)."""
    autor, contexto = _contexto_marca(marca or {})
    linhas = []
    for i, f in enumerate(frases):
        corte = " ✂" if i > 0 and f.inicio - frases[i - 1].fim >= pausa_corte else ""
        linhas.append(f"[{f.id}]{corte} ({f.inicio:.1f}s–{f.fim:.1f}s) {f.texto}")
    return INSTRUCOES.format(zoom_maximo=zoom_maximo, autor=autor, contexto=contexto) + "\n".join(linhas)


def validar(bruto: dict, frases: list[Frase], zoom_maximo: float = 1.4) -> Decisao:
    """Descarta IDs e palavras inexistentes; nunca devolve um vídeo vazio."""
    ids = {f.id for f in frases}
    manter = sorted({i for i in bruto.get("manter", []) if i in ids}) or sorted(ids)

    def norm(t: str) -> str:
        return re.sub(r"[^\w]", "", t.lower())

    mantidas = {norm(p.texto) for f in frases if f.id in manter for p in f.palavras}
    # Destaques podem vir já com a palavra corrigida.
    mantidas |= {norm(p) for c in bruto.get("correcoes", []) if c.get("frase") in manter
                 for p in str(c.get("certo", "")).split()}
    destaques = [d for d in bruto.get("destaques", []) if norm(d) and norm(d) in mantidas]
    validos = [z for z in bruto.get("zoom", []) if z.get("frase") in manter and "nivel" in z]
    zoom = {z["frase"]: min(zoom_maximo, max(1.0, float(z["nivel"]))) for z in validos}
    tipo_zoom = {z["frase"]: z.get("tipo") if z.get("tipo") in TIPOS_ZOOM else "seco" for z in validos}
    titulo = " ".join(str(bruto.get("titulo", "")).split())[:60]
    elementos = [
        {"frase": e["frase"], "tipo": e["tipo"], "texto": " ".join(str(e["texto"]).split())[:48],
         "detalhe": " ".join(str(e.get("detalhe", "")).split())[:60]}
        for e in bruto.get("elementos", [])
        if e.get("frase") in manter and e.get("tipo") in TIPOS_ELEMENTO and str(e.get("texto", "")).strip()
    ]
    textos = {f.id: norm_frase(f) for f in frases}
    correcoes = [
        {"frase": c["frase"], "errado": c["errado"], "certo": " ".join(str(c["certo"]).split())}
        for c in bruto.get("correcoes", [])
        if c.get("frase") in textos and str(c.get("certo", "")).strip()
        and _tokens(c.get("errado", "")) and _achar(textos[c["frase"]], _tokens(c["errado"])) is not None
    ]
    cortes_parciais = [
        {"frase": c["frase"], "trecho": " ".join(str(c["trecho"]).split())}
        for c in bruto.get("cortes_parciais", [])
        if c.get("frase") in manter and _tokens(c.get("trecho", ""))
        and _achar(textos[c["frase"]], _tokens(c["trecho"])) is not None
        and len(_tokens(c["trecho"])) < len(textos[c["frase"]])     # a frase não sai inteira
    ]
    return Decisao(manter, destaques, zoom, tipo_zoom, titulo, elementos, correcoes, cortes_parciais)


def _tokens(texto: str) -> list[str]:
    return [t for t in (re.sub(r"[^\w]", "", p.lower()) for p in str(texto).split()) if t]


def norm_frase(f: Frase) -> list[str]:
    return [re.sub(r"[^\w]", "", p.texto.lower()) for p in f.palavras]


def _achar(palavras: list[str], alvo: list[str]) -> int | None:
    for i in range(len(palavras) - len(alvo) + 1):
        if palavras[i:i + len(alvo)] == alvo:
            return i
    return None


def palavras_cortadas(frases: list[Frase], cortes_parciais: list[dict]) -> set[tuple[int, int]]:
    """(id da frase, posição da palavra) das palavras que saem pelos cortes parciais."""
    por_id = {f.id: f for f in frases}
    saem = set()
    for c in cortes_parciais:
        f = por_id.get(c["frase"])
        if not f:
            continue
        alvo = _tokens(c["trecho"])
        i = _achar(norm_frase(f), alvo)
        if i is not None:
            saem |= {(f.id, k) for k in range(i, i + len(alvo))}
    return saem


def aplicar_correcoes(frases: list[Frase], correcoes: list[dict]) -> list[Palavra]:
    """Palavras de todas as frases com as correções aplicadas.

    O trecho errado é trocado pelas palavras certas, que dividem o tempo dele em partes
    proporcionais ao tamanho; a pontuação no fim do trecho original é mantida.
    """
    por_frase: dict[int, list[dict]] = {}
    for c in correcoes:
        por_frase.setdefault(c["frase"], []).append(c)
    resultado: list[Palavra] = []
    for f in frases:
        palavras = list(f.palavras)
        for c in por_frase.get(f.id, []):
            alvo = _tokens(c["errado"])
            novas_n = len(c["certo"].split())
            depois = 0
            while True:                                  # todas as ocorrências na frase
                normais = [re.sub(r"[^\w]", "", p.texto.lower()) for p in palavras]
                achado = _achar(normais[depois:], alvo)
                if achado is None:
                    break
                i = depois + achado
                depois = i + novas_n
                trecho = palavras[i:i + len(alvo)]
                novas = c["certo"].split()
                pontuacao = re.search(r"[^\w]*$", trecho[-1].texto).group()
                if pontuacao and not novas[-1].endswith(pontuacao):
                    novas[-1] += pontuacao
                ini, fim = trecho[0].inicio, trecho[-1].fim
                pesos = [len(n) for n in novas]
                total, acumulado = sum(pesos), 0
                substitutas = []
                for n, peso in zip(novas, pesos):
                    a = ini + (fim - ini) * acumulado / total
                    acumulado += peso
                    substitutas.append(Palavra(n, a, ini + (fim - ini) * acumulado / total))
                palavras[i:i + len(alvo)] = substitutas
        resultado += palavras
    return resultado


def decidir(frases: list[Frase], cfg: dict, marca: dict | None = None) -> Decisao:
    """Pede a decisão ao Claude. Se falhar, segue sem decisão (mantém tudo) e avisa."""
    backend = cfg["backend"]
    if backend == "nenhum" or not frases:
        return Decisao([f.id for f in frases], [], {})
    zoom_maximo = cfg.get("zoom_maximo", 1.4)
    prompt = montar_prompt(frases, zoom_maximo, cfg.get("pausa_corte", 0.5), marca)
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
    return validar(bruto, frases, zoom_maximo)


def _via_assinatura(prompt: str, cfg: dict) -> dict:
    return claude_json(prompt, ESQUEMA, cfg)


def claude_json(prompt: str, esquema: dict, cfg: dict, anexos: tuple[Path, ...] = ()) -> dict:
    """Chama o Claude Code (assinatura) e devolve a resposta no formato de `esquema`.

    anexos: arquivos que o Claude pode ler (PDF, imagem). São copiados para a pasta de trabalho
    e só a ferramenta de leitura é liberada.
    """
    ferramentas = "Read" if anexos else ""
    cmd = [
        "claude", "-p", "--output-format", "json",
        "--json-schema", json.dumps(esquema),
        "--max-turns", "8" if anexos else "3", "--no-session-persistence", "--tools", ferramentas,
    ]
    if anexos:
        cmd += ["--allowedTools", "Read"]
    if cfg.get("modelo"):
        cmd += ["--model", cfg["modelo"]]
    # Roda numa pasta vazia para não carregar CLAUDE.md nem configurações de projeto.
    with tempfile.TemporaryDirectory() as pasta:
        for arquivo in anexos:
            shutil.copy(arquivo, Path(pasta) / arquivo.name)
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


def carregar(caminho) -> Decisao:
    """Decisão salva por `salvar` (para refazer o vídeo sem pedir de novo ao Claude)."""
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))["decisao"]
    d["zoom"] = {int(k): v for k, v in d.get("zoom", {}).items()}
    d["tipo_zoom"] = {int(k): v for k, v in d.get("tipo_zoom", {}).items()}
    return Decisao(**d)

