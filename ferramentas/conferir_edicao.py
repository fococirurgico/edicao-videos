"""Confere uma edição pronta contra o original (para quem desenvolve; não faz parte do uso).

    .venv/bin/python ferramentas/conferir_edicao.py ORIGINAL EDITADO

Usa a transcrição e a decisão salvas ao lado do editado (EDITADO.transcricao.json, ou a do
`--transcricao-json` usado, e EDITADO.decisao.json) para refazer o plano de corte e mostra:
- durações do plano, do vídeo e do áudio (devem ser iguais, quadro a quadro);
- volume integrado (LUFS) e taxa do vídeo;
- o texto que ficou no vídeo e os cortes de mais de 0,3 s (procure tentativas erradas e
  repetições);
- o desvio do áudio em relação ao plano em vários pontos (é a referência da legenda: deve ficar
  perto de zero do começo ao fim; antes da correção de 28/10/2026 chegava a 0,4 s).
"""

import argparse
import subprocess
from pathlib import Path

import av
import numpy as np

from edicao import config, decisao, midia, plano, transcricao


def _audio(caminho: Path, inicio: float, duracao: float) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, inicio):.3f}", "-t", f"{duracao:.3f}",
                        "-i", str(caminho), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("original", type=Path)
    ap.add_argument("editado", type=Path)
    ap.add_argument("--transcricao-json", type=Path)
    ap.add_argument("--decisao-json", type=Path)
    args = ap.parse_args()

    cfg = config.carregar()
    c, e = cfg["cortes"], cfg["enquadramento"]
    transc = args.transcricao_json or args.editado.with_suffix(".transcricao.json")
    decis = args.decisao_json or args.editado.with_suffix(".decisao.json")

    # Mesmo plano do cli.processar (sem o enquadramento, que não muda os tempos).
    trechos = plano.trechos_mantidos(midia.duracao(args.original),
                                     midia.detectar_silencios(args.original, c["limiar_db"], c["silencio_minimo"]),
                                     c["folga"])
    palavras = transcricao.carregar(transc)
    frases = decisao.dividir_em_frases(palavras)
    d = decisao.carregar(decis)
    trechos = plano.aplicar_decisao(trechos, frases, d, c["folga"], c["silencio_minimo"])
    if d.correcoes:
        palavras = decisao.aplicar_correcoes(frases, d.correcoes)
    plano.aparar_silencio(trechos, midia.envelope_db(args.original), palavras=palavras)
    zm = cfg["decisao"]["zoom_maximo"]
    plano.saltar_nos_cortes(trechos, e["salto_nos_cortes"], zm)
    trechos = plano.aplicar_ritmo(trechos, palavras, e["plano_maximo"], e["variacao_ritmo"], zm)
    plano.planejar_movimento(trechos, e["duracao_zoom_rapido"], 0, zm)
    trechos = plano.alinhar_quadros(trechos, midia.fps(args.original))

    with av.open(str(args.editado)) as arq:
        v = next(s for s in arq.streams if s.type == "video")
        a = next(s for s in arq.streams if s.type == "audio")
        dur_v, dur_a = float(v.duration * v.time_base), float(a.duration * a.time_base)
        taxa = (v.bit_rate or 0) / 1e6
    print(f"duração: plano {sum(t.duracao for t in trechos):.3f} s | vídeo {dur_v:.3f} s | áudio {dur_a:.3f} s")
    print(f"volume: {midia.volume_integrado(args.editado)} LUFS | vídeo {taxa:.1f} Mbps")

    print("\ntexto que ficou:")
    print(" ".join(p.texto for p in plano.remapear(palavras, trechos)))
    print("\ncortes de mais de 0,3 s (no original):",
          [(round(x.fim, 2), round(y.inicio, 2)) for x, y in zip(trechos, trechos[1:]) if y.inicio - x.fim > 0.3])

    print("\náudio em relação ao plano (legenda):")
    pos = 0.0
    for i, t in enumerate(trechos):
        if i % 3 == 0 and t.duracao > 0.8:
            meio_saida, meio_orig = pos + t.duracao / 2, t.inicio + t.duracao / 2
            trecho = _audio(args.editado, meio_saida - 0.2, 0.4)
            janela = _audio(args.original, meio_orig - 0.7, 1.4)
            n = len(trecho)
            corr = [np.dot(trecho, janela[k:k + n]) / (np.linalg.norm(janela[k:k + n]) + 1e-9)
                    for k in range(0, len(janela) - n, 4)]
            desvio = (int(np.argmax(corr)) * 4 / 8000 - 0.5) * 1000
            print(f"  {meio_saida:6.1f} s: {desvio:+5.0f} ms")
        pos += t.duracao


if __name__ == "__main__":
    main()
