"""Material de apoio: encaixe pela resposta do Claude, desfoque, cartão e sobreposição no render."""

import subprocess
import sys

import cv2
import numpy as np
import pytest

from edicao import apoio, config, decisao, midia, plano, render
from edicao.transcricao import Palavra


@pytest.fixture(autouse=True)
def pasta_usuario_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICAO_PASTA", str(tmp_path / "usuario"))


def _frases():
    return decisao.dividir_em_frases([
        Palavra("Recebi", 0.0, 0.3), Palavra("essa", 0.3, 0.5), Palavra("pergunta.", 0.5, 0.9),
        Palavra("Um", 2.0, 2.2), Palavra("estudo", 2.2, 2.6), Palavra("americano", 2.6, 3.1),
        Palavra("mostrou", 3.1, 3.5), Palavra("isso.", 3.5, 3.9),
    ])


def test_validar_aceita_gancho_e_ancora_e_completa_o_que_faltou():
    frases = _frases()
    bruto = {"imagens": [
        {"arquivo": "a.png", "gancho": True, "frase": 0, "ancora": "", "ocultar": ["@fulana"]},
        {"arquivo": "b.png", "gancho": True, "frase": 2, "ancora": "estudo americano", "ocultar": []},
        {"arquivo": "x.png", "gancho": False, "frase": 1, "ancora": "", "ocultar": []},   # não enviado
    ]}
    pedidos = apoio.validar(bruto, frases, [1, 2], ["a.png", "b.png", "c.png"])
    assert [p.arquivo for p in pedidos] == ["a.png", "b.png", "c.png"]
    assert pedidos[0].gancho and pedidos[0].ocultar == ["@fulana"]
    assert not pedidos[1].gancho                      # só um gancho
    assert (pedidos[1].frase, pedidos[1].ancora) == (2, "estudo americano")
    assert (pedidos[2].frase, pedidos[2].ancora) == (2, "")    # sem resposta: última frase


def test_programar_gancho_abre_e_os_outros_nao_se_sobrepoem():
    cfg = config.carregar()["graficos"]
    tempos = apoio.programar([(False, 2.0, 2.5), (True, 0, 0), (False, 2.5, 3.0)], cfg, 20.0)
    assert tempos[1] == (0.0, cfg["duracao_gancho"])
    ini0, fim0 = tempos[0]
    assert ini0 >= cfg["duracao_gancho"]               # espera o gancho sair
    assert tempos[2][0] > fim0
    assert apoio.programar([(False, 19.5, 19.8)], cfg, 20.0) == [None]
    depois_da_pergunta = apoio.programar([(True, 0, 0)], cfg, 20.0, inicio_livre=4.5)
    assert depois_da_pergunta[0][0] == 4.5


def test_cartao_tem_cantos_transparentes_e_sombra():
    img = np.full((300, 600, 3), 200, np.uint8)
    cartao = apoio.montar_cartao(img, 500, 500)
    assert cartao.shape[2] == 4
    sombra = 28
    assert cartao[0, 0, 3] == 0                                      # canto de fora
    assert cartao[sombra + 1, sombra + 1, 3] < 255                   # canto arredondado
    meio = cartao[cartao.shape[0] // 2, cartao.shape[1] // 2]
    assert meio[3] == 255 and abs(int(meio[0]) - 200) <= 2


def test_cartao_sempre_com_dimensoes_pares():
    # 985x515 (o artigo do IMG_4521) fez o zscale do HDR recusar a imagem.
    for w, h in ((1179, 615), (1179, 278), (601, 301)):
        c = apoio.montar_cartao(np.full((h, w, 3), 128, np.uint8), 929, 806)
        assert c.shape[0] % 2 == 0 and c.shape[1] % 2 == 0


def test_desfoque_redondo_preserva_os_cantos_da_caixa():
    img = np.zeros((100, 100, 3), np.uint8)
    img[::2, :] = 255                                                # listras: muda ao desfocar
    saida = apoio.desfocar(img, [(0, 0, 100, 100, True)])
    assert (saida[0:5, 0:5] == img[0:5, 0:5]).all()                  # fora do círculo
    assert saida[50, 50].std() == 0 and 30 < int(saida[50, 50, 0]) < 225


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision só no macOS")
def test_desfoca_nome_de_usuario_pelo_ocr(tmp_path):
    pytest.importorskip("Vision")
    img = np.full((160, 900, 3), 255, np.uint8)
    cv2.putText(img, "fulana2023  3 h", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    cv2.putText(img, "Meu resultado saiu", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    regioes = apoio.regioes_a_desfocar(img, ["@fulana2023"])
    assert len(regioes) == 1
    x0, y0, x1, y1, redonda = regioes[0]
    assert not redonda and y1 < 95 and x0 < 60 and 200 < x1 < 450    # só o nome, não a 2ª linha


def _cinza(tmp_path):
    cinza = tmp_path / "cinza.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=2:r=30",
                    "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(cinza)],
                   check=True)
    return cinza


def _quadro(saida, t, w=180, h=320, fmt="yuv420p10le"):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(saida), "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", fmt, "-"], capture_output=True, check=True)
    if fmt == "yuv420p10le":
        return np.frombuffer(r.stdout[:w * h * 2], np.uint16).reshape(h, w)
    return np.frombuffer(r.stdout[:w * h], np.uint8).reshape(h, w)


@pytest.mark.parametrize("hdr", [False, True])
def test_imagem_de_apoio_aparece_so_no_tempo_dela(tmp_path, hdr):
    if hdr and not midia.tem_filtro("zscale"):
        pytest.skip("ffmpeg sem zscale")
    video = _cinza(tmp_path)
    if hdr:
        from test_reels import _hlg
        video = _hlg(tmp_path, video)
    png = tmp_path / "branco.png"
    cv2.imwrite(str(png), apoio.montar_cartao(np.full((61, 101, 3), 255, np.uint8), 101, 61, sombra=0))
    saida = tmp_path / "saida.mp4"
    render.renderizar(video, [plano.Trecho(0, 2, 1.0, quadro=(0, 0, 360, 640))], None, saida,
                      {**config.carregar()["video"], "largura": 180, "altura": 320}, 0.02, (360, 640),
                      "arib-std-b67" if hdr else None,
                      apoios=[apoio.Cartao(png, 0.5, 1.5, 40, 100)], nits_apoio=400)
    fmt = "yuv420p10le" if hdr else "gray"
    antes, durante, depois = (_quadro(saida, t, fmt=fmt) for t in (0.2, 1.1, 1.8))
    branco = 815 if hdr else 250       # SDR lido como "gray" (faixa cheia)
    assert abs(int(np.median(durante[110:150, 50:130])) - branco) < 15   # já subiu até y = 100
    assert int(np.median(antes[110:150, 50:130])) < branco - 100
    assert int(np.median(depois[110:150, 50:130])) < branco - 100
