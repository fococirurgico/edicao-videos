import subprocess
from pathlib import Path

import pytest

from edicao import config, decisao, legendas, midia, plano
from edicao.cli import processar
from edicao.transcricao import Palavra, salvar


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


def test_legenda_destaca_palavra_atual_e_destaques():
    cfg = config.carregar()["legendas"]
    ass = legendas.gerar_ass(
        [Palavra("olha", 0, 0.4), Palavra("resultado", 0.4, 1.0)], cfg, 1080, 1920,
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
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(saida)], capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert dims == "1080,1920"


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
    assert d.zoom == {2: 1.2}               # nível limitado; zoom em frase cortada ignorado
    # Resposta vazia nunca apaga o vídeo inteiro.
    assert decisao.validar({"manter": []}, frases).manter == [1, 2]


def test_aplicar_decisao_corta_retake_e_mantem_audio_nao_transcrito():
    # Frase 1 é um retake (cortada), frase 2 é a versão boa; 4.0–5.0 tem áudio sem transcrição.
    frases = decisao.dividir_em_frases(_palavras(
        ("versão", 0.0, 0.5), ("ruim.", 0.5, 1.0), ("versão", 1.4, 1.9), ("boa.", 1.9, 2.4),
    ))
    d = decisao.Decisao(manter=[2], destaques=[], zoom={2: 1.1})
    trechos = plano.aplicar_decisao([plano.Trecho(0.0, 5.0)], frases, d, folga=0.08)
    assert trechos[0].inicio == pytest.approx(1.32)    # retake removido, folga antes da frase boa
    assert trechos[-1].fim == 5.0                      # áudio não transcrito preservado
    assert all(t.zoom == 1.1 for t in trechos)


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
