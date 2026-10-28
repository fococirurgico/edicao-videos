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

from . import config, decisao, fotos, graficos, legendas, marca, midia, plano, render, rosto, transcricao


def processar(video: Path, saida: Path, cfg: dict, transcricao_json: Path | None,
              titulo: str | None = None, pergunta: str = "", decisao_json: Path | None = None) -> None:
    """titulo: sobrepõe o título sugerido pelo Claude ("" = sem título).
    pergunta: abre com a caixinha de pergunta do Instagram no lugar do título.
    decisao_json: reaproveita a decisão salva de uma edição anterior (mesma transcrição)."""
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
    if decisao_json:
        print("3/5 usando decisão salva…")
        d = decisao.carregar(decisao_json)
    else:
        print(f"3/5 decidindo a edição ({cfg['decisao']['backend']}, {len(frases)} frases)…")
        cfg["decisao"]["pausa_corte"] = c["silencio_minimo"]
        d = decisao.decidir(frases, cfg["decisao"], cfg["marca"])
    decisao.salvar(d, frases, saida.with_suffix(".decisao.json"))
    if frases and cfg["decisao"]["backend"] != "nenhum":     # --sem-claude: só corta silêncios
        trechos = plano.aplicar_decisao(trechos, frases, d, c["folga"], c["silencio_minimo"])
    if d.correcoes:
        palavras = decisao.aplicar_correcoes(frases, d.correcoes)
    plano.aparar_silencio(trechos, midia.envelope_db(video), palavras=palavras)
    cortadas = len(frases) - len(d.manter)
    print(f"    {cortadas} frases cortadas, {len(d.destaques)} destaques, {len(d.zoom)} zooms, "
          f"{len(d.elementos)} elementos, {len(d.correcoes)} correções")
    if d.titulo:
        print(f"    título sugerido: {d.titulo}")
    print(f"    {total:.1f}s → {sum(t.duracao for t in trechos):.1f}s")

    e = cfg["enquadramento"]
    zoom_maximo = cfg["decisao"]["zoom_maximo"]
    plano.saltar_nos_cortes(trechos, e["salto_nos_cortes"], zoom_maximo)
    trechos = plano.aplicar_ritmo(trechos, palavras, e["plano_maximo"], e["variacao_ritmo"], zoom_maximo)
    plano.planejar_movimento(trechos, e["duracao_zoom_rapido"], 0, zoom_maximo)
    fps = midia.fps(video)
    trechos = plano.alinhar_quadros(trechos, fps)
    W, H = midia.dimensoes(video)
    olhos = []
    if e["rastrear_rosto"]:
        print("    procurando os olhos para enquadrar o zoom…")
        olhos = rosto.detectar_olhos(video, W, H, e["amostras_por_segundo"])
        print(f"    olhos encontrados em {len(olhos)} quadros")
    v = cfg["video"]
    proporcao = v["largura"] / v["altura"]
    reduzidos = 0
    anterior = None
    for t in trechos:
        q = rosto.enquadrar(olhos, t.inicio, t.fim, t.zoom, W, H, proporcao,
                            e["altura_olhos"], e["margem_olhos"])
        reduzidos += q.zoom < t.zoom
        t.zoom, t.quadro = q.zoom, (q.x, q.y, q.largura, q.altura)
        if t.tipo in ("suave", "rapido"):
            if anterior and t.inicio - anterior.fim <= 0.05 and t.anim_decorrido == 0:
                # Sem corte na fala: a animação parte exatamente de onde o trecho anterior parou.
                t.quadro_inicial = anterior.quadro
            else:
                q0 = rosto.enquadrar(olhos, t.inicio, t.fim, t.zoom_inicial, W, H, proporcao,
                                     e["altura_olhos"], e["margem_olhos"])
                t.quadro_inicial = (q0.x, q0.y, q0.largura, q0.altura)
            if t.quadro_inicial == t.quadro:
                t.quadro_inicial = None          # nada a animar
        anterior = t
    if reduzidos:
        print(f"    zoom reduzido em {reduzidos} trechos para manter os olhos no quadro")

    print("4/5 gerando legendas e elementos gráficos…")
    duracao_final = sum(t.duracao for t in trechos)
    por_id = {f.id: f for f in frases}
    pedidos = []
    for el in d.elementos:
        tempos = [x for x in (plano.remapear_tempo(por_id[el["frase"]].inicio, trechos),
                              plano.remapear_tempo(por_id[el["frase"]].fim, trechos)) if x is not None]
        if tempos:
            pedidos.append((el["tipo"], graficos.limpar(el["texto"]), graficos.limpar(el["detalhe"]),
                            min(tempos), max(tempos)))
    g = cfg["graficos"]
    titulo = graficos.limpar(d.titulo if titulo is None else titulo)
    programados = graficos.programar(titulo, pedidos, g, duracao_final, graficos.limpar(pergunta))
    if programados:
        print("    " + ", ".join(f"{el.tipo} {el.inicio:.1f}s" for el in programados))
    v = cfg["video"]
    ass = saida.with_suffix(".ass")
    ass.write_text(
        legendas.gerar_ass(plano.remapear(palavras, trechos), cfg["legendas"], cfg["marca"],
                           v["largura"], v["altura"], set(d.destaques),
                           graficos.gerar(programados, g, cfg["marca"], v["largura"], v["altura"], fps),
                           [graficos.estilo(cfg["marca"])]),
        encoding="utf-8",
    )

    hdr = midia.transferencia_hdr(video)
    if hdr and not midia.tem_filtro("zscale"):
        print("    aviso: vídeo HDR, mas este ffmpeg não tem o filtro zscale; as cores podem sair lavadas")
        hdr = None
    manter = hdr and v.get("hdr", "manter") == "manter"
    print("5/5 renderizando…" + ((" (HDR mantido)" if manter else " (convertendo HDR para SDR)") if hdr else ""))
    animados = sum(1 for t in trechos if t.quadro_inicial)
    if animados:
        print(f"    {animados} trechos com zoom animado")
    arquivo_fonte = cfg["marca"].get("arquivo_fonte")
    pasta_fontes = Path(arquivo_fonte).parent if arquivo_fonte else None
    ganho, filtro_audio = 0.0, ""
    a = cfg.get("audio", {})
    alvo = a.get("volume_alvo")
    if a.get("tratamento", "voz") == "voz":
        filtro_audio = render.tratamento_voz(alvo if alvo is not None else -14)
        print(f"    tratamento de voz, volume {alvo if alvo is not None else -14} LUFS")
    elif alvo is not None:
        atual = midia.volume_integrado(video)
        if atual is not None and atual > -70:
            ganho = max(-10.0, min(20.0, alvo - atual))
            print(f"    volume {atual:.1f} LUFS → {alvo} LUFS ({ganho:+.1f} dB)")
    render.renderizar(video, trechos, ass, saida, v, c["fade_audio"], (W, H), hdr, pasta_fontes, fps, ganho,
                      filtro_audio)
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
    p.add_argument("--decisao-json", type=Path, help="reaproveita a decisão salva de uma edição anterior")
    p.add_argument("--album", help="põe o editado neste álbum do Fotos (padrão: [saida] album da configuração)")
    p.add_argument("--titulo", help="título do Reels no início (no lugar do sugerido pelo Claude)")
    p.add_argument("--sem-titulo", action="store_true", help="sem título no início")
    p.add_argument("--pergunta", default="", help="abre com a caixinha de pergunta do Instagram (no lugar do título)")
    p.add_argument("--sem-graficos", action="store_true", help="sem elementos gráficos durante a fala")

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
        if args.sem_graficos:
            cfg["graficos"]["elementos"] = False
        saida = args.saida or args.video.with_name(args.video.stem + "_editado.mp4")
        processar(args.video, saida, cfg, args.transcricao_json, "" if args.sem_titulo else args.titulo, args.pergunta, args.decisao_json)
        album = args.album if args.album is not None else cfg.get("saida", {}).get("album", "")
        if album:
            print(f"pondo no álbum \"{album}\" do Fotos…")
            fotos.importar(saida, album)
    else:
        medir(args.video, cfg)


if __name__ == "__main__":
    main()
