import subprocess

import numpy as np
import pytest

from edicao import checagem, config, midia, plano
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
    assert midia.dimensoes(previa) == (540, 960)
    # Os arquivos de trabalho da prévia ficam com o nome do final, para ele reaproveitar.
    assert not (tmp_path / "editado_previa.decisao.json").exists()


def test_correcao_que_alonga_palavra_nao_corta_o_comeco():
    # IMG_4557: "com de mais úsculo" → "com D maiúsculo" deixava "maiúsculo" com 1,01 s, e o editor
    # tratava como fala escondida (só os últimos 0,45 s entravam).
    from edicao import decisao
    palavras = [Palavra("com", 111.42, 111.82), Palavra("de", 111.82, 112.16),
                Palavra("mais", 112.16, 112.44), Palavra("úsculo", 112.44, 112.88)]
    f = decisao.Frase(1, "com de mais úsculo", palavras[0].inicio, palavras[-1].fim, palavras)
    novas = decisao.aplicar_correcoes([f], [{"frase": 1, "errado": "com de mais úsculo", "certo": "com D maiúsculo"}])
    assert [p.texto for p in novas] == ["com", "D", "maiúsculo"]
    assert checagem.palavras_longas(novas) == []
    # Palavra que já era longa na transcrição continua longa depois de corrigida.
    f2 = decisao.Frase(2, "foi", 0, 3.0, [Palavra("foi", 0, 3.0)])
    assert len(checagem.palavras_longas(decisao.aplicar_correcoes([f2], [{"frase": 2, "errado": "foi", "certo": "foi"}]))) == 1


def test_frase_volta_ate_a_voz_comecar():
    # IMG_4563 (12/11/2026): o Whisper pôs "neurocirurgiões" 0,48 s depois do começo da voz, e o
    # corte levava o "neuro". O trecho volta até a voz começar; a legenda acompanha.
    import numpy as np
    from edicao.plano import Trecho, aparar_silencio
    from edicao.transcricao import Palavra
    env = np.full(1000, -70.0)
    env[100:300] = -20      # frase anterior
    env[480:700] = -20      # voz real começa em 4,8 s
    trechos = [Trecho(1.0, 3.1, 1.0), Trecho(5.2, 7.0, 1.0)]
    pal = [Palavra("antes", 1.0, 3.0), Palavra("neurocirurgiões", 5.28, 5.8), Palavra("fim", 5.8, 6.9)]
    aparar_silencio(trechos, env, palavras=pal)
    assert 4.7 <= trechos[1].inicio <= 4.8
    assert pal[1].inicio <= 4.81
    assert trechos[0].fim <= 3.2          # a frase anterior não é afetada
