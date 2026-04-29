import logging
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import html
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.sales")

def setup_sales_handlers(dp: Dispatcher, pipeline: SeekerPipeline):
    @dp.message(F.text.startswith("/crm"))
    async def cmd_crm(message: Message):

        args = message.text.split(maxsplit=2)
        filtro = None
        valor = None
        
        # Parse smart arguments
        if len(args) >= 3:
            filtro = args[1].lower()
            valor = args[2]
        elif len(args) == 2:
            arg = args[1].lower()
            if arg.isdigit():
                filtro = "ultimos"
                valor = int(arg)
            elif arg in ["janeiro", "fevereiro", "marco", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]:
                filtro = "mes"
                valor = arg
            elif arg in ["agro", "fest", "junino", "relig", "corp", "cerim", "show", "gov", "particular", "outro"]:
                filtro = "tipo"
                valor = arg
            else:
                filtro = "cidade"
                valor = arg
                
        if filtro:
            from src.skills.seeker_sales.crm_store import CRMStore
            from src.skills.seeker_sales.crm_pdf import generate_crm_report_pdf
            from aiogram.types import FSInputFile
            import os
            
            crm = CRMStore(pipeline.memory._db)
            leads = []
            title = ""
            
            if filtro == "ultimos":
                limit = valor if isinstance(valor, int) else 15
                leads = await crm.get_recent(limit)
                title = f"Últimos {limit} Leads"
            elif filtro == "cidade":
                leads = await crm.search_by_city(str(valor))
                title = f"Eventos na Cidade: {valor}"
            elif filtro == "mes" or filtro == "mês":
                leads = await crm.search_by_month(str(valor))
                title = f"Eventos no Mês: {valor}"
            elif filtro == "tipo":
                leads = await crm.search_by_type(str(valor).upper())
                title = f"Categoria: {str(valor).upper()}"
            
            if not leads:
                await message.answer(f"📭 Nenhum lead encontrado para {filtro}: '{valor}'.")
                return
                
            await message.answer(f"🔎 Encontrados {len(leads)} leads. Gerando relatório PDF...")
            try:
                pdf_path = generate_crm_report_pdf(title, leads)
                doc = FSInputFile(pdf_path)
                await message.answer_document(doc, caption=f"📊 Relatório: {title}")
            except Exception as e:
                log.error(f"[crm] Erro ao gerar PDF: {e}")
                await message.answer("❌ Erro ao gerar o relatório PDF.")
            return

        # Menu Principal (sem parâmetros)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        buttons = [
            [InlineKeyboardButton(text="📊 Gerar Relatório: Últimos 15 Leads", callback_data="crm_ultimos")],
            [InlineKeyboardButton(text="📅 Buscar por Mês", callback_data="crm_help_mes"),
             InlineKeyboardButton(text="🏙️ Buscar por Cidade", callback_data="crm_help_cidade")],
            [InlineKeyboardButton(text="🎪 Buscar por Tipo (AGRO, FEST, SHOW...)", callback_data="crm_help_tipo")],
            [InlineKeyboardButton(text="📈 Dashboard Estratégico", callback_data="crm_dashboard")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(
            "💼 <b>CRM Interativo — Revenue Hunter</b>\n\n"
            "Selecione uma opção abaixo ou use os comandos rápidos:\n"
            "• <code>/crm cidade [nome]</code>\n"
            "• <code>/crm mes [nome do mes]</code>\n"
            "• <code>/crm tipo [AGRO|FEST|JUNINO|CERIM|CORP|SHOW]</code>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    @dp.callback_query(lambda c: c.data and c.data.startswith('crm_'))
    async def process_crm_callback(callback_query: CallbackQuery):
            
        action = callback_query.data
        await callback_query.answer()
        
        if action == "crm_help_mes":
            await callback_query.message.answer("📅 Para buscar por mês, digite:\n<code>/crm mes agosto</code>", parse_mode=ParseMode.HTML)
            return
        elif action == "crm_help_cidade":
            await callback_query.message.answer("🏙️ Para buscar por cidade, digite:\n<code>/crm cidade goiania</code>", parse_mode=ParseMode.HTML)
            return
        elif action == "crm_help_tipo":
            await callback_query.message.answer("🎪 Para buscar por tipo, digite:\n<code>/crm tipo AGRO</code>\n\nTipos válidos: AGRO, FEST, JUNINO, RELIG, CORP, CERIM, SHOW, GOV, PARTICULAR, OUTRO", parse_mode=ParseMode.HTML)
            return
            
        try:
            from src.skills.seeker_sales.crm_store import CRMStore
            from src.skills.seeker_sales.crm_pdf import generate_crm_report_pdf
            from aiogram.types import FSInputFile
            
            crm = CRMStore(pipeline.memory._db)
            await crm.init_tables()
            
            if action == "crm_ultimos":
                leads = await crm.get_recent(15)
                if not leads:
                    await callback_query.message.answer("📭 CRM vazio. O Revenue Hunter ainda não minerou leads.")
                    return
                await callback_query.message.answer("⏳ Gerando relatório dos últimos 15 leads...")
                pdf_path = generate_crm_report_pdf("Últimos 15 Leads Minerados", leads)
                doc = FSInputFile(pdf_path)
                await callback_query.message.answer_document(doc, caption="📊 Relatório dos últimos leads")
                
            elif action == "crm_dashboard":
                stats = await crm.get_stats()
                
                top_cities = "\n".join([f"  • {c[0]}: {c[1]} leads" for c in stats.get('top_cities', [])])
                types = "\n".join([f"  • {c[0]}: {c[1]}" for c in stats.get('types', [])])
                
                dash = (
                    "📈 <b>Dashboard Estratégico CRM</b>\n\n"
                    f"💰 <b>Pipeline de Receita (Estimada):</b> {stats.get('pipeline_value', 'N/A')}\n\n"
                    f"🔥 <b>Leads Esfriando (>14 dias):</b> {stats.get('decaying_count', 0)} leads\n\n"
                    f"🏙️ <b>Top 5 Cidades (Densidade):</b>\n{top_cities}\n\n"
                    f"🎪 <b>Distribuição por Tipo:</b>\n{types}\n"
                )
                await callback_query.message.answer(dash, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"[crm] Erro no callback CRM '{action}': {e}", exc_info=True)
            await callback_query.message.answer(f"❌ Erro ao processar CRM: {e}")

    @dp.message(F.text.startswith("/scout"))
    async def cmd_scout(message: Message):

        await message.answer("🎯 Disparando campanha Scout B2B...", parse_mode=ParseMode.HTML)

        try:
            # Tenta obter Scout skill do pipeline
            scout_goal = None
            if hasattr(pipeline, '_goals'):
                for goal in pipeline._goals:
                    if hasattr(goal, 'name') and goal.name == 'seeker_sales':
                        scout_goal = goal
                        break

            if not scout_goal:
                await message.answer(
                    "❌ Scout skill não foi encontrada ou não está ativa.\n"
                    "Execute `/saude` para verificar o status dos goals.",
                    parse_mode=ParseMode.HTML
                )
                return

            # Dispara um ciclo da Scout
            result = await scout_goal.run_cycle()

            # Formata resposta
            summary = result.summary or "Campanha concluída"
            cost = f"💰 Custo: ${result.cost_usd:.4f}" if result.cost_usd > 0 else ""

            response_lines = [
                "✅ <b>Scout Campaign Executada</b>\n",
                f"📋 {summary}",
            ]

            if result.data:
                data = result.data
                if data.get('campaign_id'):
                    response_lines.append(f"🆔 Campaign ID: <code>{data['campaign_id'][:12]}</code>")
                if data.get('total_scraped'):
                    response_lines.append(f"📊 Leads Raspados: {data['total_scraped']}")
                if data.get('qualified'):
                    response_lines.append(f"✅ Qualificados: {data['qualified']}")
                if data.get('written'):
                    response_lines.append(f"📝 Com Copy: {data['written']}")
                if data.get('rejected'):
                    response_lines.append(f"❌ Rejeitados: {data['rejected']}")

            if cost:
                response_lines.append(cost)

            final_response = "\n".join(response_lines)
            await message.answer(final_response, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[scout] Scout skill não está configurado corretamente: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Scout skill não está disponível.\nExecute `/saude` para verificar.",
                parse_mode=ParseMode.HTML
            )
        except KeyError as e:
            log.error(
                f"[scout] Dados de campanha incompletos: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": "KeyError"}
            )
            await message.answer(
                "❌ Erro: Dados da campanha incompletos. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[scout] Scout campaign timeout (>120s)")
            await message.answer(
                "⏱️ Timeout: Scout campaign demorou muito. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except (RuntimeError, ValueError) as e:
            log.error(
                f"[scout] Erro de execução da campanha: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                f"❌ Erro ao executar Scout: {str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[scout] Erro inesperado em scout campaign: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Scout campaign falhou de forma inesperada",
                parse_mode=ParseMode.HTML
            )
