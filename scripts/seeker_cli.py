#!/usr/bin/env python3
"""
Seeker.Bot — Unified CLI wrapper for Seeker skills.
Enables execution of modular skills from the command line, facilitating integration with SeekerAgent.
"""

import os
import sys
import argparse
import asyncio
import logging

# Garante que a raiz do Seeker.Bot está no python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Configura logs para stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from src.skills.instascraper.insta_scraper import InstaScraper
from src.skills.kanban.kanban import KanbanBoard
from src.skills.osv_check.osv_check import OSVScanner
from src.skills.microsoft_graph.ms_graph import MSGraphClient


def handle_instascraper(args):
    """Executa a raspagem de perfil do Instagram."""
    print(f"📸 Iniciando InstaScraper para o perfil: @{args.profile} (limite: {args.limit})")
    scraper = InstaScraper()
    # Remove @ opcional do profile
    profile = args.profile.lstrip("@")
    result = scraper.raspar_perfil(profile, limit_posts=args.limit)
    print(result)


def handle_kanban(args):
    """Gerencia o quadro Kanban local."""
    board = KanbanBoard(pipeline=None)
    if args.action == "add":
        print(board.add_task(args.title))
    elif args.action == "move":
        print(board.move_task(args.id, args.column))
    elif args.action == "list":
        print(board.list_tasks())


def handle_osv(args):
    """Executa varredura de vulnerabilidades de dependências."""
    print("🛡️ Iniciando OSV Security Scanner...")
    scanner = OSVScanner(pipeline=None)
    result = asyncio.run(scanner.scan_vulnerabilities())
    print(result)


def handle_msgraph(args):
    """Gerencia ações do Microsoft Graph."""
    if args.action == "send":
        client = MSGraphClient(pipeline=None)
        result = asyncio.run(client.send_email(args.to, args.subject, args.body))
        print(result)


def main():
    parser = argparse.ArgumentParser(
        prog="seeker_cli",
        description="CLI Unificada para execução de skills do Seeker.Bot"
    )
    subparsers = parser.add_subparsers(dest="skill", help="Escolha a skill a ser executada")

    # InstaScraper Parser
    insta_parser = subparsers.add_parser("instascraper", help="Raspagem de perfis do Instagram")
    insta_parser.add_argument("profile", type=str, help="Username do perfil do Instagram")
    insta_parser.add_argument(
        "--limit", "-l", type=int, default=10, help="Limite de posts a serem analisados"
    )

    # Kanban Parser
    kanban_parser = subparsers.add_parser("kanban", help="Gerenciador de tarefas Kanban local")
    kanban_sub = kanban_parser.add_subparsers(dest="action", help="Ação a executar no Kanban")
    
    # Kanban Add
    add_parser = kanban_sub.add_parser("add", help="Adiciona uma nova tarefa no Backlog")
    add_parser.add_argument("title", type=str, help="Título da tarefa")
    
    # Kanban Move
    move_parser = kanban_sub.add_parser("move", help="Move uma tarefa de coluna")
    move_parser.add_argument("id", type=str, help="ID da tarefa (ex: T-1-ABCD)")
    move_parser.add_argument(
        "column", type=str, help="Coluna destino (backlog, todo, in_progress, done)"
    )
    
    # Kanban List
    kanban_sub.add_parser("list", help="Lista as tarefas organizadas por coluna")

    # OSV Check Parser
    subparsers.add_parser("osv_check", help="Auditoria de segurança de dependências (Google OSV)")

    # MS Graph Parser
    graph_parser = subparsers.add_parser("msgraph", help="Integração Microsoft Graph (Outlook)")
    graph_sub = graph_parser.add_subparsers(dest="action", help="Ação a executar no MS Graph")
    
    # MS Graph Send
    send_parser = graph_sub.add_parser("send", help="Envia um e-mail pelo Outlook")
    send_parser.add_argument("--to", type=str, required=True, help="E-mail do destinatário")
    send_parser.add_argument("--subject", type=str, required=True, help="Assunto do e-mail")
    send_parser.add_argument("--body", type=str, required=True, help="Conteúdo/corpo do e-mail")

    args = parser.parse_args()

    if args.skill == "instascraper":
        handle_instascraper(args)
    elif args.skill == "kanban":
        if not args.action:
            kanban_parser.print_help()
            sys.exit(1)
        handle_kanban(args)
    elif args.skill == "osv_check":
        handle_osv(args)
    elif args.skill == "msgraph":
        if not args.action:
            graph_parser.print_help()
            sys.exit(1)
        handle_msgraph(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
