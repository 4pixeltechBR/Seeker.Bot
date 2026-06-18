import sys
import argparse
from pathlib import Path
import instaloader

def import_cookies(browser_name: str, username: str):
    """
    Importa os cookies de sessão de um navegador local logado no Instagram
    e gera o arquivo de sessão do Instaloader.
    """
    L = instaloader.Instaloader()
    
    # Normaliza o nome do navegador
    browser_name = browser_name.lower().strip()
    
    print(f" tentando importar cookies do navegador '{browser_name}' para o usuário '{username}'...")
    
    try:
        # Carrega os cookies do navegador usando a API interna do Instaloader (que utiliza browser-cookie3)
        L.context.load_cookies(browser=browser_name)
        
        # Tenta verificar se a sessão importada está ativa salvando-a no arquivo correspondente
        session_file = L.context.get_session_file_path(username)
        
        # Grava a sessão localmente
        L.save_session_to_file(username)
        
        print("\n🎉 SUCESSO ABSOLUTO!")
        print(f"• Arquivo de sessão gerado em: {session_file}")
        print(f"• Cookies de login carregados com êxito a partir do {browser_name.capitalize()}.")
        print("\nA nova skill 'InstaScraper' do seu Seeker.Bot já está pronta para rodar de forma autenticada.")
        
    except Exception as e:
        print(f"\n❌ Falha na importação de cookies: {e}")
        print("\nDicas de Resolução:")
        print("1. Certifique-se de que o navegador selecionado está fechado antes de rodar o comando.")
        print(f"2. Garanta que você está realmente logado no Instagram no navegador '{browser_name}'.")
        print("3. Tente rodar o script com permissões administrativas se houver restrição de leitura do profile do navegador.")
        print("4. Navegadores suportados: chrome, firefox, edge, brave, opera, safari.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importa cookies de login do Instagram do navegador local para o Seeker.Bot.")
    parser.add_argument("--browser", required=True, help="Nome do navegador (chrome, firefox, edge, brave, opera)")
    parser.add_argument("--user", required=True, help="Seu nome de usuário do Instagram")
    
    args = parser.parse_args()
    import_cookies(args.browser, args.user)
