#!/usr/bin/env python3
"""
Testes de validação para Sprint 10.1 - Contabilidade de Custos
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))


def test_1_imports():
    """Teste 1: Verificar imports dos módulos"""
    print("\n=== Teste 1: Imports dos Módulos ===")
    try:
        from src.core.budget import (
            CustoMetrica, CustoAgregado, EstatisticasProveedor,
            RastreadorCustos, AlertaCusto
        )
        print("[PASS] Todos os módulos importados com sucesso")
        print(f"  - CustoMetrica: {CustoMetrica.__name__}")
        print(f"  - RastreadorCustos: {RastreadorCustos.__name__}")
        print(f"  - AlertaCusto: {AlertaCusto.__name__}")
        return True
    except Exception as e:
        print(f"[FAIL] Erro no import: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_2_custo_metrica():
    """Teste 2: Criação e serialização de CustoMetrica"""
    print("\n=== Teste 2: CustoMetrica ===")
    try:
        from src.core.budget import CustoMetrica

        metrica = CustoMetrica(
            timestamp=datetime.utcnow(),
            provider="openai",
            modelo="gpt-4",
            fase="Deliberate",
            tokens_entrada=100,
            tokens_saida=250,
            custo_usd=0.0075,
            tempo_latencia_ms=1500,
            sucesso=True,
        )

        print("[PASS] CustoMetrica criada com sucesso")
        print(f"  - Provider: {metrica.provider}")
        print(f"  - Modelo: {metrica.modelo}")
        print(f"  - Custo: ${metrica.custo_usd:.4f}")
        print(f"  - Tokens: {metrica.tokens_entrada}+{metrica.tokens_saida}")

        # Testar serialização
        dados = metrica.para_dict()
        assert "custo_usd" in dados
        print("[PASS] Serialização para dict funcionando")

        return True
    except Exception as e:
        print(f"[FAIL] Teste CustoMetrica falhou: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_3_rastreador_custos():
    """Teste 3: Rastreador de custos básico"""
    print("\n=== Teste 3: RastreadorCustos ===")
    try:
        from src.core.budget import RastreadorCustos

        rastreador = RastreadorCustos(
            limite_diario_usd=10.0,
            limite_mensal_usd=200.0,
        )

        print("[PASS] RastreadorCustos inicializado")
        print(f"  - Limite diário: ${rastreador.limite_diario_usd}")
        print(f"  - Limite mensal: ${rastreador.limite_mensal_usd}")

        # Registrar alguns custos
        for i in range(5):
            alerta = rastreador.registrar_custo(
                provider="openai",
                modelo="gpt-4",
                fase="Deliberate",
                tokens_entrada=100,
                tokens_saida=250,
                custo_usd=0.005 * (i + 1),
                tempo_latencia_ms=1000 + i*100,
                sucesso=True,
            )
            print(f"  - Custo {i+1} registrado: ${0.005 * (i + 1):.4f}")

        print("[PASS] Custos registrados com sucesso")
        return True
    except Exception as e:
        print(f"[FAIL] Teste RastreadorCustos falhou: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_4_agregacao_custos():
    """Teste 4: Agregação de custos por provider/modelo"""
    print("\n=== Teste 4: Agregacao de Custos ===")
    try:
        from src.core.budget import RastreadorCustos

        rastreador = RastreadorCustos()

        # Registrar custos de múltiplos provedores
        provedores = [
            ("openai", "gpt-4", 0.015),
            ("openai", "gpt-3.5", 0.002),
            ("groq", "mixtral", 0.001),
        ]

        for provider, modelo, custo in provedores:
            for i in range(3):
                rastreador.registrar_custo(
                    provider=provider,
                    modelo=modelo,
                    fase="Reflex",
                    tokens_entrada=50,
                    tokens_saida=100,
                    custo_usd=custo,
                    sucesso=True,
                )

        # Verificar agregados
        stats_openai = rastreador.obter_estatisticas_provedor("openai")
        assert stats_openai is not None
        assert stats_openai["total_chamadas"] == 6

        print("[PASS] Agregacao funcionando corretamente")
        print(f"  - OpenAI: {stats_openai['total_chamadas']} chamadas")
        print(f"  - Custo total OpenAI: ${stats_openai['total_custo_usd']:.4f}")
        print(f"  - Taxa de sucesso: {stats_openai['taxa_sucesso']:.1f}%")

        return True
    except Exception as e:
        print(f"[FAIL] Teste de agregacao falhou: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_5_alertas_limite():
    """Teste 5: Detecção de limite diário"""
    print("\n=== Teste 5: Alertas de Limite ===")
    try:
        from src.core.budget import RastreadorCustos

        rastreador = RastreadorCustos(limite_diario_usd=0.10)

        print(f"  - Limite diário: ${rastreador.limite_diario_usd}")

        # Registrar custos até exceder limite
        alerta = None
        for i in range(15):
            alerta = rastreador.registrar_custo(
                provider="openai",
                modelo="gpt-4",
                fase="Deep",
                tokens_entrada=100,
                tokens_saida=500,
                custo_usd=0.01,
                sucesso=True,
            )
            if alerta:
                print(f"  - Alerta disparado na chamada {i+1}: {alerta.mensagem}")
                break

        assert alerta is not None, "Alerta deveria ter sido disparado"
        assert alerta.tipo_alerta == "diario"
        print("[PASS] Alerta de limite diário funcionando")

        # Verificar resumo diário
        resumo = rastreador.obter_resumo_diario()
        print(f"  - Custo hoje: ${resumo['custo_total']:.4f}")
        print(f"  - Porcentagem do limite: {resumo['porcentagem_limite']:.0f}%")

        return True
    except Exception as e:
        print(f"[FAIL] Teste de alertas falhou: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_6_relatorio_formatado():
    """Teste 6: Formatação de relatório para Telegram"""
    print("\n=== Teste 6: Relatorio Formatado ===")
    try:
        from src.core.budget import RastreadorCustos

        rastreador = RastreadorCustos()

        # Registrar alguns custos
        for i in range(5):
            rastreador.registrar_custo(
                provider="openai",
                modelo="gpt-4",
                fase="Deliberate",
                tokens_entrada=100,
                tokens_saida=250,
                custo_usd=0.008,
                sucesso=True,
            )

        # Gerar relatório
        relatorio = rastreador.formatar_relatorio_custos()

        assert "<b>" in relatorio, "Relatório deveria ter formatação HTML"
        assert "GASTOS" in relatorio
        assert "$" in relatorio

        print("[PASS] Relatorio formatado com sucesso")
        print(f"  - Tamanho do relatorio: {len(relatorio)} caracteres")

        # Verificar conteúdo sem emojis
        assert "GASTOS" in relatorio
        assert "openai" in relatorio.lower() or "provedor" in relatorio.lower()
        print("  - Relatorio contém informações de custos")

        return True
    except Exception as e:
        print(f"[FAIL] Teste de relatorio falhou: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Executa todos os testes"""
    print("\n" + "="*70)
    print("VALIDACAO - SPRINT 10.1: CONTABILIDADE DE CUSTOS")
    print("="*70)

    testes = [
        ("Imports", test_1_imports),
        ("CustoMetrica", test_2_custo_metrica),
        ("RastreadorCustos", test_3_rastreador_custos),
        ("Agregacao", test_4_agregacao_custos),
        ("Alertas", test_5_alertas_limite),
        ("Relatorio", test_6_relatorio_formatado),
    ]

    resultados = []
    for nome, teste_func in testes:
        try:
            passou = teste_func()
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
        print("\n[SUCCESS] SPRINT 10.1 - Contabilidade de Custos VALIDADA!")
        return 0
    else:
        print(f"\n[FAIL] {total - passou} teste(s) falharam")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
