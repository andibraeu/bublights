# bublights

Lichtsteuerung mit QLC+ 5 über DMX für **UKING ZQ01334 385W Retro Wash**: Lauflicht, Farbwechsel,
interaktive Aktionen per Taster (Grobhandtaster aus `serendipity-switch`, ESP32 → OSC → QLC+).

| Pfad | Inhalt |
|---|---|
| `fixtures/UKING-ZQ01334-Retro-Wash.qxf` | Fixture-Definition (15- und 33-Kanal-Modus) |
| `tools/retro_wash.py` | Generator für Funktionen und Virtual Console in beliebigen Workspaces |
| `uking-retro.qxw` | Workspace mit 2 Geräten (DMX 1 und 34, 33-Kanal-Modus) |

## Einrichtung

1. Fixture installieren: `ln -s $PWD/fixtures/UKING-ZQ01334-Retro-Wash.qxf ~/.qlcplus/fixtures/`
2. Geräte am Display auf **33 Kanäle** stellen, Adressen **1, 34, 67, …** (je 33 Kanäle).
3. `uking-retro.qxw` öffnen, unter Ein-/Ausgänge das eigene DMX-Interface auf Universum 1 legen.
4. Für den Taster: auf **Universum 2** als Eingang **OSC** aktivieren (Port 7701). Nicht auf
   Universum 1 – dort ist Passthrough an, OSC-Werte würden auf DMX-Kanälen landen.

## Generator: in andere Projekte übernehmen

```sh
tools/retro_wash.py projekt.qxw                                  # vorhandene Retro Washes nutzen
tools/retro_wash.py projekt.qxw --add-fixtures 2 --osc-universe 2
tools/retro_wash.py vorlage.qxw -o show.qxw --page "Seite 3" --x 0 --y 200
```

- Findet alle Retro Washes (33-Kanal-Modus) im Workspace; die Reihenfolge der Kette ergibt sich
  aus der Adresse, abweichend mit `--order 1,0` (Fixture-IDs).
- Alles Erzeugte liegt im Funktions-Ordner **Retro Wash** und im VC-Rahmen **Retro Wash** auf der
  gewählten Seite (`--name` ändert beides). Ein erneuter Lauf ersetzt nur diese Teile; der Rest des
  Workspaces bleibt unverändert.
- In QLC+ von Hand gebundene Eingänge (MIDI, Tasten, …) an erzeugten Widgets werden anhand der
  Beschriftung übernommen. Eigene Änderungen an erzeugten Funktionen oder Widgets gehen dagegen
  verloren – dafür lieber den Generator anpassen.
- `--osc-universe U` bindet die Aktions-Buttons direkt an `/retro/aktion/1…4` (kein Auto Detect
  nötig). Das OSC-Plugin bildet Pfade per CRC-16 auf Kanalnummern ab, das Skript rechnet das nach.
- DMX-USB-Ausgänge mit begrenzter Kanalzahl (`UniverseChannels`) werden automatisch erweitert.
- QLC+ nicht mit derselben Datei offen haben bzw. danach ohne Speichern neu laden.

## Bedienung (VC-Rahmen „Retro Wash“)

- **Basis** öffnet den Master-Dimmer – ohne ihn bleibt alles dunkel (der Dimmer wirkt auf COBs *und* Ringe).
- **Lauflicht** synchron / gegenläufig / fortlaufend / Schlange / farbig über alle Geräte und
  „oben+unten“ (Solo-Frame: immer nur eine Variante). Schlange: Gerät 1 von oben nach unten, Gerät 2
  von unten nach oben usw., viermal so schnell wie das Tempo. oben+unten: COBs gehen paarweise von
  außen nach innen an und wieder aus. farbig: wie fortlaufend, dazu der Ring um die leuchtende COB in
  einer Farbe je Gerät. Ein gemeinsamer Speed-Dial, die Verhältnisse bleiben erhalten.
- **Glimmen** hält alle COBs schwach an (Grundlicht), Lauflicht und Aktionen hellen darüber auf.
- **Farbwechsel** synchron / versetzt (Geräte mit unterschiedlichen Farben).
- **Ringlauf** (zusätzlich zum Farbwechsel): eisblauer Punkt im Ring, läuft von unten nach oben –
  gegen das synchrone Lauflicht, im Tempo des Lauflichts.
- **Aktionen** (einmalig, legen sich über das Programm, jeweils höchstens ~10 s): Alle COBs 5 s,
  Herzschlag, Welle (läuft über alle Geräte), Gewitter (siehe unten),
  Schlange, oben+unten, Glühbirne (glimmt an, flackert, geht voll an), Funkeln (zufällige COBs),
  Countdown (COBs gehen nacheinander aus, Schlussblitz).
- **Gewitter**: Blitze in den Ringen (Wetterleuchten, Einschlag von oben nach unten, zwischen den
  Geräten springend), dazu „COBs aus“ und „Himmel dunkel“ (nachtblau abgedunkelter Farbwechsel).
  COBs und Himmel bleiben nur dunkel, *solange gehalten wird* – per Taster über die Impulsdauer, von
  Hand mit gehaltener Taste **G** (ein Klick auf den Button startet nur die Blitze). Nach dem
  Loslassen läuft alles wie vorher weiter.
- **Helligkeit COB / Farben** sind Submaster: sie dimmen alles, was über Buttons im jeweiligen Rahmen läuft.

| OSC-Pfad | Aktion |
|---|---|
| `/retro/aktion/1` | Alle COBs 5 s |
| `/retro/aktion/2` | Herzschlag (~10 s) |
| `/retro/aktion/3` | Welle (~9 s bei 2 Geräten, viermal runter und hoch) |
| `/retro/aktion/4` | Gewitter (~5 s) + „COBs aus“ + „Himmel dunkel“ (Flash, solange gehalten) |
| `/retro/aktion/5` | Schlange, dreimal hin und zurück (~7 s, nur bei mehreren Geräten) |
| `/retro/aktion/6` | oben+unten, dreimal füllen und leeren (~8 s) |
| `/retro/aktion/7` | Glühbirne (~10 s) |
| `/retro/aktion/8` | Funkeln (~8 s) |
| `/retro/aktion/9` | Countdown (~9 s) |

## Taster

Der Grobhandtaster (`serendipity-switch`) hängt im selben WLAN wie der QLC+-Rechner. Auf seiner
Einrichtungsseite:

| Feld | Wert |
|---|---|
| Was ein Treffer auslöst | OSC-Taste senden |
| Adresse von QLC+ | IP des QLC+-Rechners |
| OSC-Port | 7701 (Universum 2) |
| OSC-Pfad | `/retro/aktion` |
| Aktions-IDs | `1, 2, 3, 4, 5, 6, 7, 8, 9` – bei jedem Treffer eine zufällig, nie zweimal dieselbe hintereinander |
| Impulsdauer | 5000 ms – so lange bleiben beim Gewitter COBs und Himmel dunkel |
| Sperre | mindestens 11 s, sonst bricht ein neuer Treffer eine laufende Aktion ab |

Trefferchance nach Geschmack: 100 % löst bei jedem Druck aus. Ohne ESP32 testen:
`python3 tools/qlc_ws.py --osc-port 7701 osc <QLC-IP> /retro/aktion/3` im Taster-Projekt (der
Gewitter braucht dabei die Haltezeit, die das Tool nicht hat).

## Bausteine (übertragbar auf andere Geräte)

| Baustein | Wofür | Achtung |
|---|---|---|
| Chaser mit Duration = Fade-In, Fade-Out länger | weiches Lauflicht mit Schweif | Eine Szene kann nicht gleichzeitig in zwei Chasern laufen – eigene Szenen pro Chaser. |
| Single-Shot-Chaser über laufendem Programm | Aktionen, danach läuft alles weiter | Intensität ist HTP: eine Aktion kann nur aufhellen. |
| Submaster-Slider im Frame | Helligkeit einer Button-Gruppe, auch bei OSC-Auslösung | Wirkt nur auf Funktionen, die Buttons *im Frame* starten (nicht über Collections oder Scripts). |
| Flash-Button mit Override + Force LTP | Kanäle zwangsweise auf 0 (COBs aus) | Nur solange gedrückt, kein Fade. |
| Szene mit `BlendMode="Mask"` als Flash | bereits laufende Funktionen abdunkeln | Wirkt nur auf Faders, die *vorher* gestartet wurden. |
| Speed-Dial mit mehreren Funktionen + Presets | ein Tempo für alle Varianten, „Standard“ per Klick | Faktor (×2, ½) gilt zusätzlich zur Zeit. |

Vermeiden: Slider im Modus **Adjust** auf Intensität – sie starten ihre Funktion beim Laden selbst
und stoppen sie nach einem Stop All dauerhaft, bis man sie hochzieht.
