import subprocess
from pathlib import Path

import pytest

from edicao import config, decisao, legendas, midia, plano, rosto
from edicao.cli import processar
from edicao.transcricao import Palavra, salvar


@pytest.fixture(autouse=True)
def pasta_usuario_isolada(tmp_path, monkeypatch):
    """Os testes nunca leem nem gravam a configuração real deste computador."""
    monkeypatch.setenv("EDICAO_PASTA", str(tmp_path / "usuario"))


@pytest.fixture
def video(tmp_path: Path) -> Path:
    """Vídeo vertical de 4s: tom 0–1s, silêncio 1–2.5s, tom 2.5–4s."""
    caminho = tmp_path / "bruto.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=4:r=30",
         "-f", "lavfi", "-i", "sine=f=440:d=4",
         "-filter_complex", "[1:a]volume=enable='between(t,1,2.5)':volume=0[a]",
         "-map", "0:v", "-map", "[a]", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(caminho)],
        check=True,
    )
    return caminho


def test_detecta_silencio(video):
    silencios = midia.detectar_silencios(video, -35, 0.5)
    assert len(silencios) == 1
    ini, fim = silencios[0]
    assert ini == pytest.approx(1.0, abs=0.1)
    assert fim == pytest.approx(2.5, abs=0.1)


def test_trechos_com_folga_e_uniao():
    trechos = plano.trechos_mantidos(10.0, [(2.0, 4.0), (4.1, 6.0)], folga=0.1)
    assert [(t.inicio, t.fim) for t in trechos] == [
        (0.0, pytest.approx(2.1)), (pytest.approx(3.9), pytest.approx(4.2)), (pytest.approx(5.9), 10.0)
    ]
    # Silêncio curto (0,3s) com folga de 0,2s: as bordas se encostam e os trechos se unem.
    unidos = plano.trechos_mantidos(10.0, [(2.0, 2.3), (2.5, 6.0)], folga=0.2)
    assert [(t.inicio, t.fim) for t in unidos] == [(0.0, pytest.approx(2.7)), (pytest.approx(5.8), 10.0)]


def test_remapear_descarta_palavras_cortadas():
    trechos = [plano.Trecho(0, 1), plano.Trecho(2.5, 4)]
    palavras = [Palavra("um", 0.2, 0.6), Palavra("corte", 1.5, 2.0), Palavra("dois", 2.7, 3.1)]
    r = plano.remapear(palavras, trechos)
    assert [p.texto for p in r] == ["um", "dois"]
    assert r[1].inicio == pytest.approx(1.2)


def test_legenda_em_blocos_destaca_palavra_atual_e_destaques():
    cfg = config.carregar()
    ass = legendas.gerar_ass(
        [Palavra("olha", 0, 0.4), Palavra("resultado", 0.4, 1.0)], {**cfg["legendas"], "palavras_por_linha": 3},
        cfg["marca"], 1080, 1920,
        destaques={"Resultado"},
    )
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert len(eventos) == 2
    assert "&H0000D4FF}OLHA" in eventos[0]          # palavra atual em amarelo
    assert "&H00FFE500}RESULTADO" in eventos[0]     # destaque em ciano


def test_processar_ponta_a_ponta(video, tmp_path):
    transc = tmp_path / "t.json"
    salvar([Palavra("primeira", 0.1, 0.8), Palavra("segunda", 2.7, 3.5)], transc)
    saida = tmp_path / "editado.mp4"
    cfg = config.carregar()
    cfg["decisao"]["backend"] = "nenhum"
    processar(video, saida, cfg, transc)

    assert midia.duracao(saida) == pytest.approx(2.5 + 2 * cfg["cortes"]["folga"], abs=0.15)
    assert midia.dimensoes(saida) == (1080, 1920)


def _palavras(*itens):
    return [Palavra(t, i, f) for t, i, f in itens]


def test_divide_frases_por_pontuacao_e_pausa():
    frases = decisao.dividir_em_frases(_palavras(
        ("Oi.", 0.0, 0.3), ("tudo", 0.4, 0.6), ("bem", 0.6, 0.9), ("depois", 2.0, 2.4),
    ))
    assert [f.texto for f in frases] == ["Oi.", "tudo bem", "depois"]


def test_validar_descarta_ids_e_palavras_inexistentes():
    frases = decisao.dividir_em_frases(_palavras(("um", 0, 0.4), ("dois", 1.5, 1.9)))
    d = decisao.validar(
        {"manter": [2, 99], "destaques": ["dois", "inventada", "um"],
         "zoom": [{"frase": 2, "nivel": 3.0}, {"frase": 1, "nivel": 1.1}]},
        frases,
    )
    assert d.manter == [2]
    assert d.destaques == ["dois"]          # "um" foi cortada, "inventada" não existe
    assert d.zoom == {2: 1.4}               # nível limitado a 1,4; zoom em frase cortada ignorado
    # Resposta vazia nunca apaga o vídeo inteiro.
    assert decisao.validar({"manter": []}, frases).manter == [1, 2]


def test_aplicar_decisao_corta_retake_e_audio_nao_transcrito():
    # Frase 1 é um retake (cortada), frase 2 é a versão boa; 4.0–5.0 tem áudio sem transcrição
    # (costuma ser a tentativa errada que o Whisper pulou): sai também.
    frases = decisao.dividir_em_frases(_palavras(
        ("versão", 0.0, 0.5), ("ruim.", 0.5, 1.0), ("versão", 1.4, 1.9), ("boa.", 1.9, 2.4),
    ))
    d = decisao.Decisao(manter=[2], destaques=[], zoom={2: 1.1})
    trechos = plano.aplicar_decisao([plano.Trecho(0.0, 5.0)], frases, d, folga=0.08)
    assert trechos[0].inicio == pytest.approx(1.32)    # retake removido, folga antes da frase boa
    assert trechos[-1].fim == pytest.approx(2.48)      # áudio não transcrito removido
    assert all(t.zoom == 1.1 for t in trechos)


def test_corte_parcial_tira_a_repeticao_dentro_da_frase():
    frases = decisao.dividir_em_frases(_palavras(
        ("já", 0.0, 0.2), ("tive", 0.2, 0.4), ("pacientes,", 0.4, 0.9),
        ("não", 1.1, 1.3), ("não,", 1.3, 1.5),
        ("já", 1.7, 1.9), ("tive", 1.9, 2.1), ("pacientes", 2.1, 2.6), ("assim.", 2.6, 3.0),
    ))
    assert len(frases) == 1
    bruto = {"manter": [1], "cortes_parciais": [{"frase": 1, "trecho": "já tive pacientes, não não"},
                                                {"frase": 1, "trecho": "inexistente"}]}
    d = decisao.validar(bruto, frases)
    assert d.cortes_parciais == [{"frase": 1, "trecho": "já tive pacientes, não não"}]
    trechos = plano.aplicar_decisao([plano.Trecho(0.0, 3.5)], frases, d, folga=0.08)
    assert len(trechos) == 1
    assert trechos[0].inicio == pytest.approx(1.62) and trechos[0].fim == pytest.approx(3.08)
    # Uma frase nunca sai inteira por corte parcial.
    assert decisao.validar({"manter": [1], "cortes_parciais": [
        {"frase": 1, "trecho": frases[0].texto}]}, frases).cortes_parciais == []


def test_palavra_esticada_mantem_so_o_fim():
    # O Whisper às vezes estica uma palavra sobre fala que não transcreveu ("não, não, não…").
    frases = decisao.dividir_em_frases(_palavras(("certamente", 0.0, 0.8), ("vão", 0.9, 4.0),
                                                 ("surgir.", 4.0, 4.5)))
    d = decisao.Decisao(manter=[1], destaques=[], zoom={})
    trechos = plano.aplicar_decisao([plano.Trecho(0.0, 5.0)], frases, d, folga=0.08)
    assert [(round(t.inicio, 2), round(t.fim, 2)) for t in trechos] == [(0.0, 0.88), (3.55, 4.58)]


def test_decisao_sem_backend_mantem_tudo():
    frases = decisao.dividir_em_frases(_palavras(("a.", 0, 0.5), ("b.", 1, 1.5)))
    d = decisao.decidir(frases, {"backend": "nenhum"})
    assert d.manter == [1, 2] and d.destaques == [] and d.zoom == {}


def test_falha_do_claude_nao_impede_o_video(monkeypatch):
    frases = decisao.dividir_em_frases(_palavras(("a.", 0, 0.5)))
    def falha(*a, **k):
        raise FileNotFoundError("claude")
    monkeypatch.setattr(decisao, "_via_assinatura", falha)
    assert decisao.decidir(frases, {"backend": "assinatura"}).manter == [1]


def _olhos(x, y, t=0.5, distancia=0.04):
    return rosto.Olhos(t, (x - distancia / 2, y), (x + distancia / 2, y))


def test_enquadra_olhos_centralizados_e_um_pouco_acima():
    # Imagem horizontal 1920x1080, olhos à direita: a janela 9:16 acompanha os olhos.
    q = rosto.enquadrar([_olhos(0.7, 0.4)], 0, 1, 1.2, 1920, 1080, 9 / 16, 0.42, 0.12)
    assert q.zoom == 1.2
    olho_x = (0.7 * 1920 - q.x) / q.largura
    olho_y = (0.4 * 1080 - q.y) / q.altura
    assert olho_x == pytest.approx(0.5, abs=0.01)
    assert olho_y == pytest.approx(0.42, abs=0.01)


def test_zoom_1_em_video_vertical_nao_move():
    q = rosto.enquadrar([_olhos(0.3, 0.3)], 0, 1, 1.0, 1080, 1920, 9 / 16, 0.42, 0.12)
    assert (q.x, q.y, q.largura, q.altura) == (0, 0, 1080, 1920)


def test_olhos_na_borda_reduzem_o_zoom_para_caber():
    # Olhos colados na borda esquerda: com 1,4 sairiam da margem; o zoom diminui.
    q = rosto.enquadrar([_olhos(0.06, 0.4, distancia=0.08)], 0, 1, 1.4, 1080, 1920, 9 / 16, 0.42, 0.12)
    assert q.zoom < 1.4
    assert q.x == 0
    for px in (0.02, 0.10):
        assert (px * 1080 - q.x) / q.largura >= 0.12 or q.zoom == 1.0


def test_sem_rosto_centraliza():
    q = rosto.enquadrar([], 0, 1, 1.25, 1080, 1920, 9 / 16, 0.42, 0.12)
    assert q.x == pytest.approx((1080 - q.largura) / 2, abs=1)


def test_tipo_de_zoom_validado_e_padrao_seco():
    frases = decisao.dividir_em_frases(_palavras(("um.", 0, 0.4), ("dois.", 1.5, 1.9)))
    d = decisao.validar({"manter": [1, 2], "destaques": [],
                         "zoom": [{"frase": 1, "nivel": 1.2, "tipo": "suave"},
                                  {"frase": 2, "nivel": 1.3, "tipo": "inventado"}]}, frases)
    assert d.tipo_zoom == {1: "suave", 2: "seco"}


def test_prompt_marca_frases_depois_de_corte():
    frases = decisao.dividir_em_frases(_palavras(("um.", 0, 0.4), ("dois.", 0.5, 0.9), ("três.", 2.0, 2.4)))
    linhas = decisao.montar_prompt(frases).splitlines()[-3:]
    assert "✂" not in linhas[0] and "✂" not in linhas[1] and "✂" in linhas[2]


def test_suave_continua_entre_pedacos_da_frase_e_rapido_tem_duracao_fixa():
    trechos = [
        plano.Trecho(0, 2, 1.2, tipo="suave", frase=1),
        plano.Trecho(2.8, 4, 1.2, tipo="suave", frase=1),   # mesma frase, depois de um silêncio
        plano.Trecho(4, 6, 1.3, tipo="rapido", frase=2),
    ]
    plano.planejar_movimento(trechos, 0.4, 0.12, 1.4)
    assert (trechos[0].anim_decorrido, trechos[0].anim_duracao) == (0, pytest.approx(3.2))
    assert trechos[1].anim_decorrido == pytest.approx(2.0)
    assert (trechos[2].anim_decorrido, trechos[2].anim_duracao) == (0, 0.4)


def test_corte_seco_muda_o_nivel_quando_ficaria_igual():
    trechos = [plano.Trecho(0, 1, 1.0), plano.Trecho(1.6, 2.5, 1.0), plano.Trecho(2.5, 3, 1.0),
               plano.Trecho(3.5, 4, 1.35), plano.Trecho(4.5, 5, 1.35)]
    plano.planejar_movimento(trechos, 0.4, 0.12, 1.4)
    assert [t.zoom for t in trechos] == [1.0, 1.12, 1.0, 1.35, 1.23]
    # trecho 3 não vem de corte (emenda contínua), então fica como está;
    # no último, subir passaria do máximo, então o salto é para baixo.


def _quadro(video, n):
    import numpy as np
    dados = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"select=eq(n\\,{n}),scale=90:160",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(dados, np.uint8).astype(int)


def test_render_com_zoom_animado(tmp_path):
    from edicao import render
    fonte = tmp_path / "padrao.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:d=1:r=30",
                    "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(fonte)],
                   check=True)
    cfg_video = config.carregar()["video"]
    inicial, final = (0, 0, 360, 640), (56, 104, 248, 440)
    anim = plano.Trecho(0, 1, 1.45, quadro=final, tipo="rapido", quadro_inicial=inicial, anim_duracao=0.3)
    parado_ini = plano.Trecho(0, 1, 1.0, quadro=inicial)
    parado_fim = plano.Trecho(0, 1, 1.45, quadro=final)
    saidas = {}
    for nome, t in (("anim", anim), ("ini", parado_ini), ("fim", parado_fim)):
        saidas[nome] = tmp_path / f"{nome}.mp4"
        render.renderizar(fonte, [t], None, saidas[nome], cfg_video, 0.02, (360, 640))

    def diferenca(a, b):
        return abs(a - b).mean()
    # A animação começa igual ao enquadramento inicial e termina igual ao final.
    assert diferenca(_quadro(saidas["anim"], 0), _quadro(saidas["ini"], 0)) < 8
    assert diferenca(_quadro(saidas["anim"], 25), _quadro(saidas["fim"], 25)) < 8
    assert diferenca(_quadro(saidas["ini"], 0), _quadro(saidas["fim"], 0)) > 15


def _saturacao_media(video):
    saida = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "format=yuv420p,signalstats,metadata=print:file=-",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(saida.split("lavfi.signalstats.SATAVG=")[1].split()[0])


def test_hdr_do_iphone_sai_em_sdr_sem_ficar_lavado(tmp_path):
    from edicao import render
    if not midia.tem_filtro("zscale"):
        pytest.skip("ffmpeg sem zscale")
    sdr, hlg = tmp_path / "sdr.mp4", tmp_path / "hlg.mov"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:d=1:r=30",
                    "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(sdr)],
                   check=True)
    # Simula a gravação HDR do iPhone: HEVC 10 bits, BT.2020, HLG.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(sdr), "-vf",
                    "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv,"
                    "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt2020,"
                    "zscale=t=arib-std-b67:npl=203:m=bt2020nc:r=tv,format=yuv420p10le",
                    "-c:v", "libx265", "-x265-params", "log-level=error", "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-c:a", "copy", str(hlg)],
                   check=True)
    assert midia.transferencia_hdr(hlg) == "arib-std-b67"
    assert midia.transferencia_hdr(sdr) is None

    cfg_video = {**config.carregar()["video"], "hdr": "converter"}
    trecho = [plano.Trecho(0, 1, 1.0, quadro=(0, 0, 360, 640))]
    convertido, cru = tmp_path / "convertido.mp4", tmp_path / "cru.mp4"
    render.renderizar(hlg, trecho, None, convertido, cfg_video, 0.02, (360, 640), "arib-std-b67")
    render.renderizar(hlg, trecho, None, cru, cfg_video, 0.02, (360, 640))
    original = _saturacao_media(sdr)
    # Sem conversão a imagem perde mais da metade da cor; convertida, fica perto do original.
    assert _saturacao_media(cru) < 0.5 * original
    # (0,85: com o ffmpeg 7.1 do imageio-ffmpeg, usado no Mac Intel, a conversão fica em ~0,89.)
    assert _saturacao_media(convertido) > 0.85 * original


def test_dimensoes_respeitam_a_rotacao_do_iphone(tmp_path):
    deitado, girado = tmp_path / "deitado.mp4", tmp_path / "girado.mov"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=0.5",
                    "-c:v", "libx264", str(deitado)], check=True)
    # O iPhone grava o sensor deitado e guarda a rotação como metadado (display matrix).
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "-90", "-i", str(deitado),
                    "-c", "copy", str(girado)], check=True)
    assert midia.dimensoes(deitado) == (640, 360)
    assert midia.dimensoes(girado) == (360, 640)
    assert midia.duracao(girado) == pytest.approx(0.5, abs=0.05)


# Identidade de marca e configuração por computador

def test_config_do_computador_sobrepoe_o_padrao_e_sobrevive_a_novas_chaves():
    from edicao import config as c
    c.salvar_usuario("marca", {"autor": "um médico cirurgião", "cor_destaque": "#F2A541"})
    c.salvar_usuario("legendas", {"tamanho": 80})
    c.salvar_usuario("marca", {"nome": 'Clínica "Horizonte"'})
    cfg = c.carregar()
    assert cfg["marca"]["autor"] == "um médico cirurgião"
    assert cfg["marca"]["nome"] == 'Clínica "Horizonte"'
    assert cfg["marca"]["cor_destaque"] == "#F2A541"
    assert cfg["marca"]["cor_texto"] == "#FFFFFF"          # continua vindo do padrão
    assert cfg["legendas"]["tamanho"] == 80
    assert cfg["legendas"]["palavras_por_linha"] == 1


def test_legenda_usa_fonte_cores_e_estilo_da_marca():
    cfg = config.carregar()
    marca_ = {**cfg["marca"], "fonte": "Montserrat", "cor_texto": "#F5F5F5",
              "cor_contorno": "#0B3C5D", "negrito": False, "italico": True}
    ass = legendas.gerar_ass([Palavra("oi", 0, 1)], cfg["legendas"], marca_, 1080, 1920)
    estilo = next(l for l in ass.splitlines() if l.startswith("Style:")).split(",")
    assert estilo[1] == "Montserrat"
    assert estilo[3] == "&H00F5F5F5" and estilo[5] == "&H005D3C0B"
    assert estilo[7:9] == ["0", "-1"]                       # sem negrito, itálico


def test_prompt_usa_autor_e_contexto_da_marca():
    frases = decisao.dividir_em_frases([Palavra("oi.", 0, 1)])
    com = decisao.montar_prompt(frases, marca={"autor": "um médico cirurgião", "nome": "FOCO", "tom": ""})
    assert "gravado no celular por um médico cirurgião." in com
    assert "Marca: FOCO" in com and "Tom" not in com
    sem = decisao.montar_prompt(frases)
    assert "gravado no celular.\nAbaixo" in sem


def test_manual_de_marca_validado_e_aplicado():
    from edicao import marca as m
    proposta = m.validar_manual({
        "nome": "Clínica Horizonte", "publico": "", "tom": "acolhedor", "fontes": [],
        "cores": [{"hex": "#0b3c5d", "nome": "Azul", "uso": "primária"},
                  {"hex": "azul", "nome": "inválida", "uso": ""}],
        "legenda": {"fonte": "Montserrat", "cor_texto": "fff", "cor_palavra_atual": "#F2A541",
                    "cor_destaque": "verde", "cor_contorno": "#0B3C5D"},
        "observacoes": "",
    })
    assert [c["hex"] for c in proposta["cores"]] == ["#0B3C5D"]
    atual = {**config.carregar()["marca"], "publico": "pacientes", "arquivo_fonte": "/x/antiga.ttf"}
    novo = m.aplicar_manual(atual, proposta)
    assert novo["nome"] == "Clínica Horizonte" and novo["publico"] == "pacientes"
    assert novo["cor_texto"] == "#FFFFFF" and novo["cor_palavra_atual"] == "#F2A541"
    assert novo["cor_destaque"] == "#00E5FF"                # cor inválida não substitui
    assert novo["fonte"] == "Montserrat" and novo["arquivo_fonte"] == ""
    assert novo["cores"] == ["#0B3C5D"]


def test_ler_manual_chama_o_claude_com_o_arquivo(tmp_path, monkeypatch):
    from edicao import marca as m
    manual = tmp_path / "manual.pdf"
    manual.write_bytes(b"%PDF-1.4")
    chamadas = []

    def falso(prompt, esquema, cfg, anexos):
        chamadas.append((prompt, anexos))
        return {"nome": "X", "publico": "", "tom": "", "fontes": [], "cores": [],
                "legenda": {}, "observacoes": ""}
    monkeypatch.setattr(decisao, "claude_json", falso)
    assert m.ler_manual([manual], {})["nome"] == "X"
    assert "manual.pdf" in chamadas[0][0] and chamadas[0][1] == (manual,)
    with pytest.raises(ValueError):
        m.ler_manual([tmp_path / "manual.docx"], {})


FONTE_TESTE = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")


@pytest.mark.skipif(not FONTE_TESTE.exists(), reason="sem fonte de teste")
def test_perguntas_com_fonte_arrastada_e_cor_invalida():
    from edicao import marca as m
    respostas = iter([
        "FOCO Cirúrgico", "um médico cirurgião", "", "",
        str(FONTE_TESTE).replace(" ", "\\ "),             # caminho arrastado para o Terminal
        "", "amarelo", "#ffd400", "", "",                  # cor inválida é perguntada de novo
        "#0B3C5D, f2a541",
    ])
    novo = m.perguntar(config.carregar()["marca"], entrada=lambda _: next(respostas))
    assert novo["nome"] == "FOCO Cirúrgico" and novo["autor"] == "um médico cirurgião"
    assert novo["fonte"] == "DejaVu Serif" and novo["negrito"] and not novo["italico"]
    assert Path(novo["arquivo_fonte"]).parent == config.pasta_usuario() / "fontes"
    assert novo["cor_palavra_atual"] == "#FFD400"
    assert novo["cores"] == ["#0B3C5D", "#F2A541"]


def test_previa_da_legenda(tmp_path):
    from edicao import marca as m
    imagem = m.previa(config.carregar(), tmp_path / "previa.png")
    assert imagem.exists() and imagem.stat().st_size > 10_000
    assert not imagem.with_suffix(".ass").exists()


def test_correcao_vale_para_todas_as_ocorrencias_e_palavra_esticada_na_legenda():
    frases = decisao.dividir_em_frases(_palavras(("um", 0, 0.3), ("sisto", 0.3, 0.8), ("é", 0.8, 1.0),
                                                 ("sisto.", 1.0, 1.5)))
    palavras = decisao.aplicar_correcoes(frases, [{"frase": 1, "errado": "sisto", "certo": "cisto"}])
    assert [p.texto for p in palavras] == ["um", "cisto", "é", "cisto."]
    # A palavra esticada aparece na legenda só no fim dela, onde é dita.
    esticada = [Palavra("vão", 1.0, 4.0)]
    assert plano.remapear(esticada, [plano.Trecho(3.5, 4.2)])[0].inicio == pytest.approx(0.05)


def test_aparar_silencio_nas_bordas_dos_cortes():
    import numpy as np
    env = np.full(500, -75.0)                  # 5 s a 100 por segundo, fundo bem baixo
    env[100:200] = -20                         # fala de 1,0 a 2,0 s
    env[300:400] = -44                         # fala baixa (24 dB abaixo) de 3,0 a 4,0 s
    trechos = [plano.Trecho(0.4, 1.5), plano.Trecho(1.5, 2.6), plano.Trecho(2.7, 4.3)]
    primeira = Palavra("Vou", 0.45, 1.2)       # o Whisper marcou o início cedo demais
    plano.aparar_silencio(trechos, env, palavras=[primeira])
    assert primeira.inicio == pytest.approx(0.94)              # a legenda não a descarta
    assert trechos[0].inicio == pytest.approx(0.94)            # silêncio inicial tirado
    assert trechos[0].fim == 1.5 and trechos[1].inicio == 1.5  # emenda contígua intocada
    assert trechos[1].fim == pytest.approx(2.12)
    assert trechos[2].inicio == pytest.approx(2.94)            # fala baixa preservada
