#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscar_dispensas.py

Consulta a API PÚBLICA e OFICIAL do PNCP (Portal Nacional de Contratações
Públicas) e lista as contratações por DISPENSA DE LICITAÇÃO (modalidade 8,
Lei 14.133/2021) que estão, neste momento, com prazo de proposta em aberto,
nos municípios configurados abaixo.

Não usa nenhuma biblioteca externa (só a biblioteca padrão do Python), então
roda em qualquer máquina com Python 3.8+ instalado, sem precisar de "pip
install" de nada.

Documentação oficial da API (spec OpenAPI):
  https://pncp.gov.br/api/consulta/v3/api-docs
  Swagger UI: https://pncp.gov.br/api/consulta/swagger-ui/index.html

Uso:
  python buscar_dispensas.py
  python buscar_dispensas.py --cidade "Jundiaí"     # só uma cidade, para testar
  python buscar_dispensas.py --saida meu_arquivo.json
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuração: municípios cobertos (nome -> código IBGE de 7 dígitos)
# Fonte dos códigos: IBGE / DTB, conferidos em setembro de 2026.
# ---------------------------------------------------------------------------
CIDADES = {
    "Jundiaí": "3525904",
    "Várzea Paulista": "3556503",
    "Campo Limpo Paulista": "3509601",
    "Itupeva": "3524006",
    "Cabreúva": "3508405",
    "Louveira": "3527306",
    "Vinhedo": "3556701",
    "Cajamar": "3509205",
}

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
MODALIDADE_DISPENSA = 8  # tabela de domínio "Modalidade de Contratação" do PNCP

# IMPORTANTE: o endpoint /contratacoes/proposta aceita no MÁXIMO 50 itens por
# página (confirmado na especificação oficial OpenAPI da API). Pedir mais que
# isso faz a API devolver erro 400 (Bad Request) — foi um bug da primeira
# versão deste script, que engolia esse erro silenciosamente.
TAMANHO_PAGINA = 50

TIMEOUT_SEGUNDOS = 45    # a API do PNCP pode ser lenta às vezes
TENTATIVAS_POR_CHAMADA = 3
PAUSA_ENTRE_TENTATIVAS = 5   # segundos, entre uma tentativa e outra na mesma chamada
PAUSA_ENTRE_CHAMADAS = 0.5   # segundos — para não sobrecarregar a API pública

# Palavras que, se aparecerem no objeto da contratação, costumam indicar obra
# de engenharia / serviço muito especializado (exige ART/CREA, grande porte).
# É só um alerta heurístico, não é 100% preciso — sempre confira o edital.
PALAVRAS_OBRA = [
    "pavimenta", "construç", "construc", "reforma predial", "engenharia",
    "drenagem", "gabião", "terraplanagem", "asfalt", "edifica",
    "reforma de escola", "reforma de unidade",
]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def chamar_api(endpoint, params):
    """Faz uma chamada GET à API do PNCP e devolve o JSON decodificado.
    Tenta algumas vezes em caso de instabilidade de rede (comum nessa API).
    Devolve None se não conseguir de jeito nenhum — o resto do script segue
    normalmente para as próximas cidades, sem travar tudo."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}{endpoint}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "radar-dispensas-jundiai/1.0 (script pessoal, uso nao comercial)",
        },
    )

    for tentativa in range(1, TENTATIVAS_POR_CHAMADA + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
                if resp.status == 204:
                    return None
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))

        except urllib.error.HTTPError as e:
            corpo = ""
            try:
                corpo = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            if e.code == 204:
                return None
            log(f"  ERRO HTTP {e.code} em {endpoint} (params: {params}): {corpo}")
            return None  # erro do servidor (4xx/5xx) — tentar de novo não ajuda

        except json.JSONDecodeError:
            log(f"  AVISO: resposta não era JSON válido em {url}")
            return None

        except Exception as e:
            # Cobre timeout, conexão recusada/resetada, DNS, SSL, etc.
            log(f"  AVISO (tentativa {tentativa}/{TENTATIVAS_POR_CHAMADA}): "
                f"falha de rede ({type(e).__name__}: {e}) em {url}")
            if tentativa < TENTATIVAS_POR_CHAMADA:
                time.sleep(PAUSA_ENTRE_TENTATIVAS)
                continue
            log(f"  ERRO: desisti dessa chamada após {TENTATIVAS_POR_CHAMADA} tentativas.")
            return None

    return None


def buscar_dispensas_abertas_da_cidade(nome_cidade, codigo_ibge, data_final):
    """Percorre todas as páginas de /contratacoes/proposta para um município,
    filtrando por modalidade = Dispensa de Licitação. Nunca lança exceção —
    se algo der errado, devolve o que já tiver conseguido até ali."""
    resultados = []
    pagina = 1
    while True:
        dados = chamar_api(
            "/contratacoes/proposta",
            {
                "dataFinal": data_final,
                "codigoModalidadeContratacao": MODALIDADE_DISPENSA,
                "codigoMunicipioIbge": codigo_ibge,
                "pagina": pagina,
                "tamanhoPagina": TAMANHO_PAGINA,
            },
        )
        time.sleep(PAUSA_ENTRE_CHAMADAS)

        if not dados or "data" not in dados or not dados["data"]:
            break

        resultados.extend(dados["data"])

        total_paginas = dados.get("totalPaginas", 1)
        if pagina >= total_paginas:
            break
        pagina += 1

    log(f"  {nome_cidade}: {len(resultados)} contratação(ões) por dispensa com proposta em aberto")
    return resultados


def parece_obra(objeto_texto):
    texto = (objeto_texto or "").lower()
    return any(p in texto for p in PALAVRAS_OBRA)


def montar_link(item):
    """Reconstrói o link público do PNCP a partir do CNPJ + ano + sequencial,
    seguindo a máscara oficial do Número de Controle PNCP."""
    try:
        cnpj = item["orgaoEntidade"]["cnpj"]
        ano = item["anoCompra"]
        sequencial = item["sequencialCompra"]
        return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
    except (KeyError, TypeError):
        return None


def normalizar_item(item, cidade):
    return {
        "numero_controle_pncp": item.get("numeroControlePNCP"),
        "cidade": cidade,
        "orgao": (item.get("orgaoEntidade") or {}).get("razaosocial") or (item.get("orgaoEntidade") or {}).get("razaoSocial"),
        "unidade": (item.get("unidadeOrgao") or {}).get("nomeUnidade"),
        "objeto": item.get("objetoCompra"),
        "valor_estimado": item.get("valorTotalEstimado"),
        "modalidade": item.get("modalidadeNome"),
        "amparo_legal": (item.get("amparoLegal") or {}).get("nome"),
        "data_abertura_proposta": item.get("dataAberturaProposta"),
        "data_encerramento_proposta": item.get("dataEncerramentoProposta"),
        "link": montar_link(item),
        "possivel_obra_ou_servico_especializado": parece_obra(item.get("objetoCompra")),
    }


def main():
    parser = argparse.ArgumentParser(description="Busca dispensas de licitação abertas no PNCP.")
    parser.add_argument("--cidade", help="Rodar só para uma cidade (nome exato, ex: Jundiaí)")
    parser.add_argument("--saida", default="dispensas.json", help="Arquivo de saída (padrão: dispensas.json)")
    parser.add_argument("--dias-janela", type=int, default=120,
                         help="Janela futura para dataFinal, em dias (padrão: 120)")
    args = parser.parse_args()

    cidades = CIDADES
    if args.cidade:
        if args.cidade not in CIDADES:
            log(f"ERRO: cidade '{args.cidade}' não está configurada. Opções: {list(CIDADES)}")
            sys.exit(1)
        cidades = {args.cidade: CIDADES[args.cidade]}

    data_final = (datetime.now() + timedelta(days=args.dias_janela)).strftime("%Y%m%d")

    log(f"Buscando dispensas de licitação (modalidade {MODALIDADE_DISPENSA}) com proposta em aberto...")
    log(f"Janela de busca: até {data_final}")

    todas = []
    cidades_com_erro = []

    for nome_cidade, codigo_ibge in cidades.items():
        try:
            brutos = buscar_dispensas_abertas_da_cidade(nome_cidade, codigo_ibge, data_final)
            for item in brutos:
                todas.append(normalizar_item(item, nome_cidade))
        except Exception as e:
            log(f"  ERRO inesperado em {nome_cidade}: {type(e).__name__}: {e}")
            cidades_com_erro.append(nome_cidade)

    todas.sort(key=lambda x: x["data_encerramento_proposta"] or "9999")

    saida = {
        "gerado_em": datetime.now(timezone(timedelta(hours=-3))).isoformat(),
        "fonte": "API pública oficial do PNCP (https://pncp.gov.br/api/consulta/v1)",
        "modalidade_filtrada": "Dispensa de Licitação (código 8)",
        "cidades_consultadas": cidades,
        "cidades_com_erro_nesta_execucao": cidades_com_erro,
        "total_oportunidades": len(todas),
        "oportunidades": todas,
    }

    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    log(f"Concluído: {len(todas)} oportunidade(s) salva(s) em {args.saida}")
    if cidades_com_erro:
        log(f"AVISO: não foi possível consultar: {', '.join(cidades_com_erro)}")


if __name__ == "__main__":
    main()
