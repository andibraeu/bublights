#!/usr/bin/env python3
"""Erzeugt Funktionen und Virtual-Console-Bedienung für UKING ZQ01334 Retro Wash
(33-Kanal-Modus) in einem bestehenden QLC+-Workspace (getestet mit QLC+ 5.3.0).

Das Skript sucht alle Retro Washes im Workspace, ordnet sie nach Universum/Adresse
(= Reihenfolge der Kette) und erzeugt:

  * Lauflicht synchron / gegenläufig / fortlaufend / Schlange über alle Geräte und
    „von oben und unten“ (Solo-Frame)
  * Hintergrund-Farbwechsel synchron / versetzt
  * Lauflicht farbig (Ring um die leuchtende COB, je Gerät eine Farbe), Glimmen als Grundlicht,
    Ringlauf gegen die Lauflicht-Richtung
  * Aktionen: Alle COBs, Herzschlag, Welle (über alle Geräte), Gewitter,
    Schlange, oben+unten, Glühbirne, Funkeln, Countdown (je höchstens ~10 s)
  * Submaster für COB- und Farb-Helligkeit, Speed-Dials mit Presets
  * optional OSC-Bindungen für die Aktionen (/retro/aktion/1..9, z. B. vom Grobhandtaster)

Alles Erzeugte liegt im Funktions-Ordner NAME und im VC-Rahmen NAME auf der gewählten
Seite. Ein erneuter Lauf ersetzt genau diese Teile; Eingänge (MIDI, OSC, Tasten), die in
QLC+ von Hand an erzeugte Widgets gebunden wurden, werden anhand der Beschriftung
übernommen. Alles andere im Workspace bleibt unverändert.

Beispiele:
  tools/retro_wash.py show.qxw
  tools/retro_wash.py show.qxw --add-fixtures 2 --osc-universe 2
  tools/retro_wash.py vorlage.qxw -o neues-projekt.qxw --page "Seite 3"
"""

import argparse
import copy
import random
import sys
import xml.etree.ElementTree as ET

NS = "http://www.qlcplus.org/Workspace"
ET.register_namespace("", NS)

MANUFACTURER = "UKING"
MODEL = "ZQ01334 385W Retro Wash"
MODE = "33 Channel"
CHANNELS = 33

# Kanalbelegung im 33-Kanal-Modus (0-basiert)
DIMMER, STROBE = 0, 1
COB = [2, 3, 4, 5, 6, 7]
RGB = (8, 9, 10)
DEVICE_EFFECTS = [11, 12, 13, 14]
PIXEL = [(15 + 3 * i, 16 + 3 * i, 17 + 3 * i) for i in range(6)]

INVALID_ID = 4294967295

# Hintergrundfarben (gedimmt, damit die COBs vorne bleiben)
COLOURS = [("Rubin", 200, 0, 20), ("Bernstein", 200, 70, 0), ("Magenta", 180, 0, 120),
           ("Violett", 90, 0, 200), ("Tiefblau", 0, 20, 200), ("Petrol", 0, 120, 140)]

# Ringfarben je Gerät beim farbigen Lauflicht
DEVICE_COLOURS = [(0, 255, 255), (255, 0, 255), (255, 120, 0), (120, 255, 0)]

# Aktionen sollen innerhalb der Tastersperre (11 s) fertig sein
ACTION_MS = 10000


def q(tag):
    return f"{{{NS}}}{tag}"


def el(tag, attrib=None, text=None, children=()):
    e = ET.Element(q(tag), {k: str(v) for k, v in (attrib or {}).items()})
    if text is not None:
        e.text = str(text)
    e.extend(children)
    return e


def osc_hash(path):
    """Kanalnummer, die das QLC+-OSC-Plugin einem OSC-Pfad zuordnet (CRC-16, wie Utils::getChecksum)."""
    tbl = [0x0000, 0x1081, 0x2102, 0x3183, 0x4204, 0x5285, 0x6306, 0x7387,
           0x8408, 0x9489, 0xa50a, 0xb58b, 0xc60c, 0xd68d, 0xe70e, 0xf78f]
    crc = 0xffff
    for c in path.encode():
        crc = ((crc >> 4) & 0x0fff) ^ tbl[(crc ^ c) & 15]
        c >>= 4
        crc = ((crc >> 4) & 0x0fff) ^ tbl[(crc ^ c) & 15]
    return ~crc & 0xffff


# ---------------------------------------------------------------- Workspace

class Workspace:
    def __init__(self, path):
        self.tree = ET.parse(path)
        self.root = self.tree.getroot()
        self.engine = self.root.find(q("Engine"))
        self.vc = self.root.find(q("VirtualConsole"))

    def fixtures(self):
        out = []
        for f in self.engine.findall(q("Fixture")):
            if f.findtext(q("Manufacturer")) == MANUFACTURER and f.findtext(q("Model")) == MODEL:
                out.append(f)
        return out

    def add_fixtures(self, wanted, universe, start_address):
        existing = self.fixtures()
        all_fx = self.engine.findall(q("Fixture"))
        next_id = max([int(f.findtext(q("ID"))) for f in all_fx], default=-1) + 1
        if existing:
            last = max(existing, key=lambda f: (int(f.findtext(q("Universe"))), int(f.findtext(q("Address")))))
            universe = int(last.findtext(q("Universe")))
            address = int(last.findtext(q("Address"))) + CHANNELS
        else:
            address = start_address
        for n in range(len(existing), wanted):
            fx = el("Fixture", children=[
                el("Manufacturer", text=MANUFACTURER), el("Model", text=MODEL), el("Mode", text=MODE),
                el("ID", text=next_id), el("Name", text=f"{MODEL} [{n + 1}]"),
                el("Universe", text=universe), el("Address", text=address), el("Channels", text=CHANNELS)])
            pos = list(self.engine).index(all_fx[-1]) + 1 if all_fx else 1
            self.engine.insert(pos, fx)
            all_fx = self.engine.findall(q("Fixture"))
            print(f"Fixture hinzugefügt: ID {next_id}, Universum {universe + 1}, DMX-Adresse {address + 1}")
            next_id += 1
            address += CHANNELS

    def ensure_output_channels(self, fixtures):
        """DMX-USB-Ausgänge mit begrenzter Kanalzahl so weit öffnen, dass alle Geräte Daten bekommen."""
        need = {}
        for f in fixtures:
            u = int(f.findtext(q("Universe")))
            need[u] = max(need.get(u, 0), int(f.findtext(q("Address"))) + CHANNELS)
        iomap = self.engine.find(q("InputOutputMap"))
        for uni in iomap.findall(q("Universe")):
            u = int(uni.get("ID"))
            for params in uni.iter(q("PluginParameters")):
                cur = params.get("UniverseChannels")
                if cur is not None and u in need and int(cur) < need[u]:
                    params.set("UniverseChannels", str(need[u]))
                    print(f"Universum {u + 1}: Ausgabe von {cur} auf {need[u]} Kanäle erweitert")

    def remove_generated_functions(self, prefix):
        for f in self.engine.findall(q("Function")):
            path = f.get("Path", "")
            if path == prefix or path.startswith(prefix + "/"):
                self.engine.remove(f)

    def page(self, caption):
        for frame in self.vc.findall(q("Frame")):
            if frame.get("Caption") == caption:
                return frame
        pages = [f.get("Caption") for f in self.vc.findall(q("Frame"))]
        sys.exit(f"Seite '{caption}' nicht gefunden. Vorhanden: {', '.join(pages)}")

    def next_function_id(self):
        return max([int(f.get("ID")) for f in self.engine.findall(q("Function"))], default=-1) + 1

    def next_widget_id(self):
        return max([int(e.get("ID")) for e in self.vc.iter() if e.get("ID") is not None
                    and e.tag != q("Input") and e.tag != q("Preset")], default=-1) + 1

    def insert_functions(self, funcs):
        monitor = self.engine.find(q("Monitor"))
        pos = list(self.engine).index(monitor) if monitor is not None else len(self.engine)
        for i, f in enumerate(funcs):
            self.engine.insert(pos + i, f)

    def write(self, path):
        ET.indent(self.tree, space=" ")
        body = ET.tostring(self.root, encoding="unicode")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE Workspace>\n' + body + "\n")


# ---------------------------------------------------------------- Funktionen

class Functions:
    def __init__(self, first_id, prefix):
        self.next_id = first_id
        self.prefix = prefix
        self.items = []

    def _new(self, ftype, name, folder, attrib=None):
        fid = self.next_id
        self.next_id += 1
        path = self.prefix + (f"/{folder}" if folder else "")
        f = el("Function", {"ID": fid, "Type": ftype, "Name": name, "Path": path, **(attrib or {})})
        self.items.append(f)
        return fid, f

    def scene(self, name, values, folder=None, blend=None):
        """values: {fixture_id: {kanal: wert}}"""
        fid, f = self._new("Scene", name, folder, {"BlendMode": blend} if blend else None)
        f.append(el("Speed", {"FadeIn": 0, "FadeOut": 0, "Duration": 0}))
        for fx in sorted(values):
            vals = ",".join(f"{c},{v}" for c, v in sorted(values[fx].items()))
            f.append(el("FixtureVal", {"ID": fx}, vals))
        return fid

    def chaser(self, name, steps, folder=None, order="SingleShot", speed=None):
        """steps: Funktions-IDs (gemeinsame Zeiten aus speed=(FadeIn, FadeOut, Duration))
        oder Tupel (ID, FadeIn, Hold, FadeOut) für Zeiten pro Schritt."""
        fid, f = self._new("Chaser", name, folder)
        mode = "Common" if speed else "PerStep"
        fin, fout, dur = speed or (0, 0, 0)
        f.append(el("Speed", {"FadeIn": fin, "FadeOut": fout, "Duration": dur}))
        f.append(el("Direction", text="Forward"))
        f.append(el("RunOrder", text=order))
        f.append(el("SpeedModes", {"FadeIn": mode, "FadeOut": mode, "Duration": mode}))
        for n, st in enumerate(steps):
            sid, a, h, o = st if isinstance(st, tuple) else (st, 0, 0, 0)
            f.append(el("Step", {"Number": n, "FadeIn": a, "Hold": h, "FadeOut": o}, sid))
        return fid


def merge(*dicts):
    out = {}
    for d in dicts:
        for fx, vals in d.items():
            out.setdefault(fx, {}).update(vals)
    return out


def cobs(fxs, value, cob_idx=range(6)):
    return {fx: {COB[i]: value for i in cob_idx} for fx in fxs}


def rings(fxs, r, g, b, pixels=range(6)):
    out = {}
    for fx in fxs:
        vals = {}
        if len(pixels) == 6:
            vals.update(zip(RGB, (r, g, b)))
        for p in pixels:
            vals.update(zip(PIXEL[p], (r, g, b)))
        out[fx] = vals
    return out


def step_ms(steps, ms, budget=ACTION_MS):
    """Schrittzeit ms, bei vielen Schritten (viele Geräte) so verkürzt, dass alles ins Budget passt."""
    return min(ms, budget // len(steps))


def build_functions(F, fxs):
    n = len(fxs)
    ids = {}

    ids["basis"] = F.scene("Basis (Dimmer auf)",
                           {fx: {DIMMER: 255, STROBE: 0, **{c: 0 for c in DEVICE_EFFECTS}} for fx in fxs})

    # Lauflicht: Crossfade-Chaser, nächster Schritt startet nach dem Einblenden, der vorige
    # blendet doppelt so lang aus (Schweif). Jede Variante hat eigene Szenen.
    run = (1200, 2400, 1200)
    # Faktoren für den Speed-Dial (5 = 1/2, 6 = 1x, 7 = 2x), Chaser-Zeiten passend zu Tempo 1200
    run_factors = (6, 7, 6)
    variants = [("synchron", lambda k: {fx: k for fx in fxs})]
    if n > 1:
        variants.append(("gegenläufig", lambda k: {fx: (k if i % 2 == 0 else 5 - k) for i, fx in enumerate(fxs)}))
    ids["lauf"] = []
    for label, pos in variants:
        steps = [F.scene(f"Lauflicht {label} {k + 1}", {fx: {COB[c]: 255} for fx, c in pos(k).items()}, "Lauflicht")
                 for k in range(6)]
        ids["lauf"].append((label, F.chaser(f"COB Lauflicht {label}", steps, "Lauflicht", "PingPong", run), run_factors))
    if n > 1:
        steps = [F.scene(f"Lauflicht fortlaufend {j + 1}", {fxs[j // 6]: {COB[j % 6]: 255}}, "Lauflicht")
                 for j in range(6 * n)]
        ids["lauf"].append(("fortlaufend", F.chaser("COB Lauflicht fortlaufend", steps, "Lauflicht", "PingPong", run),
                            run_factors))
        # Schlange: Gerät 1 von oben nach unten, Gerät 2 von unten nach oben usw., viermal so schnell
        snake = [(fx, c if i % 2 == 0 else 5 - c) for i, fx in enumerate(fxs) for c in range(6)]
        steps = [F.scene(f"Lauflicht Schlange {j + 1}", {fx: {COB[c]: 255}}, "Lauflicht")
                 for j, (fx, c) in enumerate(snake)]
        ids["lauf"].append(("Schlange", F.chaser("COB Lauflicht Schlange", steps, "Lauflicht", "PingPong", (300, 600, 300)),
                            (4, 5, 4)))
    # Von oben und unten: COBs gehen paarweise von außen nach innen an und von innen nach außen
    # wieder aus. Einblenden ohne Fade, damit gemeinsame Kanäle beim Übergang nicht einbrechen (HTP).
    fill = [[], [0, 5], [0, 1, 4, 5], range(6)]
    steps = [F.scene(f"Lauflicht oben+unten {k}", cobs(fxs, 255, c) if c else {fx: {STROBE: 0} for fx in fxs},
                     "Lauflicht") for k, c in enumerate(fill)]
    ids["lauf"].append(("oben+unten", F.chaser("COB Lauflicht oben+unten", steps, "Lauflicht", "PingPong", (0, 600, 1200)),
                        (1, 5, 6)))
    # Farbig: wie fortlaufend, Ring um die leuchtende COB in der Farbe des Geräts
    steps = []
    for j in range(6 * n):
        fx, c = fxs[j // 6], j % 6
        colour = DEVICE_COLOURS[j // 6 % len(DEVICE_COLOURS)]
        steps.append(F.scene(f"Lauflicht farbig {j + 1}", merge(cobs([fx], 255, [c]), rings([fx], *colour, [c])),
                             "Lauflicht"))
    ids["lauf"].append(("farbig", F.chaser("COB Lauflicht farbig", steps, "Lauflicht", "PingPong", run), run_factors))

    ids["glimmen"] = F.scene("Glimmen (Grundlicht)", cobs(fxs, 30), "Lauflicht")

    # Hintergrundfarben
    fade = (8000, 8000, 16000)
    ids["farben"] = []
    steps = [F.scene(f"Farbe {name}", rings(fxs, r, g, b), "Farben") for name, r, g, b in COLOURS]
    ids["farben"].append(("synchron", F.chaser("RGB Farbwechsel synchron", steps, "Farben", "Loop", fade)))
    if n > 1:
        shift = len(COLOURS) // n or 1
        steps = []
        for k in range(len(COLOURS)):
            vals = {}
            for i, fx in enumerate(fxs):
                _, r, g, b = COLOURS[(k + i * shift) % len(COLOURS)]
                vals.update(rings([fx], r, g, b))
            steps.append(F.scene(f"Farben versetzt {k + 1}", vals, "Farben"))
        ids["farben"].append(("versetzt", F.chaser("RGB Farbwechsel versetzt", steps, "Farben", "Loop", fade)))

    # Ringlauf: eisblauer Punkt im Ring, läuft von unten nach oben (gegen das synchrone Lauflicht),
    # gleiches Tempo wie das Lauflicht; mischt sich per HTP mit der Hintergrundfarbe
    steps = [F.scene(f"Ringlauf {k + 1}", rings(fxs, 0, 160, 255, [5 - k]), "Farben") for k in range(6)]
    ids["ringlauf"] = F.chaser("RGB Ringlauf gegen Lauflicht", steps, "Farben", "PingPong", run)

    # Aktionen (laufen einmal und legen sich per HTP über das Programm)
    A = "Aktionen"
    alle = F.scene("Alle COBs voll", cobs(fxs, 255), A)
    ids["alle"] = F.chaser("Aktion: Alle COBs 5 s", [alle], A, speed=(400, 1500, 5400))

    stark = F.scene("Herz stark", merge(cobs(fxs, 255), rings(fxs, 255, 0, 0)), A)
    schwach = F.scene("Herz schwach", merge(cobs(fxs, 140), rings(fxs, 140, 0, 0)), A)
    pause = F.scene("Herz Pause", {fx: {STROBE: 0} for fx in fxs}, A)
    steps = []
    bpms = [78, 78, 76, 74, 72, 70, 68, 66, 63, 60, 58]   # Puls beruhigt sich
    for i, bpm in enumerate(bpms):
        cycle, gap, last = round(60000 / bpm), 300 + (78 - bpm), i == len(bpms) - 1
        steps += [(stark, 40, 60, 220), (pause, 0, gap - 100, 0), (schwach, 40, 40, 1000 if last else 300)]
        if not last:
            steps.append((pause, 0, cycle - gap - 80, 0))
    ids["herz"] = F.chaser("Aktion: Herzschlag", steps, A)

    # Welle: weißer Punkt (COB + Ring) läuft über alle Geräte viermal runter und hoch (~9 s bei 2 Geräten)
    total = 6 * n
    wave = [F.scene(f"Welle {j + 1}", merge({fxs[j // 6]: {COB[j % 6]: 255}},
                                             rings([fxs[j // 6]], 255, 255, 255, [j % 6])), A)
            for j in range(total)]
    order = [0]
    for _ in range(4):
        order += list(range(1, total)) + list(range(total - 2, -1, -1))
    ids["welle"] = F.chaser("Aktion: Welle", [wave[j] for j in order], A,
                            speed=(60, 500, step_ms(order, 200 if n == 1 else 100)))

    # Schlange als Aktion: schnell, dreimal hin und zurück (eigene Szenen, das Lauflicht kann parallel laufen)
    if n > 1:
        fast = [F.scene(f"Schlange {j + 1}", {fx: {COB[c]: 255}}, A) for j, (fx, c) in enumerate(snake)]
        order = [0]
        for _ in range(3):
            order += list(range(1, len(fast))) + list(range(len(fast) - 2, -1, -1))
        ids["schlange"] = F.chaser("Aktion: Schlange", [fast[j] for j in order], A,
                                   speed=(60, 250, step_ms(order, 100)))

    # oben+unten als Aktion: dreimal füllen und leeren, immer schneller, zum Schluss alle an
    fill_ids = [F.scene(f"oben+unten {k}", cobs(fxs, 255, c) if c else {fx: {STROBE: 0} for fx in fxs}, A)
                for k, c in enumerate(fill)]
    steps = []
    for hold in (350, 280, 220):
        steps += [(fill_ids[k], 0, hold, 200) for k in (1, 2, 3, 2, 1, 0)]
    steps += [(fill_ids[1], 0, 200, 0), (fill_ids[2], 0, 200, 0), (fill_ids[3], 0, 1000, 1500)]
    ids["obenunten"] = F.chaser("Aktion: oben+unten", steps, A)

    # Glühbirne: glimmt an, flackert, geht voll an (~10 s)
    gl = F.scene("Glühbirne glimmt", cobs(fxs, 25), A)
    gh = F.scene("Glühbirne halb", cobs(fxs, 120), A)
    gv = F.scene("Glühbirne voll", cobs(fxs, 255), A)
    go = F.scene("Glühbirne aus", {fx: {STROBE: 0} for fx in fxs}, A)
    ids["gluehbirne"] = F.chaser("Aktion: Glühbirne", [
        (gl, 800, 700, 0), (go, 0, 80, 0), (gl, 0, 120, 0), (go, 0, 150, 0), (gh, 0, 60, 0), (go, 0, 250, 0),
        (gv, 1200, 4000, 2500)], A)

    # Funkeln: zufällige einzelne COBs blitzen auf (feste Zufallsfolge, nie zweimal dieselbe hintereinander)
    spark = [F.scene(f"Funkeln {j + 1}", {fxs[j // 6]: {COB[j % 6]: 255}}, A) for j in range(total)]
    rnd, seq = random.Random(1334), []
    while len(seq) < 55:
        j = rnd.randrange(total)
        if not seq or j != seq[-1]:
            seq.append(j)
    ids["funkeln"] = F.chaser("Aktion: Funkeln", [spark[j] for j in seq], A, speed=(0, 400, 140))

    # Countdown: alle COBs an, gehen der Kette nach von hinten aus, zum Schluss Blitz mit Ringen
    countdown = [F.scene(f"Countdown {k}", merge(*({fxs[j // 6]: {COB[j % 6]: 255}} for j in range(k))), A)
                 for k in range(total, 0, -1)]
    t = step_ms(countdown, 1000, 7000)
    steps = [(sid, 0, t, 300) for sid in countdown]
    steps.append((F.scene("Countdown Pause", {fx: {STROBE: 0} for fx in fxs}, A), 0, t, 0))
    steps.append((F.scene("Countdown Blitz", merge(cobs(fxs, 255), rings(fxs, 255, 255, 255)), A), 0, 300, 1500))
    ids["countdown"] = F.chaser("Aktion: Countdown", steps, A)


    # Gewitter: Blitze nur in den Ringen, die COBs hält der Flash-Button „COBs aus“ (Override) auf 0,
    # „Himmel dunkel“ dunkelt den Farbwechsel nachtblau ab. Läuft ~5 s = Impulsdauer am Taster.
    hell, fern = (255, 255, 255), (150, 170, 255)
    half = ([0, 1, 2], [3, 4, 5])                  # obere / untere Ringhälfte
    blitz_ids = {}

    def blitz(name, targets, colour, pixels=range(6)):
        key = (name, tuple(targets))
        if key not in blitz_ids:
            blitz_ids[key] = F.scene(f"Gewitter {name}", rings(targets, *colour, pixels), A)
        return blitz_ids[key]

    nacht = F.scene("Gewitter Pause", {fx: {STROBE: 0} for fx in fxs}, A)
    first, last = fxs[:1], fxs[-1:]
    seq = [(nacht, 0, 60, 0),                                          # Mask vor dem ersten Blitz aktiv
           # fernes Wetterleuchten auf einem Gerät
           (blitz("fern oben", last, fern, half[0]), 0, 50, 0), (nacht, 0, 80, 0),
           (blitz("fern", last, fern), 0, 40, 400), (nacht, 0, 900, 0),
           # großer Einschlag: zuckt von oben nach unten, dann alles hell und Nachglühen
           (blitz("oben", fxs, hell, half[0]), 0, 40, 0), (nacht, 0, 60, 0),
           (blitz("unten", fxs, hell, half[1]), 0, 30, 0), (nacht, 0, 100, 0),
           (blitz("alle", fxs, hell), 0, 70, 700), (nacht, 0, 1100, 0),
           # zweiter Einschlag springt zwischen den Geräten
           (blitz("Gerät 1", first, hell), 0, 50, 0), (nacht, 0, 40, 0),
           (blitz("Gerät 2", last, hell), 0, 50, 0), (nacht, 0, 60, 0),
           (blitz("alle", fxs, hell), 0, 80, 900), (nacht, 0, 800, 0),
           # letztes Grollen in der Ferne
           (blitz("fern unten", first, fern, half[1]), 0, 60, 1500)]
    ids["blitz"] = F.chaser("Aktion: Gewitter", seq, A)

    ids["cobs_aus"] = F.scene("COBs aus (Flash zum Gewitter)", cobs(fxs, 0), A)
    ids["dunkel"] = F.scene("Himmel dunkel (Mask, Flash zum Gewitter)", rings(fxs, 20, 25, 70), A, blend="Mask")
    return ids


# ---------------------------------------------------------------- Virtual Console

class Widgets:
    def __init__(self, first_id, osc_universe, osc_prefix):
        self.next_id = first_id
        self.osc_universe = osc_universe
        self.osc_prefix = osc_prefix

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    @staticmethod
    def ws(x, y, w, h):
        return el("WindowState", {"Visible": "True", "X": x, "Y": y, "Width": w, "Height": h})

    def osc_input(self, path):
        if self.osc_universe is None:
            return []
        return [el("Input", {"ID": 0, "Universe": self.osc_universe,
                             "Channel": osc_hash(self.osc_prefix + path)})]

    def button(self, caption, fid, x, y, colour=None, action="Toggle", flash=False, osc=None, key=None):
        b = el("Button", {"Caption": caption, "ID": self._id()}, children=[self.ws(x, y, 130, 90)])
        if colour is not None:
            b.append(el("Appearance", children=[el("BackgroundColor", text=0xFF000000 | colour)]))
        b.append(el("Function", {"ID": fid}))
        b.append(el("Action", {"Override": 1, "ForceLTP": 1} if flash else None, action))
        b.extend(self.osc_input(osc) if osc else [])
        if key:
            b.append(el("Key", text=key))
        return b

    def submaster(self, caption, x, y):
        return el("Slider", {"Caption": caption, "ID": self._id(), "WidgetStyle": "Slider",
                             "InvertedAppearance": "false"}, children=[
            self.ws(x, y, 110, 390),
            el("SliderMode", {"ValueDisplayStyle": "Exact"}, "Submaster"),
            el("Level", {"LowLimit": 0, "HighLimit": 255, "Value": 255})])

    def speeddial(self, caption, fids, x, y, time, factors, tmax, presets):
        """factors: je Funktion (FadeIn, FadeOut, Duration)"""
        # Faktoren: 1 = 0, 4 = 1/4, 5 = 1/2, 6 = 1x, 7 = 2x; Sichtbar: +/-, Dial, Tap, s, ms, Multiplikatoren
        d = el("SpeedDial", {"Caption": caption, "ID": self._id()}, children=[
            self.ws(x, y, 230, 390), el("Visibility", text=231), el("Time", text=time),
            el("AbsoluteValue", {"Minimum": 0, "Maximum": tmax})])
        for fid, (fin, fout, dur) in zip(fids, factors):
            d.append(el("Function", {"FadeIn": fin, "FadeOut": fout, "Duration": dur}, fid))
        for i, (name, value) in enumerate(presets, 1):
            d.append(el("Preset", {"ID": i}, children=[el("Name", text=name), el("Value", text=value)]))
        return d

    def frame(self, caption, x, y, w, h, children, solo=False, header=True):
        f = el("SoloFrame" if solo else "Frame", {"Caption": caption, "ID": self._id()}, children=[
            self.ws(x, y, w, h),
            el("AllowResize", text="True"), el("ShowHeader", text="True" if header else "False"),
            el("ShowEnableButton", text="False"), el("Collapsed", text="False"), el("Disabled", text="False")])
        f.extend(children)
        return f

    def variant_buttons(self, title, variants, colour, x, y):
        """Eine Variante: einfacher Button. Mehrere: Solo-Frame, damit immer nur eine läuft."""
        if len(variants) == 1:
            return self.button(title, variants[0][1], x, y, colour)
        btns = [self.button(f"{title} {label}", fid, 10 + 140 * i, 40, colour) for i, (label, fid, *_) in enumerate(variants)]
        return self.frame(title, x, y, 20 + 140 * len(variants), 140, btns, solo=True)


def build_console(W, ids):
    top = [
        W.button("Basis (Dimmer auf)", ids["basis"], 10, 40),
        W.button("Stop All", INVALID_ID, 150, 40, 0x8B0000, action="StopAll"),
        # Gewitter außerhalb der Submaster-Rahmen (volle Helligkeit); alle drei an derselben Adresse
        # und auf Taste G: COBs und Himmel bleiben dunkel, solange gehalten wird
        W.button("Aktion: Gewitter (Taste G halten)", ids["blitz"], 310, 40, 0x1A237E, osc="/aktion/4", key="G"),
        W.button("COBs aus (Flash zum Gewitter)", ids["cobs_aus"], 450, 40, 0x303030,
                 action="Flash", flash=True, osc="/aktion/4", key="G"),
        W.button("Himmel dunkel (Flash zum Gewitter)", ids["dunkel"], 590, 40, 0x101830,
                 action="Flash", osc="/aktion/4", key="G"),
    ]
    cob_w = max(530, 30 + 140 * len(ids["lauf"]))
    col_w = max(390, 30 + 140 * len(ids["farben"]))
    # Aktionen mit fester OSC-Nummer (die Schlange gibt es nur bei mehreren Geräten)
    actions = [("Aktion: Alle COBs 5 s", "alle", 0x007583, 1), ("Aktion: Herzschlag", "herz", 0x8B1A1A, 2),
               ("Aktion: Welle", "welle", 0x5A5A5A, 3), ("Aktion: Schlange", "schlange", 0x2E7D32, 5),
               ("Aktion: oben+unten", "obenunten", 0x1565C0, 6), ("Aktion: Glühbirne", "gluehbirne", 0x8D6E00, 7),
               ("Aktion: Funkeln", "funkeln", 0x455A64, 8), ("Aktion: Countdown", "countdown", 0xBF360C, 9)]
    actions = [a for a in actions if a[1] in ids]
    per_row = (cob_w - 20) // 140
    btns = [W.button(cap, ids[key], 10 + 140 * (i % per_row), 200 + 100 * (i // per_row), colour, osc=f"/aktion/{num}")
            for i, (cap, key, colour, num) in enumerate(actions)]
    y = 210 + 100 * ((len(actions) + per_row - 1) // per_row)
    h = y + 410
    lauf = ids["lauf"] + [("Ringlauf", ids["ringlauf"], (6, 7, 6))]
    cob = [
        W.variant_buttons("Lauflicht", ids["lauf"], 0xB36B00, 10, 40),
        *btns,
        W.speeddial("Tempo Lauflicht + Ringlauf", [fid for _, fid, _ in lauf], 10, y, 1200, [f for _, _, f in lauf], 10000,
                    [("Standard", 1200), ("Langsam", 2500), ("Schnell", 600)]),
        W.submaster("Helligkeit COB", 260, y),
        W.button("Glimmen (Grundlicht)", ids["glimmen"], 390, y, 0x6D4C41),
    ]
    farben_fids = [fid for _, fid in ids["farben"]]
    col = [
        W.variant_buttons("Farbwechsel", ids["farben"], 0x4A148C, 10, 40),
        W.button("Ringlauf gegen Lauflicht", ids["ringlauf"], 10, 200, 0x00838F),
        W.speeddial("Tempo Farben", farben_fids, 10, y, 16000, [(5, 5, 6)] * len(farben_fids), 60000,
                    [("Standard", 16000), ("Langsam", 30000), ("Schnell", 8000)]),
        W.submaster("Helligkeit Farben", 260, y),
    ]
    inner = top + [
        W.frame("COB – Lauflicht & Aktionen", 10, 150, cob_w, h, cob),
        W.frame("Farben – Hintergrund", 20 + cob_w, 150, col_w, h, col),
    ]
    return inner, 40 + cob_w + col_w, h + 170

def carry_over_inputs(old_frame, new_frame):
    """Von Hand gesetzte Eingänge/Tasten (gleiche Beschriftung) aus dem alten Rahmen übernehmen."""
    if old_frame is None:
        return
    keep = {}
    for w in old_frame.iter():
        cap = w.get("Caption")
        extra = [c for c in w if c.tag in (q("Input"), q("Key"))]
        if cap and extra:
            keep[(w.tag, cap)] = extra
    for w in new_frame.iter():
        key = (w.tag, w.get("Caption"))
        if key in keep and w.find(q("Input")) is None and w.find(q("Key")) is None:
            w.extend(copy.deepcopy(e) for e in keep[key])


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workspace", help="QLC+-Workspace (.qxw)")
    ap.add_argument("-o", "--output", help="Ziel-Datei (Standard: Workspace überschreiben)")
    ap.add_argument("--name", default="Retro Wash", help="Funktions-Ordner und VC-Rahmen (Standard: %(default)s)")
    ap.add_argument("--page", default="Seite 1", help="VC-Seite für den Rahmen (Standard: %(default)s)")
    ap.add_argument("--x", type=int, default=0, help="Position des Rahmens auf der Seite")
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--add-fixtures", type=int, metavar="N",
                    help="fehlende Retro Washes ergänzen, bis N Geräte vorhanden sind (Adressen direkt hintereinander)")
    ap.add_argument("--universe", type=int, default=1, help="Universum für neue Geräte, wenn noch keins existiert")
    ap.add_argument("--address", type=int, default=1, help="DMX-Startadresse für das erste neue Gerät")
    ap.add_argument("--order", help="Reihenfolge der Kette als Fixture-IDs, z. B. 1,0 (Standard: nach Adresse)")
    ap.add_argument("--osc-universe", type=int, metavar="U",
                    help="Aktions-Buttons an OSC-Eingang auf Universum U binden (1-basiert wie in QLC+)")
    ap.add_argument("--osc-prefix", default="/retro", help="OSC-Pfad-Präfix (Standard: %(default)s)")
    args = ap.parse_args()

    ws = Workspace(args.workspace)
    if args.add_fixtures:
        ws.add_fixtures(args.add_fixtures, args.universe - 1, args.address - 1)

    fixtures = ws.fixtures()
    wrong = [f.findtext(q("Name")) for f in fixtures if f.findtext(q("Mode")) != MODE]
    if wrong:
        sys.exit(f"Diese Geräte stehen nicht im Modus '{MODE}': {', '.join(wrong)}")
    if not fixtures:
        sys.exit("Keine Retro Washes im Workspace gefunden (Option --add-fixtures N legt welche an).")
    if args.order:
        by_id = {int(f.findtext(q("ID"))): f for f in fixtures}
        fixtures = [by_id[int(i)] for i in args.order.split(",")]
    else:
        fixtures.sort(key=lambda f: (int(f.findtext(q("Universe"))), int(f.findtext(q("Address")))))
    ws.ensure_output_channels(fixtures)
    fx_ids = [int(f.findtext(q("ID"))) for f in fixtures]

    ws.remove_generated_functions(args.name)
    F = Functions(ws.next_function_id(), args.name)
    ids = build_functions(F, fx_ids)
    ws.insert_functions(F.items)

    page = ws.page(args.page)
    old = next((f for f in page if f.tag == q("Frame") and f.get("Caption") == args.name), None)
    if old is not None:
        page.remove(old)
    osc_uni = args.osc_universe - 1 if args.osc_universe else None
    W = Widgets(ws.next_widget_id(), osc_uni, args.osc_prefix)
    inner, w, h = build_console(W, ids)
    container = W.frame(args.name, args.x, args.y, w, h, inner)
    carry_over_inputs(old, container)
    page.append(container)

    out = args.output or args.workspace
    ws.write(out)
    names = ", ".join(f"{f.findtext(q('Name'))} (DMX {int(f.findtext(q('Address'))) + 1})" for f in fixtures)
    print(f"{len(F.items)} Funktionen für {len(fixtures)} Gerät(e) erzeugt: {names}")
    print(f"Geschrieben: {out}")


if __name__ == "__main__":
    main()
