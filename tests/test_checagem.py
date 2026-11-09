import subprocess

import numpy as np
import pytest

from edicao import checagem, config, plano
from edicao.cli import processar
from edicao.transcricao import Palavra, salvar


@pytest.fixture(autouse=True)
def pasta_usuario_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICAO_PASTA", str(tmp_path / "usuario"))


def _envelope(segundos: float, voz: list[tuple[float, float]]):
    env = np.full(int(segundos * 100), -75.0)
    for a, b in voz:
        env[int(a * 100):int(b * 100)] = -20
    return env


def test_tomada_refeita_sem_palavra_e_achada():
    # IMG_4539: a 2ª tentativa (3 s de voz) ficou sem nenhuma palavra; a 1ª tem as palavras.
    env = _envelope(10, [(1.0, 3.0), (4.0, 7.0)])
    palavras = [Palavra("primeira", 1.0, 2.0), Palavra("tentativa", 2.0, 3.0)]
    assert checagem.voz_sem_palavra(palavras, env) == [(4.0, 7.0)]


def test_voz_curta_ou_coberta_nao_e_suspeita():
    env = _envelope(10, [(1.0, 1.5), (4.0, 6.0)])
    palavras = [Palavra("coberta", 4.0, 6.0)]
    assert checagem.voz_sem_palavra(palavras, env) == []


def test_corte_no_meio_da_palavra_e_voz_depois_do_fim():
    env = _envelope(10, [(1.0, 2.4), (5.0, 6.0)])
    palavras = [Palavra("agora?", 1.5, 2.0), Palavra("hipertireoidismo", 5.0, 6.0)]
    trechos = [plano.Trecho(1.0, 2.05), plano.Trecho(5.4, 6.1)]
    achados = checagem.palavras_cortadas(trechos, palavras, env)
    assert (2.05, "agora?") in achados               # a voz continua depois do corte
    assert (5.4, "hipertireoidismo") in achados      # o corte cai dentro da palavra


def test_palavra_longa_para_o_tamanho():
    assert [p.texto for p in checagem.palavras_longas(
        [Palavra("foi", 0, 3.0), Palavra("hipertireoidismo", 3, 4.06)])] == ["foi"]


def test_ruido_retranscrito_vira_aviso_curto():
    assert checagem._limpar("P -p -p -p -p -p -p") == "(ruído, sem fala reconhecível)"
    assert checagem._limpar("E se a doença for agressiva") == "E se a doença for agressiva"


def test_relatorio_mostra_tempo_no_original_e_no_editado():
    texto = checagem.relatorio([checagem.Suspeita("voz sem palavra", 117.5, 120.8, None, "3.3 s")])
    assert "1:57.5 do original" in texto and "fora no editado" in texto


@pytest.fixture
def video(tmp_path):
    caminho = tmp_path / "bruto.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=4:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1.5",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
         "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(caminho)],
        check=True,
    )
    return caminho


def test_planejar_nao_renderiza_e_previa_sai_menor(video, tmp_path):
    transc = tmp_path / "t.json"
    salvar([Palavra("primeira", 0.1, 0.8), Palavra("segunda", 2.7, 3.5)], transc)
    cfg = config.carregar()
    cfg["decisao"]["backend"] = "nenhum"
    final = tmp_path / "editado.mp4"
    processar(video, final, cfg, transc, so_planejar=True)
    assert not final.exists()
    assert final.with_suffix(".decisao.json").exists() and final.with_suffix(".checagem.txt").exists()

    previa = tmp_path / "editado_previa.mp4"
    processar(video, previa, cfg, transc, previa=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(previa)], capture_output=True, text=True)
    assert r.stdout.strip() == "540,960"
    # Os arquivos de trabalho da prévia ficam com o nome do final, para ele reaproveitar.
    assert not (tmp_path / "editado_previa.decisao.json").exists()
