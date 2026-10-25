"""Linha de comando.

  edicao processar VIDEO     edita um vídeo (cortes, legendas, destaques e zoom)
  edicao medir VIDEO         mede o tempo da transcrição local neste Mac
  edicao marca               configura a identidade de marca deste computador
"""

import argparse
import os
import platform
import time
from pathlib import Path

from . import config, decisao, legendas, marca, midia, plano, render, rosto, transcricao


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
    cfg["decisao"]["pausa_corte"] = c["silencio_minimo"]
    d = decisao.decidir(frases, cfg["decisao"], cfg["marca"])
    decisao.salvar(d, frases, saida.with_suffix(".decisao.json"))
    if frases:
        trechos = plano.aplicar_decisao(trechos, frases, d, c["folga"])
    cortadas = len(frases) - len(d.manter)
    print(f"    {cortadas} frases cortadas, {len(d.destaques)} destaques, {len(d.zoom)} zooms")
    print(f"    {total:.1f}s → {sum(t.duracao for t in trechos):.1f}s")

    e = cfg["enquadramento"]
    plano.planejar_movimento(trechos, e["duracao_zoom_rapido"], e["salto_nos_cortes"],
                             cfg["decisao"]["zoom_maximo"])
    W, H = midia.dimensoes(video)
    olhos = []
    if e["rastrear_rosto"]:
        print("    procurando os olhos para enquadrar o zoom…")
        olhos = rosto.detectar_olhos(video, W, H, e["amostras_por_segundo"])
        print(f"    olhos encontrados em {len(olhos)} quadros")
    v = cfg["video"]
    proporcao = v["largura"] / v["altura"]
    reduzidos = 0
    for t in trechos:
        q = rosto.enquadrar(olhos, t.inicio, t.fim, t.zoom, W, H, proporcao,
                            e["altura_olhos"], e["margem_olhos"])
        reduzidos += q.zoom < t.zoom
        t.zoom, t.quadro = q.zoom, (q.x, q.y, q.largura, q.altura)
        if t.tipo in ("suave", "rapido"):
            q0 = rosto.enquadrar(olhos, t.inicio, t.fim, 1.0, W, H, proporcao,
                                 e["altura_olhos"], e["margem_olhos"])
            t.quadro_inicial = (q0.x, q0.y, q0.largura, q0.altura)
    if reduzidos:
        print(f"    zoom reduzido em {reduzidos} trechos para manter os olhos no quadro")

    print("4/5 gerando legendas…")
    v = cfg["video"]
    ass = saida.with_suffix(".ass")
    ass.write_text(
        legendas.gerar_ass(plano.remapear(palavras, trechos), cfg["legendas"], cfg["marca"],
                           v["largura"], v["altura"], set(d.destaques)),
        encoding="utf-8",
    )

    hdr = midia.transferencia_hdr(video)
    if hdr and not midia.tem_filtro("zscale"):
        print("    aviso: vídeo HDR, mas este ffmpeg não tem o filtro zscale; as cores podem sair lavadas")
        hdr = None
    print("5/5 renderizando…" + (" (convertendo HDR para SDR)" if hdr else ""))
    arquivo_fonte = cfg["marca"].get("arquivo_fonte")
    pasta_fontes = Path(arquivo_fonte).parent if arquivo_fonte else None
    render.renderizar(video, trechos, ass, saida, v, c["fade_audio"], (W, H), hdr, pasta_fontes)
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


def _completar_path() -> None:
    """Garante ffmpeg e claude no PATH mesmo quando aberto pelo app de arrastar.

    No Mac Intel sem Homebrew, o instalador põe o ffmpeg (do imageio-ffmpeg) em `bin/` da pasta do
    programa, com um fonts.conf para o fontconfig embutido achar as fontes do Mac.
    """
    bin_programa = config.RAIZ / "bin"
    extras = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin")]
    atual = os.environ.get("PATH", "").split(os.pathsep)
    inicio = [str(bin_programa)] if (bin_programa / "ffmpeg").exists() else []
    os.environ["PATH"] = os.pathsep.join(inicio + atual + [p for p in extras if p not in atual])
    if inicio and (bin_programa / "fonts.conf").exists():
        os.environ.setdefault("FONTCONFIG_FILE", str(bin_programa / "fonts.conf"))


def main() -> None:
    _completar_path()
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

    mc = sub.add_parser("marca", help="configura a identidade de marca deste computador")
    mc.add_argument("--manual", type=Path, nargs="+", help="manual de marca em PDF ou imagens")
    mc.add_argument("--fonte", type=Path, help="arquivo .ttf/.otf da fonte da legenda")
    mc.add_argument("--sem-perguntas", action="store_true", help="não pergunta campo a campo")
    mc.add_argument("--mostrar", action="store_true", help="só mostra a configuração atual")

    args = ap.parse_args()
    cfg = config.carregar(args.config)
    if args.comando == "marca":
        if args.mostrar:
            marca.mostrar(cfg)
        else:
            marca.configurar(cfg, args.manual, args.fonte, not args.sem_perguntas)
        return
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
