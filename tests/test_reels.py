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
    assert render._pedacos(t) == [(0, 14 / 30, True), (14 / 30, 3, False)]   # 0,45 s → 14 quadros


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
    # O fundo sai igual ao original: a transparência da camada não pode virar um véu escuro
    # (o zscale com r=tv comprimia o alfa: 6% de preto no vídeo todo e gráficos 92% opacos).
    q = _rgb(saida, 10, 180, 320, sdr_de="arib-std-b67")
    original = _rgb(hlg, 10, 360, 640, sdr_de="arib-std-b67")
    assert np.abs(q[160, 90] - [0xC1, 0xA7, 0x52]).max() < 8
    assert np.abs(q[20, 20] - original[40, 40]).max() < 3


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
    assert d.elementos == [{"frase": 2, "tipo": "numero", "texto": "90%", "detalhe": "dos casos", "ancora": ""}]
    assert len(d.correcoes) == 1
    assert d.destaques == ["radiofrequência"]          # vale a palavra já corrigida
    palavras = decisao.aplicar_correcoes(frases, d.correcoes)
    assert [p.texto for p in palavras[:5]] == ["É", "a", "ablação", "por", "radiofrequência."]
    assert (palavras[4].inicio, palavras[4].fim) == (0.7, 1.4)
    assert len(palavras) == 10


def test_prompt_pede_titulo_elementos_e_correcoes():
    texto = decisao.montar_prompt(decisao.dividir_em_frases([Palavra("oi.", 0, 1)]))
    assert all(k in texto for k in ("titulo", "elementos", "correcoes", "cortes_parciais"))


# Elementos gráficos

def test_programar_titulo_e_elementos_no_momento_da_fala():
    g = config.carregar()["graficos"]
    pedidos = [("numero", "90%", "dos casos", 1.0, 1.4),      # dito sob o título: fora de hora, sai
               ("frase", "Sem cicatriz", "", 4.0, 9.0),         # âncora longa: limita a duração
               ("check", "Funciona", "", 5.0, 5.3),             # sobre o anterior: atrasaria demais, sai
               ("alerta", "Não pare", "", 9.6, 10.0)]           # sobre o anterior por pouco: atrasa
    els = graficos.programar("Nódulo sem cirurgia?", pedidos, g, 20.0)
    assert [e.tipo for e in els] == ["titulo", "frase", "alerta"]
    assert els[0].inicio == 0 and els[0].fim == g["duracao_titulo"]
    assert els[1].inicio == pytest.approx(4.0 - 0.15)          # entra junto com a fala
    for a, b in zip(els, els[1:]):
        assert b.inicio >= a.fim
    assert els[1].fim - els[1].inicio <= g["duracao_maxima"] + 1e-9
    assert els[2].inicio - 9.6 <= 1.0
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


def test_pergunta_no_lugar_do_titulo_e_digitada():
    cfg = config.carregar()
    g = cfg["graficos"]
    els = graficos.programar("Título ignorado", [("frase", "Sem cicatriz", "", 6.0, 7.0)], g, 20.0,
                             pergunta="Cisto no pescoço é perigoso?")
    assert [e.tipo for e in els] == ["pergunta", "frase"]
    assert els[0].fim == g["duracao_pergunta"] and els[1].inicio >= els[0].fim
    linhas = graficos.gerar(els[:1], g, cfg["marca"], 1080, 1920, Fraction(30))
    textos = [l.rsplit("}", 1)[-1] for l in linhas if "\\fs76" in l]
    assert "\\1a&HFF&" in [l for l in linhas if "\\fs76" in l][20]     # no começo, ainda digitando
    assert textos[-1].replace("\\N", " ") == "Cisto no pescoço é perigoso?"   # no fim, inteira
    assert any("Faça uma pergunta" in l for l in linhas)


def test_ganho_de_audio_leva_ao_volume_alvo(tmp_path):
    baixo = tmp_path / "baixo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=4:r=30",
                    "-f", "lavfi", "-i", "sine=f=300:d=4,volume=-30dB", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(baixo)], check=True)
    antes = midia.volume_integrado(baixo)
    saida = tmp_path / "alto.mp4"
    render.renderizar(baixo, [plano.Trecho(0, 4, 1.0, quadro=(0, 0, 360, 640))], None, saida,
                      {**config.carregar()["video"], "largura": 360, "altura": 640}, 0.02, (360, 640),
                      ganho_db=-14 - antes)
    assert abs(midia.volume_integrado(saida) - (-14)) < 1.0


def test_tratamento_de_voz_chega_ao_volume_alvo(tmp_path):
    baixo = tmp_path / "baixo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=6:r=30",
                    "-f", "lavfi", "-i", "sine=f=300:d=6,volume=-28dB", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(baixo)], check=True)
    saida = tmp_path / "voz.mp4"
    render.renderizar(baixo, [plano.Trecho(0, 6, 1.0, quadro=(0, 0, 360, 640))], None, saida,
                      {**config.carregar()["video"], "largura": 360, "altura": 640}, 0.02, (360, 640),
                      filtro_audio=render.tratamento_voz(-14))
    assert abs(midia.volume_integrado(saida) - (-14)) < 1.5
    import av
    with av.open(str(saida)) as c:
        assert c.streams.audio[0].codec_context.sample_rate == 48000


def _nivel(video: Path) -> int:
    """level_idc gravado no primeiro quadro (H.264: 42 = 4.2; HEVC: 30 × nível, 153 = 5.1)."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-c:v", "copy", "-bsf:v", "trace_headers",
                          "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True).stderr
    linha = next(l for l in log.splitlines() if "level_idc" in l)
    return int(linha.split("=")[-1])


@pytest.mark.parametrize("hdr", [None, "arib-std-b67"])
def test_nivel_do_video_aceito_pelo_iphone(tmp_path, hdr):
    # Sem nível fixo, o x264/x265 marcavam 6.2 e o iPhone recusava o arquivo ("formato incompatível").
    if hdr and not midia.tem_filtro("zscale"):
        pytest.skip("ffmpeg sem zscale")
    video = tmp_path / "v.mp4"
    # Taxa fracionária e um trecho com zoom animado, como num vídeo real: o x265 recusava abrir com o
    # nível fixo ("frame rate is out of range for specified level").
    fps = Fraction(30000, 1001)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=gray:s=360x640:d=2:r=30000/1001", "-f", "lavfi", "-i", "sine=d=2", "-shortest",
                    "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    if hdr:
        video = _hlg(tmp_path, video)
    saida = tmp_path / "saida.mp4"
    trechos = [plano.Trecho(0, 0.8, 1.0, quadro=(0, 0, 360, 640)),
               plano.Trecho(1.0, 1.8, 1.4, quadro=(51, 91, 257, 457), tipo="rapido",
                            quadro_inicial=(0, 0, 360, 640), anim_duracao=0.45)]
    render.renderizar(video, trechos, None, saida, {**config.carregar()["video"], "largura": 360, "altura": 640},
                      0.02, (360, 640), hdr, fps=fps)
    assert _nivel(saida) == (153 if hdr else 42)


def test_tratamento_de_voz_nao_atrasa_o_som():
    """O afftdn atrasa 25 ms; a cadeia compensa (um impulso sai no mesmo lugar e com a mesma duração)."""
    import numpy as np
    sr = 48000
    x = np.zeros(sr * 4, np.float32)
    x[sr * 2] = 0.5
    x += np.random.default_rng(0).normal(0, 1e-4, len(x)).astype(np.float32)
    filtro = render.tratamento_voz(-14).replace(",loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000", "")
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
                        "-af", filtro, "-f", "f32le", "-"], input=x.tobytes(), capture_output=True, check=True)
    y = np.frombuffer(r.stdout, np.float32)
    assert len(y) == len(x)
    assert abs(int(np.argmax(np.abs(y))) - sr * 2) <= 48            # até 1 ms


def test_zoom_animado_em_10_bits_nao_transborda(tmp_path):
    # Pontos no brilho máximo (1023) ao lado de preto: o bicúbico passava de 1023 e o FFV1 de
    # 10 bits gravava lixo colorido daí até o quadro-chave seguinte (IMG_4038, reflexo nos óculos).
    larg, alt, n = 360, 640, 20
    y = np.full((alt, larg), 64, np.uint16)
    y[::16, ::16] = 1023
    y[1::16, ::16] = 1023
    c = np.full((alt // 2, larg // 2), 512, np.uint16)
    bruto = tmp_path / "fonte.yuv"
    bruto.write_bytes((y.tobytes() + c.tobytes() + c.tobytes()) * n)
    fonte = tmp_path / "fonte.mkv"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p10le",
                    "-s", f"{larg}x{alt}", "-r", "30", "-i", str(bruto), "-c:v", "ffv1", str(fonte)], check=True)
    t = plano.Trecho(0, n / 30, 1.4, quadro=(51, 91, 257, 457), tipo="suave",
                     quadro_inicial=(0, 0, larg, alt), anim_duracao=n / 30)
    saida = tmp_path / "anim.mkv"
    render.animar(fonte, t, 0, n / 30, saida, larg, alt, Fraction(30), (larg, alt), True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(saida), "-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-"],
                       capture_output=True, check=True)
    tam = (larg * alt + 2 * (larg // 2) * (alt // 2)) * 2
    for k in range(len(r.stdout) // tam):
        q = np.frombuffer(r.stdout[k * tam:(k + 1) * tam], np.uint16)
        croma = q[larg * alt:].astype(np.int32)
        assert np.abs(croma - 512).max() < 40, f"quadro {k} com cor que não existe na origem"


def _ass_quadrado(arquivo: Path, x: int, y: int):
    arquivo.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 180\nPlayResY: 320\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        "Style: G,Arial,20,&H00FFFFFF,&H0,&H0,&H0,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:05.00,G,,0,0,0,,{{\\an7\\pos({x},{y})\\p1}}m 0 0 l 50 0 l 50 50 l 0 50\n",
        encoding="utf-8")


def test_caixinha_de_pergunta_sai_branca_no_hdr(tmp_path):
    # Com o branco a 203 nits (o da legenda e dos cartões), a caixinha ficava cinza no iPhone.
    if not midia.tem_filtro("zscale"):
        pytest.skip("ffmpeg sem zscale")
    cinza = tmp_path / "cinza.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=1:r=30",
                    "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(cinza)],
                   check=True)
    hlg = _hlg(tmp_path, cinza)
    legenda, caixinha = tmp_path / "legenda.ass", tmp_path / "caixinha.ass"
    _ass_quadrado(legenda, 10, 10)
    _ass_quadrado(caixinha, 110, 250)
    saida = tmp_path / "hdr.mp4"
    render.renderizar(hlg, [plano.Trecho(0, 1, 1.0, quadro=(0, 0, 360, 640))], legenda, saida,
                      {**config.carregar()["video"], "largura": 180, "altura": 320}, 0.02, (360, 640),
                      "arib-std-b67", graficos_claros=caixinha, nits_claros=600)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(saida), "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-"], capture_output=True, check=True)
    y = np.frombuffer(r.stdout[:180 * 320 * 2], np.uint16).reshape(320, 180)
    assert abs(int(np.median(y[20:50, 20:50])) - 720) < 15     # legenda: branco de referência
    assert abs(int(np.median(y[260:290, 120:150])) - 870) < 15  # caixinha: branco claro


def test_pergunta_quebra_linha_pela_fonte_do_instagram():
    # Medida com a fonte da marca, a pergunta cabia numa linha e vazava da caixa (IMG_2764).
    arquivo = graficos.arquivo_sistema("Helvetica Neue", 700)
    if not arquivo:
        pytest.skip("Helvetica Neue não instalada")
    texto = "Nódulo na tireoide sempre indica cirurgia?"
    d = graficos.Desenhista(config.carregar()["graficos"], config.carregar()["marca"], 1080, 1920, Fraction(30))
    d._pergunta(graficos.Elemento("pergunta", texto, "", 0, 4))
    linhas = graficos.quebrar(texto, 76, 1080 * 0.8 - 2 * 52, arquivo, 700)
    assert len(linhas) >= 2
    assert all(graficos.largura_texto(l, 76, arquivo, 700) <= 1080 * 0.8 - 2 * 52 for l in linhas)
