# Revenue Hunter module

"""
Registro central de capabilities das skills.

Cada skill pode auto-registrar suas capabilities chamando
`get_capability_graph().register(...)` na importação. Isso permite ao bot
planejar cadeias de ações (ex: busca → análise → exportação).
"""

from src.core.capability_graph import get_capability_graph

_graph = get_capability_graph()

_graph.register("email_monitor", ["monitor_email", "extract_leads"])
_graph.register("web_search", ["search_web"])
_graph.register("custom_extension", ["scan_events", "rank_opportunities"])
_graph.register("sherlock_news", ["news_digest", "trend_alert"])
_graph.register("briefing", ["generate_briefing"], dependencies=["search_web", "news_digest"])
_graph.register("tts", ["text_to_speech"])
_graph.register("image_gen", ["generate_image"])
_graph.register("instascraper", ["scrape_instagram"])
_graph.register("osv_check", ["check_vulnerabilities"], dependencies=["search_web"])
_graph.register("kanban", ["create_task", "move_task"])
_graph.register("drive_manager", ["upload_file", "list_files"])
_graph.register("subagent_dispatcher", ["dispatch_subagent"])
_graph.register("skill_creator", ["create_skill"])
_graph.register("bug_analyzer", ["analyze_bug"])
_graph.register("scheduler_conversacional", ["schedule_event"])
_graph.register("ruflo_swarm", ["dispatch_swarm", "tune_bandit"], dependencies=["web_search", "dispatch_subagent"])
_graph.register("research_machine", ["research_query", "synthesize_videos"], dependencies=["web_search"])
