import os
import time
import random
import logging
import sys
import re
import json
import uuid
import shutil
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
        base_path: str = os.getenv("SEEKER_INSTAGRAM_PATH", "Downloads/Instagram/"),
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
        self.loader.dirname_pattern = "{target}"

        # Carrega cookies do all_cookies.txt
        self.cookie_file = os.getenv("SEEKER_INSTAGRAM_COOKIES", "docs/all_cookies.txt")
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
            
            for cookie in cookie_jar:
                domain = cookie.domain or ""
                if domain == "instagram.com" or domain.endswith(".instagram.com") or domain == "":
                    self.loader.context._session.cookies.set_cookie(cookie)
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
            for cookie in self.loader.context._session.cookies:
                self.cookies_dict[cookie.name] = cookie.value
                if cookie.name == "csrftoken":
                    self.csrf_token = cookie.value
            if self.csrf_token:
                self.loader.context._session.headers["X-CSRFToken"] = self.csrf_token
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
        # Validação do formato do username para evitar falhas de criação de diretórios e poluição do disco
        clean_profile = target_profile.lstrip("@").strip()
        invalid_chars = set(r'/:*?"<>|\\')
        if (
            not clean_profile 
            or any(c in invalid_chars for c in clean_profile) 
            or "http://" in clean_profile 
            or "https://" in clean_profile 
            or "www." in clean_profile
        ):
            log.error(f"[instascraper] Perfil inválido: {target_profile}")
            return f"Erro: O nome de usuário '{target_profile}' contém caracteres inválidos ou é uma URL. Use apenas o nome de usuário (ex: '@username')."

        try:
            target_profile = clean_profile
            target_dir = self.base_path / target_profile
            # Não cria o diretório antes de confirmar que o perfil existe

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

            # Só cria o diretório após confirmar que o perfil existe (evita lixo em disco)
            target_dir.mkdir(parents=True, exist_ok=True)

            data = resp.json()
            items = data.get("items", [])
            log.info(f"[instascraper] Encontrados {len(items)} posts no feed.")

            if not items:
                return f"Erro: Nenhum post retornado para o perfil '{target_profile}'. Verifique se ele é privado ou se a conta está ativa."

            count = 0
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
                    try:
                        target_relative = os.path.relpath(target_dir, Path.cwd())
                    except ValueError:
                        target_relative = str(target_dir)
                    self.loader.download_post(post, target=target_relative)

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

    def _download_video_with_curl(self, url: str, dest_path: Path):
        """Download video via curl_cffi com streaming robusto para arquivos grandes."""
        temp_dest = dest_path.with_suffix(".tmp")
        try:
            with open(temp_dest, "wb") as out_file:
                resp = curl_requests.get(
                    url,
                    headers=self.loader.context._session.headers,
                    cookies=self.cookies_dict,
                    impersonate="chrome120",
                    # 120 s para Reels grandes; fallback secundário não deve ser mais restritivo
                    timeout=120,
                    stream=True,
                )
                resp.raise_for_status()
                bytes_written = 0
                for chunk in resp.iter_content():
                    if chunk:
                        out_file.write(chunk)
                        bytes_written += len(chunk)
                        log.debug(f"[instascraper][curl] Progresso: {bytes_written / (1024*1024):.1f} MB")
            if temp_dest.exists():
                if dest_path.exists():
                    dest_path.unlink()
                temp_dest.rename(dest_path)
            log.info(f"[instascraper] Vídeo baixado via curl para {dest_path}")
        except Exception as dl_err:
            log.error(f"[instascraper] Erro ao baixar vídeo via curl: {dl_err}")
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            if dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass

    def download_single_post(self, post_url_or_shortcode: str) -> Path | None:
        """
        Baixa um post individual (vídeo) a partir de uma URL ou shortcode do Instagram.
        Retorna o caminho absoluto do arquivo .mp4 baixado (ou None).
        Usa curl_cffi para contornar bloqueios do WAF da API de GraphQL.
        """
        m = re.search(r"/(?:p|reel|tv)/([a-zA-Z0-9_-]+)", post_url_or_shortcode)
        if m:
            shortcode = m.group(1)
        else:
            shortcode = post_url_or_shortcode.strip().split("/")[0]

        # Validar shortcode para evitar Path Traversal
        if not re.match(r"^[a-zA-Z0-9_-]+$", shortcode):
            log.warning(f"[instascraper] Shortcode inválido detectado (possível Path Traversal): {shortcode}")
            return None
        
        log.info(f"[instascraper] Buscando post unitário para shortcode: {shortcode}")
        
        target_dir = self.base_path / "single_posts"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_file = target_dir / f"single_{shortcode}_{uuid.uuid4().hex}.mp4"
        temp_dest_file = dest_file.with_suffix(".tmp")
        
        # 1. Tenta consulta e download usando curl_cffi + GraphQL
        try:
            log.info(f"[instascraper] Tentando obter metadados via GraphQL (curl_cffi) para: {shortcode}")
            headers = {
                "Accept": "*/*",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.instagram.com/",
                "X-IG-App-ID": "936619743392459",
                "X-ASBD-ID": "198387",
                "X-Requested-With": "XMLHttpRequest",
            }
            if self.csrf_token:
                headers["X-CSRFToken"] = self.csrf_token

            graphql_url = "https://www.instagram.com/graphql/query"
            payload = {
                "doc_id": "8845758582119845",
                "variables": json.dumps({"shortcode": shortcode}, separators=(',', ':')),
                "server_timestamps": "true"
            }

            resp = curl_requests.post(
                graphql_url,
                data=payload,
                headers=headers,
                cookies=self.cookies_dict,
                impersonate="chrome120",
                timeout=30
            )
            
            if resp.status_code == 200:
                resp_json = resp.json()
                media_data = None
                if isinstance(resp_json, dict):
                    data_dict = resp_json.get("data")
                    if data_dict is not None and isinstance(data_dict, dict):
                        if "xdt_shortcode_media" in data_dict:
                            media_data = data_dict["xdt_shortcode_media"]
                        elif "shortcode_media" in data_dict:
                            media_data = data_dict["shortcode_media"]
                
                if media_data:
                    if not media_data.get("is_video", False):
                        log.warning(f"[instascraper] Post {shortcode} não é um vídeo via GraphQL.")
                        return None
                    
                    video_url = media_data.get("video_url")
                    if video_url:
                        log.info(f"[instascraper] Baixando vídeo via curl_cffi de {video_url[:60]}...")
                        try:
                            with open(temp_dest_file, "wb") as out_file:
                                dl_resp = curl_requests.get(
                                    video_url,
                                    headers={
                                        "accept": "*/*",
                                        "referer": "https://www.instagram.com/",
                                    },
                                    cookies=self.cookies_dict,
                                    impersonate="chrome120",
                                    # 120 s para suportar Reels grandes (>50 MB) em conexões lentas
                                    timeout=120,
                                    stream=True,
                                )
                                dl_resp.raise_for_status()
                                bytes_written = 0
                                # curl_cffi não suporta chunk_size; os chunks nativos já são eficientes
                                for chunk in dl_resp.iter_content():
                                    if chunk:
                                        out_file.write(chunk)
                                        bytes_written += len(chunk)
                                        log.debug(f"[instascraper] Progresso: {bytes_written / (1024*1024):.1f} MB baixados")
                            if temp_dest_file.exists():
                                if dest_file.exists():
                                    dest_file.unlink()
                                temp_dest_file.rename(dest_file)
                        except Exception as dl_err:
                            log.error(f"[instascraper] Erro durante o download do stream: {dl_err}")
                            if temp_dest_file.exists():
                                try:
                                    temp_dest_file.unlink()
                                except Exception:
                                    pass
                            raise dl_err
                        
                        if dest_file.exists() and dest_file.stat().st_size > 0:
                            log.info(f"[instascraper] Download bem sucedido via curl_cffi: {dest_file}")
                            return dest_file.resolve()
            
            log.warning(f"[instascraper] GraphQL ou download falhou para {shortcode}, tentando fallback...")
        except Exception as e:
            log.warning(f"[instascraper] Erro durante download com curl_cffi para {shortcode}: {e}. Iniciando fallback...", exc_info=True)
            if temp_dest_file.exists():
                try:
                    temp_dest_file.unlink()
                except Exception:
                    pass
            if dest_file.exists():
                try:
                    dest_file.unlink()
                except Exception:
                    pass
            
        # 2. Fallback de legado usando Instaloader
        log.info(f"[instascraper] Executando fallback via Instaloader para {shortcode}...")
        temp_target_dir = target_dir / f"tmp_{uuid.uuid4().hex}"
        try:
            temp_target_dir.mkdir(parents=True, exist_ok=True)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            if not post.is_video:
                log.warning(f"[instascraper] Post {shortcode} não é um vídeo via Instaloader.")
                return None
                
            try:
                target_relative = os.path.relpath(temp_target_dir, Path.cwd())
            except ValueError:
                target_relative = str(temp_target_dir)
            self.loader.download_post(post, target=target_relative)
                
            # Verifica se o arquivo foi baixado no diretório temporário
            downloaded_files = list(temp_target_dir.glob("*.mp4"))
            if downloaded_files:
                f = downloaded_files[0]
                dest_resolve = dest_file.resolve()
                if dest_file.exists():
                    dest_file.unlink()
                f.rename(dest_file)
                return dest_resolve
            
            # Fallback secundário: baixar com curl usando a URL obtida do objeto Post
            video_url = getattr(post, "video_url", None) or getattr(post, "video_url_hd", None)
            if video_url:
                self._download_video_with_curl(video_url, dest_file)
                if dest_file.exists():
                    return dest_file.resolve()
            return None
        except Exception as e:
            log.error(f"[instascraper] Falha crítica no fallback de download do post {shortcode}: {e}", exc_info=True)
            if dest_file.exists():
                try:
                    dest_file.unlink()
                except Exception:
                    pass
            # Tentativa de re-autenticação se possível
            if self.instagram_user:
                success, msg = self.autenticar(self.instagram_user)
                if success:
                    log.info("[instascraper] Re-autenticado, tentando download novamente no fallback.")
                    reauth_temp_target_dir = target_dir / f"tmp_reauth_{uuid.uuid4().hex}"
                    try:
                        reauth_temp_target_dir.mkdir(parents=True, exist_ok=True)
                        post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
                        if post.is_video:
                            try:
                                target_relative = os.path.relpath(reauth_temp_target_dir, Path.cwd())
                            except ValueError:
                                target_relative = str(reauth_temp_target_dir)
                            self.loader.download_post(post, target=target_relative)
                            downloaded_files = list(reauth_temp_target_dir.glob("*.mp4")) + list((self.base_path / target_relative).glob("*.mp4"))
                            if downloaded_files:
                                f = downloaded_files[0]
                                dest_resolve = dest_file.resolve()
                                if dest_file.exists():
                                    dest_file.unlink()
                                f.rename(dest_file)
                                return dest_resolve
                    except Exception as re_err:
                        log.error(f"[instascraper] Falha ao tentar novamente após re-autenticar: {re_err}")
                        if dest_file.exists():
                            try:
                                dest_file.unlink()
                            except Exception:
                                pass
                    finally:
                        if reauth_temp_target_dir.exists():
                            import shutil
                            shutil.rmtree(reauth_temp_target_dir, ignore_errors=True)
            return None
        finally:
            if temp_target_dir.exists():
                import shutil
                shutil.rmtree(temp_target_dir, ignore_errors=True)
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
