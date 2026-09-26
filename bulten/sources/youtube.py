"""YouTube videoları için isteğe bağlı transkript zenginleştirme.

YouTube kanal RSS'i yalnızca başlık ve açıklama verir. `YOUTUBE_TRANSCRIPTS=true` ve
`youtube-transcript-api` paketi kuruluysa erişilebilir (herkese açık/otomatik) transkript alınır.
Transkript alınamazsa özet "yalnızca başlık/açıklama" etiketi taşır. Varsayılan olarak kapalıdır;
YouTube kullanım koşullarını kendi kullanımınız için değerlendirin.
"""
from __future__ import annotations

import logging
import sqlite3

from ..db import jload
from .base import Observation

log = logging.getLogger(__name__)


def _fetch_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return None
    try:
        if hasattr(YouTubeTranscriptApi, "fetch"):  # youtube-transcript-api >= 1.0
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=["tr", "en"])
            return " ".join(getattr(s, "text", "") for s in fetched)
        items = YouTubeTranscriptApi.get_transcript(video_id, languages=["tr", "en"])  # eski API
        return " ".join(i.get("text", "") for i in items)
    except Exception as exc:  # noqa: BLE001 - transkript yoksa veya erişilemiyorsa
        log.info("Transkript alınamadı (%s): %s", video_id, exc.__class__.__name__)
        return None


def enrich_transcripts(conn: sqlite3.Connection, source_id: int, observations: list[Observation], *,
                       enabled: bool, max_new: int = 3) -> list[str]:
    notes: list[str] = []
    fetched = 0
    for ob in observations:
        vid = ob.fields.get("youtube_id")
        if not vid:
            continue
        row = conn.execute("SELECT body, fields_json FROM observations WHERE source_id = ? AND external_key = ?",
                           (source_id, ob.external_key)).fetchone()
        if row and jload(row["fields_json"], {}).get("transcript"):
            ob.body = row["body"]
            ob.fields["transcript"] = True
            continue
        ob.fields["transcript"] = False
        if not enabled or fetched >= max_new:
            continue
        text = _fetch_transcript(vid)
        fetched += 1
        if text:
            ob.fields["transcript"] = True
            ob.body = (ob.body + "\n\nTranskript (otomatik, kısaltılmış): " + " ".join(text.split())[:8000]).strip()
        else:
            notes.append(f"{vid}: transkript bulunamadı; yalnızca başlık/açıklama kullanılacak.")
    return notes
