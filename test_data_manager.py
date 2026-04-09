#!/usr/bin/env python3
"""
Testes de validação para Sprint 10.2 - Data Manager
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))


async def test_1_imports():
    """Teste 1: Imports dos módulos"""
    print("\n=== Teste 1: Imports ===")
    try:
        from src.core.data import (
            Fato, ArmazemDados, ResultadoBusca,
            Indexador, ResultadoIndexacao,
            PoliticaRetencao, GerenciadorRetencao
        )
        print("[PASS] Todos os módulos importados")
        return True
    except Exception as e:
        print(f"[FAIL] Import error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_2_armazem_crud():
    """Teste 2: CRUD do armazém"""
    print("\n=== Teste 2: Armazem CRUD ===")
    try:
        from src.core.data import Fato, ArmazemDados

        armazem = ArmazemDados(db_path=":memory:")

        # CREATE
        fato = Fato(
            conteudo="Victor é CTO da Seeker.Bot",
            categoria="pessoas",
            confianca=0.95,
            fonte="observacao",
        )
        fato_id = await armazem.criar(fato)
        assert fato_id > 0
        print(f"[PASS] Fato criado com ID: {fato_id}")

        # READ
        fato_lido = await armazem.obter_por_id(fato_id)
        assert fato_lido is not None
        assert fato_lido.conteudo == "Victor é CTO da Seeker.Bot"
        print(f"[PASS] Fato lido: {fato_lido.conteudo}")

        # UPDATE
        fato_lido.confianca = 0.98
        await armazem.atualizar(fato_lido)
        fato_atualizado = await armazem.obter_por_id(fato_id)
        assert fato_atualizado.confianca == 0.98
        print("[PASS] Fato atualizado")

        # DELETE
        await armazem.deletar(fato_id)
        fato_deletado = await armazem.obter_por_id(fato_id)
        assert fato_deletado is None
        print("[PASS] Fato deletado")

        return True
    except Exception as e:
        print(f"[FAIL] CRUD test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_3_busca_categoria():
    """Teste 3: Busca por categoria"""
    print("\n=== Teste 3: Busca por Categoria ===")
    try:
        from src.core.data import Fato, ArmazemDados

        armazem = ArmazemDados(db_path=":memory:")

        # Criar fatos de diferentes categorias
        for i in range(5):
            fato = Fato(
                conteudo=f"Fato sobre tecnologia {i}",
                categoria="tecnologia",
                confianca=0.8 + i*0.01,
            )
            await armazem.criar(fato)

        for i in range(3):
            fato = Fato(
                conteudo=f"Fato sobre pessoas {i}",
                categoria="pessoas",
                confianca=0.7,
            )
            await armazem.criar(fato)

        # Buscar por categoria
        fatos_tech = await armazem.obter_por_categoria("tecnologia")
        assert len(fatos_tech) == 5
        print(f"[PASS] Encontrados {len(fatos_tech)} fatos de tecnologia")

        fatos_pessoas = await armazem.obter_por_categoria("pessoas")
        assert len(fatos_pessoas) == 3
        print(f"[PASS] Encontrados {len(fatos_pessoas)} fatos de pessoas")

        return True
    except Exception as e:
        print(f"[FAIL] Categoria search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_4_busca_texto():
    """Teste 4: Busca full-text"""
    print("\n=== Teste 4: Busca Full-Text ===")
    try:
        from src.core.data import Fato, ArmazemDados

        armazem = ArmazemDados(db_path=":memory:")

        # Criar fatos
        await armazem.criar(Fato(
            conteudo="Python é uma linguagem de programação poderosa",
            categoria="tech",
            confianca=0.9,
        ))
        await armazem.criar(Fato(
            conteudo="JavaScript roda no navegador",
            categoria="tech",
            confianca=0.85,
        ))

        # Buscar
        resultado = await armazem.buscar_texto("Python")
        assert len(resultado.fatos) > 0
        print(f"[PASS] Busca encontrou {len(resultado.fatos)} resultado(s)")
        print(f"  - Tempo: {resultado.tempo_busca_ms:.2f}ms")

        return True
    except Exception as e:
        print(f"[FAIL] Full-text search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_5_indexacao():
    """Teste 5: Indexação e busca indexada"""
    print("\n=== Teste 5: Indexacao ===")
    try:
        from src.core.data import Fato, ArmazemDados, Indexador

        armazem = ArmazemDados(db_path=":memory:")
        indexador = Indexador(armazem)

        # Criar fatos
        for i in range(10):
            await armazem.criar(Fato(
                conteudo=f"Dado importante sobre sistemas {i}",
                categoria="sistemas" if i % 2 == 0 else "dados",
                confianca=0.7 + i*0.02,
            ))

        # Reindexar
        await indexador.reindexar()
        print("[PASS] Reindexacao completa")

        # Buscar por categoria indexada
        resultado = await indexador.buscar_por_categoria("sistemas")
        assert len(resultado.fatos) > 0
        print(f"[PASS] Busca indexada: {len(resultado.fatos)} resultados em {resultado.tempo_busca_ms:.2f}ms")

        # Buscar por palavras
        resultado_palavras = await indexador.buscar_por_palavras("sistemas dados")
        print(f"[PASS] Busca por palavras: {len(resultado_palavras.fatos)} resultados")

        # Estatísticas
        stats = await indexador.obter_estatisticas_indice()
        print(f"[PASS] Índices: {stats['palavras_indexadas']} palavras, {stats['categorias_indexadas']} categorias")

        return True
    except Exception as e:
        print(f"[FAIL] Indexation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_6_retencao():
    """Teste 6: Política de retenção"""
    print("\n=== Teste 6: Retencao ===")
    try:
        from src.core.data import Fato, ArmazemDados, GerenciadorRetencao, PoliticaRetencao

        armazem = ArmazemDados(db_path=":memory:")
        politica = PoliticaRetencao(
            dias_retencao_maximo=30,
            confianca_minima_permanente=0.5,
        )
        gerenciador = GerenciadorRetencao(armazem, politica)

        # Criar fatos antigos e recentes
        agora = datetime.utcnow()

        # Fato recente (será mantido)
        fato_recente = Fato(
            conteudo="Fato recente",
            categoria="teste",
            confianca=0.3,
        )
        await armazem.criar(fato_recente)

        # Simulação de limpeza
        resultado = await gerenciador.limpar_dados(simular=True)
        print(f"[PASS] Simulacao: {resultado['total_deletados']} fatos seriam deletados")

        # Análise de dados
        analise = await gerenciador.analisar_dados_para_limpeza()
        print(f"[PASS] Analise: {analise['total_fatos']} fatos, {analise['fatos_para_deletar']} para deletar")

        return True
    except Exception as e:
        print(f"[FAIL] Retention test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Executa todos os testes"""
    print("\n" + "="*70)
    print("VALIDACAO - SPRINT 10.2: DATA MANAGER")
    print("="*70)

    testes = [
        ("Imports", test_1_imports),
        ("Armazem CRUD", test_2_armazem_crud),
        ("Busca Categoria", test_3_busca_categoria),
        ("Busca Texto", test_4_busca_texto),
        ("Indexacao", test_5_indexacao),
        ("Retencao", test_6_retencao),
    ]

    resultados = []
    for nome, teste_func in testes:
        try:
            passou = await teste_func()
            resultados.append((nome, passou))
        except Exception as e:
            print(f"\n[ERRO CRITICO] em {nome}: {e}")
            import traceback
            traceback.print_exc()
            resultados.append((nome, False))

    # Resumo
    print("\n" + "="*70)
    print("RESUMO DOS TESTES")
    print("="*70)

    passou = sum(1 for _, p in resultados if p)
    total = len(resultados)

    for nome, passou_bool in resultados:
        status = "[PASS]" if passou_bool else "[FAIL]"
        print(f"{status}: {nome}")

    print(f"\nTotal: {passou}/{total} testes passaram")

    if passou == total:
        print("\n[SUCCESS] SPRINT 10.2 - Data Manager VALIDADO!")
        return 0
    else:
        print(f"\n[FAIL] {total - passou} teste(s) falharam")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
