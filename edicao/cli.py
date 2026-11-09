"""Linha de comando.

  edicao planejar VIDEO      decide a edição e confere os cortes, sem renderizar
  edicao processar VIDEO     edita um vídeo (cortes, legendas, destaques e zoom)
  edicao processar --previa  prévia rápida (menor, sem zoom animado) para aprovar antes do final
  edicao medir VIDEO         mede o tempo da transcrição local neste Mac
  edicao marca               configura a identidade de marca deste computador
"""

import argparse
import os
import platform
import time
from pathlib import Path

from . import apoio, checagem, config, decisao, fotos, graficos, legendas, marca, midia, plano, render, rosto, transcricao


def processar(video: Path, saida: Path, cfg: dict, transcricao_json: Path | None,
              titulo: str | None = None, pergunta: str = "", decisao_json: Path | None = None,
              imagens: list[Path] | None = None, apoio_json: Path | None = None,
              so_planejar: bool = False, previa: bool = False) -> None:
    """titulo: sobrepõe o título sugerido pelo Claude ("" = sem título).
    pergunta: abre com a caixinha de pergunta do Instagram no lugar do título.
    decisao_json: reaproveita a decisão salva de uma edição anterior (mesma transcrição).
    imagens: material de apoio (prints, artigos), encaixado pelo Claude; apoio_json reaproveita
    o encaixe salvo de uma edição anterior.
    so_planejar: para depois da decisão e da checagem (nada é renderizado).
    previa: render rápido para conferir (ver render.renderizar); os arquivos de trabalho (decisão,
    encaixe, legenda) ficam com o nome do vídeo final, para o final reaproveitá-los."""
    c = cfg["cortes"]
    base = saida.with_name(saida.stem.removesuffix("_previa") + saida.suffix)
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
        palavras, revistos = transcricao.revisar_tomadas(video, palavras, cfg["transcricao"])
        if revistos:
            print(f"    {revistos} trecho(s) com palavra longa retranscrito(s) com "
                  f"{cfg['transcricao']['modelo_revisao']} (possível tomada escondida)")
        transcricao.salvar(palavras, base.with_suffix(".transcricao.json"))
    print(f"    {len(palavras)} palavras")

    frases = decisao.dividir_em_frases(palavras)
    if decisao_json:
        print("3/5 usando decisão salva…")
        d = decisao.carregar(decisao_json)
    else:
        print(f"3/5 decidindo a edição ({cfg['decisao']['backend']}, {len(frases)} frases)…")
        cfg["decisao"]["pausa_corte"] = c["silencio_minimo"]
        d = decisao.decidir(frases, cfg["decisao"], cfg["marca"])
    decisao.salvar(d, frases, base.with_suffix(".decisao.json"))
    if frases and cfg["decisao"]["backend"] != "nenhum":     # --sem-claude: só corta silêncios
        trechos = plano.aplicar_decisao(trechos, frases, d, c["folga"], c["silencio_minimo"])
    if d.correcoes:
        palavras = decisao.aplicar_correcoes(frases, d.correcoes)
    envelope = midia.envelope_db(video)
    plano.aparar_silencio(trechos, envelope, palavras=palavras)
    cortadas = len(frases) - len(d.manter)
    print(f"    {cortadas} frases cortadas, {len(d.destaques)} destaques, {len(d.zoom)} zooms, "
          f"{len(d.elementos)} elementos, {len(d.correcoes)} correções")
    if d.titulo:
        print(f"    título sugerido: {d.titulo}")
    print(f"    {total:.1f}s → {sum(t.duracao for t in trechos):.1f}s")
    suspeitas = checagem.checar(video, trechos, palavras, envelope, cfg["transcricao"])
    texto = checagem.relatorio(suspeitas)
    print(texto)
    base.with_suffix(".checagem.txt").write_text(texto + "\n", encoding="utf-8")

    encaixe = []
    if imagens:
        if apoio_json:
            print("    usando o encaixe salvo do material de apoio…")
            encaixe = apoio.carregar(apoio_json)
        else:
            print(f"    encaixando {len(imagens)} imagens de apoio (Claude)…")
            encaixe = apoio.decidir(frases, d.manter, imagens, cfg["decisao"], cfg["marca"])
        apoio.salvar(encaixe, base.with_suffix(".apoio.json"))
    if so_planejar:
        print(_resumo_plano(frases, d, trechos, encaixe))
        print(f"plano salvo: {base.with_suffix('.decisao.json')}")
        return

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
        olhos = _olhos(video, W, H, e["amostras_por_segundo"])
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
    saem = decisao.palavras_cortadas(frases, d.cortes_parciais)
    for el in d.elementos:
        # O cartão entra quando o assunto é dito (âncora), não no começo da frase.
        ini, fim = decisao.tempo_da_ancora(por_id[el["frase"]], el.get("ancora", ""), saem)
        tempos = [x for x in (plano.remapear_tempo(ini, trechos), plano.remapear_tempo(fim, trechos))
                  if x is not None]
        if tempos:
            pedidos.append((el["tipo"], graficos.limpar(el["texto"]), graficos.limpar(el["detalhe"]),
                            min(tempos), max(tempos)))
    g = cfg["graficos"]
    v = cfg["video"]
    cartoes = []
    if imagens:
        janelas = []
        for p in encaixe:
            if p.gancho or p.frase not in por_id:
                janelas.append((p.gancho, duracao_final, duracao_final))
                continue
            ini, fim = decisao.tempo_da_ancora(por_id[p.frase], p.ancora, saem)
            tempos = [x for x in (plano.remapear_tempo(ini, trechos), plano.remapear_tempo(fim, trechos))
                      if x is not None]
            janelas.append((False, min(tempos), max(tempos)) if tempos else (False, duracao_final, duracao_final))
        livre = min(g.get("duracao_pergunta", 4.5), duracao_final) + 0.3 if pergunta else 0.0
        por_nome = {i.name: i for i in imagens}
        for k, (p, tempos) in enumerate(zip(encaixe, apoio.programar(janelas, g, duracao_final, livre))):
            if not tempos:
                print(f"    aviso: {p.arquivo} não coube no vídeo")
                continue
            png, desfocadas, w, _ = apoio.preparar(por_nome[p.arquivo], p.ocultar, base.with_suffix(f".apoio{k}.png"),
                                                   v["largura"], v["altura"], g)
            cartoes.append(apoio.Cartao(png, tempos[0], tempos[1], (v["largura"] - w) // 2, g.get("altura_apoio", 170)))
            print(f"    {p.arquivo}: {'gancho' if p.gancho else 'apoio'} {tempos[0]:.1f}s–{tempos[1]:.1f}s, "
                  f"{desfocadas} trechos desfocados")
            if p.gancho:
                titulo = ""                              # o print do gancho faz o papel do título
    titulo = graficos.limpar(d.titulo if titulo is None else titulo)
    programados = graficos.programar(titulo, pedidos, g, duracao_final, graficos.limpar(pergunta))
    # Cartão gráfico não divide a tela com uma imagem de apoio.
    programados = [el for el in programados if el.tipo in ("titulo", "pergunta") or not any(
        el.inicio < c.fim + 0.5 and c.inicio - 0.5 < el.fim for c in cartoes)]
    if programados:
        print("    " + ", ".join(f"{el.tipo} {el.inicio:.1f}s" for el in programados))
    # A caixinha de pergunta vai num arquivo à parte, renderizado com o branco mais claro no HDR.
    claros = [el for el in programados if el.tipo == "pergunta"]
    ass = saida.with_suffix(".ass")
    ass.write_text(
        legendas.gerar_ass(plano.remapear(palavras, trechos), cfg["legendas"], cfg["marca"],
                           v["largura"], v["altura"], set(d.destaques),
                           graficos.gerar([el for el in programados if el not in claros], g, cfg["marca"],
                                          v["largura"], v["altura"], fps),
                           [graficos.estilo(cfg["marca"])]),
        encoding="utf-8",
    )
    ass_claro = None
    if claros:
        ass_claro = saida.with_suffix(".pergunta.ass")
        ass_claro.write_text(
            legendas.gerar_ass([], cfg["legendas"], cfg["marca"], v["largura"], v["altura"], set(),
                               graficos.gerar(claros, g, cfg["marca"], v["largura"], v["altura"], fps),
                               [graficos.estilo(cfg["marca"])]),
            encoding="utf-8",
        )

    hdr = midia.transferencia_hdr(video)
    if hdr and not midia.tem_filtro("zscale"):
        print("    aviso: vídeo HDR, mas este ffmpeg não tem o filtro zscale; as cores podem sair lavadas")
        hdr = None
    manter = hdr and v.get("hdr", "manter") == "manter"
    if previa:
        print("5/5 renderizando a prévia… (540x960, zoom sem animação, áudio sem tratamento)")
    else:
        print("5/5 renderizando…" + ((" (HDR mantido)" if manter else " (convertendo HDR para SDR)") if hdr else ""))
    animados = sum(1 for t in trechos if t.quadro_inicial)
    if animados and not previa:
        print(f"    {animados} trechos com zoom animado")
    arquivo_fonte = cfg["marca"].get("arquivo_fonte")
    pasta_fontes = Path(arquivo_fonte).parent if arquivo_fonte else None
    ganho, filtro_audio = 0.0, ""
    a = cfg.get("audio", {})
    alvo = a.get("volume_alvo")
    if previa:
        pass                                     # a prévia é para conferir cortes, não o som
    elif a.get("tratamento", "voz") == "voz":
        filtro_audio = render.tratamento_voz(alvo if alvo is not None else -14)
        print(f"    tratamento de voz, volume {alvo if alvo is not None else -14} LUFS")
    elif alvo is not None:
        atual = midia.volume_integrado(video)
        if atual is not None and atual > -70:
            ganho = max(-10.0, min(20.0, alvo - atual))
            print(f"    volume {atual:.1f} LUFS → {alvo} LUFS ({ganho:+.1f} dB)")
    render.renderizar(video, trechos, ass, saida, v, c["fade_audio"], (W, H), hdr, pasta_fontes, fps, ganho,
                      filtro_audio, ass_claro, g.get("nits_pergunta", 600), g.get("nits_graficos", 400),
                      cartoes, g.get("nits_apoio", 400), previa=previa)
    print(f"pronto: {saida}")


def _olhos(video: Path, W: int, H: int, amostras: float) -> list:
    """Detecção dos olhos, guardada ao lado do vídeo: a prévia e o final usam a mesma."""
    import json

    cache = video.with_name(video.stem + ".olhos.json")
    chave = {"tamanho": video.stat().st_size, "W": W, "H": H, "amostras": amostras}
    if cache.exists():
        try:
            dados = json.loads(cache.read_text())
            if dados.get("chave") == chave:
                print("    usando os olhos já detectados")
                return [rosto.Olhos(o["t"], tuple(o["direito"]), tuple(o["esquerdo"])) for o in dados["olhos"]]
        except (ValueError, KeyError):
            pass
    olhos = rosto.detectar_olhos(video, W, H, amostras)
    try:
        cache.write_text(json.dumps({"chave": chave, "olhos": [
            {"t": float(o.t), "direito": [float(x) for x in o.direito], "esquerdo": [float(x) for x in o.esquerdo]}
            for o in olhos]}))
    except OSError:
        pass
    return olhos


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _resumo_plano(frases, d, trechos, encaixe) -> str:
    """Frases que ficam (✔, com o tempo no vídeo editado) e as que saem (✘)."""
    linhas = ["", "plano da edição:"]
    saem = decisao.palavras_cortadas(frases, d.cortes_parciais)
    for f in frases:
        if f.id in d.manter:
            ficam = [p for k, p in enumerate(f.palavras) if (f.id, k) not in saem] or f.palavras
            t = plano.remapear_tempo((ficam[0].inicio + ficam[0].fim) / 2, trechos)
            quando = _mmss(t) if t is not None else "?"
            texto = " ".join(p.texto if (f.id, k) not in saem else f"[{p.texto}]" for k, p in enumerate(f.palavras))
            linhas.append(f"  ✔ {f.id:>2} {quando:>6}  {texto}")
        else:
            linhas.append(f"  ✘ {f.id:>2} {'':>6}  {f.texto}")
    if d.titulo:
        linhas.append(f"  título: {d.titulo}")
    for el in d.elementos:
        linhas.append(f"  cartão ({el['tipo']}) na frase {el['frase']}: {el['texto']}")
    for c in d.correcoes:
        linhas.append(f"  correção na frase {c['frase']}: {c['errado']} → {c['certo']}")
    for p in encaixe:
        onde = "gancho (abre o vídeo)" if p.gancho else f"frase {p.frase} em \"{p.ancora}\""
        linhas.append(f"  imagem {p.arquivo}: {onde}" + (f", desfocar {p.ocultar}" if p.ocultar else ""))
    linhas.append("  ([palavra] = sai num corte parcial)")
    return "\n".join(linhas)


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


def _argumentos_edicao(p) -> None:
    p.add_argument("video", type=Path)
    p.add_argument("-o", "--saida", type=Path)
    p.add_argument("--modelo", help="sobrepõe o modelo de transcrição da configuração")
    p.add_argument("--transcricao-json", type=Path, help="usa uma transcrição já salva")
    p.add_argument("--sem-claude", action="store_true", help="pula a decisão do Claude (só corta silêncios)")
    p.add_argument("--decisao-json", type=Path, help="reaproveita a decisão salva de uma edição anterior")
    p.add_argument("--refazer", action="store_true",
                   help="transcreve e decide de novo, mesmo havendo plano salvo para este vídeo")
    p.add_argument("--titulo", help="título do Reels no início (no lugar do sugerido pelo Claude)")
    p.add_argument("--sem-titulo", action="store_true", help="sem título no início")
    p.add_argument("--pergunta", default="", help="abre com a caixinha de pergunta do Instagram (no lugar do título)")
    p.add_argument("--apoio", type=Path, nargs="+", default=[],
                   help="material de apoio: prints e imagens que o Claude encaixa no vídeo")
    p.add_argument("--apoio-json", type=Path, help="reaproveita o encaixe salvo do material de apoio")
    p.add_argument("--sem-graficos", action="store_true", help="sem elementos gráficos durante a fala")


def main() -> None:
    _completar_path()
    ap = argparse.ArgumentParser(prog="edicao")
    ap.add_argument("--config", type=Path, help="arquivo de configuração (padrão: config.toml)")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("processar", help="edita um vídeo")
    pl = sub.add_parser("planejar", help="decide a edição e confere os cortes, sem renderizar")
    for q in (p, pl):
        _argumentos_edicao(q)
    p.add_argument("--previa", action="store_true",
                   help="prévia rápida (540x960, sem zoom animado) para conferir antes do final")
    p.add_argument("--album", help="põe o editado neste álbum do Fotos (padrão: [saida] album da configuração)")

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

    if args.comando in ("processar", "planejar"):
        if args.sem_claude:
            cfg["decisao"]["backend"] = "nenhum"
        if args.sem_graficos:
            cfg["graficos"]["elementos"] = False
        final = args.saida or args.video.with_name(args.video.stem + "_editado.mp4")
        previa = args.comando == "processar" and args.previa
        saida = final.with_name(final.stem + "_previa" + final.suffix) if previa else final
        # O que já foi decidido para este vídeo (pelo planejar ou por uma prévia) é reaproveitado:
        # mudar só a legenda ou um cartão não refaz a transcrição nem a decisão. --refazer ignora.
        salvos = {}
        if not args.refazer:
            for nome, sufixo in (("transcricao_json", ".transcricao.json"), ("decisao_json", ".decisao.json"),
                                 ("apoio_json", ".apoio.json")):
                arquivo = final.with_suffix(sufixo)
                if getattr(args, nome) is None and arquivo.exists() and (nome != "apoio_json" or args.apoio):
                    salvos[nome] = arquivo
                    print(f"reaproveitando {arquivo.name} (--refazer para decidir de novo)")
            if "transcricao_json" not in salvos and args.transcricao_json is None:
                salvos.pop("decisao_json", None)     # a decisão vale só para a transcrição dela
                salvos.pop("apoio_json", None)
        processar(args.video, saida, cfg, args.transcricao_json or salvos.get("transcricao_json"),
                  "" if args.sem_titulo else args.titulo, args.pergunta,
                  args.decisao_json or salvos.get("decisao_json"), args.apoio,
                  args.apoio_json or salvos.get("apoio_json"), so_planejar=args.comando == "planejar", previa=previa)
        if args.comando == "planejar":
            return
        album = args.album if args.album is not None else cfg.get("saida", {}).get("album", "")
        if previa:
            album = cfg.get("saida", {}).get("album_previas", "") if args.album is None else args.album
        if album:
            print(f"pondo no álbum \"{album}\" do Fotos…")
            fotos.importar(saida, album)
    else:
        medir(args.video, cfg)


if __name__ == "__main__":
    main()
