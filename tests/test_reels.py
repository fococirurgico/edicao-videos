"""Legenda de uma palavra, ritmo de zoom dos Reels, zoom animado liso, HDR mantido e gráficos."""

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from edicao import config, decisao, graficos, legendas, midia, plano, render
from edicao.transcricao import Palavra


@pytest.fixture(autouse=True)
def pasta_usuario_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICAO_PASTA", str(tmp_path / "usuario"))


def _palavras(*itens):
    return [Palavra(t, i, f) for t, i, f in itens]


def _rgb(video, n, w, h, sdr_de=None):
    """Quadro n como RGB 8 bits; sdr_de converte de HDR (curva dada) para SDR antes."""
    conversao = ""
    if sdr_de:
        conversao = (f"setparams=color_primaries=bt2020:color_trc={sdr_de}:colorspace=bt2020nc:range=tv,"
                     "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,"
                     "zscale=t=iec61966-2-1:m=bt709:r=pc,")
    dados = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf",
         f"select=eq(n\\,{n}),{conversao}format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(dados, np.uint8).reshape(h, w, 3).astype(int)


# Legenda

def test_legenda_uma_palavra_por_vez_com_pop_e_destaque_maior():
    cfg = config.carregar()
    marca = {**cfg["marca"], "cor_texto": "#C1A752"}
    ass = legendas.gerar_ass(
        _palavras(("tireoide", 0.0, 0.5), ("nódulo", 0.6, 1.1), ("benigno.", 2.5, 3.0)),
        cfg["legendas"], marca, 1080, 1920, destaques={"nódulo"},
    )
    estilo = next(l for l in ass.splitlines() if l.startswith("Style: Padrao")).split(",")
    assert estilo[3] == "&H0052A7C1"                       # dourado da marca
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert [e.rsplit("}", 1)[-1] for e in eventos] == ["TIREOIDE", "NÓDULO", "BENIGNO."]
    assert eventos[0].split(",")[2] == "0:00:00.60"         # fica até a próxima palavra começar
    assert eventos[1].split(",")[2] == "0:00:01.35"         # pausa longa: some logo depois de dita
    assert "\\t(" in eventos[0]                            # entra com pop
    assert "\\fscx125" in eventos[1] and "\\fscx100" in eventos[0]


# Ritmo do zoom

def test_ritmo_divide_fala_longa_e_alterna_nivel_com_animacao():
    palavras = [Palavra(f"p{i}", i * 0.5, i * 0.5 + 0.4) for i in range(20)]     # 10 s de fala
    trechos = plano.aplicar_ritmo([plano.Trecho(0, 10, 1.0, frase=1)], palavras, 3.0, 0.15, 1.4)
    assert len(trechos) == 3
    assert [t.zoom for t in trechos] == [1.0, 1.15, 1.0]
    assert [t.tipo for t in trechos] == ["seco", "rapido", "rapido"]
    assert trechos[0].fim == pytest.approx(2.95) and trechos[1].inicio == trechos[0].fim
    plano.planejar_movimento(trechos, 0.45, 0, 1.4)
    assert [t.zoom_inicial for t in trechos[1:]] == [1.0, 1.15]   # parte do nível anterior
    # Trecho curto ou "suave" fica como está.
    curto = [plano.Trecho(0, 3.5, 1.2)]
    assert plano.aplicar_ritmo(curto, palavras, 3.0, 0.15, 1.4) == curto
    suave = [plano.Trecho(0, 10, 1.2, tipo="suave")]
    assert plano.aplicar_ritmo(suave, palavras, 3.0, 0.15, 1.4) == suave


def test_animacao_depois_de_corte_parte_de_1():
    trechos = [plano.Trecho(0, 1, 1.15), plano.Trecho(1.5, 3, 1.3, tipo="rapido")]
    plano.planejar_movimento(trechos, 0.45, 0, 1.4)
    assert trechos[1].zoom_inicial == 1.0


# Zoom animado

def _fonte_textura(tmp_path, w=360, h=640, d=1):
    fonte = tmp_path / "textura.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d={d}:r=30",
                    "-f", "lavfi", "-i", f"sine=d={d}", "-shortest", "-c:v", "libx264", "-crf", "10",
                    "-c:a", "aac", str(fonte)], check=True)
    return fonte


def test_zoom_animado_e_liso_quadro_a_quadro(tmp_path):
    """A janela muda um pouco a cada quadro (sem quadros repetidos nem saltos)."""
    fonte = _fonte_textura(tmp_path)
    cfg_video = {**config.carregar()["video"], "largura": 180, "altura": 320}
    t = plano.Trecho(0, 1, 1.4, quadro=(51, 91, 257, 457), tipo="suave",
                     quadro_inicial=(0, 0, 360, 640), anim_duracao=1.0)
    saida = tmp_path / "anim.mp4"
    render.renderizar(fonte, [t], None, saida, cfg_video, 0.02, (360, 640), fps=Fraction(30))
    quadros = [_rgb(saida, n, 180, 320) for n in range(4, 26)]
    diferencas = [np.abs(a - b).mean() for a, b in zip(quadros, quadros[1:])]
    assert min(diferencas) > 0.3                       # todo quadro se move
    assert max(diferencas) < 3 * np.median(diferencas)  # sem trancos


def test_janela_interpola_em_escala_geometrica():
    t = plano.Trecho(0, 1, 2.0, quadro=(90, 160, 180, 320), tipo="suave",
                     quadro_inicial=(0, 0, 360, 640), anim_duracao=1.0)
    x, y, w, h = render._janela(t, 0.5)
    assert w == pytest.approx(360 / 2 ** 0.5)
    assert x + w / 2 == pytest.approx(180)             # o centro não sai do lugar


def test_rapido_anima_so_o_inicio():
    t = plano.Trecho(0, 3, 1.3, quadro=(1, 1, 2, 2), tipo="rapido", quadro_inicial=(0, 0, 4, 4),
                     anim_duracao=0.45)
    assert render._pedacos(t) == [(0, 0.45, True), (0.45, 3, False)]


# HDR mantido

def _hlg(tmp_path, origem):
    hlg = tmp_path / "hlg.mov"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(origem), "-vf",
                    "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv,"
                    "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt2020,"
                    "zscale=t=arib-std-b67:npl=203:m=bt2020nc:r=tv,format=yuv420p10le",
                    "-c:v", "libx265", "-x265-params", "log-level=error", "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-c:a", "copy", str(hlg)],
                   check=True)
    return hlg


def test_hdr_mantido_com_legenda_na_cor_da_marca(tmp_path):
    if not midia.tem_filtro("zscale"):
        pytest.skip("ffmpeg sem zscale")
    cinza = tmp_path / "cinza.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=1:r=30",
                    "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(cinza)],
                   check=True)
    hlg = _hlg(tmp_path, cinza)
    # Quadrado dourado no centro, desenhado pelo libass.
    ass = tmp_path / "q.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 180\nPlayResY: 320\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        "Style: G,Arial,20,&H0052A7C1,&H0,&H0,&H0,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:05.00,G,,0,0,0,,{\\an5\\pos(90,160)\\p1}m 0 0 l 80 0 l 80 80 l 0 80\n",
        encoding="utf-8")
    cfg_video = {**config.carregar()["video"], "largura": 180, "altura": 320}
    saida = tmp_path / "hdr.mp4"
    render.renderizar(hlg, [plano.Trecho(0, 1, 1.0, quadro=(0, 0, 360, 640))], ass, saida, cfg_video,
                      0.02, (360, 640), "arib-std-b67")
    assert midia.transferencia_hdr(saida) == "arib-std-b67"
    import av
    with av.open(str(saida)) as c:
        cc = c.streams.video[0].codec_context
        assert cc.name == "hevc" and cc.pix_fmt == "yuv420p10le"
    # De volta em SDR, o quadrado tem o dourado #C1A752 e o fundo continua cinza.
    q = _rgb(saida, 10, 180, 320, sdr_de="arib-std-b67")
    assert np.abs(q[160, 90] - [0xC1, 0xA7, 0x52]).max() < 14
    assert np.abs(q[20, 20] - [0x80, 0x80, 0x80]).max() < 14


# Decisão: título, elementos e correções

def test_validar_titulo_elementos_e_correcoes():
    frases = decisao.dividir_em_frases(_palavras(
        ("É", 0, 0.2), ("a", 0.2, 0.3), ("ablação", 0.3, 0.6), ("por", 0.6, 0.7), ("ar", 0.7, 0.8),
        ("de", 0.8, 0.9), ("frequência.", 0.9, 1.4), ("Funciona", 3, 3.5), ("em", 3.5, 3.6),
        ("90%", 3.6, 4.0), ("dos", 4.0, 4.2), ("casos.", 4.2, 4.6),
    ))
    d = decisao.validar({
        "manter": [1, 2], "destaques": ["radiofrequência"], "zoom": [],
        "titulo": "  Nódulo   sem cirurgia?  ",
        "elementos": [{"frase": 2, "tipo": "numero", "texto": "90%", "detalhe": "dos casos"},
                      {"frase": 2, "tipo": "inventado", "texto": "x", "detalhe": ""},
                      {"frase": 9, "tipo": "frase", "texto": "x", "detalhe": ""}],
        "correcoes": [{"frase": 1, "errado": "ar de frequência", "certo": "radiofrequência"},
                      {"frase": 1, "errado": "não existe", "certo": "x"}],
    }, frases)
    assert d.titulo == "Nódulo sem cirurgia?"
    assert d.elementos == [{"frase": 2, "tipo": "numero", "texto": "90%", "detalhe": "dos casos"}]
    assert len(d.correcoes) == 1
    assert d.destaques == ["radiofrequência"]          # vale a palavra já corrigida
    palavras = decisao.aplicar_correcoes(frases, d.correcoes)
    assert [p.texto for p in palavras[:5]] == ["É", "a", "ablação", "por", "radiofrequência."]
    assert (palavras[4].inicio, palavras[4].fim) == (0.7, 1.4)
    assert len(palavras) == 10


def test_prompt_pede_titulo_elementos_e_correcoes():
    texto = decisao.montar_prompt(decisao.dividir_em_frases([Palavra("oi.", 0, 1)]))
    assert "titulo" in texto and "elementos" in texto and "correcoes" in texto


# Elementos gráficos

def test_programar_titulo_e_elementos_sem_sobrepor():
    g = config.carregar()["graficos"]
    pedidos = [("numero", "90%", "dos casos", 1.0, 2.0),      # cairia sobre o título: desloca
               ("frase", "Sem cicatriz", "", 4.0, 9.0),         # frase longa: limita a duração
               ("check", "Funciona", "", 4.5, 5.0)]             # sobre o anterior: desloca
    els = graficos.programar("Nódulo sem cirurgia?", pedidos, g, 20.0)
    assert [e.tipo for e in els] == ["titulo", "numero", "frase", "check"]
    assert els[0].inicio == 0 and els[0].fim == g["duracao_titulo"]
    for a, b in zip(els, els[1:]):
        assert b.inicio >= a.fim
    assert els[2].fim - els[2].inicio <= g["duracao_maxima"] + 1e-9
    assert graficos.programar("", pedidos, {**g, "elementos": False}, 20.0) == []


def test_graficos_quadro_a_quadro_sem_buraco_entre_eventos():
    cfg = config.carregar()
    els = [graficos.Elemento("titulo", "Nódulo sem cirurgia?", "", 0, 1.0),
           graficos.Elemento("numero", "90%", "dos casos", 1.0, 2.0),
           graficos.Elemento("check", "Sem cicatriz", "", 2.0, 3.0),
           graficos.Elemento("alerta", "Não pare o acompanhamento", "", 3.0, 4.0),
           graficos.Elemento("frase", "Destrói o nódulo por dentro", "", 4.0, 5.0)]
    linhas = graficos.gerar(els, cfg["graficos"], cfg["marca"], 1080, 1920, Fraction(30))
    fundos = [l for l in linhas if l.startswith("Dialogue: 10,")]
    assert len(fundos) == 5 * 30                       # um fundo por quadro, sem repetir as bordas
    tempos = [(l.split(",")[1], l.split(",")[2]) for l in fundos[:30]]
    assert all(fim == prox for (_, fim), (prox, _) in zip(tempos, tempos[1:]))
    # A contagem do número sobe até o valor dito.
    numeros = [l.rsplit("}", 1)[-1] for l in linhas if "\\fs190" in l]
    assert numeros[0] == "0%" and numeros[-1] == "90%"


def test_render_dos_graficos(tmp_path):
    """O ASS com legenda e gráficos é aceito pelo libass e desenha algo no quadro."""
    cfg = config.carregar()
    els = graficos.programar("Nódulo sem cirurgia?", [("check", "Funciona", "", 0.5, 2)],
                             {**cfg["graficos"], "duracao_titulo": 1.0}, 5.0)
    ass = tmp_path / "g.ass"
    ass.write_text(legendas.gerar_ass(_palavras(("oi", 0, 0.5)), cfg["legendas"], cfg["marca"], 1080, 1920,
                                      graficos=graficos.gerar(els, cfg["graficos"], cfg["marca"], 1080, 1920,
                                                              Fraction(30)),
                                      estilos_extras=[graficos.estilo(cfg["marca"])]), encoding="utf-8")
    fonte = tmp_path / "preto.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=5:r=30",
                    "-f", "lavfi", "-i", "sine=d=5", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(fonte)],
                   check=True)
    saida = tmp_path / "g.mp4"
    render.renderizar(fonte, [plano.Trecho(0, 5, 1.0, quadro=(0, 0, 1080, 1920))], ass, saida,
                      config.carregar()["video"], 0.02, (1080, 1920))
    titulo = _rgb(saida, 20, 1080, 1920)
    assert titulo[230:350, 200:880].mean() > 60        # cartão claro do título no alto
    check = _rgb(saida, 90, 1080, 1920)
    assert check[230:340, 150:930].mean() > 15         # cartão do check
    assert check[1700:, :].mean() < 1                  # embaixo, nada além da legenda
