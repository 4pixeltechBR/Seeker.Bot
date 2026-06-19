import os
import time
import random
import logging
import sys
from pathlib import Path
import instaloader
import yaml
from datetime import datetime
import http.cookiejar
from curl_cffi import requests as curl_requests

# Força stdout a usar UTF-8 no Windows para evitar UnicodeEncodeError de emojis
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

log = logging.getLogger("seeker.skills.instascraper")

# Configurações do Obsidian
DEFAULT_VAULT_PATH = r"D:\Obsidian\Segundo Cérebro\Segundo Cérebro"
DEFAULT_INBOX_PATH = os.path.join(DEFAULT_VAULT_PATH, "Inbox")


class InstaScraper:
    """
    Skill modular para extração de mídias e metadados do Instagram.
    Implementa delay randômico para mitigar shadowban e gera notas formatadas para o Obsidian.
    """

    def __init__(
        self,
        base_path: str = "E:/Seeker.Bot/Downloads/Instagram/",
        inbox_path: str = DEFAULT_INBOX_PATH,
    ):
        self.base_path = Path(base_path)
        self.inbox_path = Path(inbox_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.inbox_path.mkdir(parents=True, exist_ok=True)

        # Configura o Instaloader com restrições solicitadas
        self.loader = instaloader.Instaloader(
            download_pictures=False,            # Desabilita fotos normais (baixa apenas posts de vídeo)
            download_videos=True,               # Foco em vídeos
            download_video_thumbnails=False,   # Poupar disco
            download_geotags=False,
            download_comments=False,           # Evita chamadas extras que disparam ban
            save_metadata=True,                # Salva metadados brutos (JSON)
            compress_json=False
        )

        # Carrega cookies do all_cookies.txt
        self.cookie_file = "E:/Seeker.Bot/docs/all_cookies.txt"
        self.cookies_dict = {}
        self.csrf_token = None
        self._load_cookies()

        # Tenta carregar usuário padrão do .env para autenticação
        self.instagram_user = os.getenv("INSTAGRAM_USER")
        if self.instagram_user:
            self.autenticar(self.instagram_user)

    def _load_cookies(self):
        """Carrega os cookies do arquivo all_cookies.txt para a sessão do Instaloader e curl_cffi."""
        if not os.path.exists(self.cookie_file):
            log.warning(f"[instascraper] Arquivo de cookies não encontrado em {self.cookie_file}")
            return

        cookie_jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
        try:
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            self.loader.context._session.cookies.update(cookie_jar)
            
            for cookie in cookie_jar:
                if "instagram.com" in cookie.domain or cookie.domain == "":
                    self.cookies_dict[cookie.name] = cookie.value
                    if cookie.name == "csrftoken":
                        self.csrf_token = cookie.value
            
            if self.csrf_token:
                self.loader.context._session.headers["X-CSRFToken"] = self.csrf_token
                
            log.info(f"[instascraper] Cookies do Instagram carregados de {self.cookie_file}")
        except Exception as e:
            log.error(f"[instascraper] Erro ao carregar cookies do arquivo {self.cookie_file}: {e}")

    def autenticar(self, username: str):
        """
        Carrega sessão salva para evitar requisições anônimas bloqueadas.
        Se não encontrar, tenta login interativo.
        """
        try:
            self.loader.load_session_from_file(username)
            log.info(f"[instascraper] Sessão de {username} carregada.")
            return True, f"Sessão de {username} carregada com sucesso."
        except FileNotFoundError:
            log.warning(f"[instascraper] Sessão de {username} não encontrada.")
            return False, "Sessão não encontrada. Requer login interativo."
        except Exception as e:
            log.error(f"[instascraper] Erro ao autenticar: {e}")
            return False, f"Falha na autenticação: {e}"

    def raspar_perfil(self, target_profile: str, limit_posts: int = 50) -> str:
        """
        Clona posts de vídeo e metadados de um perfil do Instagram de forma assíncrona/loop.
        Gera as notas formatadas diretamente para a pasta Inbox do Obsidian.
        """
        try:
            target_profile = target_profile.lstrip("@").strip()
            target_dir = self.base_path / target_profile
            target_dir.mkdir(parents=True, exist_ok=True)

            log.info(f"[instascraper] Carregando perfil: {target_profile}")

            # Configura cabeçalhos idênticos aos do browser para curl_cffi
            headers = {
                "Accept": "*/*",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": f"https://www.instagram.com/{target_profile}/",
                "X-IG-App-ID": "936619743392459",
                "X-ASBD-ID": "198387",
                "X-Requested-With": "XMLHttpRequest",
            }
            if self.csrf_token:
                headers["X-CSRFToken"] = self.csrf_token

            # Executa a requisição para obter o feed de posts do usuário via curl_cffi para contornar WAF
            url = f"https://www.instagram.com/api/v1/feed/user/{target_profile}/username/?count={limit_posts}"
            log.info(f"[instascraper] Buscando feed via API: {url}")
            
            resp = curl_requests.get(
                url,
                headers=headers,
                cookies=self.cookies_dict,
                impersonate="chrome120",
                timeout=15
            )

            log.info(f"[instascraper] Resposta da API de Feed: Status {resp.status_code}")
            if resp.status_code == 404:
                log.error(f"[instascraper] Perfil não encontrado: {target_profile}")
                return f"Erro: O perfil '{target_profile}' não foi encontrado no Instagram."
            elif resp.status_code != 200:
                log.error(f"[instascraper] Falha ao obter feed (Status {resp.status_code}): {resp.text[:500]}")
                return f"Erro: Falha ao carregar o feed do perfil '{target_profile}' (Status {resp.status_code})."

            data = resp.json()
            items = data.get("items", [])
            log.info(f"[instascraper] Encontrados {len(items)} posts no feed.")

            if not items:
                return f"Erro: Nenhum post retornado para o perfil '{target_profile}'. Verifique se ele é privado ou se a conta está ativa."

            count = 0
            original_cwd = os.getcwd()

            # Itera pelos posts do perfil
            for item in items:
                if count >= limit_posts:
                    break

                try:
                    post = instaloader.Post.from_iphone_struct(self.loader.context, item)
                except Exception as parse_err:
                    log.error(f"[instascraper] Erro ao analisar item do feed: {parse_err}")
                    continue

                if post.is_video:
                    log.info(f"[instascraper] Baixando post de vídeo {post.shortcode}...")
                    
                    # Salva a CWD original e altera para self.base_path antes de chamar download_post
                    # para evitar problemas de higienização de caminhos absolutos do Instaloader
                    try:
                        os.chdir(self.base_path)
                        self.loader.download_post(post, target=target_profile)
                    finally:
                        os.chdir(original_cwd)

                    # Tenta converter os metadados brutos do post em nota do Obsidian
                    try:
                        self._create_obsidian_note(post, target_dir)
                    except Exception as parse_err:
                        log.error(f"[instascraper] Erro ao gerar nota Obsidian para {post.shortcode}: {parse_err}")

                    count += 1

                    # Protocolo Anti-Ban: Sleep randômico entre 10 e 15 segundos
                    sleep_time = random.uniform(10, 15)
                    log.info(f"[instascraper] Aguardando {sleep_time:.2f}s (Anti-Ban)...")
                    time.sleep(sleep_time)

            return f"Sucesso: Perfil {target_profile} clonado. {count} vídeos processados em {target_dir}."

        except instaloader.exceptions.ProfileNotExistsException:
            log.error(f"[instascraper] Perfil não encontrado: {target_profile}")
            return f"Erro: O perfil '{target_profile}' não foi encontrado no Instagram."
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            log.error(f"[instascraper] Perfil privado: {target_profile}")
            return f"Erro: O perfil '{target_profile}' é privado e não temos acesso."
        except Exception as e:
            log.error(f"[instascraper] Erro crítico na raspagem: {e}", exc_info=True)
            return f"Erro crítico na extração do perfil {target_profile}: {e}"

    def download_single_post(self, post_url_or_shortcode: str) -> Path | None:
        """
        Baixa um post individual (vídeo) a partir de uma URL ou shortcode do Instagram.
        Retorna o caminho absoluto do arquivo .mp4 baixado (ou None).
        """
        import re
        m = re.search(r"/(?:p|reel|tv)/([a-zA-Z0-9_-]+)", post_url_or_shortcode)
        if m:
            shortcode = m.group(1)
        else:
            # Pega o shortcode limpo caso o usuário envie direto
            shortcode = post_url_or_shortcode.strip().split("/")[0]
            
        log.info(f"[instascraper] Buscando post unitário para shortcode: {shortcode}")
        
        try:
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            if not post.is_video:
                log.warning(f"[instascraper] Post {shortcode} não é um vídeo.")
                return None
                
            target_dir = self.base_path / "single_posts"
            target_dir.mkdir(parents=True, exist_ok=True)
            
            original_cwd = os.getcwd()
            try:
                os.chdir(self.base_path)
                self.loader.download_post(post, target="single_posts")
            finally:
                os.chdir(original_cwd)
                
            for f in target_dir.glob(f"*{shortcode}*.mp4"):
                return f.resolve()
                
        except Exception as e:
            log.error(f"[instascraper] Falha ao baixar post {shortcode}: {e}", exc_info=True)
            
        return None

    def _create_obsidian_note(self, post: instaloader.Post, target_dir: Path):
        """
        Gera uma nota Markdown estruturada na Inbox do Obsidian referenciando a mídia local.
        """
        # Extrai hashtags
        hashtags = list(post.caption_hashtags) if post.caption_hashtags else []
        
        # Define os metadados do YAML frontmatter
        metadata = {
            "date": post.date_local.strftime("%Y-%m-%d"),
            "owner": post.owner_username,
            "url": f"https://instagram.com/p/{post.shortcode}/",
            "tags": hashtags + ["instagram", "video_scraping"],
            "type": "social_intel",
            "typename": post.typename,
            "shortcode": post.shortcode,
            "captured_by": "seeker_instascraper"
        }

        # Descobre o arquivo de mídia baixado localmente
        # O Instaloader nomeia arquivos com o padrão '{date_utc}_{shortcode}' ou similar
        media_file_name = None
        date_pattern = post.date_utc.strftime("%Y-%m-%d")
        
        # Varre a pasta do perfil procurando o arquivo .mp4 correspondente
        for f in target_dir.glob(f"*{post.shortcode}*.mp4"):
            media_file_name = f.name
            break

        # Se não achar o mp4, tenta jpg (em caso de posts de carrossel ou falha)
        if not media_file_name:
            for f in target_dir.glob(f"*{post.shortcode}*.jpg"):
                media_file_name = f.name
                break

        # Se achar a mídia, cria um link local relativo/absoluto para o Obsidian ler
        if media_file_name:
            media_path = target_dir / media_file_name
            media_display = f"![[file:///{media_path.as_posix()}]]"
        else:
            media_display = f"Mídia local salva em: `{target_dir.as_posix()}`"

        filename = f"{metadata['date']}_{post.shortcode}.md"
        filepath = self.inbox_path / filename

        # Formata o Markdown
        content = f"---\n{yaml.dump(metadata, default_flow_style=False, allow_unicode=True)}---\n\n"
        content += f"# Post de {post.owner_username} - {post.shortcode}\n\n"
        content += f"## Legenda\n{post.caption or 'Sem legenda.'}\n\n"
        content += f"## Mídia Local\n{media_display}\n\n"
        content += "## Conexões e Análise de 2ª Ordem\n"
        content += "- [ ] Revisar insights para o Obsidian\n"
        content += "- [ ] Conectar ao grafo de conhecimento B2B\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        log.info(f"[instascraper] Nota Obsidian salva em: {filepath}")
        return filepath
