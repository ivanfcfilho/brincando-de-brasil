#!/usr/bin/env python3
"""O job: checa as fontes oficiais, baixa o que mudou, ingere e resume o diff.

Desenhado para rodar todo dia sem supervisão:

  - a checagem é um HEAD e custa ~1 KB por fonte; só baixa se mudou de verdade;
  - lock em arquivo, para que uma execução longa não seja atropelada pela do
    dia seguinte (dois ingestores no mesmo banco produziriam um diff sem sentido);
  - periodicidade por fonte: o TSE de 2022 é estático e não entra no ciclo
    diário (use --fonte tse_munzona_2022 quando quiser);
  - toda checagem vira linha em `checagem`, inclusive as sem novidade —
    "olhamos e nada mudou" é afirmação que também precisa de prova;
  - encerra com o resumo do que mudou, que é o material publicável.

Uso:
    python3.13 pipeline/atualizar.py                # ciclo diário
    python3.13 pipeline/atualizar.py --dry-run      # só checa, não baixa
    python3.13 pipeline/atualizar.py --fonte tse_munzona_2022 --forcar
    python3.13 pipeline/atualizar.py --resumo 7     # o que mudou em 7 dias
"""
import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
import fontes as F

LOCK = os.path.join(bd.RAIZ, "data", ".atualizar.lock")


def _vivo(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Lock:
    def __enter__(self):
        if os.path.exists(LOCK):
            pid = open(LOCK).read().strip()
            if pid.isdigit() and _vivo(int(pid)):
                sys.exit(f"já em execução (pid {pid}); saindo")
            print(f"lock órfão do pid {pid} removido")
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        with open(LOCK, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        if os.path.exists(LOCK):
            os.remove(LOCK)


def ingerir(fonte):
    """Despacha para o ingestor da fonte. Devolve o código de saída."""
    argv = sys.argv
    try:
        if fonte.id == "cgu_emendas":
            import ingest_emendas
            sys.argv = ["ingest_emendas"]
            return ingest_emendas.main()
        if fonte.id.startswith("tse_munzona"):
            import ingest_tse
            sys.argv = ["ingest_tse", "--ano", fonte.id.rsplit("_", 1)[1]]
            return ingest_tse.main()
    finally:
        sys.argv = argv
    print(f"  sem ingestor para {fonte.id} — arquivo baixado, nada ingerido")
    return 0


def ciclo(args):
    con = bd.conectar()
    bd.init(con)

    alvo = ([F.FONTES[args.fonte]] if args.fonte
            else [f for f in F.FONTES.values()
                  if args.todas or f.periodicidade == "diaria"])
    houve_erro = False

    for fonte in alvo:
        bd.registrar_fonte(con, fonte)
        print(f"\n── {fonte.id} ({fonte.periodicidade})")
        try:
            cab = F.checar(fonte)
        except Exception as e:
            print(f"  ERRO na checagem: {e}")
            bd.registrar_checagem(con, fonte.id, None, False, str(e))
            houve_erro = True
            continue

        snap = bd.ultimo_snapshot(con, fonte.id)
        mudou, motivo = F.mudou(cab, snap)
        if args.forcar and not mudou:
            mudou, motivo = True, "forçado"
        bd.registrar_checagem(con, fonte.id, cab, mudou)
        print(f"  {motivo}")

        if not mudou:
            continue
        if args.dry_run:
            print("  (dry-run: não baixou)")
            continue

        try:
            caminho = F.baixar(fonte)
            snap_novo, ja = bd.registrar_snapshot(con, fonte.id, caminho, cab)
            if ja and snap_novo["ingerido_em"]:
                # Cabeçalho mudou mas o conteúdo é bit a bit o mesmo
                # (republicação sem alteração). Não há o que ingerir.
                print(f"  conteúdo idêntico ao snapshot {snap_novo['id']} — nada a ingerir")
                continue
            con.close()                 # o ingestor abre a própria conexão
            ingerir(fonte)
            con = bd.conectar()
        except Exception:
            traceback.print_exc()
            houve_erro = True
            if con.closed:
                con = bd.conectar()

    # As invariantes rodam SEMPRE, mesmo em ciclo sem novidade: o dado pode
    # ter sido corrompido por outro caminho, e erro que não grita é o caro.
    print()
    from conferir import conferir
    if conferir(con):
        houve_erro = True

    print("\n" + resumo(con, args.dias_resumo))
    return 1 if houve_erro else 0


def brl(v):
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def resumo(con, dias=1):
    """O que mudou na janela — a matéria-prima do alerta diário.

    Separado em duas leituras, porque misturá-las torna o resumo inútil:

      1. mudanças com autor identificado — o feed acionável, deputado a
         deputado, município a município;
      2. mudanças sem autor individual (relator, bancada, comissão: RP8/RP9)
         — que costumam ser a MAIOR parte do dinheiro e não têm a quem
         atribuir. Esse volume é, ele próprio, um dos argumentos da PEC.

    Sem adjetivo e sem inferência: valor que entrou, valor que subiu, autor e
    município. A leitura é de quem lê.
    """
    linhas = [f"RESUMO — mudanças nos últimos {dias} dia(s)"]
    with con.cursor() as cur:
        cur.execute("""
            SELECT tipo, COUNT(*) AS n, SUM(valor_depois - valor_antes) AS delta
            FROM mudanca WHERE detectado_em >= now() - make_interval(days => %s)
            GROUP BY tipo ORDER BY n DESC
        """, (dias,))
        tot = cur.fetchall()
        if not tot:
            return "\n".join(linhas + ["  nenhuma mudança registrada na janela"])
        for t in tot:
            linhas.append(f"  {t['tipo']:10s} {t['n']:>7} linhas  "
                          f"delta {brl(t['delta'] or 0)}")

        cur.execute("""
            SELECT COUNT(*) AS n, SUM(m.valor_depois - m.valor_antes) AS delta
            FROM mudanca m
            LEFT JOIN autor a ON a.cod_autor = m.cod_autor
            WHERE m.detectado_em >= now() - make_interval(days => %s)
              AND m.campo IN ('empenhado','valor_recebido')
              AND (a.sq_candidato IS NULL)
        """, (dias,))
        anon = cur.fetchone()
        if anon and anon["n"]:
            linhas.append(f"\n  sem deputado identificado (relator/bancada/comissão "
                          f"ou autor não vinculado): {anon['n']} linhas, "
                          f"{brl(anon['delta'] or 0)}")

        cur.execute("""
            SELECT d.nome_urna, d.uf, d.partido, m.municipio,
                   SUM(m.valor_depois - m.valor_antes) AS delta
            FROM mudanca m
            JOIN autor a    ON a.cod_autor = m.cod_autor
            JOIN deputado d ON d.sq_candidato = a.sq_candidato
            WHERE m.detectado_em >= now() - make_interval(days => %s)
              AND m.campo IN ('empenhado','valor_recebido')
              AND d.situacao LIKE 'ELEITO%%'
            GROUP BY 1,2,3,4
            HAVING SUM(m.valor_depois - m.valor_antes) <> 0
            ORDER BY ABS(SUM(m.valor_depois - m.valor_antes)) DESC LIMIT 15
        """, (dias,))
        top = cur.fetchall()
    if top:
        linhas.append("\n  maiores variações com deputado identificado:")
        for r in top:
            linhas.append(f"    {r['nome_urna'][:26]:26s} {r['partido'] or '':8s}"
                          f"{r['uf']:3s} → {(r['municipio'] or '(sem município)')[:24]:24s} "
                          f"{brl(r['delta'])}")
    else:
        linhas.append("\n  nenhuma variação atribuível a deputado eleito na janela")
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", help="roda só esta fonte")
    ap.add_argument("--todas", action="store_true",
                    help="inclui fontes não-diárias (TSE)")
    ap.add_argument("--forcar", action="store_true",
                    help="baixa e reingere mesmo sem mudança nos cabeçalhos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dias-resumo", type=int, default=1)
    ap.add_argument("--resumo", type=int, metavar="DIAS",
                    help="só imprime o resumo da janela e sai")
    args = ap.parse_args()

    if args.resumo:
        print(resumo(bd.conectar(), args.resumo))
        return 0
    with Lock():
        return ciclo(args)


if __name__ == "__main__":
    raise SystemExit(main())
