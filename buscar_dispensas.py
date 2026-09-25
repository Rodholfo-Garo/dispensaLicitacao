#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscar_dispensas.py

Consulta a API PÚBLICA e OFICIAL do PNCP (Portal Nacional de Contratações
Públicas) e lista as contratações por DISPENSA DE LICITAÇÃO (modalidade 8,
Lei 14.133/2021) que estão, neste momento, com prazo de proposta em aberto,
em TODO O ESTADO configurado abaixo (padrão: SP).

Não usa nenhuma biblioteca externa (só a biblioteca padrão do Python), então
roda em qualquer máquina com Python 3.8+ instalado, sem precisar de "pip
install" de nada.

Documentação oficial da API (spec OpenAPI):
  https://pncp.gov.br/api/consulta/v3/api-docs
  Swagger UI: https://pncp.gov.br/api/consulta/swagger-ui/index.html

Uso:
  python buscar_dispensas.py
  python buscar_dispensas.py --cidade "Jundiaí"     # filtra uma cidade (após a busca), para testar
  python buscar_dispensas.py --max-paginas 2        # busca rápida, para testar
  python buscar_dispensas.py --saida meu_arquivo.json
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
UF = "SP"  # sigla do estado consultado (parâmetro "uf" do endpoint /contratacoes/proposta)

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
MODALIDADE_DISPENSA = 8  # tabela de domínio "Modalidade de Contratação" do PNCP

# IMPORTANTE: o endpoint /contratacoes/proposta aceita no MÁXIMO 50 itens por
# página (confirmado na especificação oficial OpenAPI da API). Pedir mais que
# isso faz a API devolver erro 400 (Bad Request) — foi um bug da primeira
# versão deste script, que engolia esse erro silenciosamente.
TAMANHO_PAGINA = 50

TIMEOUT_SEGUNDOS = 45    # a API do PNCP pode ser lenta às vezes
TENTATIVAS_POR_CHAMADA = 4
PAUSA_ENTRE_TENTATIVAS = 5   # segundos (multiplicado pelo nº da tentativa)
PAUSA_ENTRE_CHAMADAS = 0.5   # segundos — para não sobrecarregar a API pública

# Códigos HTTP que indicam instabilidade passageira — vale tentar de novo.
# Outros erros (400, 404...) são problema na requisição: tentar de novo não ajuda.
HTTP_REPETIVEIS = {429, 500, 502, 503, 504}

# Palavras que, se aparecerem no objeto da contratação, costumam indicar obra
# de engenharia / serviço muito especializado (exige ART/CREA, grande porte).
# É só um alerta heurístico, não é 100% preciso — sempre confira o edital.
PALAVRAS_OBRA = [
    "pavimenta", "construç", "construc", "reforma predial", "engenharia",
    "drenagem", "gabião", "terraplanagem", "asfalt", "edifica",
    "reforma de escola", "reforma de unidade",
]

# Categorias de interesse (destacadas no topo do painel). A comparação é feita
# no objeto da contratação, SEM acentos e em minúsculas — então escreva as
# palavras aqui também sem acento. "incluir": basta uma aparecer. "excluir":
# se alguma aparecer, a categoria NÃO é marcada (evita falsos positivos).
# É heurístico — ajuste as listas conforme for vendo os resultados.
CATEGORIAS = {
    "eletronicos": {
        "rotulo": "Eletrônicos e acessórios",
        "incluir": [
            "eletronicos", "equipamentos eletronicos", "componentes eletronicos",
            "eletroeletronic", "eletroportat", "equipamentos de informatica",
            "equipamento de informatica", "material de informatica",
            "materiais de informatica", "suprimentos de informatica",
            "acessorios de informatica", "periferico", "cabo hdmi", "cabos hdmi",
            "cabo usb", "cabos usb", "adaptador usb", "adaptadores usb",
            "adaptador hdmi", "adaptadores hdmi", "adaptador conversor", "carregador", "fone de ouvido",
            "fones de ouvido", "headset", "pilha", "mouse", "teclado", "pen drive",
            "pendrive", "cartao de memoria", "cartoes de memoria", "hd externo",
            "webcam", "caixa de som", "caixas de som", "extensao eletrica",
            "extensoes eletricas", "filtro de linha", "estabilizador de tensao",
            "estabilizadores de tensao", "estabilizador de energia", "nobreak",
            "no-break", "lampada", "roteador", "monitor de video", "monitores de video",
            "notebook", "computador", "tablet", "impressora", "material eletrico",
            "materiais eletricos",
        ],
        "excluir": [
            "monitoramento", "monitor de sinais vitais", "eletrocardiog",
            "manutencao de veiculo", "manutencao preventiva e corretiva de veiculo",
            "bateria automotiva", "baterias automotivas", "prontuario eletronico",
            "ponto eletronico", "leilao eletronico", "pregao eletronico",
            "programas de computador", "programa de computador", "pedagio", "pedagios",
        ],
    },
    "papelaria": {
        "rotulo": "Papelaria e escritório",
        "incluir": [
            "papelaria", "material de escritorio", "materiais de escritorio",
            "material de expediente", "materiais de expediente", "papel a4",
            "papel sulfite", "sulfite", "caneta", "canetas", "lapis", "borracha escolar",
            "grampeador", "grampos", "clips", "clipes", "pasta suspensa", "pastas suspensas",
            "envelope", "envelopes", "toner", "toners", "cartucho", "cartuchos",
            "fita adesiva", "post-it", "bloco de notas", "caderno", "cadernos",
            "material escolar", "materiais escolares", "etiqueta", "etiquetas",
            "arquivo morto", "caixa arquivo", "marca texto", "corretivo",
        ],
        "excluir": [
            "etiqueta eletronica", "etiquetas eletronicas", "pedagio", "pedagios",
        ],
    },
    "limpeza": {
        "rotulo": "Material de limpeza",
        "incluir": [
            "material de limpeza", "materiais de limpeza", "produtos de limpeza",
            "produto de limpeza", "material de higiene", "materiais de higiene",
            "higiene e limpeza", "limpeza e higiene", "detergente",
            "desinfetante", "agua sanitaria", "saco de lixo", "sacos de lixo",
            "saco para lixo", "sacos para lixo", "papel higienico", "papel toalha",
            "sabonete", "sabao", "alcool 70", "alcool em gel", "alcool gel",
            "vassoura", "rodo de", "rodos", "pano de chao", "panos de chao",
            "esponja", "luva de limpeza", "luvas de limpeza",
            "limpa vidro", "limpador multiuso", "limpadores multiuso", "hipoclorito", "lixeira", "dispenser",
        ],
        "excluir": [
            "limpeza urbana", "limpeza de terreno", "limpeza de terrenos",
            "limpeza de via", "limpeza de vias", "limpeza de fossa", "limpeza de caixa",
            "limpeza de bueiro", "limpeza de galeria", "limpeza de rio",
            "limpeza de corrego", "rocada", "capina", "servicos de limpeza",
            "servico de limpeza", "prestacao de servico de limpeza",
            "limpeza de reservatorio", "limpeza e desinfeccao de reservatorio",
        ],
    },
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def sem_acentos(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


class FalhaNaApi(Exception):
    """A API não respondeu (ou respondeu com erro) mesmo após as tentativas."""


def chamar_api(endpoint, params):
    """Faz uma chamada GET à API do PNCP e devolve o JSON decodificado.
    Tenta algumas vezes em caso de instabilidade (rede, 429, 5xx — comum nessa
    API). Devolve None quando a API responde "sem conteúdo" (204 / corpo vazio).
    Lança FalhaNaApi se não conseguir de jeito nenhum — assim quem chamou sabe
    diferenciar "não há resultados" de "não consegui consultar"."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}{endpoint}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "radar-dispensas-sp/2.0 (script pessoal, uso nao comercial)",
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
            if e.code not in HTTP_REPETIVEIS:
                raise FalhaNaApi(f"HTTP {e.code} em {endpoint} (params: {params}): {corpo}")
            log(f"  AVISO (tentativa {tentativa}/{TENTATIVAS_POR_CHAMADA}): HTTP {e.code} em {url}")

        except json.JSONDecodeError:
            log(f"  AVISO (tentativa {tentativa}/{TENTATIVAS_POR_CHAMADA}): resposta não era JSON válido em {url}")

        except Exception as e:
            # Cobre timeout, conexão recusada/resetada, DNS, SSL, etc.
            log(f"  AVISO (tentativa {tentativa}/{TENTATIVAS_POR_CHAMADA}): "
                f"falha de rede ({type(e).__name__}: {e}) em {url}")

        if tentativa < TENTATIVAS_POR_CHAMADA:
            time.sleep(PAUSA_ENTRE_TENTATIVAS * tentativa)

    raise FalhaNaApi(f"desisti de {url} após {TENTATIVAS_POR_CHAMADA} tentativas")


def buscar_dispensas_abertas_da_uf(uf, data_final, max_paginas=None):
    """Percorre todas as páginas de /contratacoes/proposta para a UF inteira,
    filtrando por modalidade = Dispensa de Licitação.
    Devolve (itens, erro): se uma página falhar de vez, para ali e devolve o
    que já tiver conseguido, junto com a mensagem de erro."""
    resultados = []
    pagina = 1
    while True:
        try:
            dados = chamar_api(
                "/contratacoes/proposta",
                {
                    "dataFinal": data_final,
                    "codigoModalidadeContratacao": MODALIDADE_DISPENSA,
                    "uf": uf,
                    "pagina": pagina,
                    "tamanhoPagina": TAMANHO_PAGINA,
                },
            )
        except FalhaNaApi as e:
            log(f"  ERRO na página {pagina}: {e}")
            return resultados, f"página {pagina}: {e}"
        time.sleep(PAUSA_ENTRE_CHAMADAS)

        if not dados or not dados.get("data"):
            break

        resultados.extend(dados["data"])

        total_paginas = dados.get("totalPaginas", 1)
        log(f"  página {pagina}/{total_paginas}: {len(resultados)} item(ns) até agora")
        if pagina >= total_paginas:
            break
        if max_paginas and pagina >= max_paginas:
            log(f"  parando na página {pagina} (--max-paginas)")
            break
        pagina += 1

    return resultados, None


def parece_obra(objeto_texto):
    texto = (objeto_texto or "").lower()
    return any(p in texto for p in PALAVRAS_OBRA)


def _compilar(palavras):
    # Cada termo precisa começar no início de uma palavra ("pilha" casa com
    # "pilhas", mas não com "empilhadeira"). O fim pode continuar ("rodo"
    # casaria com "rodovia"), por isso termos curtos ambíguos levam contexto.
    if not palavras:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in palavras) + ")")


_REGEX_CATEGORIAS = {
    chave: (_compilar(cfg["incluir"]), _compilar(cfg["excluir"]))
    for chave, cfg in CATEGORIAS.items()
}


def categorias_do_objeto(objeto_texto):
    texto = sem_acentos(objeto_texto)
    encontradas = []
    for chave, (incluir, excluir) in _REGEX_CATEGORIAS.items():
        if excluir and excluir.search(texto):
            continue
        if incluir.search(texto):
            encontradas.append(chave)
    return encontradas


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


def normalizar_item(item):
    unidade = item.get("unidadeOrgao") or {}
    orgao = item.get("orgaoEntidade") or {}
    return {
        "numero_controle_pncp": item.get("numeroControlePNCP"),
        "cidade": unidade.get("municipioNome") or "(município não informado)",
        "uf": unidade.get("ufSigla"),
        "codigo_ibge": unidade.get("codigoIbge"),
        "orgao": orgao.get("razaosocial") or orgao.get("razaoSocial"),
        "unidade": unidade.get("nomeUnidade"),
        "objeto": item.get("objetoCompra"),
        "valor_estimado": item.get("valorTotalEstimado"),
        "modalidade": item.get("modalidadeNome"),
        "amparo_legal": (item.get("amparoLegal") or {}).get("nome"),
        "data_abertura_proposta": item.get("dataAberturaProposta"),
        "data_encerramento_proposta": item.get("dataEncerramentoProposta"),
        "link": montar_link(item),
        "possivel_obra_ou_servico_especializado": parece_obra(item.get("objetoCompra")),
        "categorias": categorias_do_objeto(item.get("objetoCompra")),
    }


def main():
    parser = argparse.ArgumentParser(description="Busca dispensas de licitação abertas no PNCP.")
    parser.add_argument("--uf", default=UF, help=f"Sigla do estado (padrão: {UF})")
    parser.add_argument("--cidade", help="Manter só uma cidade no resultado (nome exato, ex: Jundiaí)")
    parser.add_argument("--max-paginas", type=int, help="Limite de páginas (para testes rápidos)")
    parser.add_argument("--saida", default="dispensas.json", help="Arquivo de saída (padrão: dispensas.json)")
    parser.add_argument("--dias-janela", type=int, default=120,
                         help="Janela futura para dataFinal, em dias (padrão: 120)")
    args = parser.parse_args()

    uf = args.uf.upper()
    data_final = (datetime.now() + timedelta(days=args.dias_janela)).strftime("%Y%m%d")

    log(f"Buscando dispensas de licitação (modalidade {MODALIDADE_DISPENSA}) com proposta em aberto em {uf}...")
    log(f"Janela de busca: até {data_final}")

    brutos, erro = buscar_dispensas_abertas_da_uf(uf, data_final, args.max_paginas)

    if erro and not brutos:
        # Não sobrescreve o arquivo: melhor o painel mostrar os dados de ontem
        # do que uma lista vazia que parece "não há nenhuma dispensa".
        log(f"ERRO: nenhum dado obtido ({erro}). {args.saida} NÃO foi alterado.")
        sys.exit(1)

    # A ordem da paginação pode mudar entre uma página e outra (itens novos
    # entrando), então removemos duplicatas pelo número de controle.
    vistos = set()
    todas = []
    for item in brutos:
        norm = normalizar_item(item)
        chave = norm["numero_controle_pncp"]
        if chave and chave in vistos:
            continue
        vistos.add(chave)
        todas.append(norm)

    if args.cidade:
        todas = [d for d in todas if d["cidade"] == args.cidade]

    todas.sort(key=lambda x: x["data_encerramento_proposta"] or "9999")

    saida = {
        "gerado_em": datetime.now(timezone(timedelta(hours=-3))).isoformat(),
        "fonte": "API pública oficial do PNCP (https://pncp.gov.br/api/consulta/v1)",
        "modalidade_filtrada": "Dispensa de Licitação (código 8)",
        "uf_consultada": uf,
        "busca_incompleta": bool(erro),
        "erro_na_busca": erro,
        "categorias": {k: v["rotulo"] for k, v in CATEGORIAS.items()},
        "total_cidades": len({d["cidade"] for d in todas}),
        "total_oportunidades": len(todas),
        "oportunidades": todas,
    }

    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    por_cat = {k: sum(k in d["categorias"] for d in todas) for k in CATEGORIAS}
    log(f"Concluído: {len(todas)} oportunidade(s) em {saida['total_cidades']} cidade(s) salva(s) em {args.saida}")
    log(f"Relevantes por categoria: {por_cat}")
    if erro:
        log(f"AVISO: busca incompleta — {erro}")


if __name__ == "__main__":
    main()
