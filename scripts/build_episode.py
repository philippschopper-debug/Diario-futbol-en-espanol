#!/usr/bin/env python3
"""
Baut eine taegliche Podcast-Folge aus content/latest.txt + content/latest.json:
1. Waehlt eine spanische (es-ES) Stimme ueber die Google Cloud TTS API.
2. Zerlegt den Text in Haeppchen (API-Limit) und synthetisiert sie.
3. Haengt Intro-Jingle + Sprache zusammen (ffmpeg via pydub).
4. Legt die fertige MP3 in docs/episodes/ ab.
5. Aktualisiert docs/episodes.json und docs/feed.xml (RSS/iTunes-Podcast-Feed).
6. Entfernt alte Folgen, wenn mehr als MAX_EPISODES vorhanden sind.

Benoetigt die Umgebungsvariable GOOGLE_TTS_API_KEY.
"""

import base64
import datetime
import json
import os
import sys
import textwrap
from email.utils import format_datetime
from pathlib import Path

import requests
from pydub import AudioSegment

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
DOCS_DIR = ROOT / "docs"
EPISODES_DIR = DOCS_DIR / "episodes"
ASSETS_DIR = ROOT / "assets"
EPISODES_JSON = DOCS_DIR / "episodes.json"
FEED_XML = DOCS_DIR / "feed.xml"

MAX_EPISODES = 21
API_KEY = os.environ.get("GOOGLE_TTS_API_KEY")
TTS_BASE = "https://texttospeech.googleapis.com/v1"

# Bevorzugte Stimm-Qualitaetsstufe, in dieser Reihenfolge.
TIER_PRIORITY = ["Neural2", "Wavenet", "Standard"]

PODCAST_TITLE = "Diario Fútbol en Español"
PODCAST_DESCRIPTION = (
    "Tägliche, kurze Zusammenfassung der spanischen Fußballliga (La Liga) auf "
    "Spanisch - für Lernende mit gutem Grundwortschatz. Erstellt automatisch "
    "von Claude."
)
# Wird nach dem ersten Push automatisch anhand des Repos gesetzt (siehe unten),
# kann aber auch manuell ueberschrieben werden.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")


def log(*args):
    print(*args, file=sys.stderr)


def _tier_rank(name):
    for i, tier in enumerate(TIER_PRIORITY):
        if tier in name:
            return i
    return len(TIER_PRIORITY)


def pick_voice():
    """Waehlt eine maennliche es-ES Stimme, beste verfuegbare Qualitaetsstufe."""
    resp = requests.get(f"{TTS_BASE}/voices", params={"languageCode": "es-ES", "key": API_KEY}, timeout=30)
    resp.raise_for_status()
    voices = resp.json().get("voices", [])
    if not voices:
        raise RuntimeError("Keine es-ES Stimme gefunden - API-Key/Region pruefen.")

    male = [v for v in voices if v.get("ssmlGender") == "MALE"]
    pool = male if male else voices
    if not male:
        log("Warnung: keine maennliche es-ES Stimme gefunden, nehme verfuegbare Stimme.")

    pool.sort(key=lambda v: (_tier_rank(v["name"]), v["name"]))
    chosen = pool[0]["name"]
    log(f"Stimme gewaehlt: {chosen} (gender={pool[0].get('ssmlGender')})")
    return chosen


def chunk_text(text, max_bytes=4500):
    """Teilt den Text an Satzgrenzen in Stuecke < max_bytes (UTF-8)."""
    sentences = []
    buf = ""
    for part in text.replace("\n", " \n ").split(". "):
        part = part.strip()
        if not part:
            continue
        sentences.append(part if part.endswith((".", "!", "?")) else part + ".")

    chunks = []
    current = ""
    for sentence in sentences:
        candidate = (current + " " + sentence).strip()
        if len(candidate.encode("utf-8")) > max_bytes and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def synthesize_chunk(text, voice_name, tmp_path):
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "es-ES", "name": voice_name},
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 0.94,
            "pitch": 0.0,
        },
    }
    resp = requests.post(f"{TTS_BASE}/text:synthesize", params={"key": API_KEY}, json=body, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"TTS-Fehler ({resp.status_code}): {resp.text[:500]}")
    audio_b64 = resp.json()["audioContent"]
    tmp_path.write_bytes(base64.b64decode(audio_b64))


def build_narration(script_text, voice_name, workdir: Path) -> AudioSegment:
    chunks = chunk_text(script_text)
    log(f"{len(chunks)} Text-Haeppchen zu synthetisieren")
    segments = []
    for i, chunk in enumerate(chunks):
        tmp_path = workdir / f"chunk_{i:03d}.mp3"
        synthesize_chunk(chunk, voice_name, tmp_path)
        segments.append(AudioSegment.from_mp3(tmp_path))
    narration = segments[0]
    for seg in segments[1:]:
        narration += AudioSegment.silent(duration=250) + seg
    return narration


def assemble_episode(narration: AudioSegment) -> AudioSegment:
    intro = AudioSegment.from_mp3(ASSETS_DIR / "intro.mp3")
    pause = AudioSegment.silent(duration=400)
    episode = intro + pause + narration + AudioSegment.silent(duration=500)
    return episode.set_channels(1)


def load_episodes():
    if EPISODES_JSON.exists():
        return json.loads(EPISODES_JSON.read_text(encoding="utf-8"))
    return []


def save_episodes(episodes):
    EPISODES_JSON.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")


def prune_episodes(episodes):
    if len(episodes) <= MAX_EPISODES:
        return episodes
    keep, drop = episodes[:MAX_EPISODES], episodes[MAX_EPISODES:]
    for ep in drop:
        for key in ("filename", "transcript_filename"):
            fname = ep.get(key)
            if not fname:
                continue
            f = EPISODES_DIR / fname
            if f.exists():
                f.unlink()
                log(f"Alte Datei geloescht: {fname}")
    return keep


def rfc2822(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=6, minute=0, second=0, tzinfo=datetime.timezone.utc
    )
    return format_datetime(dt)


def build_feed(episodes, base_url):
    items_xml = []
    for ep in episodes:
        h, rem = divmod(int(ep["duration_seconds"]), 3600)
        m, s = divmod(rem, 60)
        duration_str = f"{h:02d}:{m:02d}:{s:02d}"
        enclosure_url = f"{base_url}/episodes/{ep['filename']}"
        transcript_block = ""
        full_text_block = ""
        transcript_filename = ep.get("transcript_filename")
        if transcript_filename:
            transcript_url = f"{base_url}/episodes/{transcript_filename}"
            transcript_block = (
                f'\n      <podcast:transcript url="{transcript_url}" '
                f'type="text/plain" language="es-ES" />'
            )
            full_text = (EPISODES_DIR / transcript_filename).read_text(encoding="utf-8")
            # Zeilenumbrueche als <br/> fuer lesbare Show-Notes in Podcast-Apps.
            full_text_html = escape_xml(full_text).replace("\n", "<br/>")
            full_text_block = f"\n      <content:encoded><![CDATA[{full_text_html}]]></content:encoded>"
        items_xml.append(f"""    <item>
      <title>{escape_xml(ep['title'])}</title>
      <description>{escape_xml(ep['description'])}</description>{full_text_block}
      <pubDate>{rfc2822(ep['date'])}</pubDate>
      <guid isPermaLink="false">{ep['filename']}</guid>
      <enclosure url="{enclosure_url}" length="{ep['filesize']}" type="audio/mpeg" />
      <itunes:duration>{duration_str}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>{transcript_block}
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
  <channel>
    <title>{escape_xml(PODCAST_TITLE)}</title>
    <link>{base_url}/</link>
    <language>es-es</language>
    <description>{escape_xml(PODCAST_DESCRIPTION)}</description>
    <itunes:author>Claude</itunes:author>
    <itunes:image href="{base_url}/cover.png" />
    <itunes:category text="Sports" />
    <itunes:explicit>false</itunes:explicit>
    <image>
      <url>{base_url}/cover.png</url>
      <title>{escape_xml(PODCAST_TITLE)}</title>
      <link>{base_url}/</link>
    </image>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    FEED_XML.write_text(feed, encoding="utf-8")


def escape_xml(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main():
    if not API_KEY:
        raise SystemExit("GOOGLE_TTS_API_KEY ist nicht gesetzt.")

    meta = json.loads((CONTENT_DIR / "latest.json").read_text(encoding="utf-8"))
    script_text = (CONTENT_DIR / "latest.txt").read_text(encoding="utf-8").strip()

    base_url = SITE_BASE_URL
    if not base_url:
        # Wird aus GITHUB_REPOSITORY (owner/repo) abgeleitet, wenn im Workflow gesetzt.
        gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in gh_repo:
            owner, repo = gh_repo.split("/", 1)
            base_url = f"https://{owner}.github.io/{repo}"
    if not base_url:
        raise SystemExit("SITE_BASE_URL konnte nicht bestimmt werden.")

    EPISODES_DIR.mkdir(parents=True, exist_ok=True)

    voice_name = pick_voice()

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        narration = build_narration(script_text, voice_name, Path(tmp))
        episode_audio = assemble_episode(narration)

        date_str = meta["date"]
        filename = f"ep-{date_str}.mp3"
        out_path = EPISODES_DIR / filename
        episode_audio.export(out_path, format="mp3", bitrate="96k")

    transcript_filename = f"ep-{date_str}.txt"
    (EPISODES_DIR / transcript_filename).write_text(script_text, encoding="utf-8")

    duration_seconds = len(episode_audio) / 1000.0
    filesize = out_path.stat().st_size

    episodes = load_episodes()
    episodes = [e for e in episodes if e["date"] != date_str]  # Ersetzen falls gleicher Tag erneut laeuft
    episodes.insert(0, {
        "date": date_str,
        "title": meta["title"],
        "description": meta.get("description", ""),
        "filename": filename,
        "transcript_filename": transcript_filename,
        "duration_seconds": duration_seconds,
        "filesize": filesize,
    })
    episodes.sort(key=lambda e: e["date"], reverse=True)
    episodes = prune_episodes(episodes)
    save_episodes(episodes)
    build_feed(episodes, base_url)

    log(f"Fertig: {filename} ({duration_seconds:.0f}s, {filesize/1024:.0f} KB)")


if __name__ == "__main__":
    main()
