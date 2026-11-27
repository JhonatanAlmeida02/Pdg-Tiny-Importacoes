"""
sincronizar_core.py
-------------------
Envia a base de produtos do Tiny (TB_bases/Tb_BaseProdutos_Tiny.csv) para o
cadastro mestre da Plataforma Prodigy (schema core, banco prodigy-plataforma).

Quem decide o que entra é a função core.sync_tiny_products() no banco:
cria os novos, atualiza os que mudaram, vincula pelo SKU e devolve as
pendências (produto sem código ou com código repetido no Tiny).

Variável de ambiente obrigatória:
  CORE_DATABASE_URL  conexão do papel core_tiny_sync (ver docs/sincronizacao-tiny.md
                     no Pdg-Hub). Sem ela, o script avisa e termina sem erro.

Uso:  python sincronizar_core.py [caminho_do_csv]
"""

import csv
import json
import os
import sys

ARQUIVO = os.path.join("TB_bases", "Tb_BaseProdutos_Tiny.csv")

# coluna do CSV -> campo esperado pela função do banco
CAMPOS = {
    "id": "tiny_id",
    "codigo": "sku",
    "nome": "name",
    "gtin": "gtin",
    "unidade": "unit",
    "marca": "brand",
    "situacao": "situation",
    "tipo_variacao": "variation",
    "classe_produto": "product_class",
    "id_produto_pai": "parent_id",
    "data_alteracao": "updated_at",
}


def limpar(valor: str) -> str:
    valor = (valor or "").strip()
    # o pandas grava IDs como 123.0 quando a coluna tem vazios
    if valor.endswith(".0") and valor[:-2].isdigit():
        valor = valor[:-2]
    return "" if valor.lower() == "nan" else valor


def ler_base(caminho: str) -> list[dict]:
    csv.field_size_limit(10**9)
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        faltando = [c for c in CAMPOS if c not in (leitor.fieldnames or [])]
        if faltando:
            raise SystemExit(f"❌ O CSV não tem as colunas: {', '.join(faltando)}")
        return [{destino: limpar(linha.get(origem, "")) for origem, destino in CAMPOS.items()} for linha in leitor]


def main() -> int:
    caminho = sys.argv[1] if len(sys.argv) > 1 else ARQUIVO
    url = os.environ.get("CORE_DATABASE_URL", "").strip()
    if not url:
        print("⚠️ CORE_DATABASE_URL não configurada: sincronização com o core pulada.")
        return 0
    if not os.path.exists(caminho):
        print(f"⚠️ {caminho} não existe: nada a enviar.")
        return 0

    produtos = ler_base(caminho)
    print(f"📦 {len(produtos)} produtos lidos de {caminho}")

    import psycopg  # só é preciso quando há conexão

    # prepare_threshold=None: funciona também no pooler do Supabase (modo transação)
    with psycopg.connect(url, connect_timeout=30, prepare_threshold=None) as conexao:
        conexao.execute("set statement_timeout = '10min'")
        origem = "github_actions" if os.environ.get("GITHUB_ACTIONS") else "manual"
        resultado = conexao.execute(
            "select core.sync_tiny_products(%s::jsonb, %s)", (json.dumps(produtos), origem)
        ).fetchone()[0]

    print(
        f"✅ Core sincronizado (execução {resultado['execucao']}): "
        f"{resultado['criados']} criados, {resultado['atualizados']} atualizados, "
        f"{resultado['vinculados']} vinculados, {resultado['sem_mudanca']} sem mudança, "
        f"{resultado['pendencias']} pendências. Total no core: {resultado['total_no_core']}."
    )
    pendencias = resultado.get("lista_pendencias") or []
    if pendencias:
        print(f"\n⚠️ {len(pendencias)} produtos ficaram de fora até serem corrigidos no Tiny:")
        for p in pendencias[:100]:
            print(f"   - {p.get('motivo')}: ID {p.get('tiny_id')} | SKU {p.get('sku') or '(vazio)'} | {p.get('nome')}")
        if len(pendencias) > 100:
            print(f"   ... e mais {len(pendencias) - 100}.")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=Pendências no cadastro do Tiny::{len(pendencias)} produtos sem código ou com código repetido ficaram fora do core.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
