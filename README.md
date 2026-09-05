# Diario Fútbol en Español

Automatisch erzeugter, täglicher Mini-Podcast (Spanisch) über LaLiga-Neuigkeiten.
Läuft komplett selbststaendig ueber GitHub Actions - kein manuelles Zutun noetig,
sobald die zwei API-Keys hinterlegt sind.

## Wie es funktioniert

Jeden Morgen (02:30 UTC) startet der Workflow `.github/workflows/episode.yml`
automatisch und macht der Reihe nach:

1. **`scripts/write_script.py`** - ruft Claude (Anthropic API) mit
   Web-Suche auf, recherchiert aktuelle LaLiga-News und schreibt ein
   ca. 10-minuetiges spanisches Skript (Niveau B1-B2) nach
   `content/latest.txt` + `content/latest.json`.
2. **`scripts/build_episode.py`** - waehlt eine spanische Google-Cloud-TTS-
   Stimme, synthetisiert das Skript, haengt den Intro-Jingle
   (`assets/intro.mp3`) davor, legt die fertige Folge in `docs/episodes/`
   ab und aktualisiert `docs/feed.xml` (RSS/iTunes-Feed) + `docs/episodes.json`.
3. Der Workflow committet und pusht die neuen Dateien - GitHub Pages liefert
   `docs/` danach automatisch als Website + Podcast-Feed aus.
4. Eine Podcast-App (Apple Podcasts, Overcast, Pocket Casts, AntennaPod, ...)
   abonniert die Feed-URL einmalig und laedt jeden Morgen automatisch die
   neue Folge.

## Einmaliges Setup

- [ ] **GitHub Pages aktivieren:** Settings → Pages → Source: "Deploy from a
      branch", Branch: `main`, Ordner: `/docs`.
- [ ] **Anthropic-API-Key** auf console.anthropic.com anlegen (eigenes,
      separates Konto von claude.ai, nutzungsbasierte Abrechnung).
- [ ] **Google-Cloud-Projekt** anlegen, Text-to-Speech API aktivieren,
      API-Key erzeugen (auf die Text-to-Speech-API einschraenken).
- [ ] Repository-Secrets anlegen: Settings → Secrets and variables →
      Actions → New repository secret:
      - `ANTHROPIC_API_KEY`
      - `GOOGLE_TTS_API_KEY`
- [ ] Feed-URL (`https://<user>.github.io/<repo>/feed.xml`) in einer
      Podcast-App als "Add by URL" / "Nach URL hinzufuegen" abonnieren.

## Manuell testen

Im Reiter "Actions" den Workflow "Build daily episode" oeffnen und
"Run workflow" klicken (funktioniert erst, sobald beide Secrets gesetzt sind).

## Kosten

- Anthropic API: wenige Cent pro Tag (kurzer Text + Web-Suche).
- Google Cloud TTS: bei ca. 7.500 Zeichen/Folge bleibt eine taegliche
  10-Minuten-Folge innerhalb des monatlichen Gratis-Kontingents (1 Mio.
  Zeichen/Monat bei WaveNet/Neural2-Stimmen).
- GitHub Actions + Pages: kostenlos fuer ein oeffentliches Repository.
