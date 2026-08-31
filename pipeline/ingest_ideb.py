#!/usr/bin/env python3
"""Ideb do INEP → banco, em formato longo.

A planilha do INEP é larga: uma linha por município/rede e ~120 colunas, com
o ano embutido no NOME da coluna (`VL_OBSERVADO_2023`). Isso é cômodo para
quem abre no Excel e péssimo para consultar: perguntar "como este município
evoluiu" viraria um SELECT com dez colunas escritas à mão, e acrescentar o
Ideb de 2025 exigiria mexer no schema.

Aqui a planilha vira **formato longo** — uma linha por (município, etapa,
rede, ano) — e o ano passa a ser dado, não estrutura. A divulgação de 2025
entra sem migração nenhuma.

Três decisões que valem a leitura:

  1. **O md5 do próprio INEP é conferido.** O .zip traz um `md5_*.txt` com o
     hash que o INEP declara para a planilha. Conferir custa nada e fecha o
     ciclo de proveniência do lado de lá: o sha256 do snapshot prova que o
     arquivo não mudou depois que baixamos; o md5 declarado prova que o que
     baixamos é o que o INEP publicou.
  2. **Ausência não vira zero.** Rede sem alunos suficientes não é divulgada
     e vem como '-'. Um município com "Ideb 0" entraria em toda média como
     medição real e puxaria o número nacional para baixo. Fica NULL.
  3. **As três redes não somam.** 'Pública' já é o agregado de 'Estadual' e
     'Municipal'. Guardamos as três porque a pergunta muda conforme a rede
     (o prefeito responde pela municipal), mas quem consulta tem que
     escolher uma — somar conta o mesmo aluno duas vezes.

Uso:
    python3.13 pipeline/ingest_ideb.py                 # as três etapas
    python3.13 pipeline/ingest_ideb.py --etapa anos_iniciais
"""
import argparse
import hashlib
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
import fontes as F
from xlsx import linhas as linhas_xlsx, numero

ETAPAS = ["anos_iniciais", "anos_finais", "ensino_medio"]

# A linha 10 (1-based) é a dos códigos de máquina (SG_UF, CO_MUNICIPIO, …).
# Acima dela vêm quatro linhas de título e duas de rótulo humano em células
# mescladas. Ler o cabeçalho humano daria nomes repetidos e vazios.
LINHA_CABECALHO = 10

MEDIDAS = {
    "ideb":  "VL_OBSERVADO",
    "nota":  "VL_NOTA_MEDIA",
    "fluxo": "VL_INDICADOR_REND",
    "meta":  "VL_PROJECAO",
}
COLS = ["cod_ibge", "etapa", "rede", "ano", "ideb", "nota", "fluxo", "meta",
        "snapshot_id"]


def _planilha(z):
    nomes = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
    if not nomes:
        raise ValueError("nenhum .xlsx dentro do zip")
    return nomes[0]


def conferir_md5(z, alvo):
    """Confere a planilha contra o md5 que o próprio INEP publica no zip.

    Devolve (ok, mensagem). Sem arquivo de md5, devolve (None, …) — ausência
    de conferência é diferente de conferência que falhou, e o log tem que
    dizer qual dos dois aconteceu.
    """
    md5s = [n for n in z.namelist() if os.path.basename(n).startswith("md5_")]
    if not md5s:
        return None, "o zip não traz md5 declarado"
    declarado = {}
    for linha in z.read(md5s[0]).decode("utf-8", "replace").splitlines():
        partes = linha.split()
        if len(partes) == 2:
            declarado[partes[1].lstrip("*")] = partes[0].lower()
    esperado = declarado.get(os.path.basename(alvo))
    if not esperado:
        return None, f"md5 declarado não cobre {os.path.basename(alvo)}"
    h = hashlib.md5()
    with z.open(alvo) as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    obtido = h.hexdigest()
    if obtido != esperado:
        return False, f"md5 DIVERGE: declarado {esperado}, obtido {obtido}"
    return True, f"md5 confere ({obtido})"


def ler(caminho, etapa):
    """Gera tuplas longas a partir do zip do INEP."""
    with zipfile.ZipFile(caminho) as z:
        alvo = _planilha(z)
        ok, msg = conferir_md5(z, alvo)
        print(f"  {msg}")
        if ok is False:
            raise ValueError("planilha corrompida ou adulterada — abortado")
        with z.open(alvo) as f:
            dados = f.read()

    import io
    anos = None
    for linha in linhas_xlsx(io.BytesIO(dados), cabecalho=LINHA_CABECALHO):
        if anos is None:
            anos = sorted({int(m.group(1)) for c in linha
                           for m in [re.search(r"^VL_OBSERVADO_(\d{4})$", c)] if m})
            print(f"  anos na planilha: {anos[0]}–{anos[-1]} ({len(anos)} edições)")
        cod = (linha.get("CO_MUNICIPIO") or "").strip()
        rede = (linha.get("REDE") or "").strip()
        if not cod.isdigit() or not rede:
            continue
        for ano in anos:
            valores = [numero(linha.get(f"{col}_{ano}")) for col in MEDIDAS.values()]
            # Linha sem nenhuma medição não é dado: é a rede não divulgada.
            if all(v is None for v in valores):
                continue
            yield (int(cod), etapa, rede, ano, *valores)


def ingerir(con, etapa):
    fonte = F.FONTES[f"inep_ideb_{etapa}"]
    caminho = F.caminho(fonte)
    if not os.path.exists(caminho):
        print(f"  arquivo ausente: {caminho}\n"
              f"  rode: python3.13 pipeline/atualizar.py --fonte {fonte.id}")
        return 0

    bd.registrar_fonte(con, fonte)
    snap, ja = bd.registrar_snapshot(con, fonte.id, caminho)
    print(f"  snapshot {snap['id']} sha256={snap['sha256'][:12]}…"
          + (" (já existia)" if ja else ""))

    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE stg_ideb (LIKE ideb) ON COMMIT DROP")
    n = bd.copiar(con, "stg_ideb", COLS,
                  (t + (snap["id"],) for t in ler(caminho, etapa)))
    with con.cursor() as cur:
        # A planilha traz a série histórica inteira a cada divulgação, então a
        # reingestão é idempotente por natureza: mesma chave, mesmo valor.
        cur.execute(f"""
            INSERT INTO ideb ({','.join(COLS)})
            SELECT {','.join(COLS)} FROM stg_ideb
            ON CONFLICT (cod_ibge, etapa, rede, ano) DO UPDATE SET
                ideb=EXCLUDED.ideb, nota=EXCLUDED.nota, fluxo=EXCLUDED.fluxo,
                meta=EXCLUDED.meta, snapshot_id=EXCLUDED.snapshot_id
        """)
        cur.execute("""
            SELECT COUNT(DISTINCT s.cod_ibge) AS c FROM stg_ideb s
            LEFT JOIN municipio m ON m.cod_ibge = s.cod_ibge
            WHERE m.cod_ibge IS NULL
        """)
        orfaos = cur.fetchone()["c"]
    con.commit()
    bd.marcar_ingerido(con, snap["id"], n)
    print(f"  {n} linhas ingeridas"
          + (f" — ATENÇÃO: {orfaos} municípios sem correspondência em `municipio`"
             if orfaos else " — todos os municípios casaram com a tabela `municipio`"))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etapa", choices=ETAPAS, action="append")
    args = ap.parse_args()
    con = bd.conectar()
    bd.init(con)
    total = 0
    for etapa in (args.etapa or ETAPAS):
        print(f"── {etapa}")
        total += ingerir(con, etapa)
    print(f"\nok: {bd.contar(con, 'ideb')} linhas na tabela ideb "
          f"({total} vindas desta execução)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
