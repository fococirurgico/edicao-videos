"""Linha de comando.

  edicao processar VIDEO     edita um vídeo (cortes, legendas, destaques e zoom)
  edicao medir VIDEO         mede o tempo da transcrição local neste Mac
"""

import argparse
import platform
import time
from pathlib import Path

from . import config, decisao, legendas, midia, plano, render, rosto, transcricao


def processar(video: Path, saida: Path, cfg: dict, transcricao_json: Path | None) -> None:
    c = cfg["cortes"]
    total = midia.duracao(video)

    print("1/5 detectando silêncios…")
    silencios = midia.detectar_silencios(video, c["limiar_db"], c["silencio_minimo"])
    trechos = plano.trechos_mantidos(total, silencios, c["folga"])
    print(f"    {len(silencios)} silêncios")

    if transcricao_json:
        print("2/5 usando transcrição salva…")
        palavras = transcricao.carregar(transcricao_json)
    else:
        backend = transcricao.escolher_backend(cfg["transcricao"]["backend"])
        print(f"2/5 transcrevendo localmente ({backend}, modelo {cfg['transcricao']['modelo']})…")
        palavras = transcricao.transcrever(video, cfg["transcricao"])
        transcricao.salvar(palavras, saida.with_suffix(".transcricao.json"))
    print(f"    {len(palavras)} palavras")

    frases = decisao.dividir_em_frases(palavras)
    print(f"3/5 decidindo a edição ({cfg['decisao']['backend']}, {len(frases)} frases)…")
    d = decisao.decidir(frases, cfg["decisao"])
    decisao.salvar(d, frases, saida.with_suffix(".decisao.json"))
    if frases:
        trechos = plano.aplicar_decisao(trechos, frases, d, c["folga"])
    cortadas = len(frases) - len(d.manter)
    print(f"    {cortadas} frases cortadas, {len(d.destaques)} destaques, {len(d.zoom)} zooms")
    print(f"    {total:.1f}s → {sum(t.duracao for t in trechos):.1f}s")

    e = cfg["enquadramento"]
    if e["rastrear_rosto"]:
        print("    procurando os olhos para enquadrar o zoom…")
        W, H = midia.dimensoes(video)
        olhos = rosto.detectar_olhos(video, W, H, e["amostras_por_segundo"])
        v = cfg["video"]
        reduzidos = 0
        for t in trechos:
            q = rosto.enquadrar(olhos, t.inicio, t.fim, t.zoom, W, H, v["largura"] / v["altura"],
                                e["altura_olhos"], e["margem_olhos"])
            reduzidos += q.zoom < t.zoom
            t.zoom, t.quadro = q.zoom, (q.x, q.y, q.largura, q.altura)
        print(f"    olhos encontrados em {len(olhos)} quadros"
              + (f"; zoom reduzido em {reduzidos} trechos para manter os olhos no quadro" if reduzidos else ""))

    print("4/5 gerando legendas…")
    v = cfg["video"]
    ass = saida.with_suffix(".ass")
    ass.write_text(
        legendas.gerar_ass(plano.remapear(palavras, trechos), cfg["legendas"],
                           v["largura"], v["altura"], set(d.destaques)),
        encoding="utf-8",
    )

    print("5/5 renderizando…")
    render.renderizar(video, trechos, ass, saida, v, c["fade_audio"])
    print(f"pronto: {saida}")


def medir(video: Path, cfg: dict) -> None:
    backend = transcricao.escolher_backend(cfg["transcricao"]["backend"])
    total = midia.duracao(video)
    print(f"Mac: {platform.machine()} | backend: {backend} | modelo: {cfg['transcricao']['modelo']}")
    t0 = time.perf_counter()
    palavras = transcricao.transcrever(video, cfg["transcricao"])
    gasto = time.perf_counter() - t0
    print(f"vídeo de {total:.1f}s transcrito em {gasto:.1f}s "
          f"({gasto / total:.2f}x a duração) — {len(palavras)} palavras")
    print("(a primeira execução inclui o download do modelo; rode de novo para medir)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="edicao")
    ap.add_argument("--config", type=Path, help="arquivo de configuração (padrão: config.toml)")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("processar", help="edita um vídeo")
    p.add_argument("video", type=Path)
    p.add_argument("-o", "--saida", type=Path)
    p.add_argument("--modelo", help="sobrepõe o modelo de transcrição da configuração")
    p.add_argument("--transcricao-json", type=Path, help="usa uma transcrição já salva")
    p.add_argument("--sem-claude", action="store_true", help="pula a decisão do Claude (só corta silêncios)")

    m = sub.add_parser("medir", help="mede a velocidade da transcrição neste Mac")
    m.add_argument("video", type=Path)
    m.add_argument("--modelo")

    args = ap.parse_args()
    cfg = config.carregar(args.config)
    if args.modelo:
        cfg["transcricao"]["modelo"] = args.modelo

    if args.comando == "processar":
        if args.sem_claude:
            cfg["decisao"]["backend"] = "nenhum"
        saida = args.saida or args.video.with_name(args.video.stem + "_editado.mp4")
        processar(args.video, saida, cfg, args.transcricao_json)
    else:
        medir(args.video, cfg)


if __name__ == "__main__":
    main()
