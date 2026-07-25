from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("seeker.research_machine.yt_search")


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str
    channel_name: str
    view_count: int = 0
    upload_date: str = ""
    duration_s: int = 0
    description: str = ""


class YouTubeSearch:
    def __init__(self, cookies_path: str | None = None):
        self.cookies_path = cookies_path

    def search(self, query: str, max_results: int = 20) -> list[YouTubeVideo]:
        import yt_dlp

        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "playlistend": max_results,
            "socket_timeout": 8,
            "retries": 0,
        }
        if self.cookies_path:
            ydl_opts["cookiefile"] = self.cookies_path

        search_url = f"ytsearch{max_results}:{query}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
        except Exception as e:
            log.warning(f"[yt_search] Busca falhou para {query!r}: {e}")
            return []

        entries = info.get("entries", []) if info else []
        results: list[YouTubeVideo] = []
        for entry in entries:
            if not entry:
                continue
            vid = entry.get("id", "")
            results.append(YouTubeVideo(
                video_id=vid,
                title=entry.get("title", ""),
                url=f"https://youtube.com/watch?v={vid}",
                channel_name=entry.get("channel", entry.get("uploader", "")),
                view_count=entry.get("view_count", 0),
                upload_date=entry.get("upload_date", ""),
                duration_s=entry.get("duration", 0),
            ))
        return results

    def enrich(self, video: YouTubeVideo) -> YouTubeVideo:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 8,
            "retries": 0,
        }
        if self.cookies_path:
            ydl_opts["cookiefile"] = self.cookies_path
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video.url, download=False)
            if info:
                return YouTubeVideo(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    channel_name=video.channel_name,
                    view_count=info.get("view_count", video.view_count),
                    upload_date=info.get("upload_date", video.upload_date),
                    duration_s=info.get("duration", video.duration_s),
                    description=(info.get("description") or "")[:1000],
                )
        except Exception as e:
            log.warning(f"[yt_search] Enrich falhou para {video.url}: {e}")
        return video
