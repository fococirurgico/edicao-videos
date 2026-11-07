from edicao.transcricao import Palavra, revisar_tomadas, trechos_suspeitos


def _p(*itens):
    return [Palavra(t, i, f) for t, i, f in itens]


def test_sem_palavra_longa_nao_ha_trecho():
    palavras = _p(("a", 0, 0.4), ("b", 0.5, 1.2), ("c", 1.3, 2.0))
    assert trechos_suspeitos(palavras) == []


def test_faixa_em_volta_da_palavra_longa():
    # caso real do IMG_4521: "foi" com 2,94 s e "feito" com 1,94 s engoliam a tentativa
    palavras = _p(("2023.", 17.12, 17.84), ("Só", 22.58, 23.08), ("que", 23.08, 23.22),
                  ("artigo", 24.06, 24.5), ("que", 24.5, 25.12), ("foi", 25.12, 28.06),
                  ("feito", 28.06, 30.0), ("com", 30.0, 30.16), ("pacientes", 30.16, 30.62),
                  ("idosos", 30.62, 31.22), ("em", 31.22, 31.66))
    assert trechos_suspeitos(palavras) == [(1, 8)]


def test_faixas_distantes_ficam_separadas():
    palavras = _p(("a", 0, 2.0), ("b", 2.1, 2.5), *[(str(k), 3 + k, 3.5 + k) for k in range(10)],
                  ("z", 14, 16.0))
    assert trechos_suspeitos(palavras) == [(0, 1), (9, 12)]


def test_sem_modelo_de_revisao_nao_mexe(tmp_path):
    palavras = _p(("foi", 0, 3.0))
    cfg = {"modelo": "small", "modelo_revisao": "", "backend": "auto", "idioma": "pt"}
    assert revisar_tomadas(tmp_path / "x.mov", palavras, cfg) == (palavras, 0)


def test_revisao_troca_o_trecho_e_tira_reticencias_do_corte(monkeypatch, tmp_path):
    import edicao.transcricao as t
    palavras = _p(("antes.", 0, 0.5), ("artigo", 5.0, 5.4), ("foi", 5.4, 8.4), ("feito", 8.4, 8.8),
                  ("depois", 12.0, 12.5))
    monkeypatch.setattr(t.subprocess, "run", lambda *a, **k: None)
    # o trecho cortado começa em 4,7 s (0,3 s antes de "artigo")
    monkeypatch.setattr(t, "transcrever", lambda audio, cfg: _p(
        ("artigo", 0.3, 0.7), ("que...", 0.7, 1.5), ("artigo", 2.5, 2.9), ("que", 2.9, 3.0),
        ("foi", 3.0, 3.6), ("feito...", 3.7, 4.1)))
    cfg = {"modelo": "small", "modelo_revisao": "large-v3", "backend": "auto", "idioma": "pt"}
    novas, n = revisar_tomadas(tmp_path / "x.mov", palavras, cfg)
    assert n == 1
    assert [w.texto for w in novas] == ["antes.", "artigo", "que...", "artigo", "que", "foi", "feito",
                                        "depois"]
    assert novas[1].inicio == 5.0 and novas[-2].fim == 8.8
