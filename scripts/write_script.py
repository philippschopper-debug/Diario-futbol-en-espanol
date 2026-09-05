#!/usr/bin/env python3
"""
Recherchiert aktuelle spanische Fussball-News (v.a. LaLiga) per Claude +
Web-Suche und schreibt daraus content/latest.txt + content/latest.json.

Benoetigt die Umgebungsvariable ANTHROPIC_API_KEY.
"""

import datetime
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
API_URL = "https://api.anthropic.com/v1/messages"


def log(*args):
    print(*args, file=sys.stderr)


SYSTEM_PROMPT = """\
Du schreibst das taegliche Skript fuer einen privaten spanischsprachigen
Podcast namens "Diario Futbol en Espanol". Der Hoerer ist ein
deutschsprachiger Spanischlernender mit gutem Grundwortschatz (Niveau B1-B2),
der frueher den (inzwischen eingestellten) Podcast "Marca Daily" gehoert hat:
ca. 10 Minuten Sprechzeit, Fokus auf spanischen Fussball (v.a. LaLiga),
Sprechtempo/Wortschatz moderat und gut verstaendlich, keine sehr
umgangssprachlichen oder extrem seltenen Woerter, klare kurze bis
mittellange Saetze, aber trotzdem natuerliches, authentisches Spanisch (wie
ein echter Sportjournalist, nicht wie ein Lehrbuch).

Nutze die Websuche, um echte, aktuelle Informationen zu finden (letzte
Spieltag-Ergebnisse, Tabellenstand, bevorstehende Spiele, wichtige
Transfers/News). Erfinde keine Fakten. Wenn gerade keine LaLiga-Spiele
laufen (Laenderspielpause, Sommerpause etc.), weiche auf andere aktuelle
spanische Fussball-Themen aus (Champions League mit spanischen Teams,
spanische Nationalmannschaft, wichtige Transfers, etc.).

Struktur wie beim Vorbild "Marca Daily": kurze Begruessung, dann 2-4
Nachrichten/Themen mit echten Details (Ergebnisse, Torschuetzen, Tabelle),
dann ein Ausblick auf die kommenden Tage, kurzer Abschluss. Ca. 1300-1500
Woerter Fließtext (das ergibt bei normalem Sprechtempo ca. 10 Minuten).
Reiner Fliesstext zum Vorlesen - keine Ueberschriften, keine Aufzaehlungen,
keine Emojis, keine Regieanweisungen.

Antworte NUR mit einem einzigen JSON-Objekt, exakt in diesem Format, ohne
Markdown-Codeblock, ohne weiteren Text davor oder danach:
{"title": "Kurzer Folgentitel auf Spanisch (max. 100 Zeichen)", "description": "1-2 Saetze Zusammenfassung auf Spanisch (max. 300 Zeichen)", "script": "Der vollstaendige Podcast-Text auf Spanisch"}
"""


def extract_text(content_blocks):
    parts = []
    for block in content_blocks:
        if block.get("type") == "text":
            parts.append(block["text"])
    return "".join(parts).strip()


def parse_json_response(raw_text):
    text = raw_text.strip()
    # Falls Claude trotz Anweisung einen Codeblock verwendet hat, entfernen.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def main():
    if not API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY ist nicht gesetzt.")

    today = datetime.date.today()
    weekday_es = [
        "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
    ][today.weekday()]
    user_prompt = (
        f"Heute ist {today.isoformat()} ({weekday_es}). "
        "Recherchiere die aktuellen spanischen Fussball-News (LaLiga zuerst) "
        "und schreibe die heutige Folge gemaess Systemanweisung."
    )

    body = {
        "model": MODEL,
        "max_tokens": 6000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 6,
            }
        ],
    }

    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    log(f"Rufe {MODEL} mit Web-Suche auf ...")
    resp = requests.post(API_URL, headers=headers, json=body, timeout=180)
    if resp.status_code != 200:
        raise RuntimeError(f"Anthropic API Fehler ({resp.status_code}): {resp.text[:1000]}")

    data = resp.json()
    raw_text = extract_text(data.get("content", []))
    if not raw_text:
        raise RuntimeError(f"Keine Textantwort erhalten: {json.dumps(data)[:1000]}")

    try:
        result = parse_json_response(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Konnte Antwort nicht als JSON parsen: {e}\n---\n{raw_text[:2000]}")

    for field in ("title", "description", "script"):
        if not result.get(field):
            raise RuntimeError(f"Feld '{field}' fehlt in der Antwort: {result}")

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    (CONTENT_DIR / "latest.txt").write_text(result["script"].strip() + "\n", encoding="utf-8")
    (CONTENT_DIR / "latest.json").write_text(
        json.dumps(
            {
                "date": today.isoformat(),
                "title": result["title"].strip(),
                "description": result["description"].strip(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    word_count = len(result["script"].split())
    log(f"Skript geschrieben: '{result['title']}' ({word_count} Woerter)")


if __name__ == "__main__":
    main()
