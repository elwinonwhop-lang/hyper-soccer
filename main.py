import asyncio
import pygame
import sys
import math
import random
import json
import os
import time
from array import array

WEB_BUILD = sys.platform == "emscripten"
RELAY_URL = "wss://hyper-soccer-relay-1.onrender.com"

if WEB_BUILD:
  import platform
else:
  import socket
  import threading


if int(pygame.version.ver.split(".")[0]) < 2:
    print("Hyper Soccer needs pygame 2 or newer.  Install it with:  pip install --upgrade pygame")
    sys.exit(1)

try:
    pygame.mixer.pre_init(22050, -16, 1, 512, allowedchanges=0)
except Exception:
    try:
        pygame.mixer.pre_init(22050, -16, 1, 512)
    except Exception:
        pass

pygame.init()
pygame.font.init()

# ============================================================
# DISPLAY / GAME SETTINGS
# ============================================================

SCREEN_WIDTH = 1200
SCREEN_HEIGHT = 700
W, H = SCREEN_WIDTH, SCREEN_HEIGHT
FPS = 120            # render cap; all physics is delta-time based (60 Hz units)
MATCH_SECONDS = 90

# Online settings
NET_PORT = 47821     # UDP port the host listens on
PROTO = 2            # bump when the network protocol changes
MAGIC = "HSOC"
INTERP_DELAY = 0.07  # seconds the guest renders behind the host (smooths jitter)

MENU_STATES = ("menu", "online_menu", "join", "lobby", "settings", "customize", "upgrades")
GAME_STATES = ("countdown", "play", "goal", "finished")
STATE_IDX = {"countdown": 0, "play": 1, "goal": 2, "finished": 3}
IDX_STATE = {v: k for k, v in STATE_IDX.items()}

OT_FRAMES = 60 * 60                      # golden goal lasts at most 60 seconds
MATCH_LENGTHS = (60, 90, 120, 180)       # selectable match lengths (seconds)

# Power-ups: 0 = speed, 1 = mega shot, 2 = freeze
PU_NAMES = ("SPEED", "MEGA SHOT", "FREEZE")
PU_COLORS = ((255, 225, 60), (255, 130, 40), (120, 215, 255))
PU_DUR = (480.0, 600.0, 100.0)           # effect length in 60 Hz frames

BOT_LEVELS = [
    {"name": "EASY", "lull": 0.0050, "lull_len": (25, 60), "think": (16, 34), "mag": 0.60,
     "err": 55, "aim": 110, "shoot": 0.009, "shoot_x": 560, "charge": (0.0, 0.30),
     "tackle": 0.018, "tk_range": 60, "fumble": 0.0025, "dash": False, "seek_pu": False},
    {"name": "NORMAL", "lull": 0.0035, "lull_len": (18, 45), "think": (12, 26), "mag": 0.74,
     "err": 40, "aim": 100, "shoot": 0.013, "shoot_x": 600, "charge": (0.0, 0.45),
     "tackle": 0.030, "tk_range": 66, "fumble": 0.0012, "dash": False, "seek_pu": False},
    {"name": "HARD", "lull": 0.0, "lull_len": (1, 2), "think": (5, 11), "mag": 1.0,
     "err": 16, "aim": 85, "shoot": 0.045, "shoot_x": 760, "charge": (0.25, 0.85),
     "tackle": 0.100, "tk_range": 74, "fumble": 0.0003, "dash": True, "seek_pu": True},
]

if WEB_BUILD:
  screen = pygame.display.set_mode((W, H))
else:
  try:
    screen = pygame.display.set_mode((W, H), pygame.SCALED, vsync=1)
  except Exception:
    screen = pygame.display.set_mode((W, H))

pygame.display.set_caption("Hyper Soccer 1v1")
clock = pygame.time.Clock()

# ============================================================
# COLORS
# ============================================================

FIELD = (38, 125, 55)
FIELD_DARK = (30, 105, 45)
FIELD_LIGHT = (48, 145, 63)
WHITE = (245, 248, 245)
BLACK = (15, 18, 18)

BLUE = (35, 135, 255)
BLUE_DARK = (12, 72, 155)
BLUE_LIGHT = (105, 195, 255)

RED = (235, 55, 70)
RED_DARK = (145, 20, 35)
RED_LIGHT = (255, 125, 135)

GOLD = (255, 210, 55)
GOAL_FRAME = (225, 230, 232)
GOAL_NET = (160, 170, 175)

UI = (20, 25, 31)
UI_LIGHT = (42, 50, 58)
SHADOW = (0, 0, 0, 75)

# Eight selectable kits, each with a main, shadow, highlight and trim colour.
KITS = (
    ("NEON BLUE", (35, 135, 255), (12, 72, 155), (105, 195, 255), (235, 250, 255)),
    ("CRIMSON", (245, 55, 75), (135, 18, 35), (255, 130, 145), (255, 230, 235)),
    ("VOLT", (195, 255, 35), (70, 115, 15), (235, 255, 125), (255, 255, 255)),
    ("CYBER PURPLE", (155, 75, 255), (75, 30, 145), (205, 155, 255), (255, 230, 255)),
    ("AQUA", (20, 220, 205), (5, 105, 110), (125, 255, 240), (235, 255, 255)),
    ("SUNSET", (255, 145, 35), (145, 60, 12), (255, 205, 100), (255, 245, 210)),
    ("PINK NOVA", (255, 70, 190), (135, 20, 95), (255, 155, 220), (255, 240, 250)),
    ("STEALTH GOLD", (175, 155, 95), (65, 55, 30), (230, 210, 140), (255, 240, 175)),
    ("MIDNIGHT", (45, 55, 85), (12, 18, 35), (115, 150, 220), (205, 225, 255)),
    ("LIME PULSE", (95, 245, 80), (25, 100, 30), (180, 255, 145), (245, 255, 220)),
    ("ICE WHITE", (220, 238, 255), (95, 125, 155), (255, 255, 255), (90, 205, 255)),
    ("MINT", (85, 235, 160), (25, 105, 75), (170, 255, 210), (235, 255, 245)),
)

# ============================================================
# FIELD
# ============================================================

FIELD_RECT = pygame.Rect(35, 35, W - 70, H - 105)
FIELD_LEFT = FIELD_RECT.left
FIELD_RIGHT = FIELD_RECT.right
FIELD_TOP = FIELD_RECT.top
FIELD_BOTTOM = FIELD_RECT.bottom
FIELD_CY = FIELD_RECT.centery

GOAL_WIDTH = 32
GOAL_HEIGHT = 180

GOAL_Y = FIELD_CY - GOAL_HEIGHT // 2
LEFT_GOAL = pygame.Rect(FIELD_LEFT - GOAL_WIDTH + 4, GOAL_Y, GOAL_WIDTH, GOAL_HEIGHT)
RIGHT_GOAL = pygame.Rect(FIELD_RIGHT - 4, GOAL_Y, GOAL_WIDTH, GOAL_HEIGHT)

GOAL_TOP = GOAL_Y
GOAL_BOTTOM = GOAL_Y + GOAL_HEIGHT

POST_R = 6
POSTS = [(FIELD_LEFT, GOAL_TOP), (FIELD_LEFT, GOAL_BOTTOM),
         (FIELD_RIGHT, GOAL_TOP), (FIELD_RIGHT, GOAL_BOTTOM)]

# ============================================================
# HELPERS
# ============================================================


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def ease(a, dt):
    """Frame-rate independent smoothing factor (a is the per-60Hz-frame factor)."""
    return 1.0 - (1.0 - a) ** dt


def normalize(x, y, default=(1.0, 0.0)):
    length = math.hypot(x, y)
    if length < 0.1:
        return default
    return x / length, y / length


def make_shadow(w, h, alpha):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(s, (0, 0, 0, alpha), (0, 0, w, h))
    return s


PLAYER_SHADOW = make_shadow(66, 26, 75)
BALL_SHADOW = make_shadow(42, 15, 70)


def load_font(size):
    return pygame.font.SysFont("arial,helveticaneue,dejavusans", size, bold=True)


def draw_text(surf, font, text, color, pos, anchor="center", shadow=True, alpha=255):
    img = font.render(text, True, color)
    if alpha < 255:
        img.set_alpha(alpha)
    r = img.get_rect(**{anchor: pos})
    if shadow:
        sh = font.render(text, True, (0, 0, 0))
        sh.set_alpha(min(alpha, 150))
        surf.blit(sh, r.move(2, 3))
    surf.blit(img, r)
    return r


def draw_ball(surf, x, y, r, rot, ground_y=None):
    """Draws the soccer ball; ground_y lets the shadow sit below a 'lifted' ball."""
    gy = y if ground_y is None else ground_y
    height = max(0.0, gy - y)
    sc = clamp(1.0 - height / 380.0, 0.45, 1.0)
    sw, sh = max(4, int(42 * sc)), max(2, int(15 * sc))
    shadow = BALL_SHADOW if sc == 1.0 else pygame.transform.smoothscale(BALL_SHADOW, (sw, sh))
    surf.blit(shadow, (int(x - sw / 2), int(gy + 12 - sh / 2 + 2)))
    pygame.draw.circle(surf, (245, 245, 245), (int(x), int(y)), r)
    for i in range(5):
        a = rot + i * math.tau / 5
        pygame.draw.circle(surf, (35, 35, 35),
                           (int(x + math.cos(a) * r * 0.54), int(y + math.sin(a) * r * 0.54)), 2)
    pygame.draw.circle(surf, (35, 35, 35), (int(x), int(y)), 3)
    pygame.draw.circle(surf, (90, 90, 90), (int(x), int(y)), r, 2)
    pygame.draw.circle(surf, (255, 255, 255), (int(x - r * 0.35), int(y - r * 0.4)), 3)


def clipboard_text():
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        try:
            t = pygame.scrap.get_text()
            if t:
                return t
        except Exception:
            pass
        raw = pygame.scrap.get(pygame.SCRAP_TEXT)
        if raw:
            return raw.decode("utf-8", "ignore").strip("\x00")
    except Exception:
        pass
    return ""


# ============================================================
# SOUND  (everything is synthesised - no audio files needed)
# ============================================================


class Sound:
    def __init__(self):
        self.ok = False
        self.on = True
        self.snd = {}
        self.rate = 22050
        self.channels = 1
        self.music_enabled = True
        self.music_tracks = {}
        self.music_channel = None
        self.current_music = None
        try:
            if not pygame.mixer.get_init():
                try:
                    pygame.mixer.init(22050, -16, 1, 512, allowedchanges=0)
                except TypeError:
                    pygame.mixer.init(22050, -16, 1, 512)
            info = pygame.mixer.get_init()
            if not info or info[1] != -16:
                return
            self.rate, _, self.channels = info
            pygame.mixer.set_num_channels(16)
            # Reserve one dedicated channel so effects never interrupt the soundtrack.
            self.music_channel = pygame.mixer.Channel(15)
            self.build()
            self.ok = True
        except Exception:
            self.ok = False
            self.snd = {}

    def render(self, dur, f0=0.0, f1=None, vol=0.8, decay=4.0, noise=0.0, lp=1.0,
               vib=0.0, vibf=0.0, partials=((1.0, 1.0),), attack=0.004):
        n = max(1, int(self.rate * dur))
        out = []
        phase = 0.0
        filt = 0.0
        if f1 is None:
            f1 = f0
        for i in range(n):
            t = i / n
            f = f0 + (f1 - f0) * t
            if vib:
                f += math.sin(i / self.rate * math.tau * vibf) * vib
            phase += math.tau * f / self.rate
            s = 0.0
            if f0:
                for mul, amp in partials:
                    s += math.sin(phase * mul) * amp
            if noise:
                filt += (random.uniform(-1, 1) - filt) * lp
                s += filt * noise
            env = math.exp(-decay * t)
            a = i / (self.rate * attack)
            if a < 1.0:
                env *= a
            out.append(s * env * vol)
        return out

    def mix(self, parts):
        total = max(int(off * self.rate) + len(smp) for off, smp in parts)
        out = [0.0] * total
        for off, smp in parts:
            o = int(off * self.rate)
            for i, v in enumerate(smp):
                out[o + i] += v
        return out

    def make(self, samples):
        arr = array("h")
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32000)
            for _ in range(self.channels):
                arr.append(v)
        snd = pygame.mixer.Sound(buffer=arr.tobytes())
        snd.set_volume(0.8)
        return snd

    def build(self):
        r = self.render
        mk = self.make
        s = self.snd
        s["kick"] = mk(r(0.13, 190, 55, 0.9, 5.0, noise=0.5, lp=0.35))
        s["tackle"] = mk(r(0.20, 0, None, 0.7, 5.5, noise=1.6, lp=0.12))
        s["steal"] = mk(r(0.14, 450, 950, 0.5, 4.0))
        s["post"] = mk(r(0.40, 1250, None, 0.35, 6.5, partials=((1, 1.0), (2.76, 0.5), (5.4, 0.25))))
        s["beep"] = mk(r(0.14, 880, None, 0.45, 1.5))
        s["go"] = mk(r(0.40, 1320, None, 0.5, 2.0, partials=((1, 1.0), (2, 0.3))))
        s["whistle"] = mk(r(0.50, 2850, None, 0.35, 1.2, noise=0.25, lp=0.5, vib=140, vibf=26))
        s["click"] = mk(r(0.04, 700, 520, 0.4, 4.0))
        s["menuok"] = mk(r(0.10, 520, 880, 0.4, 3.0))
        s["freeze"] = mk(r(0.45, 2400, 700, 0.35, 4.0, noise=0.4, lp=0.6))
        s["pickup"] = mk(self.mix([(0.00, r(0.10, 660, None, 0.4, 3.0)),
                                   (0.06, r(0.10, 880, None, 0.4, 3.0)),
                                   (0.12, r(0.16, 1320, None, 0.4, 3.0))]))
        notes = [(0.00, 523), (0.11, 659), (0.22, 784), (0.33, 1047)]
        parts = [(0.0, r(1.6, 0, None, 0.8, 1.6, noise=1.1, lp=0.08, attack=0.15))]
        for off, f in notes:
            parts.append((off, r(0.30, f, None, 0.28, 3.0, partials=((1, 1.0), (2, 0.35)))))
        s["goal"] = mk(self.mix(parts))
        melody = [(0.00, 523), (0.14, 659), (0.28, 784), (0.42, 659), (0.64, 1047)]
        s["win"] = mk(self.mix([(off, r(0.26, f, None, 0.3, 2.5, partials=((1, 1.0), (2, 0.3))))
                                for off, f in melody]))
        self.build_music_tracks()

    def build_music_tracks(self):
        """Create original soccer-anthem loops procedurally; no copyrighted or external audio."""
        rate = self.rate
        tau = math.tau

        # A relaxed stadium warm-up for menus and a fast, chant-like sports anthem in matches.
        # Both loops contain exactly four bars, so each downbeat lands cleanly on the loop.
        settings = {
            "menu": {
                "bpm": 112.0,
                "chords": [(57, 60, 64), (53, 57, 60), (55, 59, 62), (52, 55, 59)],
                "melody": [(76, None, 79, 81), (77, None, 81, 84),
                           (79, 76, 72, 76), (74, None, 79, 83)],
                "energy": 0.72,
            },
            "match": {
                "bpm": 150.0,
                # Bright, stadium-anthem harmony with a rising finish.
                "chords": [(48, 55, 60), (45, 52, 57), (41, 48, 53), (43, 50, 55)],
                "melody": [(76, None, 79, 81), (74, None, 77, 79),
                           (72, 76, 79, 76), (74, 77, 81, 84)],
                "energy": 1.0,
            },
        }

        def hz(midi_note):
            return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

        for style, cfg in settings.items():
            bpm = cfg["bpm"]
            chords = cfg["chords"]
            melody = cfg["melody"]
            energy = cfg["energy"]
            duration = 16.0 * 60.0 / bpm  # four 4/4 bars, looped continuously
            total = int(rate * duration)
            samples = array("h")

            for i in range(total):
                t = i / rate
                beat = t * bpm / 60.0
                beat_index = int(beat)
                beat_phase = beat - beat_index
                beat_in_bar = beat_index % 4
                bar = (beat_index // 4) % 4
                chord = chords[bar]
                previous_chord = chords[(bar - 1) % 4]
                bar_phase = beat % 4.0
                blend = min(1.0, bar_phase / 0.18)

                # Stadium-sized chord bed: warm low notes with a brighter octave above.
                pad = 0.0
                for voice, midi_note in enumerate(chord):
                    f = hz(midi_note)
                    pf = hz(previous_chord[voice])
                    current = math.sin(tau * f * t) * 0.72 + math.sin(tau * f * 2.0 * t) * 0.18
                    previous = math.sin(tau * pf * t) * 0.72 + math.sin(tau * pf * 2.0 * t) * 0.18
                    pad += previous * (1.0 - blend) + current * blend
                pad *= 0.046 * energy

                # Bouncy, moving bass line keeps the pulse driving forward.
                root = chord[0]
                bass_freq = hz(root - 12)
                bass_gate = 0.80 + 0.20 * (1.0 - beat_phase)
                bass = math.sin(tau * bass_freq * t) * 0.14 * bass_gate
                bass += math.sin(tau * bass_freq * 2.0 * t) * 0.035 * bass_gate
                if style == "match":
                    bass += math.sin(tau * hz(root - 24) * t) * 0.045 * bass_gate

                # Big kick drum on the beat, with extra weight on beats 1 and 3.
                kick = 0.0
                kick_weight = (1.0 if beat_in_bar in (0, 2) else (0.62 if style == "match" else 0.28))
                if beat_phase < 0.19:
                    k_env = math.exp(-beat_phase * (25.0 if style == "match" else 20.0))
                    k_freq = 105.0 - 58.0 * min(1.0, beat_phase / 0.19)
                    kick = math.sin(tau * k_freq * t) * k_env * 0.22 * kick_weight * energy
                    kick += math.sin(tau * 48.0 * t) * k_env * 0.06 * kick_weight * energy

                # Claps/snare on beats 2 and 4 give the match a crowd-stomp rhythm.
                snare = 0.0
                if style == "match" and beat_in_bar in (1, 3) and beat_phase < 0.085:
                    s_env = math.exp(-beat_phase * 62.0)
                    snap = (math.sin(tau * 1703.0 * t) + 0.68 * math.sin(tau * 2513.0 * t)
                            + 0.42 * math.sin(tau * 3691.0 * t))
                    clap = math.sin(tau * 225.0 * t) + 0.45 * math.sin(tau * 510.0 * t)
                    snare = (snap * 0.035 + clap * 0.045) * s_env

                # Bright hi-hat on every eighth note adds movement without becoming harsh.
                hat = 0.0
                eighth_phase = (beat * 2.0) % 1.0
                if style == "match" and eighth_phase < 0.045:
                    h_env = math.exp(-eighth_phase * 105.0)
                    metal = (math.sin(tau * 5231.0 * t) + 0.65 * math.sin(tau * 6817.0 * t)
                             + 0.40 * math.sin(tau * 8123.0 * t))
                    hat = metal * h_env * 0.012

                # Synth-brass stabs on bar starts: the little fanfare gives it a football-anthem feel.
                brass = 0.0
                if beat_in_bar == 0 and beat_phase < 0.24:
                    b_env = min(1.0, beat_phase * 42.0) * math.exp(-beat_phase * 7.0)
                    for n in chord[1:]:
                        f = hz(n + 12)
                        tone = (math.sin(tau * f * t) + 0.43 * math.sin(tau * f * 2.0 * t)
                                + 0.20 * math.sin(tau * f * 3.0 * t))
                        brass += tone * b_env * (0.050 if style == "match" else 0.032)

                # A synthetic crowd "oh-oh" chant, made from layered harmonics rather than a sample.
                chant = 0.0
                chant_beats = (0, 2) if style == "match" else (0,)
                if beat_in_bar in chant_beats and beat_phase < 0.47:
                    c_env = min(1.0, beat_phase * 13.0) * math.exp(-beat_phase * 1.25)
                    chant_note = chord[1] + 12
                    f = hz(chant_note)
                    choir = (math.sin(tau * f * t) + 0.56 * math.sin(tau * f * 2.01 * t)
                             + 0.30 * math.sin(tau * f * 3.02 * t)
                             + 0.16 * math.sin(tau * hz(chant_note + 7) * t))
                    chant = choir * c_env * (0.045 if style == "match" else 0.025)

                # A short, melodic hook between drum hits.
                lead = 0.0
                note = melody[bar][beat_in_bar]
                gate = 0.28 if style == "match" else 0.34
                if note is not None and beat_phase < gate:
                    lead_env = min(1.0, beat_phase * 36.0) * math.exp(-beat_phase * (6.5 if style == "match" else 5.5))
                    f = hz(note)
                    lead_wave = math.sin(tau * f * t) + 0.32 * math.sin(tau * f * 2.0 * t)
                    if style == "match":
                        lead_wave += 0.14 * math.sin(tau * f * 3.0 * t)
                    lead = lead_wave * lead_env * (0.105 if style == "match" else 0.075)

                value = (pad + bass + kick + snare + hat + brass + chant + lead) * 0.90
                # Gentle edge fade protects against clicks at the loop seam.
                edge_len = max(1.0, rate * 0.018)
                edge = min(1.0, i / edge_len, (total - 1 - i) / edge_len)
                value *= edge
                samples.append(int(max(-1.0, min(1.0, value)) * 30000))

            snd = pygame.mixer.Sound(buffer=samples.tobytes())
            snd.set_volume(1.0)
            self.music_tracks[style] = snd

    def set_music(self, track):
        """Start/restart the requested background loop when the game screen changes."""
        if not self.ok or self.music_channel is None:
            return
        if not self.music_enabled:
            if self.music_channel.get_busy():
                self.music_channel.stop()
            self.current_music = None
            return
        if track not in self.music_tracks:
            return
        if self.current_music != track or not self.music_channel.get_busy():
            try:
                self.music_channel.play(self.music_tracks[track], loops=-1, fade_ms=650)
                self.current_music = track
            except pygame.error:
                self.current_music = None
                return
        self.music_channel.set_volume(0.20 if track == "menu" else 0.32)

    def toggle_music(self):
        self.music_enabled = not self.music_enabled
        if not self.music_enabled and self.music_channel is not None:
            self.music_channel.stop()
            self.current_music = None

    def play(self, name, vol=1.0):
        if not (self.ok and self.on):
            return
        snd = self.snd.get(name)
        if snd is None:
            return
        try:
            ch = snd.play()
            if ch is not None:
                ch.set_volume(clamp(vol, 0.0, 1.0))
        except Exception:
            pass


def draw_powerup(surf, t, x, y, tm, r=17):
    """A pulsing power-up pickup: 0 = lightning, 1 = star, 2 = snowflake."""
    col = PU_COLORS[t % 3]
    y = y + math.sin(tm * 0.1 + x * 0.01) * 3
    ix, iy = int(x), int(y)
    halo = int(r + 6 + math.sin(tm * 0.15) * 2)
    pygame.draw.circle(surf, tuple(c // 3 for c in col), (ix, iy), halo)
    pygame.draw.circle(surf, (24, 30, 36), (ix, iy), r)
    pygame.draw.circle(surf, col, (ix, iy), r, 3)
    k = r / 17.0
    if t % 3 == 0:
        pts = [(2, -10), (-6, 2), (-1, 2), (-3, 10), (6, -3), (1, -3)]
        pygame.draw.polygon(surf, col, [(ix + px * k, iy + py * k) for px, py in pts])
    elif t % 3 == 1:
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5 + tm * 0.02
            rad = (10 if i % 2 == 0 else 4.5) * k
            pts.append((ix + math.cos(ang) * rad, iy + math.sin(ang) * rad))
        pygame.draw.polygon(surf, col, pts)
    else:
        for i in range(3):
            ang = math.pi / 2 + i * math.pi / 3
            dx, dy = math.cos(ang) * 9 * k, math.sin(ang) * 9 * k
            pygame.draw.line(surf, col, (ix - dx, iy - dy), (ix + dx, iy + dy), 2)
        pygame.draw.circle(surf, col, (ix, iy), max(2, int(2 * k)))


# ============================================================
# NETWORKING  (UDP, host-authoritative)
# ============================================================

B32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 32 symbols, no I/O/0/1 to avoid typos


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # no packet is actually sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def encode_code(ip, port=NET_PORT):
    n = int.from_bytes(socket.inet_aton(ip) + port.to_bytes(2, "big"), "big")
    chars = []
    for _ in range(10):
        chars.append(B32[n & 31])
        n >>= 5
    s = "".join(reversed(chars))
    return s[:5] + "-" + s[5:]


def decode_code(text):
    s = text.upper().replace("-", "").replace(" ", "")
    if len(s) != 10:
        return None
    n = 0
    for ch in s:
        i = B32.find(ch)
        if i < 0:
            return None
        n = (n << 5) | i
    if n >> 48:
        return None
    b = n.to_bytes(6, "big")
    port = int.from_bytes(b[4:], "big")
    if port < 1024:
        return None
    return socket.inet_ntoa(b[:4]), port


def parse_target(text):
    """Accepts a party code, 'ip', 'ip:port' or a host name."""
    t = text.strip()
    if not t:
        return None
    if "." in t:
        host, sep, port_s = t.partition(":")
        try:
            port = int(port_s) if sep and port_s else NET_PORT
        except ValueError:
            return None
        if not 1 <= port <= 65535:
            return None
        try:
            if host.count(".") == 3 and all(p.isdigit() for p in host.split(".")):
                socket.inet_aton(host)
                ip = host
            else:
                ip = socket.gethostbyname(host)
        except OSError:
            return None
        return ip, port
    return decode_code(t)


def clean_name(s, default="Player"):
    s = "".join(ch for ch in str(s or "") if ch.isprintable()).strip()[:12]
    return s or default


class Net:
    """Thin non-blocking UDP wrapper that exchanges small JSON messages."""

    def __init__(self):
        self.sock = None
        self.role = None

    def open(self, role):
        self.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("", NET_PORT if role == "host" else 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setblocking(False)
        except OSError:
            s.close()
            raise
        self.sock = s
        self.role = role

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.role = None

    def send(self, msg, addr):
        if not self.sock or not addr:
            return
        msg["g"] = MAGIC
        msg["v"] = PROTO
        try:
            self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), addr)
        except OSError:
            pass

    def broadcast(self, msg):
        targets = {("255.255.255.255", NET_PORT)}
        ip = local_ip()
        if ip.count(".") == 3 and not ip.startswith("127."):
            targets.add((ip.rsplit(".", 1)[0] + ".255", NET_PORT))
        for t in targets:
            self.send(dict(msg), t)

    def poll(self):
        out = []
        if not self.sock:
            return out
        for _ in range(300):
            try:
                data, addr = self.sock.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:          # e.g. Windows ICMP "connection reset" noise
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(msg, dict) and msg.get("g") == MAGIC:
                out.append((msg, addr))
        return out

class WebNet:
  """Browser WebSocket adapter that routes packets through your Render relay."""

  def __init__(self):
    self.ws = None
    self.role = None
    self.inbox = []
    self.ready = False
    self.room_code = ""
    self.err = ""

  def open(self, role):
    self.close()
    self.role = role
    self.inbox.clear()
    self.ready = False
    self.room_code = ""
    self.err = ""
    ws = platform.window.WebSocket.new(RELAY_URL)

    def on_open(evt):
      self.ready = True
      if role == "host":
        ws.send(json.dumps({"relay": "create"}))

    def on_msg(evt):
      try:
        msg = json.loads(str(evt.data))
        if msg.get("relay") == "created":
          self.room_code = msg.get("code", "")
        elif msg.get("relay") == "error":
          self.err = msg.get("msg", "Room not found or full")
        elif msg.get("g") == MAGIC:
          self.inbox.append((msg, ("relay", 0)))
      except Exception:
        pass

    def on_err(evt):
      self.err = "Could not connect to relay server (waking up? Try again)"

    ws.onopen = on_open
    ws.onmessage = on_msg
    ws.onerror = on_err
    self.ws = ws

  def close(self):
    if self.ws:
      try:
        self.ws.close()
      except Exception:
        pass
    self.ws = None
    self.role = None
    self.ready = False

  def send(self, msg, addr=None):
    if not self.ws or not self.ready:
      return
    msg["g"] = MAGIC
    msg["v"] = PROTO
    try:
      self.ws.send(json.dumps(msg, separators=(",", ":")))
    except Exception:
      pass

  def join_room(self, code):
    if self.ws and self.ready:
      self.ws.send(json.dumps({"relay": "join", "code": code.upper().strip()}))

  def broadcast(self, msg):
    pass

  def poll(self):
    out = list(self.inbox)
    self.inbox.clear()
    return out



def r1(v):
    return round(v, 1)


def r2(v):
    return round(v, 2)


def pack_player(p):
    return [r2(p.x), r2(p.y), r2(p.vx), r2(p.vy), r2(p.facing_x), r2(p.facing_y),
            int(p.stamina), int(p.charging), r2(p.charge), r1(p.kick_timer),
            r1(p.tackle_timer), r2(p.squash), r1(p.flash_timer), int(p.exhausted),
            int(p.boost_t), int(p.mega_t), int(p.frozen_t)]


# ============================================================
# PARTICLES
# ============================================================


class Particle:
    def __init__(self, x, y, vx, vy, color, size=4, life=30, gravity=0.0, ring=False):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.color = color[:3]
        self.size = size
        self.life = float(life)
        self.max_life = float(life)
        self.gravity = gravity
        self.ring = ring

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.97 ** dt
        self.vy = self.vy * (0.98 ** dt) + self.gravity * dt
        self.life -= dt

    def draw(self, layer):
        if self.life <= 0:
            return
        ratio = self.life / self.max_life
        alpha = int(255 * ratio)
        if self.ring:
            pygame.draw.circle(layer, (*self.color, int(alpha * 0.75)),
                               (int(self.x), int(self.y)),
                               int(self.size + (1 - ratio) * 34), 3)
            return
        size = max(1, int(self.size * (0.65 + 0.35 * ratio)))
        pygame.draw.circle(layer, (*self.color, alpha), (int(self.x), int(self.y)), size)


# ============================================================
# PLAYER
# ============================================================


class Player:
    def __init__(self, x, y, color, dark_color, light_color, is_p2=False):
        self.x = float(x)
        self.y = float(y)

        self.color = color
        self.dark_color = dark_color
        self.light_color = light_color
        self.accent_color = light_color
        self.kit_name = "CUSTOM"
        self.shape = "ROUND"
        self.is_p2 = is_p2

        self.radius = 25

        self.vx = 0.0
        self.vy = 0.0
        self.max_speed = 6.2
        # Persistent career upgrades are applied by Game to the main player.
        self.shooting_level = 0
        self.pace_level = 0
        self.defending_level = 0
        self.celebration_timer = 0.0

        self.stamina = 100.0
        self.max_stamina = 100.0
        self.exhausted = False

        self.has_ball = False
        self.dribble_phase = random.random() * 10

        self.kick_timer = 0.0
        self.tackle_timer = 0.0
        self.tackle_cooldown = 0.0
        self.flash_timer = 0.0

        # Power-up timers (60 Hz frames)
        self.boost_t = 0.0
        self.mega_t = 0.0
        self.frozen_t = 0.0

        # Charged shots + input buffers (all in 60Hz frame units)
        self.charging = False
        self.charge = 0.0
        self.shot_charge = 0.0
        self.shot_buffer = 0.0
        self.tackle_buffer = 0.0

        self.facing_x = -1.0 if is_p2 else 1.0
        self.facing_y = 0.0

        self.animation_time = random.random() * 10
        self.squash = 0.0

    # --- actions ------------------------------------------------

    def tackle(self):
        if self.tackle_cooldown > 0 or self.tackle_timer > 0 or self.frozen_t > 0:
            return False
        defense = int(getattr(self, "defending_level", 0))
        self.tackle_timer = 12.0 + defense * 1.2
        self.tackle_cooldown = max(26.0, 42.0 - defense * 2.4)
        fx, fy = normalize(self.facing_x, self.facing_y,
                           (-1.0 if self.is_p2 else 1.0, 0.0))
        tackle_power = 7.5 + int(getattr(self, "defending_level", 0)) * 0.35
        self.vx += fx * tackle_power
        self.vy += fy * tackle_power
        return True

    def tick_timers(self, dt):
        speed = math.hypot(self.vx, self.vy)
        self.animation_time += (0.16 + speed * 0.025) * dt
        self.dribble_phase += (0.20 + speed * 0.03) * dt
        self.kick_timer = max(0.0, self.kick_timer - dt)
        self.tackle_timer = max(0.0, self.tackle_timer - dt)
        self.tackle_cooldown = max(0.0, self.tackle_cooldown - dt)
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.celebration_timer = max(0.0, self.celebration_timer - dt)
        self.boost_t = max(0.0, self.boost_t - dt)
        self.mega_t = max(0.0, self.mega_t - dt)
        self.frozen_t = max(0.0, self.frozen_t - dt)
        self.squash *= 0.86 ** dt
        if self.charging:
            self.charge = min(1.0, self.charge + dt / 38.0)

    def clamp_to_field(self):
        self.x = clamp(self.x, FIELD_LEFT + self.radius, FIELD_RIGHT - self.radius)
        self.y = clamp(self.y, FIELD_TOP + self.radius, FIELD_BOTTOM - self.radius)

    def update(self, dx, dy, dash, dt, particles):
        """dx/dy are -1..1 input axes (analog allowed, e.g. for the bot)."""
        if self.frozen_t > 0:
            dx = dy = 0.0
            dash = False
        length = math.hypot(dx, dy)
        if length > 1.0:
            dx /= length
            dy /= length
            length = 1.0
        moving_input = length > 0.05

        if moving_input:
            ux, uy = dx / length, dy / length
            t = ease(0.32, dt)
            self.facing_x = lerp(self.facing_x, ux, t)
            self.facing_y = lerp(self.facing_y, uy, t)
            fl = math.hypot(self.facing_x, self.facing_y)
            if fl > 0.01:
                self.facing_x /= fl
                self.facing_y /= fl

        mult = 1.0
        if self.exhausted and self.stamina > 22:
            self.exhausted = False
        if dash and moving_input and self.stamina > 0 and not self.exhausted:
            mult = 1.55
            self.stamina = max(0.0, self.stamina - (0.0 if self.boost_t > 0 else 1.45) * dt)
            if self.stamina <= 0:
                self.exhausted = True
            if random.random() < 0.42 * dt:
                particles.append(Particle(
                    self.x - dx * 12, self.y - dy * 12,
                    -dx * 1.3 + random.uniform(-0.7, 0.7),
                    -dy * 1.3 + random.uniform(-0.7, 0.7),
                    (205, 220, 180), random.randint(2, 4), 18))
        else:
            self.stamina = min(self.max_stamina, self.stamina + 0.6 * dt)

        if self.charging:
            mult *= 0.88
        if self.boost_t > 0:
            mult = min(mult * 1.22, 1.8)

        tvx = dx * self.max_speed * mult
        tvy = dy * self.max_speed * mult

        a = 0.45 if moving_input else 0.30
        self.vx = lerp(self.vx, tvx, ease(a, dt))
        self.vy = lerp(self.vy, tvy, ease(a, dt))
        if not moving_input:
            f = (0.7 if self.frozen_t > 0 else 0.85) ** dt
            self.vx *= f
            self.vy *= f

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.clamp_to_field()

        speed = math.hypot(self.vx, self.vy)
        if speed > 2.5 and random.random() < 0.16 * dt:
            particles.append(Particle(
                self.x - self.vx * 1.8,
                self.y - self.vy * 1.8 + self.radius * 0.65,
                random.uniform(-0.5, 0.5), random.uniform(-0.4, 0.4),
                (170, 195, 145), random.randint(2, 4), 14))

        self.tick_timers(dt)

    # --- drawing ------------------------------------------------

    def draw(self, surface):
        speed = math.hypot(self.vx, self.vy)
        moving = speed > 0.7

        surface.blit(PLAYER_SHADOW, (int(self.x - 33), int(self.y + 17)))

        bounce = math.sin(self.animation_time * 1.8) * min(3.0, speed * 0.5) if moving else \
            math.sin(self.animation_time * 0.7) * 1.2
        stretch = 1.0 + min(0.10, speed * 0.014) + self.squash * 0.10

        body_w = int(self.radius * 2 * stretch)
        body_h = int(self.radius * 2 / stretch)

        body_rect = pygame.Rect(
            int(self.x - body_w / 2),
            int(self.y - body_h / 2 + bounce),
            body_w, body_h)

        # Body silhouette is player-customizable: each shape gets a contrasting outline.
        body_shape_rect = body_rect.inflate(5, 5)
        def silhouette(rect):
            cx, cy = rect.center
            left, right, top, bottom = rect.left, rect.right, rect.top, rect.bottom
            if self.shape == "SQUARE":
                return "rect", rect, 9
            if self.shape == "DIAMOND":
                return "poly", [(cx, top), (right, cy), (cx, bottom), (left, cy)], 0
            if self.shape == "HEXAGON":
                return "poly", [(left + rect.w * .25, top), (right - rect.w * .25, top),
                                 (right, cy), (right - rect.w * .25, bottom),
                                 (left + rect.w * .25, bottom), (left, cy)], 0
            if self.shape == "STAR":
                pts = []
                for i in range(10):
                    ang = -math.pi / 2 + i * math.pi / 5
                    rad = (0.52 if i % 2 == 0 else 0.25)
                    pts.append((cx + math.cos(ang) * rect.w * rad,
                                cy + math.sin(ang) * rect.h * rad))
                return "poly", pts, 0
            if self.shape == "SHIELD":
                return "poly", [(left + rect.w * .12, top), (right - rect.w * .12, top),
                                 (right, top + rect.h * .52), (cx, bottom),
                                 (left, top + rect.h * .52)], 0
            return "ellipse", rect, 0

        for rect, col, stroke in ((body_shape_rect, self.dark_color, False),
                                  (body_rect, self.color, True)):
            kind, geo, radius = silhouette(rect)
            if self.flash_timer > 0 and not stroke:
                pygame.draw.ellipse(surface, GOLD, body_rect.inflate(11, 11))
            if kind == "ellipse":
                pygame.draw.ellipse(surface, col, geo)
            elif kind == "rect":
                pygame.draw.rect(surface, col, geo, border_radius=radius)
            else:
                pygame.draw.polygon(surface, col, geo)
        highlight = pygame.Rect(body_rect.x + 6, body_rect.y + 5,
                                max(4, body_rect.w // 3), max(5, body_rect.h // 3))
        if self.shape in ("ROUND", "SQUARE"):
            pygame.draw.ellipse(surface, self.light_color, highlight)
        else:
            pygame.draw.circle(surface, self.light_color,
                               (int(self.x - body_w * .13), int(self.y - body_h * .18 + bounce)),
                               max(4, int(self.radius * .18)))
        # Contrasting kit stripe and collar make each custom uniform readable in motion.
        stripe_y = int(self.y + bounce)
        pygame.draw.line(surface, self.accent_color,
                         (int(self.x - body_w * 0.27), stripe_y),
                         (int(self.x + body_w * 0.27), stripe_y), max(3, int(self.radius * 0.22)))
        pygame.draw.circle(surface, self.accent_color,
                           (int(self.x), int(self.y - body_h * 0.28 + bounce)), 3)

        # Goal celebration: both arms rise and wave while the player hops.
        fx, fy = self.facing_x, self.facing_y
        perp_x, perp_y = -fy, fx
        if self.celebration_timer > 0:
            wave = math.sin(self.animation_time * 0.42) * 5
            lift = 19 + abs(math.sin(self.animation_time * 0.28)) * 8
            for side in (-1, 1):
                shoulder = (int(self.x + side * 12), int(self.y + bounce - 5))
                hand = (int(self.x + side * 27 + wave * side),
                        int(self.y + bounce - lift - 8))
                elbow = (int(self.x + side * 21), int(self.y + bounce - lift * 0.48))
                pygame.draw.line(surface, self.dark_color, shoulder, elbow, 9)
                pygame.draw.line(surface, self.light_color, shoulder, elbow, 6)
                pygame.draw.line(surface, self.dark_color, elbow, hand, 8)
                pygame.draw.line(surface, self.light_color, elbow, hand, 5)
                pygame.draw.circle(surface, WHITE, hand, 5)

        fx, fy = self.facing_x, self.facing_y
        face_x = self.x + fx * 8
        face_y = self.y + fy * 8 + bounce
        perp_x, perp_y = -fy, fx

        for side in (-1, 1):
            ex = face_x + perp_x * 7 * side
            ey = face_y + perp_y * 7 * side - 4
            pygame.draw.circle(surface, WHITE, (int(ex), int(ey)), 5)
            pygame.draw.circle(surface, BLACK, (int(ex + fx * 1.9), int(ey + fy * 1.9)), 2)

        kick = self.kick_timer > 0
        stride = math.sin(self.animation_time * 2.3) * min(4, speed * 0.7) if moving else 0

        for side in (-1, 1):
            foot_x = self.x + perp_x * side * 9 - fx * 2
            foot_y = self.y + perp_y * side * 9 + 18 + stride * side
            if kick and side == 1:
                foot_x += fx * 14
                foot_y += fy * 14
            pygame.draw.ellipse(surface, GOLD if kick and side == 1 else BLACK,
                                (int(foot_x - 7), int(foot_y - 4), 15, 9))

        if self.tackle_timer > 0:
            pygame.draw.circle(surface, GOLD, (int(self.x), int(self.y)),
                               int(self.radius + 8 + (12 - self.tackle_timer)), 2)

        # Speed aura: orbiting sparks and a soft pulsing ring make boosts feel punchier.
        tt = self.animation_time
        if speed > 4.8 or self.boost_t > 0:
            pulse = 1 + math.sin(tt * 0.7) * 0.12
            ring_col = self.accent_color if self.boost_t > 0 else self.light_color
            pygame.draw.circle(surface, ring_col, (int(self.x), int(self.y)),
                               int((self.radius + 8) * pulse), 2)
            for i in range(4):
                ang = tt * 0.22 + i * math.tau / 4
                sx = int(self.x + math.cos(ang) * (self.radius + 10))
                sy = int(self.y + math.sin(ang) * (self.radius + 10))
                pygame.draw.circle(surface, ring_col, (sx, sy), 2 + (i % 2))

        # Power-up auras.
        if self.boost_t > 0:
            pygame.draw.circle(surface, PU_COLORS[0], (int(self.x), int(self.y)),
                               int(self.radius + 7 + math.sin(tt * 3) * 2), 2)
        if self.mega_t > 0:
            pygame.draw.circle(surface, PU_COLORS[1], (int(self.x), int(self.y)),
                               int(self.radius + 12 + math.sin(tt * 2.2 + 1) * 2), 2)
        if self.frozen_t > 0:
            ice = pygame.Surface((76, 76), pygame.SRCALPHA)
            pygame.draw.ellipse(ice, (150, 220, 255, 120), (10, 10, 56, 56))
            pygame.draw.ellipse(ice, (225, 247, 255, 220), (10, 10, 56, 56), 3)
            surface.blit(ice, (int(self.x - 38), int(self.y - 38 + bounce)))

        # Shot charge ring.
        if self.charging and self.charge > 0.03:
            r = self.radius + 10
            steps = max(2, int(36 * self.charge))
            pts = []
            for i in range(steps + 1):
                ang = -math.pi / 2 + (i / steps) * math.tau * self.charge
                pts.append((self.x + math.cos(ang) * r, self.y + math.sin(ang) * r))
            col = (int(lerp(GOLD[0], RED[0], self.charge)),
                   int(lerp(GOLD[1], RED[1], self.charge)),
                   int(lerp(GOLD[2], RED[2], self.charge)))
            pygame.draw.lines(surface, col, False, pts, 4)

        # Stamina bar.
        bar_w, bar_h = 48, 5
        bar_x = int(self.x - bar_w / 2)
        bar_y = int(self.y - self.radius - 18)
        pygame.draw.rect(surface, (50, 55, 60), (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        fill = int(bar_w * self.stamina / self.max_stamina)
        if fill > 0:
            pygame.draw.rect(surface, GOLD if not self.exhausted else RED,
                             (bar_x, bar_y, fill, bar_h), border_radius=3)

        # Remaining time of active power-ups, drawn under the feet.
        by = int(self.y + self.radius + 22)
        for left, dur, col in ((self.boost_t, PU_DUR[0], PU_COLORS[0]),
                               (self.mega_t, PU_DUR[1], PU_COLORS[1])):
            if left > 0:
                pygame.draw.rect(surface, col, (bar_x, by, max(2, int(bar_w * left / dur)), 3),
                                 border_radius=2)
                by += 5


# ============================================================
# SOCCER BALL
# ============================================================


class SoccerBall:
    MAX_SPEED = 24.0

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.radius = 13
        self.vx = 0.0
        self.vy = 0.0
        self.friction = 0.986
        self.bounce = 0.74
        self.kick_cooldown = 0.0
        self.possession_lock = 0.0
        self.steal_lock = 0.0
        self.owner = None
        self.rotation = 0.0
        self.trail = []
        self.post_hit = False
        self.last_shot_origin = None
        self.last_shot_side = None

    def give_to(self, player):
        if self.owner and self.owner is not player:
            self.owner.has_ball = False
        self.owner = player
        player.has_ball = True
        self.steal_lock = 18.0     # brief protection so possession doesn't flip-flop
        self.vx = self.vy = 0.0

    def release_owner(self):
        if self.owner:
            self.owner.has_ball = False
        self.owner = None

    def keep_in_bounds(self):
        self.y = clamp(self.y, FIELD_TOP + self.radius, FIELD_BOTTOM - self.radius)
        if not (GOAL_TOP <= self.y <= GOAL_BOTTOM):
            self.x = clamp(self.x, FIELD_LEFT + self.radius, FIELD_RIGHT - self.radius)

    def dribble_with(self, player, dt):
        fx, fy = normalize(player.facing_x, player.facing_y,
                           (-1.0 if player.is_p2 else 1.0, 0.0))
        sx, sy = -fy, fx
        wobble = math.sin(player.dribble_phase) * 3
        distance = 34 + min(8, math.hypot(player.vx, player.vy) * 0.7)
        tx = player.x + fx * distance + sx * wobble
        ty = player.y + fy * distance + sy * wobble
        t = ease(0.60, dt)
        self.x = lerp(self.x, tx, t)
        self.y = lerp(self.y, ty, t)
        self.vx = player.vx * 0.65
        self.vy = player.vy * 0.65
        self.keep_in_bounds()

    def update(self, dt, particles):
        self.kick_cooldown = max(0.0, self.kick_cooldown - dt)
        self.possession_lock = max(0.0, self.possession_lock - dt)
        self.steal_lock = max(0.0, self.steal_lock - dt)
        self.post_hit = False

        if self.owner:
            self.dribble_with(self.owner, dt)
            self.rotation += math.hypot(self.owner.vx, self.owner.vy) * 0.1 * dt
            self.trail.clear()
            return

        self.x += self.vx * dt
        self.y += self.vy * dt
        f = self.friction ** dt
        self.vx *= f
        self.vy *= f
        speed = math.hypot(self.vx, self.vy)
        self.rotation += speed * 0.08 * dt

        if self.y - self.radius < FIELD_TOP:
            self.y = FIELD_TOP + self.radius
            self.vy = abs(self.vy) * self.bounce
        if self.y + self.radius > FIELD_BOTTOM:
            self.y = FIELD_BOTTOM - self.radius
            self.vy = -abs(self.vy) * self.bounce

        in_goal = GOAL_TOP <= self.y <= GOAL_BOTTOM
        if self.x - self.radius < FIELD_LEFT and not in_goal:
            self.x = FIELD_LEFT + self.radius
            self.vx = abs(self.vx) * self.bounce
        if self.x + self.radius > FIELD_RIGHT and not in_goal:
            self.x = FIELD_RIGHT - self.radius
            self.vx = -abs(self.vx) * self.bounce

        # Inside the net: back and side walls.
        if self.x < FIELD_LEFT or self.x > FIELD_RIGHT:
            self.y = clamp(self.y, GOAL_TOP + self.radius, GOAL_BOTTOM - self.radius)
            if self.x < LEFT_GOAL.left + self.radius:
                self.x = LEFT_GOAL.left + self.radius
                self.vx = abs(self.vx) * 0.25
            if self.x > RIGHT_GOAL.right - self.radius:
                self.x = RIGHT_GOAL.right - self.radius
                self.vx = -abs(self.vx) * 0.25

        # Goal posts.
        for px, py in POSTS:
            dx, dy = self.x - px, self.y - py
            d = math.hypot(dx, dy)
            m = self.radius + POST_R
            if d < m:
                if d < 0.001:
                    dx, dy, d = 1.0, 0.0, 1.0
                nx, ny = dx / d, dy / d
                self.x = px + nx * m
                self.y = py + ny * m
                dot = self.vx * nx + self.vy * ny
                if dot < 0:
                    self.vx -= 1.8 * dot * nx
                    self.vy -= 1.8 * dot * ny
                    if abs(dot) > 3:
                        self.post_hit = True
                        for _ in range(8):
                            particles.append(Particle(
                                px, py, random.uniform(-3, 3), random.uniform(-3, 3),
                                (255, 255, 255), random.randint(2, 3), 14))

        if speed > 7:
            self.trail.append((self.x, self.y))
            if len(self.trail) > 12:
                self.trail.pop(0)
        elif self.trail:
            self.trail.pop(0)

    def shoot(self, player, particles, charge=0.0):
        """Returns True if a kick actually happened."""
        speed_p = math.hypot(player.vx, player.vy)
        if self.owner is player:
            self.last_shot_origin = (float(player.x), float(player.y))
            self.last_shot_side = 2 if player.is_p2 else 1
            self.release_owner()
            fx, fy = normalize(player.facing_x, player.facing_y,
                               (-1.0 if player.is_p2 else 1.0, 0.0))
            self.x = player.x + fx * 34
            self.y = player.y + fy * 34
            power = 15.5 + charge * 8.5 + min(3, speed_p * 0.35)
            power *= 1.0 + int(getattr(player, "shooting_level", 0)) * 0.08
            if player.mega_t > 0:
                power *= 1.35
            self.vx = fx * power + player.vx * 0.25
            self.vy = fy * power + player.vy * 0.25
            self.keep_in_bounds()
        else:
            if self.owner is not None or self.kick_cooldown > 0:
                return False
            dx = self.x - player.x
            dy = self.y - player.y
            dist = math.hypot(dx, dy)
            if dist > 68:
                return False
            self.last_shot_origin = (float(player.x), float(player.y))
            self.last_shot_side = 2 if player.is_p2 else 1
            if dist < 0.001:
                dx, dy = player.facing_x, player.facing_y
                dist = max(0.001, math.hypot(dx, dy))
            nx, ny = dx / dist, dy / dist
            fl = math.hypot(player.facing_x, player.facing_y)
            if fl > 0.2:
                nx = nx * 0.55 + player.facing_x / fl * 0.45
                ny = ny * 0.55 + player.facing_y / fl * 0.45
                nx, ny = normalize(nx, ny)
            power = 14.5 + charge * 8.0 + min(3.5, speed_p * 0.4)
            power *= 1.0 + int(getattr(player, "shooting_level", 0)) * 0.08
            if player.mega_t > 0:
                power *= 1.35
            self.vx = nx * power + player.vx * 0.18
            self.vy = ny * power + player.vy * 0.18

        sp = math.hypot(self.vx, self.vy)
        cap = self.MAX_SPEED * (1.0 + int(getattr(player, "shooting_level", 0)) * 0.07) * (1.3 if player.mega_t > 0 else 1.0)
        if sp > cap:
            self.vx = self.vx / sp * cap
            self.vy = self.vy / sp * cap

        player.kick_timer = 12.0
        player.flash_timer = 5.0
        player.squash = 1.0
        self.kick_cooldown = 10.0
        self.possession_lock = 15.0
        particles.append(Particle(self.x, self.y, 0, 0, (255, 255, 255), 10, 16, ring=True))
        for _ in range(10 + int(charge * 10)):
            particles.append(Particle(
                self.x, self.y, random.uniform(-3.5, 3.5) + self.vx * 0.1,
                random.uniform(-3.5, 3.5) + self.vy * 0.1, GOLD, random.randint(2, 5), 20))
        return True

    def check_collision(self, player):
        """Returns 'steal' when the ball is won off the opponent."""
        dx = self.x - player.x
        dy = self.y - player.y
        dist = math.hypot(dx, dy)

        tackle_range = 80 + int(getattr(player, "defending_level", 0)) * 7
        if player.tackle_timer > 0 and self.owner and self.owner is not player and dist < tackle_range:
            self.give_to(player)
            self.possession_lock = 10.0
            return "steal"

        # Defending: simply touching the ball off the opponent wins possession.
        if self.owner:
            if (self.owner is not player and self.steal_lock <= 0
                    and dist < self.radius + player.radius + 2):
                self.give_to(player)
                self.possession_lock = 10.0
                return "steal"
            return None

        min_dist = self.radius + player.radius + 2
        if dist < min_dist:
            if self.possession_lock <= 0 and math.hypot(self.vx, self.vy) < 9.0:
                self.give_to(player)
                return None
            if dist < 0.001:
                dx, dy, dist = 1, 0, 1
            nx, ny = dx / dist, dy / dist
            overlap = min_dist - dist
            self.x += nx * overlap
            self.y += ny * overlap
            push = 2 + math.hypot(player.vx, player.vy) * 0.75
            self.vx += nx * push
            self.vy += ny * push
            speed = math.hypot(self.vx, self.vy)
            if speed > 19:
                self.vx = self.vx / speed * 19
                self.vy = self.vy / speed * 19
        return None

    def draw(self, surface):
        draw_ball(surface, self.x, self.y, self.radius, self.rotation)


# ============================================================
# GAME
# ============================================================


class Game:
    def __init__(self):
        self.blue_score = 0
        self.red_score = 0
        self.mode = None            # None / "pvp" / "bot" / "host" / "client"
        self.state = "menu"         # menu / online_menu / join / lobby / countdown / play / goal / paused / finished
        self.prev_state = "play"
        self.menu_selection = 0
        self.menu_rects = [pygame.Rect(W // 2 - 260, 200 + i * 76, 520, 64) for i in range(4)]
        self.on_rects = [pygame.Rect(W // 2 - 260, 175, 520, 70),
                         pygame.Rect(W // 2 - 260, 275, 520, 84),
                         pygame.Rect(W // 2 - 260, 375, 520, 84)]
        self.menu_t = 0.0

        self.font = load_font(30)
        self.small_font = load_font(17)
        self.tiny_font = load_font(15)
        self.big_font = load_font(64)
        self.title_font = load_font(78)
        self.menu_font = load_font(30)
        self.huge_font = load_font(150)

        self.match_duration = MATCH_SECONDS * 60.0
        self.clock_frames = 0.0

        self.goal_timer = 0.0
        self.goal_message = ""
        self.goal_color = GOLD
        self.goal_flash = 0.0
        self.countdown = 0.0
        self.countdown_total = 1.0
        self.go_timer = 0.0
        self.shake = 0.0
        self.fade = 255.0
        self.ui_t = 0.0

        self.particles = []
        self.fx_layer = pygame.Surface((W, H), pygame.SRCALPHA)
        self.canvas = pygame.Surface((W, H))
        self.field_surface = None
        self.vignette = self.build_vignette()

        self.bot_state = {"think": 0.0, "tx": W * 0.7, "ty": FIELD_CY, "lull": 0.0}

        self.running = True
        self.touch_held = set()
        self.touch_pointer_map = {}
        self.settings = {"len": MATCH_SECONDS, "pu": True, "bot": 1}
        self.sound = Sound()
        self.profile = self.load_profile()
        self.upgrade_keys = ("shooting", "pace", "defending")
        self.upgrade_titles = ("SHOOTING POWER", "PACE", "DEFENDING")
        self.upgrade_descriptions = (
            "Faster shots and a higher shot-speed cap",
            "Move quicker and close down the ball faster",
            "Stronger tackles with a wider steal range",
        )
        self.upgrade_rects = [pygame.Rect(64 + i * 365, 205, 342, 286) for i in range(3)]
        self.upgrade_back_rect = pygame.Rect(W // 2 - 105, 548, 210, 48)
        self.upgrades_return_state = "menu"
        self.shop_message = ""
        self.shop_message_timer = 0.0
        self.coin_message = ""
        self.coin_timer = 0.0
        self.last_match_reward = ""
        self.match_rewarded = False
        self.set_sel = 0
        self.settings_rect = pygame.Rect(W - 200, 22, 170, 46)
        self.customize_rect = pygame.Rect(30, 22, 190, 46)
        self.upgrade_rect = pygame.Rect(30, 80, 190, 46)
        self.kit_indices = [0, 1]
        self.shape_indices = [0, 0]
        self.shape_options = ("ROUND", "SQUARE", "DIAMOND", "HEXAGON", "STAR", "SHIELD")
        self.powerups = []
        self.pu_timer = 300.0
        self.overtime = False
        self.stats = self.new_stats()
        self.cd_last = 0
        self.snd_prev = "menu"

        # ---- online state ----
        self.name = f"Player{random.randint(10, 99)}"
        self.net = WebNet() if WEB_BUILD else Net()
        self.net_msg = ""
        self.online_sel = 1
        self.join_text = ""
        self.join_sel = 0
        self.lan_found = {}
        self.find_t = -10.0
        self.joining = None
        self.host_addr = None
        self.host_last = 0.0
        self.party_code = ""
        self.public_code = None
        self.public_state = ""
        self.guest_addr = None
        self.guest_name = None
        self.guest_ready = False
        self.guest_last = 0.0
        self.my_ready = False
        self.lobby_names = ["", ""]
        self.lobby_ready = [True, False]
        self.lobby_send_t = 0.0
        self.match_id = 0
        self.cur_mid = 0
        self.net_in = {"dx": 0, "dy": 0, "dash": False, "sh": False, "tk": 0, "t": 0.0}
        self.p2_sh_prev = False
        self.p2_tk_prev = 0
        self.ev_log = []
        self.ev_id = 0
        self.goal_history = []
        self.highlight_video_rect = pygame.Rect(W // 2 - 269, H - 62, 170, 42)
        self.highlight_rematch_rect = pygame.Rect(W // 2 - 85, H - 62, 170, 42)
        self.highlight_menu_rect = pygame.Rect(W // 2 + 99, H - 62, 170, 42)
        self.highlight_upgrade_rect = pygame.Rect(W // 2 + 282, H - 62, 170, 42)

        # In-game highlight-video recorder. Frames are sampled during live play;
        # each goal stores the few seconds leading up to the shot as a replay clip.
        self.replay_buffer = []
        self.replay_capture_accum = 0.0
        self.goal_replays = []
        self.replay_clip_i = 0
        self.replay_cursor = 0.0
        self.replay_playing = True
        self.replay_hold = 0.0
        self.replay_actor1 = None
        self.replay_actor2 = None
        self.replay_back_rect = pygame.Rect(36, H - 58, 190, 38)
        self.replay_pause_rect = pygame.Rect(W // 2 - 88, H - 58, 176, 38)
        self.replay_next_rect = pygame.Rect(W - 226, H - 58, 190, 38)
        self.last_ev = 0
        self.snap_buf = []
        self.clock_off = None
        self.snap_send_t = 0.0
        self.in_send_t = 0.0
        self.c_shoot = False
        self.c_tackle = 0
        self.ping = 0.0
        self.guest_ping = 0.0
        self.last_echo = 0.0
        self.host_t0 = time.perf_counter()
        self._repeat_on = False

        # Penalty shootout state (used both as a tiebreaker and as a standalone mode).
        self.penalty_standalone = False
        self.penalty_scores = [0, 0]
        self.penalty_taken = [0, 0]
        self.penalty_round = 0
        self.penalty_shooter = 0
        self.penalty_aim_x = 1
        self.penalty_aim_y = 1
        self.penalty_keeper_x = 1
        self.penalty_keeper_y = 1
        self.penalty_anim = 0.0
        self.penalty_result = ""
        self.penalty_last_scored = False
        self.penalty_wait = 0.0
        self.penalty_finished = False
        self.penalty_winner = None
        self.penalty_report_delay = 0.0

        self.reset_positions()
        self.menu_p1 = Player(0, 0, BLUE, BLUE_DARK, BLUE_LIGHT, False)
        self.menu_p2 = Player(0, 0, RED, RED_DARK, RED_LIGHT, True)
        self.apply_kit(self.menu_p1, self.kit_indices[0])
        self.apply_kit(self.menu_p2, self.kit_indices[1])
        self.apply_shape(self.menu_p1, self.shape_indices[0])
        self.apply_shape(self.menu_p2, self.shape_indices[1])
        self.apply_profile_to_player(self.menu_p1)

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    def apply_kit(self, player, index):
        name, main, dark, light, accent = KITS[index % len(KITS)]
        player.kit_name = name
        player.color, player.dark_color, player.light_color = main, dark, light
        player.accent_color = accent

    def apply_shape(self, player, index):
        player.shape = self.shape_options[index % len(self.shape_options)]

    def load_profile(self):
        """Load a tiny local career save; defaults give a new player 60 coins."""
        profile = {
            "coins": 60,
            "upgrades": {"shooting": 0, "pace": 0, "defending": 0},
            "total_goals": 0,
            "wins": 0,
            "matches": 0,
        }
        self.profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "hyper_soccer_profile.json")
        try:
            with open(self.profile_path, "r", encoding="utf-8") as save:
                stored = json.load(save)
            if not isinstance(stored, dict):
                raise ValueError("Invalid career save format")
            profile["coins"] = max(0, int(stored.get("coins", profile["coins"])))
            profile["total_goals"] = max(0, int(stored.get("total_goals", 0)))
            profile["wins"] = max(0, int(stored.get("wins", 0)))
            profile["matches"] = max(0, int(stored.get("matches", 0)))
            saved_upgrades = stored.get("upgrades", {})
            if not isinstance(saved_upgrades, dict):
                saved_upgrades = {}
            for key in profile["upgrades"]:
                profile["upgrades"][key] = int(clamp(int(saved_upgrades.get(key, 0)), 0, 5))
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            pass
        return profile

    def save_profile(self):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as save:
                json.dump(self.profile, save, indent=2)
        except OSError:
            # The game can still be played if the folder is read-only.
            self.shop_message = "Could not save career data in this folder."
            self.shop_message_timer = 120.0

    def apply_profile_to_player(self, player):
        # Career boosts are intentionally disabled in network matches so both
        # connected players keep identical movement and shot physics.
        levels = ({} if self.mode in ("host", "client") else self.profile["upgrades"])
        player.shooting_level = int(levels.get("shooting", 0))
        player.pace_level = int(levels.get("pace", 0))
        player.defending_level = int(levels.get("defending", 0))
        player.max_speed = 6.2 + player.pace_level * 0.38

    def upgrade_cost(self, key):
        level = int(self.profile["upgrades"].get(key, 0))
        base, step = {"shooting": (55, 45), "pace": (50, 40), "defending": (50, 42)}[key]
        return base + level * step

    def open_upgrades(self, return_state=None):
        self.upgrades_return_state = return_state or self.state
        self.state = "upgrades"
        self.sound.play("menuok")

    def buy_upgrade(self, index):
        if not 0 <= index < len(self.upgrade_keys):
            return
        key = self.upgrade_keys[index]
        level = int(self.profile["upgrades"].get(key, 0))
        if level >= 5:
            self.shop_message = f"{self.upgrade_titles[index]} IS MAXED OUT!"
            self.shop_message_timer = 95.0
            self.sound.play("click")
            return
        cost = self.upgrade_cost(key)
        if self.profile["coins"] < cost:
            self.shop_message = f"NOT ENOUGH COINS — NEED {cost - self.profile['coins']} MORE."
            self.shop_message_timer = 110.0
            self.sound.play("click")
            return
        self.profile["coins"] -= cost
        self.profile["upgrades"][key] = level + 1
        self.apply_profile_to_player(self.p1)
        self.apply_profile_to_player(self.menu_p1)
        self.save_profile()
        self.shop_message = f"UPGRADE BOUGHT: {self.upgrade_titles[index]}  LV {level + 1}!"
        self.shop_message_timer = 120.0
        self.sound.play("pickup")
        for _ in range(20):
            self.particles.append(Particle(W // 2, 178, random.uniform(-4, 4),
                random.uniform(-5, 1), GOLD, random.randint(2, 4), random.randint(24, 38)))

    def events_upgrades(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self.upgrade_rects):
                if rect.collidepoint(event.pos):
                    self.buy_upgrade(i)
                    return
            if self.upgrade_back_rect.collidepoint(event.pos):
                self.state = self.upgrades_return_state
                self.sound.play("click")
        elif event.type == pygame.KEYDOWN:
            k = event.key
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.state = self.upgrades_return_state
                self.sound.play("click")
            elif k in (pygame.K_1, pygame.K_KP1):
                self.buy_upgrade(0)
            elif k in (pygame.K_2, pygame.K_KP2):
                self.buy_upgrade(1)
            elif k in (pygame.K_3, pygame.K_KP3):
                self.buy_upgrade(2)
            elif k == pygame.K_n:
                self.toggle_sound()

    def cycle_kit(self, side, delta):
        self.kit_indices[side] = (self.kit_indices[side] + delta) % len(KITS)
        for player in ((self.menu_p1, self.p1) if side == 0 else (self.menu_p2, self.p2)):
            self.apply_kit(player, self.kit_indices[side])
        self.sound.play("menuok")

    def cycle_shape(self, side, delta):
        self.shape_indices[side] = (self.shape_indices[side] + delta) % len(self.shape_options)
        for player in ((self.menu_p1, self.p1) if side == 0 else (self.menu_p2, self.p2)):
            self.apply_shape(player, self.shape_indices[side])
        self.sound.play("menuok")

    def open_customize(self):
        self.state = "customize"
        self.sound.play("menuok")

    def reset_positions(self):
        self.p1 = Player(FIELD_LEFT + 180, FIELD_CY, BLUE, BLUE_DARK, BLUE_LIGHT, False)
        self.p2 = Player(FIELD_RIGHT - 180, FIELD_CY, RED, RED_DARK, RED_LIGHT, True)
        self.apply_kit(self.p1, self.kit_indices[0])
        self.apply_kit(self.p2, self.kit_indices[1])
        self.apply_shape(self.p1, self.shape_indices[0])
        self.apply_shape(self.p2, self.shape_indices[1])
        self.apply_profile_to_player(self.p1)
        self.ball = SoccerBall(W // 2, FIELD_CY)
        self.powerups = []
        self.bot_state.update({"think": 20.0, "lull": 0.0})

    def begin_countdown(self, frames):
        self.state = "countdown"
        self.countdown = float(frames)
        self.countdown_total = float(frames)

    def start_match(self, mode):
        self.mode = mode
        self.blue_score = 0
        self.red_score = 0
        self.clock_frames = 0.0
        self.match_duration = self.settings["len"] * 60.0
        self.overtime = False
        self.stats = self.new_stats()
        self.match_rewarded = False
        self.coin_message = ""
        self.coin_timer = 0.0
        self.last_match_reward = ""
        self.goal_history = []
        self.replay_buffer = []
        self.replay_capture_accum = 0.0
        self.goal_replays = []
        self.replay_clip_i = 0
        self.replay_cursor = 0.0
        self.replay_playing = True
        self.replay_hold = 0.0
        self.penalty_standalone = False
        self.penalty_scores = [0, 0]
        self.penalty_taken = [0, 0]
        self.penalty_finished = False
        self.penalty_winner = None
        self.penalty_report_delay = 0.0
        self.pu_timer = 300.0
        self.goal_timer = 0.0
        self.goal_flash = 0.0
        self.shake = 0.0
        self.go_timer = 0.0
        self.fade = 255.0
        self.particles.clear()
        self.reset_positions()
        self.begin_countdown(150)

    # --------------------------------------------------------
    # MATCH FLOW, POWER-UPS, AUDIO CUES
    # --------------------------------------------------------

    def new_stats(self):
        return {"shots": [0, 0], "steals": [0, 0], "poss": [0.0, 0.0], "pu": [0, 0]}

    def end_regulation(self):
        """Full time: a tie goes to golden-goal overtime, otherwise the match ends."""
        if self.blue_score == self.red_score and self.mode not in ("host", "client"):
            self.start_penalty_shootout(standalone=False)
        else:
            # The current network protocol syncs regular match states only; keep online
            # games stable rather than desynchronizing the host and guest at full time.
            self.finish_match()

    def spawn_powerup(self):
        for _ in range(25):
            x = random.uniform(FIELD_LEFT + 230, FIELD_RIGHT - 230)
            y = random.uniform(FIELD_TOP + 60, FIELD_BOTTOM - 60)
            if any(math.hypot(x - p.x, y - p.y) < 120 for p in (self.p1, self.p2)):
                continue
            if math.hypot(x - self.ball.x, y - self.ball.y) < 70:
                continue
            if any(math.hypot(x - q["x"], y - q["y"]) < 160 for q in self.powerups):
                continue
            self.powerups.append({"t": random.randint(0, 2), "x": x, "y": y})
            return

    def update_powerups(self, dt):
        if self.settings["pu"]:
            self.pu_timer -= dt
            if self.pu_timer <= 0:
                self.pu_timer = random.uniform(420, 780)
                if len(self.powerups) < 2:
                    self.spawn_powerup()
        for pu in self.powerups[:]:
            for idx, p in ((1, self.p1), (2, self.p2)):
                if math.hypot(p.x - pu["x"], p.y - pu["y"]) < p.radius + 20:
                    self.collect_powerup(pu, idx)
                    break

    def collect_powerup(self, pu, idx):
        p = self.p1 if idx == 1 else self.p2
        foe = self.p2 if idx == 1 else self.p1
        kind = pu["t"]
        if pu in self.powerups:
            self.powerups.remove(pu)
        self.stats["pu"][idx - 1] += 1
        if kind == 0:
            p.boost_t = PU_DUR[0]
        elif kind == 1:
            p.mega_t = PU_DUR[1]
        else:
            foe.frozen_t = PU_DUR[2]
            foe.charging = False
            foe.charge = 0.0
            foe.vx *= 0.3
            foe.vy *= 0.3
        self.pu_burst(pu["x"], pu["y"], kind, idx)
        self.emit("pu", pu["x"], pu["y"], kind + idx * 10)

    def pu_burst(self, x, y, kind, idx):
        col = PU_COLORS[kind % 3]
        self.particles.append(Particle(x, y, 0, 0, col, 14, 26, ring=True))
        for _ in range(26):
            a = random.uniform(0, math.tau)
            sp = random.uniform(1.5, 6)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, col,
                                           random.randint(2, 5), random.randint(20, 36), 0.03))
        self.shake = max(self.shake, 3.0)

    def event_sound(self, typ, ex=0.0):
        if typ == "kick":
            self.sound.play("kick", 0.55 + 0.45 * clamp(ex, 0.0, 1.0))
        elif typ == "tk":
            self.sound.play("tackle", 0.8)
        elif typ == "steal":
            self.sound.play("steal")
        elif typ == "post":
            self.sound.play("post")
        elif typ == "pu":
            self.sound.play("freeze" if int(ex) % 10 == 2 else "pickup")

    def toggle_sound(self):
        self.sound.on = not self.sound.on
        self.sound.play("click")

    def audio_cues(self):
        """Countdown beeps, kick-off whistle and the final whistle (host, solo and guest)."""
        st = self.state
        if st == "countdown" and self.countdown_total > 0:
            part = self.countdown_total / 3.0
            num = max(1, math.ceil(self.countdown / part))
            if num != self.cd_last:
                self.cd_last = num
                self.sound.play("beep")
        elif self.cd_last:
            self.cd_last = 0
            if st == "play":
                self.sound.play("go")
                self.sound.play("whistle")
        if st == "finished" and self.snd_prev != "finished":
            self.sound.play("whistle")
            if self.blue_score != self.red_score:
                self.sound.play("win")
        self.snd_prev = st

    def return_to_menu(self):
        self.net.close()
        self.mode = None
        self.state = "menu"
        self.particles.clear()
        self.fade = 255.0
        self.reset_positions()

    def side_name(self, n):
        if self.mode in ("host", "client"):
            nm = self.lobby_names[n - 1] or ("BLUE", "RED")[n - 1]
            return nm.upper()[:10]
        return "BLUE" if n == 1 else "RED"

    # --------------------------------------------------------
    # ONLINE: session management
    # --------------------------------------------------------

    def open_online_menu(self):
        self.state = "online_menu"
        self.online_sel = 1
        self.net_msg = ""

    def start_hosting(self):
        try:
            self.net.open("host")
        except OSError as e:
            self.net_msg = f"Could not open UDP port {NET_PORT}: {e.strerror or e}"
            return
        self.mode = "host"
        self.state = "lobby"
        self.guest_addr = None
        self.guest_name = None
        self.guest_ready = False
        self.lobby_names = [self.name, ""]
        self.lobby_ready = [True, False]
        self.party_code = "..." if WEB_BUILD else encode_code(local_ip())
        self.public_code = None
        self.public_state = ""
        self.net_msg = ""
        self.match_id = 0
        self.ev_log.clear()
        self.fade = 255.0

    def open_join(self):
        try:
            self.net.open("client")
        except OSError as e:
            self.net_msg = f"Network error: {e.strerror or e}"
            return
        self.state = "join"
        self.mode = None
        self.lan_found.clear()
        self.join_text = ""
        self.join_sel = 0
        self.joining = None
        self.find_t = -10.0
        self.net_msg = ""

    def try_join(self, addr):
        if not addr:
            return
        self.joining = {"addr": addr, "start": time.perf_counter(), "last": -10.0}
        self.net_msg = "Connecting..."

    def join_submit(self):
      text = self.join_text.strip()
      if WEB_BUILD:
        if len(text) < 4:
          self.net_msg = "Type the 5-letter room code from your friend."
          return
        self.try_join(("relay", 0))
        return
      if text:
        target = parse_target(text)
        if target is None:
          self.net_msg = "That doesn't look like a party code or IP address."
          return
        self.try_join(target)
      else:
        lst = self.lan_list()
        if lst:
          self.try_join(lst[clamp(self.join_sel, 0, len(lst) - 1)])
        else:
          self.net_msg = (
              "Type a party code or IP address, or wait for a party to appear."
          )



    def lan_list(self):
        return sorted(self.lan_found.items(), key=lambda kv: (kv[1]["name"], kv[0]))[:4]

    def leave_party(self, msg=""):
        n = self.net
        if n.role == "client" and self.host_addr and self.mode == "client":
            for _ in range(3):
                n.send({"t": "leave"}, self.host_addr)
        elif n.role == "host" and self.guest_addr:
            for _ in range(3):
                n.send({"t": "closed"}, self.guest_addr)
        n.close()
        self.mode = None
        self.guest_addr = None
        self.host_addr = None
        self.joining = None
        self.particles.clear()
        self.reset_positions()
        self.snap_buf.clear()
        self.clock_off = None
        self.c_shoot = False
        self.c_tackle = 0
        self.state = "online_menu"
        self.online_sel = 1
        self.net_msg = msg
        self.fade = 255.0

    def net_shutdown(self):
        if self.net.role:
            self.leave_party()

    def host_to_lobby(self, msg=""):
        self.state = "lobby"
        self.particles.clear()
        self.reset_positions()
        self.guest_ready = False
        self.p2_sh_prev = False
        self.lobby_names = [self.name, self.guest_name or ""]
        self.lobby_send_t = -10.0
        self.net_msg = msg
        self.fade = 255.0

    def client_to_lobby(self):
        self.state = "lobby"
        self.particles.clear()
        self.snap_buf.clear()
        self.my_ready = False
        self.c_shoot = False
        self.fade = 255.0

    def host_start_match(self):
        if not self.guest_addr:
            self.net_msg = "Waiting for a player to join."
            return
        if not self.guest_ready:
            self.net_msg = "Waiting for the other player to ready up."
            return
        self.net_msg = ""
        self.match_id += 1
        self.ev_log.clear()
        self.lobby_names = [self.name, self.guest_name or ""]
        self.p2_sh_prev = False
        self.p2_tk_prev = self.net_in["tk"]
        self.start_match("host")

    def drop_guest(self, reason):
        self.guest_addr = None
        self.guest_name = None
        self.guest_ready = False
        self.lobby_names = [self.name, ""]
        if self.state in GAME_STATES:
            self.host_to_lobby(reason)
        else:
            self.net_msg = reason

    def lookup_public(self):
        if self.public_state == "loading":
            return
        self.public_state = "loading"

        def work():
            try:
                import urllib.request
                ip = urllib.request.urlopen("https://api.ipify.org", timeout=4).read().decode().strip()
                self.public_code = encode_code(ip)
                self.public_state = "done"
            except Exception:
                self.public_state = "error"

        threading.Thread(target=work, daemon=True).start()

    def emit(self, typ, x=0.0, y=0.0, extra=0.0):
        """Play the sound locally; as host also record the event so the guest can mirror it."""
        self.event_sound(typ, extra)
        if self.mode != "host":
            return
        self.ev_id += 1
        ht = time.perf_counter() - self.host_t0
        self.ev_log.append([self.ev_id, typ, round(x, 1), round(y, 1), round(extra, 2), ht])
        if len(self.ev_log) > 16:
            self.ev_log.pop(0)

    # --------------------------------------------------------
    # ONLINE: message pumps
    # --------------------------------------------------------

    def net_pump(self):
        now = time.perf_counter()
        msgs = self.net.poll()
        if self.net.role == "host":
            self.host_pump(msgs, now)
        elif self.net.role == "client":
            self.client_pump(msgs, now)

    def host_pump(self, msgs, now):
        net = self.net
        if WEB_BUILD:
          if net.room_code:
            self.party_code = net.room_code
          if net.err:
            self.net_msg = net.err
        
        for msg, addr in msgs:
            try:
                t = msg.get("t")
                if t == "find":
                    net.send({"t": "here", "name": self.name,
                              "n": 1 + (1 if self.guest_addr else 0),
                              "ph": "lobby" if self.state == "lobby" else "play",
                              "code": self.party_code}, addr)
                elif t == "join":
                    if msg.get("v") != PROTO:
                        net.send({"t": "bad_ver"}, addr)
                    elif addr == self.guest_addr:
                        self.guest_last = now
                        net.send({"t": "welcome", "names": self.lobby_names}, addr)
                    elif self.guest_addr is None and self.state == "lobby":
                        self.guest_addr = addr
                        self.guest_name = clean_name(msg.get("name"))
                        self.guest_ready = False
                        self.guest_last = now
                        self.lobby_names = [self.name, self.guest_name]
                        self.net_in = {"dx": 0, "dy": 0, "dash": False, "sh": False, "tk": 0, "t": 0.0}
                        self.lobby_send_t = -10.0
                        self.net_msg = ""
                        net.send({"t": "welcome", "names": self.lobby_names}, addr)
                    else:
                        net.send({"t": "full"}, addr)
                elif addr == self.guest_addr:
                    self.guest_last = now
                    if t == "cl":
                        self.guest_ready = bool(msg.get("r"))
                    elif t == "in":
                        self.net_in = {
                            "dx": clamp(float(msg.get("dx", 0)), -1, 1),
                            "dy": clamp(float(msg.get("dy", 0)), -1, 1),
                            "dash": bool(msg.get("d")),
                            "sh": bool(msg.get("sh")),
                            "tk": int(msg.get("tk", 0)),
                            "t": now,
                        }
                        self.last_echo = float(msg.get("ts", 0))
                        self.guest_ping = float(msg.get("pg", 0))
                    elif t == "leave":
                        self.drop_guest("The other player left the party")
            except (TypeError, ValueError, KeyError, AttributeError):
                continue

        if self.guest_addr and now - self.guest_last > 6.0:
            self.drop_guest("The other player timed out")

        if self.state == "lobby" and self.guest_addr and now - self.lobby_send_t > 0.2:
            self.lobby_send_t = now
            net.send({"t": "lobby", "names": self.lobby_names,
                      "ready": [True, self.guest_ready], "ph": "lobby",
                      "mid": self.match_id}, self.guest_addr)

    def client_pump(self, msgs, now):
        net = self.net
        for msg, addr in msgs:
            try:
                t = msg.get("t")
                if t == "here":
                    self.lan_found[addr] = {"name": clean_name(msg.get("name"), "Party"),
                                            "n": int(msg.get("n", 1)),
                                            "ph": msg.get("ph", "lobby"), "seen": now}
                elif t == "welcome" and self.joining and self.state == "join":
                    names = msg.get("names") or ["", ""]
                    self.host_addr = addr
                    self.host_last = now
                    self.mode = "client"
                    self.state = "lobby"
                    self.joining = None
                    self.my_ready = False
                    self.cur_mid = 0
                    self.net_msg = ""
                    self.snap_buf.clear()
                    self.clock_off = None
                    self.c_shoot = False
                    self.c_tackle = 0
                    self.lobby_names = [str(names[0] or ""), str(names[1] or self.name)]
                    self.lobby_ready = [True, False]
                    self.fade = 255.0
                elif t in ("full", "bad_ver") and self.joining and self.state == "join":
                    self.joining = None
                    self.net_msg = ("That party is full." if t == "full" else
                                    "That host runs a different version of the game.")
                elif self.mode == "client" and addr == self.host_addr:
                    self.host_last = now
                    if t == "lobby":
                        names = msg.get("names") or ["", ""]
                        self.lobby_names = [str(names[0] or ""), str(names[1] or self.name)]
                        self.lobby_ready = msg.get("ready") or [True, False]
                        if (self.state in GAME_STATES and msg.get("ph") == "lobby"
                                and int(msg.get("mid", 0)) >= self.cur_mid):
                            self.client_to_lobby()
                    elif t == "snap":
                        self.on_snap(msg, now)
                    elif t == "closed":
                        self.leave_party("The host closed the party")
                        return
            except (TypeError, ValueError, KeyError, AttributeError, IndexError):
                continue

        if self.state == "join":
          if WEB_BUILD:
            if net.err:
              self.joining = None
              self.net_msg = net.err
              net.err = ""
            if self.joining:
              j = self.joining
              if now - j["start"] > 25.0:
                self.joining = None
                self.net_msg = (
                    "Timed out. Check the 5-letter room code and try again."
                )
              elif net.ready and now - j["last"] > 0.6:
                j["last"] = now
                net.join_room(self.join_text)
                net.send({"t": "join", "name": self.name}, ("relay", 0))
          else:
            if now - self.find_t > 1.0:
              self.find_t = now
              net.broadcast({"t": "find"})
            for a in list(self.lan_found):
              if now - self.lan_found[a]["seen"] > 3.5:
                del self.lan_found[a]
            if self.joining:
              j = self.joining
              if now - j["start"] > 6.0:
                self.joining = None
                self.net_msg = (
                    "No answer from the host. Check the code/IP, the host's"
                    f" firewall and (over the internet) UDP port {NET_PORT}"
                    " forwarding."
                )
              elif now - j["last"] > 0.4:
                j["last"] = now
                net.send({"t": "join", "name": self.name}, j["addr"])


    def client_send_input(self, now):
        if now - self.in_send_t < 1.0 / 65.0:
            return
        self.in_send_t = now
        dx, dy, dash = self.combined_input(pygame.key.get_pressed())
        self.net.send({"t": "in", "dx": dx, "dy": dy, "d": int(bool(dash)),
                       "sh": int(self.c_shoot), "tk": self.c_tackle,
                       "ts": now, "pg": int(self.ping)}, self.host_addr)

    def host_send_snapshot(self, now):
        if now - self.snap_send_t < 1.0 / 65.0:
            return
        self.snap_send_t = now
        ht = now - self.host_t0
        b = self.ball
        owner = 1 if b.owner is self.p1 else (2 if b.owner is self.p2 else 0)
        snap = {"t": "snap", "ht": round(ht, 4), "mid": self.match_id,
                "st": STATE_IDX[self.state],
                "cd": r1(self.countdown), "ct": self.countdown_total,
                "cl": r1(self.clock_frames), "gt": r1(self.goal_timer),
                "s": [self.blue_score, self.red_score],
                "p": [pack_player(self.p1), pack_player(self.p2)],
                "b": [r2(b.x), r2(b.y), r2(b.vx), r2(b.vy), owner, r2(b.rotation)],
                "ev": [e[:5] for e in self.ev_log if ht - e[5] < 0.6][-8:],
                "e": self.last_echo, "pg": int(self.guest_ping),
                "ot": int(self.overtime), "md": int(self.match_duration),
                "pw": [[pu["t"], int(pu["x"]), int(pu["y"])] for pu in self.powerups],
                "x": [self.stats["shots"][0], self.stats["shots"][1],
                      self.stats["steals"][0], self.stats["steals"][1],
                      int(self.stats["poss"][0]), int(self.stats["poss"][1]),
                      self.stats["pu"][0], self.stats["pu"][1]]}
        self.net.send(snap, self.guest_addr)

    # --------------------------------------------------------
    # ONLINE: guest-side snapshot handling
    # --------------------------------------------------------

    def on_snap(self, msg, now):
        ht = float(msg["ht"])
        mid = int(msg.get("mid", 0))
        entering = self.state in MENU_STATES
        if entering:
            if mid <= self.cur_mid:
                return                      # stale packet from a finished match
            self.state = IDX_STATE.get(int(msg["st"]), "countdown")
            self.mode = "client"
            self.snap_buf.clear()
            self.clock_off = None
            self.particles.clear()
            self.goal_history = []
            self.fade = 255.0
            self.c_shoot = False
            evs = msg.get("ev") or []
            self.last_ev = max([self.last_ev] + [int(e[0]) for e in evs])
        elif mid < self.cur_mid:
            return
        if mid > self.cur_mid:
            self.cur_mid = mid
            if not entering:
                self.snap_buf.clear()
                self.particles.clear()
        if self.snap_buf and ht <= self.snap_buf[-1]["ht"]:
            return                          # out-of-order / duplicate
        off = now - ht
        if self.clock_off is None or off < self.clock_off:
            self.clock_off = off
        else:
            self.clock_off += (off - self.clock_off) * 0.005
        msg["done"] = False
        self.snap_buf.append(msg)
        if len(self.snap_buf) > 80:
            self.snap_buf.pop(0)
        e = float(msg.get("e", 0) or 0)
        if e > 0:
            rtt = (now - e) * 1000.0
            if 0 <= rtt < 5000:
                self.ping = rtt if self.ping == 0 else self.ping * 0.9 + rtt * 0.1

    def client_event(self, ev):
        typ, x, y, ex = ev[1], float(ev[2]), float(ev[3]), float(ev[4])
        self.event_sound(typ, ex)
        if typ == "kick":
            self.particles.append(Particle(x, y, 0, 0, (255, 255, 255), 10, 16, ring=True))
            for _ in range(10 + int(ex * 10)):
                self.particles.append(Particle(
                    x, y, random.uniform(-3.5, 3.5), random.uniform(-3.5, 3.5),
                    GOLD, random.randint(2, 5), 20))
            self.shake = max(self.shake, 2.0 + 4.0 * ex)
        elif typ == "tk":
            pl = self.p2 if int(ex) == 2 else self.p1
            for _ in range(8):
                self.particles.append(Particle(
                    pl.x + pl.facing_x * 20, pl.y + pl.facing_y * 20,
                    random.uniform(-2.5, 2.5), random.uniform(-2.5, 2.5),
                    GOLD, random.randint(2, 4), 16))
        elif typ == "steal":
            self.shake = max(self.shake, 6)
            self.particles.append(Particle(x, y, 0, 0, GOLD, 12, 18, ring=True))
        elif typ == "post":
            self.shake = max(self.shake, 5)
            for _ in range(8):
                self.particles.append(Particle(
                    x, y, random.uniform(-3, 3), random.uniform(-3, 3),
                    (255, 255, 255), random.randint(2, 3), 14))
        elif typ == "pu":
            self.pu_burst(x, y, int(ex) % 10, int(ex) // 10)
        elif typ == "goal":
            side = int(ex)
            self.goal_fx(x, y, side)
            # Guests get the same replay clips as the host, built from their
            # interpolated view of the network match.
            if self.replay_buffer:
                self.goal_replays.append({
                    "side": side,
                    "time": max(0.0, float(self.clock_frames) / 60.0),
                    "frames": list(self.replay_buffer[-105:]),
                })
                if len(self.goal_replays) > 8:
                    self.goal_replays.pop(0)

    def client_dust(self, p, dt):
        speed = math.hypot(p.vx, p.vy)
        if speed > 2.5 and random.random() < 0.16 * dt:
            self.particles.append(Particle(
                p.x - p.vx * 1.8, p.y - p.vy * 1.8 + p.radius * 0.65,
                random.uniform(-0.5, 0.5), random.uniform(-0.4, 0.4),
                (170, 195, 145), random.randint(2, 4), 14))
        if speed > 7.2 and random.random() < 0.42 * dt:
            self.particles.append(Particle(
                p.x - p.vx * 2, p.y - p.vy * 2, random.uniform(-0.7, 0.7), random.uniform(-0.7, 0.7),
                (205, 220, 180), random.randint(2, 4), 18))

    def update_client(self, dt):
        now = time.perf_counter()
        buf = self.snap_buf
        self.go_timer = max(0.0, self.go_timer - dt)
        self.goal_flash = max(0.0, self.goal_flash - dt)
        if not buf or self.clock_off is None:
            return
        rt = now - self.clock_off - INTERP_DELAY

        # Fire events once playback reaches their snapshot.
        for s in buf:
            if s["ht"] <= rt and not s["done"]:
                s["done"] = True
                for ev in s.get("ev") or []:
                    if int(ev[0]) > self.last_ev:
                        self.last_ev = int(ev[0])
                        self.client_event(ev)

        # Pick the two snapshots around the render time.
        a = b = buf[0]
        if rt >= buf[-1]["ht"]:
            a = b = buf[-1]
        elif rt > buf[0]["ht"]:
            for i in range(len(buf) - 1):
                if buf[i]["ht"] <= rt <= buf[i + 1]["ht"]:
                    a, b = buf[i], buf[i + 1]
                    break
        f = 0.0 if a is b else clamp((rt - a["ht"]) / max(1e-6, b["ht"] - a["ht"]), 0.0, 1.0)

        # Match flow comes from the newest-bracket snapshot.
        new_state = IDX_STATE.get(int(b["st"]), "play")
        if new_state != self.state:
            if self.state == "countdown" and new_state == "play":
                self.go_timer = 45.0
            self.state = new_state
            if new_state == "finished":
                self.blue_score, self.red_score = b["s"]
                for _ in range(60):
                    self.spawn_confetti()
        self.countdown = float(b["cd"])
        self.countdown_total = float(b["ct"])
        self.clock_frames = float(b["cl"])
        self.goal_timer = float(b["gt"])
        self.blue_score, self.red_score = b["s"]
        self.overtime = bool(b.get("ot", 0))
        self.match_duration = float(b.get("md", self.match_duration))
        self.powerups = [{"t": int(a[0]), "x": float(a[1]), "y": float(a[2])}
                         for a in (b.get("pw") or [])]
        sx = b.get("x")
        if sx and len(sx) >= 8:
            self.stats = {"shots": [sx[0], sx[1]], "steals": [sx[2], sx[3]],
                          "poss": [sx[4], sx[5]], "pu": [sx[6], sx[7]]}

        for p, pa, pb in ((self.p1, a["p"][0], b["p"][0]), (self.p2, a["p"][1], b["p"][1])):
            jump = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) > 150     # kickoff reset: don't slide
            ff = 1.0 if jump else f
            p.x = lerp(pa[0], pb[0], ff)
            p.y = lerp(pa[1], pb[1], ff)
            p.vx = lerp(pa[2], pb[2], ff)
            p.vy = lerp(pa[3], pb[3], ff)
            fx, fy = lerp(pa[4], pb[4], ff), lerp(pa[5], pb[5], ff)
            fl = math.hypot(fx, fy)
            if fl > 0.01:
                p.facing_x, p.facing_y = fx / fl, fy / fl
            p.stamina = float(pb[6])
            p.charging = bool(pb[7])
            p.charge = float(pb[8])
            p.kick_timer = float(pb[9])
            p.tackle_timer = float(pb[10])
            p.squash = float(pb[11])
            p.flash_timer = float(pb[12])
            p.exhausted = bool(pb[13])
            if len(pb) > 16:
                p.boost_t, p.mega_t, p.frozen_t = float(pb[14]), float(pb[15]), float(pb[16])
            speed = math.hypot(p.vx, p.vy)
            p.animation_time += (0.16 + speed * 0.025) * dt
            p.dribble_phase += (0.20 + speed * 0.03) * dt
            self.client_dust(p, dt)

        ba, bb = a["b"], b["b"]
        ball = self.ball
        jump = math.hypot(bb[0] - ba[0], bb[1] - ba[1]) > 150
        ff = 1.0 if jump else f
        ball.x = lerp(ba[0], bb[0], ff)
        ball.y = lerp(ba[1], bb[1], ff)
        ball.vx, ball.vy = float(bb[2]), float(bb[3])
        ball.rotation = float(bb[5])
        owner = int(bb[4])
        ball.owner = self.p1 if owner == 1 else (self.p2 if owner == 2 else None)
        self.p1.has_ball = owner == 1
        self.p2.has_ball = owner == 2
        sp = math.hypot(ball.vx, ball.vy)
        if ball.owner is None and sp > 7:
            ball.trail.append((ball.x, ball.y))
            if len(ball.trail) > 12:
                ball.trail.pop(0)
        elif ball.trail:
            ball.trail.pop(0)

        if self.state == "play":
            self.record_replay_frame(dt)

        if self.state == "finished" and random.random() < 0.5 * dt:
            self.spawn_confetti()

        while len(buf) > 2 and buf[1]["ht"] < rt - 0.25:
            buf.pop(0)
        self.update_particles(dt)

    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    def release_shot(self, player):
        if player.charging:
            player.charging = False
            player.shot_charge = player.charge
            player.charge = 0.0
            player.shot_buffer = 9.0

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            # B toggles background music from every screen without changing gameplay controls.
            if event.type == pygame.KEYDOWN and event.key == pygame.K_b:
                self.sound.toggle_music()
                continue

            st = self.state
            # SDL may deliver touch events without synthesizing mouse clicks on mobile.
            # Convert menu taps to clicks; gameplay keeps native finger events for multitouch.
            if WEB_BUILD and event.type == pygame.FINGERDOWN and st in (
                    "menu", "online_menu", "join", "lobby", "settings", "customize", "upgrades"):
                event = pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN,
                    {"pos": (int(event.x * W), int(event.y * H)), "button": 1})
            if st == "menu":
                self.events_menu(event)
            elif st == "online_menu":
                self.events_online_menu(event)
            elif st == "join":
                self.events_join(event)
            elif st == "lobby":
                self.events_lobby(event)
            elif st == "settings":
                self.events_settings(event)
            elif st == "customize":
                self.events_customize(event)
            elif st == "upgrades":
                self.events_upgrades(event)
            elif st in ("penalties", "penalty_finished"):
                self.events_penalties(event)
            else:
                self.events_game(event)

    def menu_choose(self, i):
        if i == 0:
            self.start_match("pvp")
        elif i == 1:
            self.start_match("bot")
        elif i == 2:
            self.open_online_menu()
            if WEB_BUILD:
                self.net_msg = "Online party mode is not available in the browser build. Try 1 V 1 or 1 V BOT."
            else:
                self.open_online_menu()
        elif i == 3:
            self.start_penalty_shootout(standalone=True)

    def events_menu(self, event):
        if event.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self.menu_rects):
                if r.collidepoint(event.pos):
                    self.menu_selection = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, r in enumerate(self.menu_rects):
                if r.collidepoint(event.pos):
                    self.menu_choose(i)
            if self.settings_rect.collidepoint(event.pos):
                self.open_settings()
            if self.customize_rect.collidepoint(event.pos):
                self.open_customize()
            if self.upgrade_rect.collidepoint(event.pos):
                self.open_upgrades("menu")
        elif event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_n:
                self.toggle_sound()
            elif k == pygame.K_c:
                self.open_customize()
            elif k == pygame.K_u:
                self.open_upgrades("menu")
            elif k in (pygame.K_4, pygame.K_KP4):
                self.menu_choose(3)
            elif k in (pygame.K_o,):
                self.open_settings()
            elif k in (pygame.K_1, pygame.K_KP1):
                self.menu_choose(0)
            elif k in (pygame.K_2, pygame.K_KP2):
                self.menu_choose(1)
            elif k in (pygame.K_3, pygame.K_KP3):
                self.menu_choose(2)
            elif k in (pygame.K_UP, pygame.K_w):
                self.menu_selection = max(0, self.menu_selection - 1)
                self.sound.play("click")
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.menu_selection = min(3, self.menu_selection + 1)
                self.sound.play("click")
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.menu_choose(self.menu_selection)

    # --------------------------------------------------------
    # SETTINGS / HOW TO PLAY
    # --------------------------------------------------------

    SET_ROWS = (("MATCH LENGTH", "How long a game lasts"),
                ("POWER-UPS", "Pick-ups that appear on the pitch"),
                ("BOT LEVEL", "How good the computer player is"),
                ("SOUND EFFECTS", "Goals, kicks and whistles  (N toggles anywhere)"),
                ("BACKGROUND MUSIC", "Original looping soundtrack  (B toggles anywhere)"))

    def open_settings(self):
        self.state = "settings"
        self.set_sel = 0
        self.sound.play("menuok")

    def set_row_rect(self, i):
        return pygame.Rect(50, 165 + i * 92, 540, 76)

    def settings_text(self, i):
        s = self.settings
        if i == 0:
            return f"{s['len']} SECONDS"
        if i == 1:
            return "ON" if s["pu"] else "OFF"
        if i == 2:
            return BOT_LEVELS[s["bot"]]["name"]
        if i == 3:
            if not self.sound.ok:
                return "NO AUDIO"
            return "ON" if self.sound.on else "OFF"
        if not self.sound.ok:
            return "NO AUDIO"
        return "ON" if self.sound.music_enabled else "OFF"

    def settings_change(self, i, d):
        s = self.settings
        if i == 0:
            idx = MATCH_LENGTHS.index(s["len"]) if s["len"] in MATCH_LENGTHS else 1
            s["len"] = MATCH_LENGTHS[(idx + d) % len(MATCH_LENGTHS)]
        elif i == 1:
            s["pu"] = not s["pu"]
        elif i == 2:
            s["bot"] = (s["bot"] + d) % len(BOT_LEVELS)
        elif i == 3:
            self.sound.on = not self.sound.on
        else:
            self.sound.toggle_music()
        self.sound.play("click")

    def events_settings(self, event):
        n = len(self.SET_ROWS)
        if event.type == pygame.MOUSEMOTION:
            for i in range(n):
                if self.set_row_rect(i).collidepoint(event.pos):
                    self.set_sel = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(n):
                r = self.set_row_rect(i)
                if r.collidepoint(event.pos):
                    self.set_sel = i
                    self.settings_change(i, -1 if event.pos[0] < r.centerx else 1)
        elif event.type == pygame.KEYDOWN:
            k = event.key
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.state = "menu"
            elif k in (pygame.K_UP, pygame.K_w):
                self.set_sel = (self.set_sel - 1) % n
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.set_sel = (self.set_sel + 1) % n
            elif k in (pygame.K_LEFT, pygame.K_a):
                self.settings_change(self.set_sel, -1)
            elif k in (pygame.K_RIGHT, pygame.K_d, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.settings_change(self.set_sel, 1)
            elif k == pygame.K_n:
                self.settings_change(3, 1)

    def events_online_menu(self, event):
        if event.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self.on_rects):
                if r.collidepoint(event.pos):
                    self.online_sel = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, r in enumerate(self.on_rects):
                if r.collidepoint(event.pos):
                    self.online_sel = i
                    if i == 1:
                        self.start_hosting()
                    elif i == 2:
                        self.open_join()
        elif event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_ESCAPE:
                self.state = "menu"
            elif k == pygame.K_UP:
                self.online_sel = max(0, self.online_sel - 1)
            elif k == pygame.K_DOWN or k == pygame.K_TAB:
                self.online_sel = min(2, self.online_sel + 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.online_sel == 0:
                    self.online_sel = 1
                elif self.online_sel == 1:
                    self.start_hosting()
                else:
                    self.open_join()
            elif self.online_sel == 0:
                if k == pygame.K_BACKSPACE:
                    self.name = self.name[:-1]
                elif event.unicode and event.unicode.isprintable() and len(self.name) < 12:
                    self.name += event.unicode

    def join_row_rect(self, i):
        return pygame.Rect(W // 2 - 290, 190 + i * 54, 580, 48)

    def events_join(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, (addr, _) in enumerate(self.lan_list()):
                if self.join_row_rect(i).collidepoint(event.pos):
                    self.join_sel = i
                    self.join_text = ""
                    self.try_join(addr)
        elif event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_ESCAPE:
                self.net.close()
                self.joining = None
                self.state = "online_menu"
                self.net_msg = ""
            elif k == pygame.K_UP:
                self.join_sel = max(0, self.join_sel - 1)
            elif k == pygame.K_DOWN:
                self.join_sel = min(max(0, len(self.lan_list()) - 1), self.join_sel + 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.join_submit()
            elif k == pygame.K_BACKSPACE:
                self.join_text = self.join_text[:-1]
            elif k == pygame.K_v and (event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)):
                self.join_text = (self.join_text + clipboard_text().strip())[:30]
            elif event.unicode and event.unicode.isprintable() and len(self.join_text) < 30:
                self.join_text += event.unicode

    def events_lobby(self, event):
        if event.type != pygame.KEYDOWN:
            return
        k = event.key
        if k == pygame.K_n:
            self.toggle_sound()
        elif k == pygame.K_ESCAPE:
            self.leave_party()
        elif k in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.mode == "host":
                self.host_start_match()
            else:
                self.my_ready = not self.my_ready
                self.lobby_send_t = -10.0
        elif k == pygame.K_i and self.mode == "host":
            self.lookup_public()

    def events_game(self, event):

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state == "play" and self.handle_touch_pointer("mouse", event.pos, True):
                return
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.handle_touch_pointer("mouse", event.pos, False):
                return
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * W), int(event.y * H))
            if self.state == "play" and self.handle_touch_pointer(("finger", event.finger_id), pos, True):
                return
        elif event.type == pygame.FINGERUP:
            if self.handle_touch_pointer(("finger", event.finger_id), (0, 0), False):
                return

        if self.state == "replay":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.replay_back_rect.collidepoint(event.pos):
                    self.state = "finished"
                elif self.replay_pause_rect.collidepoint(event.pos):
                    self.replay_playing = not self.replay_playing
                    self.replay_hold = 0.0
                elif self.replay_next_rect.collidepoint(event.pos) and self.goal_replays:
                    self._next_replay_clip(1)
                return
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    self.state = "finished"
                elif event.key == pygame.K_SPACE:
                    self.replay_playing = not self.replay_playing
                    self.replay_hold = 0.0
                elif event.key in (pygame.K_RIGHT, pygame.K_n) and self.goal_replays:
                    self._next_replay_clip(1)
                elif event.key in (pygame.K_LEFT, pygame.K_p) and self.goal_replays:
                    self._next_replay_clip(-1)
                return
            return

        if self.state == "finished" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.highlight_video_rect.collidepoint(event.pos):
                self.start_highlight_replay()
            elif self.highlight_upgrade_rect.collidepoint(event.pos):
                self.open_upgrades("finished")
            elif self.highlight_rematch_rect.collidepoint(event.pos):
                if self.mode == "host":
                    self.host_start_match()
                elif self.mode != "client":
                    self.start_match(self.mode)
            elif self.highlight_menu_rect.collidepoint(event.pos):
                if self.mode == "host":
                    self.host_to_lobby()
                elif self.mode == "client":
                    self.leave_party()
                else:
                    self.return_to_menu()
            return

        if event.type == pygame.KEYUP:
            if self.mode == "client":
                if event.key in (pygame.K_e, pygame.K_p):
                    self.c_shoot = False
                return
            if event.key == pygame.K_e:
                self.release_shot(self.p1)
            elif event.key == pygame.K_p:
                self.release_shot(self.p2 if self.mode == "pvp" else self.p1)
            return

        if event.type != pygame.KEYDOWN:
            return
        k = event.key
        if k == pygame.K_n:
            self.toggle_sound()
            return
        if self.state == "finished" and k == pygame.K_u:
            self.open_upgrades("finished")
            return

        if self.mode == "client":
            if k == pygame.K_ESCAPE or (k == pygame.K_m and self.state == "finished"):
                self.leave_party()
            elif k in (pygame.K_e, pygame.K_p):
                self.c_shoot = True
            elif k in (pygame.K_r, pygame.K_l):
                self.c_tackle += 1
            return

        if self.mode == "host":
            if k == pygame.K_ESCAPE:
                self.host_to_lobby()
                return
            if self.state == "finished":
                if k == pygame.K_SPACE:
                    self.host_start_match()
                elif k == pygame.K_h:
                    self.start_highlight_replay()
                elif k == pygame.K_m:
                    self.host_to_lobby()
                return
        else:
            if self.state == "paused":
                if k == pygame.K_ESCAPE:
                    self.state = self.prev_state
                elif k == pygame.K_m:
                    self.return_to_menu()
                return
            if self.state == "finished":
                if k == pygame.K_SPACE:
                    self.start_match(self.mode)
                elif k == pygame.K_h:
                    self.start_highlight_replay()
                elif k in (pygame.K_ESCAPE, pygame.K_m):
                    self.return_to_menu()
                return
            if k == pygame.K_ESCAPE:
                self.prev_state = self.state
                self.state = "paused"
                for p in (self.p1, self.p2):
                    p.charging = False
                    p.charge = 0.0
                return

        if self.state != "play":
            return

        if k == pygame.K_e:
            self.p1.charging = True
            self.p1.charge = 0.0
        elif k == pygame.K_r:
            self.p1.tackle_buffer = 8.0
        elif k == pygame.K_p:
            pl = self.p2 if self.mode == "pvp" else self.p1
            pl.charging = True
            pl.charge = 0.0
        elif k == pygame.K_l:
            (self.p2 if self.mode == "pvp" else self.p1).tackle_buffer = 8.0

    def attempt_tackle(self, player):
        if not player.tackle():
            return False
        self.emit("tk", player.x, player.y, 2 if player.is_p2 else 1)
        if self.ball.check_collision(player) == "steal":
            self.stats["steals"][1 if player.is_p2 else 0] += 1
            self.shake = max(self.shake, 6)
            self.particles.append(Particle(self.ball.x, self.ball.y, 0, 0, GOLD, 12, 18, ring=True))
            self.emit("steal", self.ball.x, self.ball.y)
        for _ in range(8):
            self.particles.append(Particle(
                player.x + player.facing_x * 20, player.y + player.facing_y * 20,
                random.uniform(-2.5, 2.5), random.uniform(-2.5, 2.5),
                GOLD, random.randint(2, 4), 16))
        return True

    def process_actions(self, p, dt):
        if p.frozen_t > 0:
            p.shot_buffer = p.tackle_buffer = 0.0
            p.charging = False
            p.charge = 0.0
            return
        if p.shot_buffer > 0:
            p.shot_buffer -= dt
            if self.ball.shoot(p, self.particles, p.shot_charge):
                p.shot_buffer = 0.0
                self.stats["shots"][1 if p.is_p2 else 0] += 1
                self.shake = max(self.shake, 2.0 + 4.0 * p.shot_charge)
                self.emit("kick", self.ball.x, self.ball.y, p.shot_charge)
        if p.tackle_buffer > 0:
            p.tackle_buffer -= dt
            if self.attempt_tackle(p):
                p.tackle_buffer = 0.0

    def apply_remote_actions(self, now):
        """Host: turn the guest's held-key state into charge / release / tackle."""
        ni = self.net_in
        fresh = (now - ni["t"]) < 0.5
        sh = bool(ni["sh"]) and fresh
        if self.state == "play":
            if sh and not self.p2_sh_prev:
                self.p2.charging = True
                self.p2.charge = 0.0
            elif not sh and self.p2_sh_prev:
                self.release_shot(self.p2)
            if ni["tk"] != self.p2_tk_prev:
                self.p2.tackle_buffer = 8.0
        self.p2_sh_prev = sh
        self.p2_tk_prev = ni["tk"]

    # --------------------------------------------------------
    # BOT  (deliberately a bit bad: slow reactions, sloppy aim, naps)
    # --------------------------------------------------------

    def bot_level(self):
        return BOT_LEVELS[int(clamp(self.settings["bot"], 0, len(BOT_LEVELS) - 1))]

    def bot_inputs(self, dt):
        bot, ball, foe = self.p2, self.ball, self.p1
        b = self.bot_state
        lv = self.bot_level()

        if bot.frozen_t > 0:
            return 0.0, 0.0, False
        if b["lull"] > 0:
            b["lull"] -= dt
            return 0.0, 0.0, False
        if lv["lull"] and random.random() < lv["lull"] * dt:
            b["lull"] = random.uniform(*lv["lull_len"])

        b["think"] -= dt
        if b["think"] <= 0:
            b["think"] = random.uniform(*lv["think"])
            chase = None
            if lv["seek_pu"] and ball.owner is not bot:
                best = 320.0
                for pu in self.powerups:
                    d = math.hypot(pu["x"] - bot.x, pu["y"] - bot.y)
                    if d < best:
                        best, chase = d, pu
            if chase:
                tx, ty = chase["x"], chase["y"]
            elif ball.owner is bot:
                tx, ty = FIELD_LEFT + 40, FIELD_CY + random.uniform(-lv["aim"], lv["aim"]) * 1.2
            elif ball.owner is foe:
                tx, ty = foe.x, foe.y
            else:
                tx, ty = ball.x + ball.vx * 2, ball.y + ball.vy * 2
            b["tx"] = tx + random.uniform(-lv["err"], lv["err"])
            b["ty"] = ty + random.uniform(-lv["err"], lv["err"])

        dx, dy = b["tx"] - bot.x, b["ty"] - bot.y
        dist = math.hypot(dx, dy)
        if dist < 10:
            return 0.0, 0.0, False
        mag = lv["mag"] * min(1.0, dist / 50)
        dash = bool(lv["dash"] and dist > 190 and bot.stamina > 35 and not bot.exhausted)
        return dx / dist * mag, dy / dist * mag, dash

    def bot_actions(self, dt):
        bot, ball, foe = self.p2, self.ball, self.p1
        lv = self.bot_level()
        if bot.frozen_t > 0:
            return

        if ball.owner is foe and bot.tackle_cooldown <= 0 and \
                math.hypot(foe.x - bot.x, foe.y - bot.y) < lv["tk_range"] and \
                random.random() < lv["tackle"] * dt:
            bot.tackle_buffer = 4.0

        if ball.owner is bot:
            if random.random() < lv["fumble"] * dt:      # occasional fumble
                ball.release_owner()
                ball.vx = random.uniform(-4, 4)
                ball.vy = random.uniform(-4, 4)
                ball.possession_lock = 18.0
                return
            if bot.x < FIELD_LEFT + lv["shoot_x"] and random.random() < lv["shoot"] * dt:
                aim_y = FIELD_CY + random.uniform(-lv["aim"], lv["aim"])
                gx, gy = normalize(FIELD_LEFT - bot.x, aim_y - bot.y)
                bot.facing_x, bot.facing_y = gx, gy
                bot.shot_charge = random.uniform(*lv["charge"])
                bot.shot_buffer = 3.0

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    def separate_players(self):
        dx = self.p2.x - self.p1.x
        dy = self.p2.y - self.p1.y
        dist = math.hypot(dx, dy)
        min_dist = self.p1.radius + self.p2.radius
        if dist < min_dist:
            if dist < 0.001:
                dx, dy, dist = 1.0, 0.0, 1.0
            nx, ny = dx / dist, dy / dist
            push = (min_dist - dist) / 2
            self.p1.x -= nx * push
            self.p1.y -= ny * push
            self.p2.x += nx * push
            self.p2.y += ny * push
            self.p1.clamp_to_field()
            self.p2.clamp_to_field()


    def touch_down(self, name):
        if name in self.touch_held:
            return
        self.touch_held.add(name)
        side, action = name.split("_", 1)
        player = self.p2 if side == "p2" else self.p1
        if action == "shoot":
            if self.mode == "client":
                self.c_shoot = True
            else:
                player.charging = True
                player.charge = 0.0
        elif action == "tackle":
            if self.mode == "client":
                self.c_tackle += 1
            else:
                player.tackle_buffer = 8.0

    def touch_up(self, name):
        if name not in self.touch_held:
            return
        self.touch_held.discard(name)
        side, action = name.split("_", 1)
        if action == "shoot":
            if self.mode == "client":
                self.c_shoot = False
            else:
                self.release_shot(self.p2 if side == "p2" else self.p1)

    def touch_rects(self):
        def pad(cx, cy, side):
            return {
                side + "_up": pygame.Rect(cx - 25, cy - 78, 50, 50),
                side + "_down": pygame.Rect(cx - 25, cy + 28, 50, 50),
                side + "_left": pygame.Rect(cx - 78, cy - 25, 50, 50),
                side + "_right": pygame.Rect(cx + 28, cy - 25, 50, 50),
            }
        rects = pad(100, H - 135, "p1")
        rects.update({
            "p1_dash": pygame.Rect(235, H - 205, 76, 58),
            "p1_tackle": pygame.Rect(235, H - 137, 76, 58),
            "p1_shoot": pygame.Rect(320, H - 171, 94, 94),
        })
        if self.mode == "pvp":
            rects.update(pad(W - 100, H - 135, "p2"))
            rects.update({
                "p2_dash": pygame.Rect(W - 311, H - 205, 76, 58),
                "p2_tackle": pygame.Rect(W - 311, H - 137, 76, 58),
                "p2_shoot": pygame.Rect(W - 414, H - 171, 94, 94),
            })
        return rects

    def handle_touch_pointer(self, pointer_id, pos, down):
        if down:
            for name, rect in self.touch_rects().items():
                if rect.collidepoint(pos):
                    self.touch_pointer_map[pointer_id] = name
                    self.touch_down(name)
                    return True
        else:
            name = self.touch_pointer_map.pop(pointer_id, None)
            if name:
                self.touch_up(name)
                return True
        return False

    def combined_input(self, keys):
        dx = (int(keys[pygame.K_d]) - int(keys[pygame.K_a])
              + int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT])
              + int("p1_right" in self.touch_held) - int("p1_left" in self.touch_held))
        dy = (int(keys[pygame.K_s]) - int(keys[pygame.K_w])
              + int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
              + int("p1_down" in self.touch_held) - int("p1_up" in self.touch_held))
        dash = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or keys[pygame.K_SLASH]
                    or "p1_dash" in self.touch_held)
        return clamp(dx, -1, 1), clamp(dy, -1, 1), dash

    def read_inputs(self, keys):
        if self.mode == "pvp":
            in1 = (clamp(int(keys[pygame.K_d]) - int(keys[pygame.K_a])
                         + int("p1_right" in self.touch_held) - int("p1_left" in self.touch_held), -1, 1),
                   clamp(int(keys[pygame.K_s]) - int(keys[pygame.K_w])
                         + int("p1_down" in self.touch_held) - int("p1_up" in self.touch_held), -1, 1),
                   bool(keys[pygame.K_LSHIFT] or "p1_dash" in self.touch_held))
            in2 = (clamp(int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT])
                         + int("p2_right" in self.touch_held) - int("p2_left" in self.touch_held), -1, 1),
                   clamp(int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
                         + int("p2_down" in self.touch_held) - int("p2_up" in self.touch_held), -1, 1),
                   bool(keys[pygame.K_RSHIFT] or keys[pygame.K_SLASH] or "p2_dash" in self.touch_held))
            return in1, in2
        return self.combined_input(keys), None

    def update(self, dt):
        self.ui_t += dt
        self.fade = max(0.0, self.fade - 7.0 * dt)
        self.coin_timer = max(0.0, self.coin_timer - dt)
        self.shop_message_timer = max(0.0, self.shop_message_timer - dt)
        self.shake *= 0.86 ** dt
        if self.shake < 0.2:
            self.shake = 0.0

        want_repeat = self.state in ("online_menu", "join")
        if want_repeat != self._repeat_on:
            self._repeat_on = want_repeat
            if want_repeat:
                pygame.key.set_repeat(350, 40)
            else:
                pygame.key.set_repeat()

        if self.net.role:
            self.net_pump()

        self._update_inner(dt)
        self.audio_cues()
        music_track = "menu" if self.state in MENU_STATES else "match"
        self.sound.set_music(music_track)

        if (self.net.role == "host" and self.mode == "host" and self.guest_addr
                and self.state in GAME_STATES):
            self.host_send_snapshot(time.perf_counter())

    def _update_inner(self, dt):
        if self.state == "replay":
            self.update_highlight_replay(dt)
            return
        if self.state in MENU_STATES:
            self.update_menu(dt)
            return
        if self.state == "paused":
            return
        if self.state in ("penalties", "penalty_finished"):
            self.update_penalties(dt)
            return
        if self.mode == "client":
            if self.state in GAME_STATES:
                self.update_client(dt)
            return

        if self.mode == "host":
            self.apply_remote_actions(time.perf_counter())

        self.go_timer = max(0.0, self.go_timer - dt)
        self.goal_flash = max(0.0, self.goal_flash - dt)

        if self.state == "finished":
            self.update_particles(dt)
            self.p1.tick_timers(dt)
            self.p2.tick_timers(dt)
            if random.random() < 0.5 * dt:
                self.spawn_confetti()
            return

        if self.state == "countdown":
            self.p1.update(0, 0, False, dt, self.particles)
            self.p2.update(0, 0, False, dt, self.particles)
            self.ball.update(dt, self.particles)
            self.update_particles(dt)
            self.countdown -= dt
            if self.countdown <= 0:
                self.state = "play"
                self.go_timer = 45.0
            return

        if self.state == "goal":
            slow = dt * 0.35
            self.p1.update(0, 0, False, slow, self.particles)
            self.p2.update(0, 0, False, slow, self.particles)
            self.ball.update(slow, self.particles)
            self.update_particles(dt * 0.6)
            self.goal_timer -= dt
            if self.goal_timer <= 0:
                if self.clock_frames >= self.match_duration:
                    self.end_regulation()
                else:
                    self.reset_positions()
                    self.begin_countdown(95)
            return

        # ---- playing ----
        keys = pygame.key.get_pressed()
        in1, in2 = self.read_inputs(keys)

        self.p1.update(*in1, dt, self.particles)
        if self.mode == "pvp":
            self.p2.update(*in2, dt, self.particles)
        elif self.mode == "host":
            ni = self.net_in
            if time.perf_counter() - ni["t"] > 0.5:
                self.p2.update(0, 0, False, dt, self.particles)
            else:
                self.p2.update(ni["dx"], ni["dy"], ni["dash"], dt, self.particles)
        else:
            self.p2.update(*self.bot_inputs(dt), dt, self.particles)
            self.bot_actions(dt)

        self.process_actions(self.p1, dt)
        self.process_actions(self.p2, dt)
        self.separate_players()

        self.ball.update(dt, self.particles)
        for p in (self.p1, self.p2):
            if self.ball.check_collision(p) == "steal":
                self.stats["steals"][1 if p.is_p2 else 0] += 1
                self.shake = max(self.shake, 6)
                self.particles.append(Particle(self.ball.x, self.ball.y, 0, 0, GOLD, 12, 18, ring=True))
                self.emit("steal", self.ball.x, self.ball.y)

        if self.ball.post_hit:
            self.shake = max(self.shake, 5)
            self.emit("post", self.ball.x, self.ball.y)

        holder = self.ball.owner
        if holder is self.p1:
            self.stats["poss"][0] += dt
        elif holder is self.p2:
            self.stats["poss"][1] += dt
        self.update_powerups(dt)

        self.update_particles(dt)
        self.record_replay_frame(dt)

        if self.ball.x < FIELD_LEFT - 2 and GOAL_TOP <= self.ball.y <= GOAL_BOTTOM:
            self.score_goal(2)
        elif self.ball.x > FIELD_RIGHT + 2 and GOAL_TOP <= self.ball.y <= GOAL_BOTTOM:
            self.score_goal(1)

        if self.state == "play":
            self.clock_frames += dt
            if not self.overtime and self.clock_frames >= self.match_duration:
                self.end_regulation()
            elif self.overtime and self.clock_frames >= self.match_duration + OT_FRAMES:
                if self.blue_score == self.red_score:
                    self.start_penalty_shootout(standalone=False)
                else:
                    self.finish_match()

    def _replay_player_state(self, p):
        """Capture only the visual/position properties needed for smooth playback."""
        return {
            "x": float(p.x), "y": float(p.y), "vx": float(p.vx), "vy": float(p.vy),
            "fx": float(p.facing_x), "fy": float(p.facing_y),
            "anim": float(p.animation_time), "squash": float(p.squash),
            "kick": float(p.kick_timer), "tackle": float(p.tackle_timer),
            "flash": float(p.flash_timer), "stamina": float(p.stamina),
            "exhausted": bool(p.exhausted), "charging": bool(p.charging),
            "charge": float(p.charge), "boost": float(p.boost_t),
            "mega": float(p.mega_t), "frozen": float(p.frozen_t),
        }

    def _capture_replay_frame(self):
        return {
            "p1": self._replay_player_state(self.p1),
            "p2": self._replay_player_state(self.p2),
            "bx": float(self.ball.x), "by": float(self.ball.y),
            "br": float(self.ball.rotation),
            "trail": [(float(x), float(y)) for x, y in self.ball.trail[-10:]],
            "clock": max(0.0, float(self.clock_frames) / 60.0),
        }

    def record_replay_frame(self, dt, force=False):
        """Sample at about 30 fps (game time uses 60-Hz frame units)."""
        self.replay_capture_accum += max(0.0, dt)
        if force or self.replay_capture_accum >= 2.0:
            self.replay_capture_accum %= 2.0
            self.replay_buffer.append(self._capture_replay_frame())
            # About five seconds of rolling footage. Keep memory use predictable.
            if len(self.replay_buffer) > 155:
                del self.replay_buffer[:-155]

    def start_highlight_replay(self):
        if not self.goal_replays:
            self.replay_clip_i = 0
            self.replay_cursor = 0.0
            self.replay_playing = False
            self.replay_hold = 0.0
            self.state = "replay"
            self.sound.play("menuok")
            return
        self.replay_clip_i = 0
        self.replay_cursor = 0.0
        self.replay_playing = True
        self.replay_hold = 0.0
        self.replay_actor1 = Player(self.p1.x, self.p1.y, self.p1.color,
                                    self.p1.dark_color, self.p1.light_color, False)
        self.replay_actor2 = Player(self.p2.x, self.p2.y, self.p2.color,
                                    self.p2.dark_color, self.p2.light_color, True)
        for src, dst in ((self.p1, self.replay_actor1), (self.p2, self.replay_actor2)):
            dst.color, dst.dark_color, dst.light_color = src.color, src.dark_color, src.light_color
            dst.accent_color = src.accent_color
            dst.kit_name = getattr(src, "kit_name", "CUSTOM")
            dst.shape = getattr(src, "shape", "ROUND")
        self.state = "replay"
        self.sound.play("menuok")

    def update_highlight_replay(self, dt):
        if not self.goal_replays:
            return
        if not self.replay_playing:
            return
        clip = self.goal_replays[self.replay_clip_i]
        frames = clip.get("frames", [])
        if not frames:
            self._next_replay_clip()
            return
        # Cinematic slow motion: about 0.7x normal speed.
        if self.replay_cursor < len(frames) - 1:
            self.replay_cursor = min(len(frames) - 1, self.replay_cursor + dt / 2.8)
        else:
            self.replay_hold += dt
            if self.replay_hold >= 25.0:
                self._next_replay_clip()

    def _next_replay_clip(self, direction=1):
        if not self.goal_replays:
            return
        self.replay_clip_i = (self.replay_clip_i + direction) % len(self.goal_replays)
        self.replay_cursor = 0.0
        self.replay_hold = 0.0
        self.replay_playing = True

    def finish_match(self):
        self.award_match_rewards()
        self.state = "finished"
        self.powerups = []
        for p in (self.p1, self.p2):
            p.charging = False
        for _ in range(60):
            self.spawn_confetti()

    # --------------------------------------------------------
    # PENALTY SHOOTOUTS
    # --------------------------------------------------------

    def start_penalty_shootout(self, standalone=False):
        """Start a local penalty shootout. Tied matches enter here after golden goal."""
        self.penalty_standalone = standalone
        self.penalty_scores = [0, 0]
        self.penalty_taken = [0, 0]
        self.penalty_round = 0
        self.penalty_shooter = 0
        self.penalty_aim_x = 1
        self.penalty_aim_y = 1
        self.penalty_keeper_x = 1
        self.penalty_keeper_y = 1
        self.penalty_anim = 0.0
        self.penalty_result = "CHOOSE YOUR SHOT"
        self.penalty_last_scored = False
        self.penalty_wait = 0.0
        self.penalty_finished = False
        self.penalty_winner = None
        self.penalty_report_delay = 0.0
        self.particles.clear()
        self.shake = 0.0
        self.state = "penalties"
        self.sound.play("menuok")

    def penalty_is_bot_turn(self):
        return self.mode == "bot" and self.penalty_shooter == 1 and not self.penalty_standalone

    def take_penalty(self):
        if self.state != "penalties" or self.penalty_anim > 0 or self.penalty_wait > 0:
            return
        shooter = self.penalty_shooter
        ax, ay = self.penalty_aim_x, self.penalty_aim_y
        if self.penalty_is_bot_turn():
            ax, ay = random.randrange(3), random.randrange(3)
        self.penalty_aim_x, self.penalty_aim_y = ax, ay
        # The keeper chooses independently, so every attempt feels unpredictable.
        self.penalty_keeper_x, self.penalty_keeper_y = random.randrange(3), random.randrange(3)
        exact = (ax == self.penalty_keeper_x and ay == self.penalty_keeper_y)
        near = (ax == self.penalty_keeper_x or ay == self.penalty_keeper_y)
        roll = random.random()
        scored = not (exact or (near and roll < 0.38) or roll < 0.08)
        # The keeper is a little less perfect in the computer mode, keeping it fun.
        if self.mode == "bot" and self.penalty_shooter == 0 and exact and random.random() < 0.28:
            scored = True
        self.penalty_last_scored = scored
        self.penalty_anim = 36.0
        self.penalty_result = "GOAL!" if scored else "SAVED!"
        self.sound.play("kick")
        self.shake = 5.0 if scored else 2.0

    def _resolve_penalty(self):
        shooter = self.penalty_shooter
        if self.penalty_last_scored:
            self.penalty_scores[shooter] += 1
            self.sound.play("goal")
            color = BLUE_LIGHT if shooter == 0 else RED_LIGHT
            for _ in range(28):
                self.particles.append(Particle(W // 2 + random.randint(-110, 110), 170,
                    random.uniform(-3.5, 3.5), random.uniform(-4.5, 1.0), color,
                    random.randint(2, 5), random.randint(28, 55), 0.08))
        else:
            self.sound.play("post")
        self.penalty_taken[shooter] += 1
        self.penalty_anim = 0.0
        self.penalty_wait = 48.0
        # Check whether the shootout has been decided before switching shooters.
        a, b = self.penalty_scores
        ta, tb = self.penalty_taken
        if ta >= 5 and tb >= 5 and ta == tb and a != b:
            self.penalty_winner = 0 if a > b else 1
            self.penalty_finished = True
        elif ta < 5 or tb < 5:
            if (a > b + (5 - tb)) or (b > a + (5 - ta)):
                self.penalty_winner = 0 if a > b else 1
                self.penalty_finished = True
        elif ta == tb and a != b:
            self.penalty_winner = 0 if a > b else 1
            self.penalty_finished = True
        if self.penalty_finished:
            self.state = "penalty_finished"
            self.penalty_report_delay = 180.0 if not self.penalty_standalone else 0.0
            self.penalty_result = "SHOOTOUT WON!" if self.penalty_winner == 0 else "SHOOTOUT LOST!"
            return
        # Five each; if tied, continue one kick each until the tie breaks.
        if ta >= 5 and tb >= 5 and a == b:
            self.penalty_result = "SUDDEN DEATH!"
        else:
            self.penalty_result = "NEXT KICK"
        self.penalty_shooter = 1 - shooter
        self.penalty_aim_x, self.penalty_aim_y = 1, 1

    def update_penalties(self, dt):
        self.update_particles(dt)
        if self.state == "penalty_finished":
            if not self.penalty_standalone:
                self.penalty_report_delay -= dt
                if self.penalty_report_delay <= 0:
                    # A tie-break ends the match too: show the richer post-match report
                    # after the shootout result has had a moment on screen.
                    self.award_match_rewards()
                    self.state = "finished"
                    return
            if random.random() < 0.65 * dt:
                self.spawn_confetti()
            return
        if self.penalty_anim > 0:
            self.penalty_anim -= dt
            if self.penalty_anim <= 0:
                self._resolve_penalty()
            return
        if self.penalty_wait > 0:
            self.penalty_wait -= dt
            if self.penalty_wait <= 0:
                if self.penalty_finished:
                    self.state = "penalty_finished"
                else:
                    self.penalty_result = "CHOOSE YOUR SHOT"
            return
        if self.penalty_is_bot_turn():
            self.penalty_aim_x, self.penalty_aim_y = random.randrange(3), random.randrange(3)
            self.take_penalty()

    def events_penalties(self, event):
        if event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_n:
                self.toggle_sound()
            elif k in (pygame.K_ESCAPE, pygame.K_m):
                self.return_to_menu()
            elif self.state == "penalty_finished":
                if k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_r):
                    self.start_penalty_shootout(standalone=self.penalty_standalone)
            elif self.penalty_anim <= 0 and self.penalty_wait <= 0 and not self.penalty_is_bot_turn():
                shooter = self.penalty_shooter
                if shooter == 0:
                    if k in (pygame.K_a, pygame.K_LEFT): self.penalty_aim_x = max(0, self.penalty_aim_x - 1)
                    elif k in (pygame.K_d, pygame.K_RIGHT): self.penalty_aim_x = min(2, self.penalty_aim_x + 1)
                    elif k in (pygame.K_w, pygame.K_UP): self.penalty_aim_y = max(0, self.penalty_aim_y - 1)
                    elif k in (pygame.K_s, pygame.K_DOWN): self.penalty_aim_y = min(2, self.penalty_aim_y + 1)
                    elif k in (pygame.K_SPACE, pygame.K_RETURN): self.take_penalty()
                else:
                    if k == pygame.K_LEFT: self.penalty_aim_x = max(0, self.penalty_aim_x - 1)
                    elif k == pygame.K_RIGHT: self.penalty_aim_x = min(2, self.penalty_aim_x + 1)
                    elif k == pygame.K_UP: self.penalty_aim_y = max(0, self.penalty_aim_y - 1)
                    elif k == pygame.K_DOWN: self.penalty_aim_y = min(2, self.penalty_aim_y + 1)
                    elif k in (pygame.K_RETURN, pygame.K_KP_ENTER): self.take_penalty()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state == "penalty_finished":
                if pygame.Rect(W//2-120, H-110, 240, 54).collidepoint(event.pos):
                    self.start_penalty_shootout(standalone=self.penalty_standalone)
                elif pygame.Rect(W//2-390, H-110, 240, 54).collidepoint(event.pos):
                    self.return_to_menu()
            elif self.penalty_anim <= 0 and self.penalty_wait <= 0 and not self.penalty_is_bot_turn():
                for ix in range(3):
                    for iy in range(3):
                        r = pygame.Rect(W//2-180+ix*120, 355+iy*65, 105, 52)
                        if r.collidepoint(event.pos):
                            self.penalty_aim_x, self.penalty_aim_y = ix, iy
                            self.sound.play("click")
                            return
                if pygame.Rect(W//2-110, H-105, 220, 52).collidepoint(event.pos):
                    self.take_penalty()

    def draw_penalties(self):
        self.draw_menu_bg()
        title = "PENALTY SHOOTOUT" if self.state == "penalties" else "SHOOTOUT COMPLETE"
        draw_text(screen, self.big_font, title, WHITE, (W//2, 55))
        draw_text(screen, self.small_font, "AIM YOUR SHOT • THE KEEPER WILL DIVE RANDOMLY", GOLD, (W//2, 100))
        # Stylized penalty area and goal.
        goal = pygame.Rect(W//2-220, 135, 440, 190)
        pygame.draw.rect(screen, (210, 225, 225), goal, border_radius=8)
        pygame.draw.rect(screen, (25, 32, 35), goal.inflate(-10, -10), border_radius=5)
        for xx in range(goal.left+10, goal.right-8, 28):
            pygame.draw.line(screen, (65, 85, 90), (xx, goal.top+8), (xx, goal.bottom-8), 1)
        for yy in range(goal.top+8, goal.bottom-8, 22):
            pygame.draw.line(screen, (65, 85, 90), (goal.left+8, yy), (goal.right-8, yy), 1)
        # Three-by-three target zones. Selected lane pulses; keeper dive animates to its random lane.
        lane_centres = [goal.left+75, goal.centerx, goal.right-75]
        lane_y = [goal.top+45, goal.centery, goal.bottom-42]
        for ix, xx in enumerate(lane_centres):
            for iy, yy in enumerate(lane_y):
                r = pygame.Rect(xx-32, yy-22, 64, 44)
                selected = self.state == "penalties" and self.penalty_anim <= 0 and ix == self.penalty_aim_x and iy == self.penalty_aim_y
                color = GOLD if selected else (85, 105, 110)
                pygame.draw.rect(screen, color, r, 3 if selected else 1, border_radius=6)
                if selected:
                    draw_text(screen, self.tiny_font, "AIM", GOLD, (xx, yy), shadow=False)
        # Keeper silhouette, diving toward the random lane during the shot animation.
        kx = lane_centres[self.penalty_keeper_x]
        ky = lane_y[self.penalty_keeper_y]
        dive = min(1.0, (36.0-self.penalty_anim)/24.0) if self.penalty_anim > 0 else 0.0
        keeper_x = lerp(goal.centerx, kx, dive)
        keeper_y = lerp(goal.bottom-25, ky, dive)
        kcol = (75, 190, 255) if self.penalty_shooter == 1 else (255, 100, 110)
        pygame.draw.ellipse(screen, (15, 20, 25), (keeper_x-25, keeper_y-12, 50, 24))
        pygame.draw.circle(screen, kcol, (int(keeper_x), int(keeper_y-22)), 13)
        pygame.draw.line(screen, kcol, (int(keeper_x-6), int(keeper_y-12)), (int(keeper_x-30), int(keeper_y+2)), 8)
        pygame.draw.line(screen, kcol, (int(keeper_x+6), int(keeper_y-12)), (int(keeper_x+30), int(keeper_y+2)), 8)
        if self.penalty_anim > 0:
            bx = lane_centres[self.penalty_aim_x]
            by = lane_y[self.penalty_aim_y]
            prog = 1.0-self.penalty_anim/36.0
            ball_x = lerp(W//2, bx, prog)
            ball_y = lerp(505, by, prog)
            draw_ball(screen, ball_x, ball_y, max(5, int(13-6*prog)), prog*5, 505)
        else:
            draw_ball(screen, W//2, 505, 13, self.ui_t*0.08)
        # Scoreboard and attempt markers.
        panel = pygame.Rect(W//2-280, 535, 560, 65)
        pygame.draw.rect(screen, UI, panel, border_radius=14)
        pygame.draw.rect(screen, (85, 100, 105), panel, 2, border_radius=14)
        draw_text(screen, self.menu_font, f"BLUE  {self.penalty_scores[0]}  -  {self.penalty_scores[1]}  RED", WHITE, (W//2, 553))
        draw_text(screen, self.tiny_font, f"KICKS  {self.penalty_taken[0]} / 5  •  {self.penalty_taken[1]} / 5", (195, 210, 210), (W//2, 582), shadow=False)
        draw_text(screen, self.menu_font, self.penalty_result, GOLD if self.penalty_last_scored else WHITE, (W//2, 625))
        if self.state == "penalty_finished":
            winner = "BLUE PLAYER WINS!" if self.penalty_winner == 0 else ("RED PLAYER WINS!" if self.penalty_winner == 1 else "SHOOTOUT COMPLETE!")
            if self.mode == "bot" and not self.penalty_standalone:
                winner = "YOU WIN!" if self.penalty_winner == 0 else "BOT WINS!"
            draw_text(screen, self.font, winner, GOLD, (W//2, 665))
            pygame.draw.rect(screen, UI, (W//2-390, H-110, 240, 54), border_radius=12)
            pygame.draw.rect(screen, (100, 115, 120), (W//2-390, H-110, 240, 54), 2, border_radius=12)
            draw_text(screen, self.small_font, "MAIN MENU  [ESC]", WHITE, (W//2-270, H-83), shadow=False)
            pygame.draw.rect(screen, UI, (W//2-120, H-110, 240, 54), border_radius=12)
            pygame.draw.rect(screen, GOLD, (W//2-120, H-110, 240, 54), 2, border_radius=12)
            draw_text(screen, self.small_font, "PLAY AGAIN  [ENTER]", GOLD, (W//2, H-83), shadow=False)
        elif self.penalty_is_bot_turn():
            draw_text(screen, self.small_font, "BOT IS SHOOTING...", RED_LIGHT, (W//2, H-28))
        elif self.penalty_shooter == 0:
            draw_text(screen, self.tiny_font, "PLAYER 1: WASD AIM • SPACE SHOOT • CLICK A TARGET", WHITE, (W//2, H-28), shadow=False)
        else:
            draw_text(screen, self.tiny_font, "PLAYER 2: ARROWS AIM • ENTER SHOOT • CLICK A TARGET", WHITE, (W//2, H-28), shadow=False)
        self.fx_layer.fill((0, 0, 0, 0))
        for particle in self.particles:
            particle.draw(self.fx_layer)
        screen.blit(self.fx_layer, (0, 0))

    def spawn_confetti(self):
        if self.blue_score > self.red_score:
            cols = [BLUE, BLUE_LIGHT, WHITE, GOLD]
        elif self.red_score > self.blue_score:
            cols = [RED, RED_LIGHT, WHITE, GOLD]
        else:
            cols = [GOLD, WHITE]
        self.particles.append(Particle(
            random.uniform(0, W), random.uniform(-30, 80),
            random.uniform(-1, 1), random.uniform(1, 3.5),
            random.choice(cols), random.randint(3, 5), random.randint(90, 160), 0.03))

    def update_particles(self, dt):
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]

    def goal_fx(self, bx, by, player_number):
        """Banner text + burst of particles (shared by host, solo play and the guest)."""
        self.goal_history.append({"side": int(player_number),
                                  "time": max(0.0, float(self.clock_frames) / 60.0)})
        color = BLUE if player_number == 1 else RED
        self.goal_color = color
        self.goal_message = f"{self.side_name(player_number)} SCORES!"
        self.goal_flash = 22.0
        self.shake = 16.0
        self.sound.play("goal")
        self.particles.append(Particle(bx, by, 0, 0, color, 20, 34, ring=True))
        for _ in range(80):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(2, 9)
            self.particles.append(Particle(
                bx, by, math.cos(angle) * speed, math.sin(angle) * speed,
                color if random.random() < 0.65 else GOLD,
                random.randint(2, 6), random.randint(30, 60), 0.06))

    def award_goal_coins(self, player_number):
        """Grant career coins when the main player scores a genuine shot goal."""
        if self.mode not in ("bot", "pvp") or player_number != 1:
            return
        if self.ball.last_shot_side != 1:
            return  # don't award coins for an own goal or an opponent's shot
        origin = self.ball.last_shot_origin
        from_own_half = bool(origin and origin[0] < W / 2)
        amount = 10 if from_own_half else 5
        self.profile["coins"] += amount
        self.profile["total_goals"] += 1
        self.coin_message = f"+{amount} COINS  ·  " + ("LONG-RANGE GOAL!" if from_own_half else "GOAL!")
        self.coin_timer = 130.0
        self.save_profile()
        self.sound.play("pickup", 0.85)

    def award_match_rewards(self):
        """Give a one-time career reward for a local match result."""
        if self.match_rewarded:
            return
        self.match_rewarded = True
        if self.mode not in ("bot", "pvp"):
            return
        if self.penalty_finished and not self.penalty_standalone and self.penalty_winner in (0, 1):
            winner = self.penalty_winner + 1
        elif self.blue_score > self.red_score:
            winner = 1
        elif self.red_score > self.blue_score:
            winner = 2
        else:
            winner = 0
        self.profile["matches"] += 1
        if winner == 1:
            self.profile["coins"] += 30
            self.profile["wins"] += 1
            self.coin_message = "+30 COINS  ·  MATCH WIN BONUS!"
            self.last_match_reward = "REWARD: +30 COINS FOR THE WIN!"
            self.coin_timer = 180.0
        elif winner == 0:
            self.profile["coins"] += 10
            self.coin_message = "+10 COINS  ·  DRAW BONUS"
            self.last_match_reward = "REWARD: +10 COINS FOR THE DRAW"
            self.coin_timer = 150.0
        else:
            self.last_match_reward = "NO WIN BONUS THIS MATCH — GOALS STILL EARN COINS"
        self.save_profile()

    def score_goal(self, player_number):
        if player_number == 1:
            self.blue_score += 1
        else:
            self.red_score += 1

        self.award_goal_coins(player_number)
        scorer = self.p1 if player_number == 1 else self.p2
        scorer.celebration_timer = 150.0
        scorer.flash_timer = max(scorer.flash_timer, 24.0)

        # Preserve the action leading into the goal. Clips are played back later
        # as short slow-motion replays on the full-time highlight screen.
        self.record_replay_frame(0.0, force=True)
        clip_frames = list(self.replay_buffer[-105:])
        if clip_frames:
            self.goal_replays.append({
                "side": int(player_number),
                "time": max(0.0, float(self.clock_frames) / 60.0),
                "frames": clip_frames,
            })
            if len(self.goal_replays) > 8:
                self.goal_replays.pop(0)

        self.state = "goal"
        self.goal_timer = 150.0
        for p in (self.p1, self.p2):
            p.charging = False
            p.charge = 0.0
            p.shot_buffer = p.tackle_buffer = 0.0

        self.goal_fx(self.ball.x, self.ball.y, player_number)
        self.emit("goal", self.ball.x, self.ball.y, player_number)

    def update_menu(self, dt):
        self.menu_t += dt
        for p in (self.menu_p1, self.menu_p2):
            p.vx = 3.0
            p.tick_timers(dt)
        # Ambient drifting motes.
        if random.random() < 0.25 * dt:
            self.particles.append(Particle(
                random.uniform(0, W), H + 10, random.uniform(-0.3, 0.3), random.uniform(-1.4, -0.6),
                (200, 240, 200), random.randint(2, 4), random.randint(120, 200)))
        self.update_particles(dt)

    # --------------------------------------------------------
    # DRAWING
    # --------------------------------------------------------

    def build_vignette(self):
        v = pygame.Surface((W, H), pygame.SRCALPHA)
        steps = 70
        for i in range(steps):
            a = int(85 * (1 - i / steps) ** 2.2)
            pygame.draw.rect(v, (0, 0, 0, a), (i, i, W - 2 * i, H - 2 * i), 1)
        return v

    def draw_menu_bg(self):
        t = self.menu_t
        screen.fill((10, 27, 16))

        stripe = 120
        off = (t * 0.5) % (stripe * 2)
        x = -stripe * 2 + off
        i = 0
        while x < W:
            pygame.draw.rect(screen, FIELD if i % 2 == 0 else FIELD_DARK, (int(x), 0, stripe + 1, H))
            x += stripe
            i += 1

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 80))
        screen.blit(overlay, (0, 0))

        pulse = 150 + math.sin(t * 0.03) * 8
        pygame.draw.circle(screen, (235, 245, 235), (W // 2, H // 2 + 20), int(pulse), 3)
        pygame.draw.line(screen, (235, 245, 235), (W // 2, 0), (W // 2, H), 2)
        pygame.draw.circle(screen, WHITE, (W // 2, H // 2 + 20), 5)

        self.fx_layer.fill((0, 0, 0, 0))
        for p in self.particles:
            p.draw(self.fx_layer)
        screen.blit(self.fx_layer, (0, 0))

    def draw_button(self, base_rect, selected, name, desc):
        t = self.menu_t
        rect = base_rect.copy()
        if selected:
            grow = int(4 + math.sin(t * 0.12) * 2)
            rect.inflate_ip(grow * 2, grow)
            glow = pygame.Surface((rect.w + 40, rect.h + 40), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*GOLD, 40), glow.get_rect(), border_radius=28)
            screen.blit(glow, (rect.x - 20, rect.y - 20))
        pygame.draw.rect(screen, UI_LIGHT if selected else UI, rect, border_radius=18)
        pygame.draw.rect(screen, GOLD if selected else (90, 100, 105), rect, 3, border_radius=18)
        draw_text(screen, self.menu_font, name, GOLD if selected else WHITE,
                  (rect.centerx, rect.top + int(rect.h * 0.33)), shadow=False)
        draw_text(screen, self.small_font, desc, (205, 215, 210),
                  (rect.centerx, rect.top + int(rect.h * 0.72)), shadow=False)

    def draw_menu(self):
        t = self.menu_t
        self.draw_menu_bg()

        # Juggling demo: two players pass the ball in an arc.
        ground = 585
        phase = t * 0.028
        lx, rx = 200, W - 200
        bx = W / 2 + math.sin(phase) * (W / 2 - 250)
        height = abs(math.cos(phase)) * 170
        for p, px, face in ((self.menu_p1, lx, 1.0), (self.menu_p2, rx, -1.0)):
            p.x = px
            p.y = ground - 16 + math.sin(t * 0.07 + (0 if face > 0 else 1.5)) * 3
            p.facing_x, p.facing_y = face, 0.0
            p.kick_timer = 6.0 if abs(math.cos(phase)) < 0.1 and (bx - W / 2) * face < 0 else 0.0
        self.menu_p1.draw(screen)
        self.menu_p2.draw(screen)
        draw_ball(screen, bx, ground - height - 4, 13, t * 0.15, ground - 4)

        # Title with wavy letters.
        words = [("HYPER", BLUE_LIGHT), ("SOCCER", RED_LIGHT)]
        total_w = sum(self.title_font.size(w)[0] for w, _ in words) + 36
        cx = W // 2 - total_w // 2
        for word, col in words:
            for ch in word:
                gw = self.title_font.size(ch)[0]
                k = (cx - W // 2) * 0.012
                yo = math.sin(t * 0.05 + k) * 7
                img = self.title_font.render(ch, True, col)
                sh = self.title_font.render(ch, True, (0, 0, 0))
                sh.set_alpha(170)
                screen.blit(sh, (cx + 4, 56 + yo + 5))
                screen.blit(img, (cx, 56 + yo))
                cx += gw
            cx += 36
        draw_text(screen, self.small_font, "LOCAL SOCCER  -  CHOOSE YOUR GAME MODE",
                  (220, 235, 220), (W // 2, 160))

        options = [
            ("1 V 1", "Play against another player on this device"),
            ("1 V BOT", "Play against the computer"),
            ("ONLINE PARTY", "Create or join a party over the internet"),
            ("PENALTY SHOOTOUTS", "Pick your shot. Can you beat the keeper?"),
        ]
        for i, (name, description) in enumerate(options):
          self.draw_button(
              self.menu_rects[i], self.menu_selection == i, name, description
          )


        cr = self.customize_rect
        chov = cr.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, UI_LIGHT if chov else UI, cr, border_radius=14)
        pygame.draw.rect(screen, GOLD if chov else (90, 100, 105), cr, 3, border_radius=14)
        draw_text(screen, self.small_font, "CUSTOMIZE  (C)", GOLD if chov else WHITE, cr.center, shadow=False)

        ur = self.upgrade_rect
        uhov = ur.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, UI_LIGHT if uhov else UI, ur, border_radius=14)
        pygame.draw.rect(screen, GOLD if uhov else (90, 100, 105), ur, 3 if uhov else 1, border_radius=14)
        draw_text(screen, self.small_font, f"UPGRADES  (U)  ·  {self.profile['coins']} C",
                  GOLD if uhov else WHITE, ur.center, shadow=False)

        sr = self.settings_rect
        hov = sr.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, UI_LIGHT if hov else UI, sr, border_radius=14)
        pygame.draw.rect(screen, GOLD if hov else (90, 100, 105), sr, 3, border_radius=14)
        draw_text(screen, self.small_font, "SETTINGS  (O)", GOLD if hov else WHITE, sr.center,
                  shadow=False)

        music_label = "MUSIC ON [B]" if self.sound.music_enabled else "MUSIC OFF [B]"
        draw_text(screen, self.small_font,
                  f"UP / DOWN SELECT   ENTER PLAY   C CUSTOMIZE   U UPGRADES   O SETTINGS   {music_label}",
                  WHITE, (W // 2, H - 24))
        if WEB_BUILD and self.net_msg:
            draw_text(screen, self.small_font, self.net_msg, GOLD, (W // 2, H - 54))

    def events_customize(self, event):
        if event.type == pygame.KEYDOWN:
            k = event.key
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.state = "menu"
                self.sound.play("click")
            elif k in (pygame.K_a, pygame.K_LEFT):
                self.cycle_kit(0, -1)
            elif k in (pygame.K_d, pygame.K_RIGHT):
                self.cycle_kit(0, 1)
            elif k == pygame.K_q:
                self.cycle_kit(1, -1)
            elif k in (pygame.K_e, pygame.K_TAB):
                self.cycle_kit(1, 1)
            elif k in (pygame.K_w, pygame.K_UP):
                self.cycle_shape(0, -1)
            elif k in (pygame.K_s, pygame.K_DOWN):
                self.cycle_shape(0, 1)
            elif k == pygame.K_z:
                self.cycle_shape(1, -1)
            elif k == pygame.K_x:
                self.cycle_shape(1, 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.state = "menu"
                self.sound.play("click")
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for side, rects in enumerate(self.kit_card_rects()):
                for idx, rect in enumerate(rects):
                    if rect.collidepoint(event.pos):
                        self.kit_indices[side] = idx
                        for player in ((self.menu_p1, self.p1) if side == 0 else (self.menu_p2, self.p2)):
                            self.apply_kit(player, idx)
                        self.sound.play("menuok")
                        return
            for side, rects in enumerate(self.shape_card_rects()):
                for idx, rect in enumerate(rects):
                    if rect.collidepoint(event.pos):
                        self.shape_indices[side] = idx
                        for player in ((self.menu_p1, self.p1) if side == 0 else (self.menu_p2, self.p2)):
                            self.apply_shape(player, idx)
                        self.sound.play("menuok")
                        return
            if pygame.Rect(W // 2 - 110, 590, 220, 48).collidepoint(event.pos):
                self.state = "menu"
                self.sound.play("click")

    def kit_card_rects(self):
        # Twelve compact colour swatches per player, all visible without scrolling.
        return [[pygame.Rect(110 + i * 82, 245 + side * 80, 72, 68)
                 for i in range(len(KITS))] for side in range(2)]

    def shape_card_rects(self):
        return [[pygame.Rect(270 + i * 116, 400 + side * 42, 108, 34)
                 for i in range(len(self.shape_options))] for side in range(2)]

    def draw_customize(self):
        self.draw_menu_bg()
        draw_text(screen, self.big_font, "PLAYER LAB", WHITE, (W // 2, 38))
        draw_text(screen, self.small_font, "YOUR LOOK. YOUR COLOURS. YOUR STYLE.", GOLD, (W // 2, 76))

        # Animated player previews are rendered with the actual selected shape and kit.
        t = self.menu_t
        for side, player, x in ((0, self.menu_p1, W // 2 - 285), (1, self.menu_p2, W // 2 + 285)):
            player.x = x
            player.y = 132 + math.sin(t * 0.08 + side) * 4
            player.facing_x = 1 if side == 0 else -1
            player.facing_y = math.sin(t * 0.025 + side) * 0.12
            player.animation_time += 0.7
            player.draw(screen)
            title = "PLAYER 1 / BLUE SIDE" if side == 0 else "PLAYER 2 / RED SIDE"
            draw_text(screen, self.small_font, title, player.light_color, (x, 178))
            draw_text(screen, self.tiny_font,
                      f"{KITS[self.kit_indices[side]][0]}  |  {self.shape_options[self.shape_indices[side]]}",
                      GOLD, (x, 199))

        # Colour palettes.
        for side, rects in enumerate(self.kit_card_rects()):
            draw_text(screen, self.tiny_font,
                      f"PLAYER {side + 1} COLOURS  -  " + ("A / D" if side == 0 else "Q / E"),
                      WHITE, (W // 2, rects[0].top - 9), shadow=False)
            for idx, rect in enumerate(rects):
                name, main, dark, light, accent = KITS[idx]
                selected = self.kit_indices[side] == idx
                pygame.draw.rect(screen, (24, 31, 38), rect, border_radius=10)
                pygame.draw.rect(screen, GOLD if selected else (75, 89, 98), rect,
                                 3 if selected else 1, border_radius=10)
                pygame.draw.circle(screen, dark, (rect.centerx, rect.centery - 7), 19)
                pygame.draw.circle(screen, main, (rect.centerx, rect.centery - 9), 16)
                pygame.draw.arc(screen, accent,
                                (rect.centerx - 14, rect.centery - 23, 28, 28), 0.35, 2.8, 3)
                pygame.draw.line(screen, light,
                                 (rect.centerx - 10, rect.centery - 8),
                                 (rect.centerx + 10, rect.centery - 8), 3)
                draw_text(screen, self.tiny_font, name[:9],
                          WHITE if selected else (180, 192, 198),
                          (rect.centerx, rect.bottom - 9), shadow=False)

        # Shape picker for each player.
        for side, rects in enumerate(self.shape_card_rects()):
            draw_text(screen, self.tiny_font, f"P{side + 1} SHAPE",
                      GOLD, (118, rects[0].centery), shadow=False)
            for idx, rect in enumerate(rects):
                selected = self.shape_indices[side] == idx
                pygame.draw.rect(screen, (25, 33, 40), rect, border_radius=9)
                pygame.draw.rect(screen, GOLD if selected else (75, 89, 98), rect,
                                 2 if selected else 1, border_radius=9)
                draw_text(screen, self.tiny_font, self.shape_options[idx],
                          WHITE if selected else (175, 187, 194), rect.center, shadow=False)

        pygame.draw.rect(screen, UI, (W // 2 - 110, 590, 220, 48), border_radius=14)
        pygame.draw.rect(screen, GOLD, (W // 2 - 110, 590, 220, 48), 2, border_radius=14)
        draw_text(screen, self.menu_font, "DONE  [ENTER]", GOLD, (W // 2, 614), shadow=False)
        draw_text(screen, self.tiny_font,
                  "P1 shape: W / S   |   P2 shape: Z / X   |   Click any colour or shape to equip it",
                  (215, 225, 220), (W // 2, 670))

    def draw_settings(self):
        self.draw_menu_bg()
        draw_text(screen, self.big_font, "SETTINGS", WHITE, (W // 2, 70))

        for i, (name, hint) in enumerate(self.SET_ROWS):
            r = self.set_row_rect(i)
            sel = i == self.set_sel
            pygame.draw.rect(screen, UI_LIGHT if sel else UI, r, border_radius=16)
            pygame.draw.rect(screen, GOLD if sel else (90, 100, 105), r, 3, border_radius=16)
            draw_text(screen, self.small_font, name, WHITE if sel else (205, 215, 210),
                      (r.left + 22, r.top + 26), anchor="midleft", shadow=False)
            draw_text(screen, self.tiny_font, hint, (150, 165, 160),
                      (r.left + 22, r.top + 54), anchor="midleft", shadow=False)
            val = self.settings_text(i)
            cx = r.right - 150
            font = self.font if len(val) <= 6 else self.small_font
            draw_text(screen, font, val, GOLD if sel else WHITE, (cx, r.centery), shadow=False)
            if sel:
                bump = int(math.sin(self.menu_t * 0.2) * 3)
                draw_text(screen, self.font, "<", GOLD, (cx - 100 - bump, r.centery), shadow=False)
                draw_text(screen, self.font, ">", GOLD, (cx + 100 + bump, r.centery), shadow=False)

        panel = pygame.Rect(620, 150, 530, 470)
        pygame.draw.rect(screen, UI, panel, border_radius=18)
        pygame.draw.rect(screen, UI_LIGHT, panel, 2, border_radius=18)
        draw_text(screen, self.small_font, "HOW TO PLAY", GOLD, (panel.centerx, panel.top + 28),
                  shadow=False)
        lines = (("MOVE", "WASD OR ARROW KEYS"),
                 ("SHOOT", "E OR P  -  HOLD FOR MORE POWER"),
                 ("TACKLE", "R OR L  -  STEAL THE BALL"),
                 ("DASH", "SHIFT  -  USES STAMINA"))
        for i, (a, b) in enumerate(lines):
            y = panel.top + 68 + i * 30
            draw_text(screen, self.tiny_font, a, BLUE_LIGHT, (panel.left + 30, y), anchor="midleft",
                      shadow=False)
            draw_text(screen, self.tiny_font, b, WHITE, (panel.left + 130, y), anchor="midleft",
                      shadow=False)
        draw_text(screen, self.tiny_font, "1 V 1:  BLUE = WASD  E  R  LSHIFT",
                  (170, 185, 180), (panel.left + 30, panel.top + 198), anchor="midleft", shadow=False)
        draw_text(screen, self.tiny_font, "              RED = ARROWS  P  L  RSHIFT",
                  (170, 185, 180), (panel.left + 30, panel.top + 220), anchor="midleft", shadow=False)

        draw_text(screen, self.small_font, "POWER-UPS", GOLD, (panel.centerx, panel.top + 262),
                  shadow=False)
        descs = ("FASTER AND NO STAMINA DRAIN  -  8 SECONDS",
                 "YOUR SHOTS FLY 35% HARDER  -  10 SECONDS",
                 "FREEZES YOUR OPPONENT  -  1.7 SECONDS")
        for t in range(3):
            ry = panel.top + 308 + t * 42
            draw_powerup(screen, t, panel.left + 50, ry, self.menu_t, 14)
            draw_text(screen, self.small_font, PU_NAMES[t], PU_COLORS[t],
                      (panel.left + 90, ry - 9), anchor="midleft", shadow=False)
            draw_text(screen, self.tiny_font, descs[t], (205, 215, 210),
                      (panel.left + 90, ry + 11), anchor="midleft", shadow=False)
        draw_text(screen, self.tiny_font, "TIED AT FULL TIME  =  GOLDEN GOAL  (NEXT GOAL WINS)",
                  WHITE, (panel.centerx, panel.bottom - 22), shadow=False)

        draw_text(screen, self.small_font,
                  "UP / DOWN  SELECT      LEFT / RIGHT  CHANGE      ESC  BACK", WHITE,
                  (W // 2, H - 36))

    def draw_online_menu(self):
        t = self.menu_t
        self.draw_menu_bg()
        draw_text(screen, self.big_font, "ONLINE PARTY", WHITE, (W // 2, 80))
        draw_text(screen, self.small_font, "PLAY WITH FRIENDS ON THE SAME WI-FI OR OVER THE INTERNET",
                  (220, 235, 220), (W // 2, 132))

        # Name box.
        r = self.on_rects[0]
        sel = self.online_sel == 0
        pygame.draw.rect(screen, UI_LIGHT if sel else UI, r, border_radius=16)
        pygame.draw.rect(screen, GOLD if sel else (90, 100, 105), r, 3, border_radius=16)
        draw_text(screen, self.tiny_font, "YOUR NAME  (SELECT AND TYPE TO CHANGE)", (170, 185, 180),
                  (r.centerx, r.top + 16), shadow=False)
        caret = "|" if sel and int(t * 0.08) % 2 == 0 else ""
        draw_text(screen, self.menu_font, self.name + caret, WHITE, (r.centerx, r.top + 45), shadow=False)

        self.draw_button(self.on_rects[1], self.online_sel == 1, "HOST A PARTY",
                         "Create a party and share the code")
        self.draw_button(self.on_rects[2], self.online_sel == 2, "JOIN A PARTY",
                         "Find a party on your network or enter a code")

        if self.net_msg:
            draw_text(screen, self.small_font, self.net_msg, RED_LIGHT, (W // 2, 505))

        draw_text(screen, self.tiny_font,
                  "SAME WI-FI / LAN: JUST HOST AND JOIN - PARTIES SHOW UP AUTOMATICALLY.",
                  WHITE, (W // 2, 560))
        draw_text(screen, self.tiny_font,
                  f"OVER THE INTERNET: THE HOST FORWARDS UDP PORT {NET_PORT} ON THEIR ROUTER, "
                  "OR EVERYONE USES A VPN (TAILSCALE / ZEROTIER).",
                  (220, 235, 220), (W // 2, 585))
        draw_text(screen, self.small_font, "UP / DOWN  SELECT      ENTER  CONFIRM      ESC  BACK",
                  WHITE, (W // 2, H - 36))

    def draw_join(self):
        t = self.menu_t
        self.draw_menu_bg()
        draw_text(screen, self.big_font, "JOIN A PARTY", WHITE, (W // 2, 70))

        panel = pygame.Rect(W // 2 - 310, 130, 620, 270)
        pygame.draw.rect(screen, UI, panel, border_radius=18)
        pygame.draw.rect(screen, UI_LIGHT, panel, 2, border_radius=18)
        draw_text(screen, self.tiny_font, "PARTIES ON YOUR NETWORK", (170, 185, 180),
                  (panel.centerx, panel.top + 22), shadow=False)

        lst = self.lan_list()
        if not lst:
            dots = "." * (1 + int(t * 0.05) % 3)
            draw_text(screen, self.small_font, "SEARCHING" + dots, (205, 215, 210),
                      (panel.centerx, panel.top + 120), shadow=False)
        for i, (addr, info) in enumerate(lst):
            rr = self.join_row_rect(i)
            sel = (i == self.join_sel) and not self.join_text
            pygame.draw.rect(screen, UI_LIGHT if sel else (28, 34, 41), rr, border_radius=12)
            pygame.draw.rect(screen, GOLD if sel else (70, 80, 86), rr, 2, border_radius=12)
            draw_text(screen, self.small_font, info["name"].upper(), WHITE,
                      (rr.left + 18, rr.centery), anchor="midleft", shadow=False)
            status = f"{info['n']}/2 PLAYERS" if info["ph"] == "lobby" else "IN A MATCH"
            draw_text(screen, self.tiny_font, status, GOLD if info["ph"] == "lobby" else RED_LIGHT,
                      (rr.right - 18, rr.centery), anchor="midright", shadow=False)

        box = pygame.Rect(W // 2 - 310, 440, 620, 70)
        pygame.draw.rect(screen, UI_LIGHT, box, border_radius=16)
        pygame.draw.rect(screen, GOLD if self.join_text else (90, 100, 105), box, 3, border_radius=16)
        draw_text(screen, self.tiny_font, "OR TYPE A PARTY CODE / IP ADDRESS  (CTRL+V TO PASTE)",
                  (170, 185, 180), (box.centerx, box.top + 16), shadow=False)
        caret = "|" if int(t * 0.08) % 2 == 0 else ""
        shown = (self.join_text + caret) if self.join_text or caret else ""
        draw_text(screen, self.menu_font, shown, WHITE, (box.centerx, box.top + 46), shadow=False)

        if self.net_msg:
            col = GOLD if self.net_msg.startswith("Connecting") else RED_LIGHT
            draw_text(screen, self.small_font, self.net_msg, col, (W // 2, 545))
        draw_text(screen, self.small_font,
                  "ENTER  JOIN      UP / DOWN  PICK A PARTY      ESC  BACK", WHITE, (W // 2, H - 36))

    def draw_lobby(self):
        t = self.menu_t
        self.draw_menu_bg()
        host = self.mode == "host"
        draw_text(screen, self.big_font, "PARTY LOBBY", WHITE, (W // 2, 70))

        if host:
            draw_text(screen, self.tiny_font, "PARTY CODE - SHARE THIS WITH YOUR FRIEND", (170, 185, 180),
                      (W // 2, 128), shadow=False)
            draw_text(screen, self.title_font, self.party_code, GOLD, (W // 2, 172))
            line = "THAT CODE WORKS ON YOUR WI-FI / LAN."
            if self.public_state == "loading":
                line = "LOOKING UP YOUR PUBLIC IP..."
            elif self.public_state == "error":
                line = "COULDN'T LOOK UP YOUR PUBLIC IP (OFFLINE?)."
            elif self.public_code:
                line = f"INTERNET CODE: {self.public_code}   (FORWARD UDP PORT {NET_PORT} ON YOUR ROUTER)"
            draw_text(screen, self.tiny_font, line, (220, 235, 220), (W // 2, 218), shadow=False)
        else:
            draw_text(screen, self.small_font, f"CONNECTED TO {self.lobby_names[0].upper() or 'HOST'}",
                      (220, 235, 220), (W // 2, 140), shadow=False)
            draw_text(screen, self.tiny_font, f"PING {int(self.ping)} MS" if self.ping else "",
                      (170, 185, 180), (W // 2, 175), shadow=False)

        # Player cards.
        names = self.lobby_names
        ready = [True, self.guest_ready] if host else list(self.lobby_ready)
        if not host:
            ready[1] = self.my_ready
        cards = [(pygame.Rect(W // 2 - 440, 260, 380, 160), BLUE, BLUE_LIGHT, 0),
                 (pygame.Rect(W // 2 + 60, 260, 380, 160), RED, RED_LIGHT, 1)]
        for rect, col, light, idx in cards:
            pygame.draw.rect(screen, UI, rect, border_radius=20)
            pygame.draw.rect(screen, col, rect, 4, border_radius=20)
            nm = names[idx]
            if nm:
                draw_text(screen, self.font, nm.upper(), light, (rect.centerx, rect.top + 55))
                tag = "HOST" if idx == 0 else "GUEST"
                draw_text(screen, self.tiny_font, tag, (170, 185, 180), (rect.centerx, rect.top + 92),
                          shadow=False)
                ok = ready[idx]
                draw_text(screen, self.small_font, "READY" if ok else "NOT READY",
                          (110, 230, 130) if ok else (190, 150, 90), (rect.centerx, rect.top + 125),
                          shadow=False)
            else:
                dots = "." * (1 + int(t * 0.05) % 3)
                draw_text(screen, self.small_font, "WAITING FOR PLAYER" + dots, (170, 185, 180),
                          (rect.centerx, rect.centery), shadow=False)
        draw_text(screen, self.font, "VS", WHITE, (W // 2, 340))

        # Action hint.
        if host:
            if self.guest_addr and self.guest_ready:
                pulse = 0.5 + 0.5 * math.sin(t * 0.12)
                col = (255, int(190 + 40 * pulse), 55)
                draw_text(screen, self.menu_font, "SPACE   START MATCH", col, (W // 2, 480))
            elif self.guest_addr:
                draw_text(screen, self.small_font, "WAITING FOR THE OTHER PLAYER TO READY UP...",
                          (205, 215, 210), (W // 2, 480), shadow=False)
            else:
                draw_text(screen, self.small_font, "WAITING FOR A FRIEND TO JOIN...",
                          (205, 215, 210), (W // 2, 480), shadow=False)
        else:
            if self.my_ready:
                draw_text(screen, self.menu_font, "READY!  WAITING FOR THE HOST TO START", (110, 230, 130),
                          (W // 2, 480))
                draw_text(screen, self.tiny_font, "SPACE  UNREADY", (170, 185, 180), (W // 2, 515),
                          shadow=False)
            else:
                pulse = 0.5 + 0.5 * math.sin(t * 0.12)
                draw_text(screen, self.menu_font, "SPACE   READY UP", (255, int(190 + 40 * pulse), 55),
                          (W // 2, 480))

        if self.net_msg:
            draw_text(screen, self.small_font, self.net_msg, RED_LIGHT, (W // 2, 565))
        bottom = ("I  LOOK UP INTERNET CODE (CONTACTS API.IPIFY.ORG)      ESC  CLOSE PARTY" if host
                  else "ESC  LEAVE PARTY")
        draw_text(screen, self.small_font, bottom, WHITE, (W // 2, H - 36))

    def build_field_surface(self):
        surf = pygame.Surface((W, H))
        surf.fill((18, 26, 20))

        crowd = random.Random(5)
        pal = [(190, 60, 60), (70, 110, 200), (225, 205, 90), (220, 220, 220),
               (90, 160, 90), (150, 90, 180), (230, 130, 60)]
        for zx, zy, zw, zh in ((0, 0, W, FIELD_TOP - 3),
                               (0, FIELD_TOP, FIELD_LEFT - 3, FIELD_BOTTOM - FIELD_TOP),
                               (FIELD_RIGHT + 3, FIELD_TOP, W - FIELD_RIGHT - 3, FIELD_BOTTOM - FIELD_TOP),
                               (0, FIELD_BOTTOM + 3, W, H - FIELD_BOTTOM - 3)):
            pygame.draw.rect(surf, (26, 31, 36), (zx, zy, zw, zh))
            for _ in range(int(zw * zh / 120)):
                c = crowd.choice(pal)
                shade = crowd.uniform(0.30, 0.58)
                pygame.draw.circle(surf, tuple(int(v * shade) for v in c),
                                   (zx + crowd.randint(2, max(3, zw - 2)),
                                    zy + crowd.randint(2, max(3, zh - 2))), 3)

        pygame.draw.rect(surf, FIELD_DARK, FIELD_RECT)

        stripe_width = FIELD_RECT.width // 10
        for i in range(10):
            if i % 2 == 0:
                pygame.draw.rect(surf, FIELD,
                                 (FIELD_LEFT + i * stripe_width, FIELD_TOP,
                                  stripe_width + 1, FIELD_RECT.height))

        rng = random.Random(12)
        for _ in range(900):
            x = rng.randint(FIELD_LEFT, FIELD_RIGHT)
            y = rng.randint(FIELD_TOP, FIELD_BOTTOM)
            pygame.draw.circle(surf, FIELD_LIGHT if rng.random() < 0.5 else FIELD_DARK, (x, y), 1)

        pygame.draw.rect(surf, WHITE, FIELD_RECT, 4)
        pygame.draw.line(surf, WHITE, (FIELD_RECT.centerx, FIELD_TOP),
                         (FIELD_RECT.centerx, FIELD_BOTTOM), 3)
        pygame.draw.circle(surf, WHITE, FIELD_RECT.center, 92, 3)
        pygame.draw.circle(surf, WHITE, FIELD_RECT.center, 5)

        penalty_w, penalty_h = 150, 310
        pygame.draw.rect(surf, WHITE, (FIELD_LEFT, FIELD_CY - penalty_h // 2, penalty_w, penalty_h), 3)
        pygame.draw.rect(surf, WHITE, (FIELD_RIGHT - penalty_w, FIELD_CY - penalty_h // 2,
                                       penalty_w, penalty_h), 3)

        box_w, box_h = 62, 170
        pygame.draw.rect(surf, WHITE, (FIELD_LEFT, FIELD_CY - box_h // 2, box_w, box_h), 3)
        pygame.draw.rect(surf, WHITE, (FIELD_RIGHT - box_w, FIELD_CY - box_h // 2, box_w, box_h), 3)

        pygame.draw.circle(surf, WHITE, (FIELD_LEFT + 105, FIELD_CY), 4)
        pygame.draw.circle(surf, WHITE, (FIELD_RIGHT - 105, FIELD_CY), 4)

        for goal in (LEFT_GOAL, RIGHT_GOAL):
            pygame.draw.rect(surf, GOAL_NET, goal, border_radius=5)
            for x in range(goal.left + 4, goal.right, 7):
                pygame.draw.line(surf, (120, 130, 135), (x, goal.top), (x, goal.bottom), 1)
            for y in range(goal.top + 5, goal.bottom, 10):
                pygame.draw.line(surf, (120, 130, 135), (goal.left, y), (goal.right, y), 1)
            pygame.draw.rect(surf, GOAL_FRAME, goal, 5, border_radius=4)
        for px, py in POSTS:
            pygame.draw.circle(surf, GOAL_FRAME, (px, py), POST_R)
            pygame.draw.circle(surf, (150, 155, 158), (px, py), POST_R, 1)

        surf.blit(self.vignette, (0, 0))
        return surf

    def draw_hud(self):
        online = self.mode in ("host", "client")
        panel = pygame.Rect(W // 2 - 225, 8, 450, 64)
        pygame.draw.rect(screen, UI, panel, border_radius=16)
        pygame.draw.rect(screen, UI_LIGHT, panel, 2, border_radius=16)
        pygame.draw.rect(screen, BLUE, (panel.left + 10, panel.top + 12, 6, 40), border_radius=3)
        pygame.draw.rect(screen, RED, (panel.right - 16, panel.top + 12, 6, 40), border_radius=3)

        draw_text(screen, self.tiny_font, self.side_name(1)[:8], BLUE_LIGHT,
                  (panel.left + 62, panel.centery), shadow=False)
        draw_text(screen, self.tiny_font, self.side_name(2)[:8], RED_LIGHT,
                  (panel.right - 62, panel.centery), shadow=False)
        draw_text(screen, self.font, str(self.blue_score), WHITE, (panel.left + 124, panel.centery))
        draw_text(screen, self.font, str(self.red_score), WHITE, (panel.right - 120, panel.centery))

        remaining = max(0, math.ceil((self.match_duration - self.clock_frames) / 60))
        low = remaining <= 10 and self.state in ("play", "goal", "countdown")
        col = RED_LIGHT if low and int(self.ui_t * 0.1) % 2 == 0 else WHITE
        if self.overtime:
            pulse = 0.5 + 0.5 * math.sin(self.ui_t * 0.15)
            draw_text(screen, self.small_font, "GOLDEN GOAL",
                      (255, int(190 + 45 * pulse), 55), (panel.centerx, panel.centery), shadow=False)
        else:
            draw_text(screen, self.font, f"{remaining // 60:02d}:{remaining % 60:02d}", col,
                      (panel.centerx, panel.centery), shadow=False)

        if online:
            controls_text = ("MOVE: WASD OR ARROWS  -  SHOOT: E / P (HOLD = POWER)  -  "
                             "TACKLE: R / L  -  DASH: SHIFT")
        elif self.mode == "pvp":
            controls_text = ("BLUE: WASD MOVE - E SHOOT (HOLD = POWER) - R TACKLE - LSHIFT DASH     "
                             "RED: ARROWS - P SHOOT (HOLD) - L TACKLE - RSHIFT DASH")
        else:
            controls_text = ("YOU: WASD OR ARROWS MOVE - E / P SHOOT (HOLD = POWER) - R / L TACKLE - SHIFT DASH"
                             "     RED: BOT")

        control_panel = pygame.Rect(W // 2 - 520, H - 58, 1040, 40)
        pygame.draw.rect(screen, UI, control_panel, border_radius=12)
        draw_text(screen, self.tiny_font, controls_text, WHITE, control_panel.center, shadow=False)

        if online:
            esc = "ESC  LOBBY" if self.mode == "host" else "ESC  LEAVE"
            draw_text(screen, self.small_font, esc, (200, 205, 205), (18, 13), anchor="topleft",
                      shadow=False)
            ping = self.ping if self.mode == "client" else self.guest_ping
            if ping:
                pc = (110, 230, 130) if ping < 80 else (GOLD if ping < 150 else RED_LIGHT)
                draw_text(screen, self.tiny_font, f"PING {int(ping)} MS", pc, (18, 38),
                          anchor="topleft", shadow=False)
        else:
            draw_text(screen, self.small_font, "ESC  PAUSE", (200, 205, 205), (18, 13), anchor="topleft",
                      shadow=False)

        snd = "NO AUDIO" if not self.sound.ok else ("ON" if self.sound.on else "OFF")
        draw_text(screen, self.tiny_font, "N  SOUND " + snd, (200, 205, 205), (W - 18, 13),
                  anchor="topright", shadow=False)

    def draw_big_center(self, text, color, scale=1.0, y=H // 2 - 30, font=None):
        font = font or self.huge_font
        img = font.render(text, True, color)
        sh = font.render(text, True, (0, 0, 0))
        w, h = max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale))
        img = pygame.transform.smoothscale(img, (w, h))
        sh = pygame.transform.smoothscale(sh, (w, h))
        sh.set_alpha(150)
        screen.blit(sh, (W // 2 - w // 2 + 4, y - h // 2 + 6))
        screen.blit(img, (W // 2 - w // 2, y - h // 2))

    def draw_goal_message(self):
        prog = 1.0 - self.goal_timer / 150.0
        slide = min(1.0, prog * 6)
        slide = 1 - (1 - slide) ** 3
        band = pygame.Surface((W, 120), pygame.SRCALPHA)
        band.fill((*self.goal_color, 150))
        band_y = H // 2 - 110
        screen.blit(band, (int((1 - slide) * -W), band_y))
        scale = 0.6 + 0.4 * slide + 0.05 * math.sin(prog * 14)
        self.draw_big_center("GOAL!", WHITE, scale, band_y + 60, self.big_font)
        draw_text(screen, self.font, self.goal_message, GOLD, (W // 2, band_y + 150))
        if self.coin_timer > 0 and self.coin_message:
            draw_text(screen, self.font, self.coin_message, GOLD,
                      (W // 2, band_y + 190), shadow=True)

    def draw_overlay_text(self, title, color, lines):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((5, 8, 10, 180))
        screen.blit(overlay, (0, 0))
        self.draw_big_center(title, color, 1.0, H // 2 - 90, self.big_font)
        for i, line in enumerate(lines):
            draw_text(screen, self.font if i == 0 else self.small_font, line, WHITE,
                      (W // 2, H // 2 + 10 + i * 42))

    def award_winner(self, metric, goals=None):
        """Choose a side for a post-match award; return None for a draw."""
        vals = []
        for side in range(2):
            if metric == "mvp":
                goals_n = (goals or [0, 0])[side]
                value = goals_n * 4.0 + self.stats["shots"][side] * 0.8 + \
                    self.stats["steals"][side] * 1.15 + self.stats["pu"][side] * 0.7 + \
                    self.stats["poss"][side] / 240.0
            else:
                value = self.stats[metric][side]
            vals.append(float(value))
        if abs(vals[0] - vals[1]) < 0.01:
            return None, vals
        return (0 if vals[0] > vals[1] else 1), vals

    def draw_match_highlights(self):
        """A dedicated full-time report with awards, stats, and a goal timeline."""
        screen.fill((8, 14, 23))
        t = self.ui_t
        # Ambient stadium beams and a subtle pitch-like grid.
        for i in range(9):
            x = int(i * W / 8 + math.sin(t * 0.01 + i) * 14)
            pygame.draw.line(screen, (15, 29, 39), (x, 0), (x - 110, H), 2)
        pygame.draw.ellipse(screen, (12, 27, 35), (80, -145, W - 160, 430), 2)
        pygame.draw.ellipse(screen, (12, 27, 35), (175, -100, W - 350, 340), 2)

        draw_text(screen, self.tiny_font, "HYPER SOCCER  /  POST-MATCH REPORT",
                  (145, 175, 185), (W // 2, 22), shadow=False)
        draw_text(screen, self.big_font, "MATCH HIGHLIGHTS", WHITE, (W // 2, 56))

        score_panel = pygame.Rect(58, 86, W - 116, 108)
        pygame.draw.rect(screen, (19, 29, 39), score_panel, border_radius=18)
        pygame.draw.rect(screen, (56, 72, 82), score_panel, 2, border_radius=18)
        left_col = self.p1.color
        right_col = self.p2.color
        draw_text(screen, self.font, self.side_name(1), left_col,
                  (score_panel.left + 170, score_panel.centery - 10))
        draw_text(screen, self.font, self.side_name(2), right_col,
                  (score_panel.right - 170, score_panel.centery - 10))
        draw_text(screen, self.big_font, f"{self.blue_score}  -  {self.red_score}",
                  GOLD if self.blue_score == self.red_score else WHITE,
                  (score_panel.centerx, score_panel.centery - 7))
        shootout_decided = (not self.penalty_standalone and self.penalty_finished
                            and self.penalty_winner in (0, 1))
        if shootout_decided:
            winner_side = self.penalty_winner + 1
            result = f"{self.side_name(winner_side)} WIN ON PENALTIES!"
            result_col = left_col if winner_side == 1 else right_col
        elif self.blue_score > self.red_score:
            result = f"{self.side_name(1)} TAKE THE WIN!"
            result_col = left_col
        elif self.red_score > self.blue_score:
            result = f"{self.side_name(2)} TAKE THE WIN!"
            result_col = right_col
        else:
            result, result_col = "IT'S A DRAW!", GOLD
        if shootout_decided:
            result += f"  ({self.penalty_scores[0]} - {self.penalty_scores[1]} pens)"
        draw_text(screen, self.small_font, result, result_col,
                  (score_panel.centerx, score_panel.bottom - 15), shadow=False)

        goals = [0, 0]
        for g in self.goal_history:
            if int(g.get("side", 1)) in (1, 2):
                goals[int(g["side"]) - 1] += 1
        awards = [
            ("MATCH MVP", "mvp", goals, "impact score"),
            ("SHOT CREATOR", "shots", None, "shots taken"),
            ("TACKLE ACE", "steals", None, "clean steals"),
            ("POWER-UP PRO", "pu", None, "power-ups"),
        ]
        card_y, card_h, card_w, card_gap = 211, 111, 250, 23
        total_w = card_w * 4 + card_gap * 3
        start_x = (W - total_w) // 2
        for i, (label, metric, goalarg, sublabel) in enumerate(awards):
            x = start_x + i * (card_w + card_gap)
            rect = pygame.Rect(x, card_y, card_w, card_h)
            pygame.draw.rect(screen, (19, 29, 39), rect, border_radius=14)
            pygame.draw.rect(screen, (57, 74, 84), rect, 1, border_radius=14)
            winner, vals = self.award_winner(metric, goalarg)
            draw_text(screen, self.tiny_font, label, (165, 185, 193),
                      (rect.centerx, rect.y + 18), shadow=False)
            if winner is None:
                name, col, val = "SHARED", GOLD, "TIED"
            else:
                name = self.side_name(winner + 1)
                col = left_col if winner == 0 else right_col
                val = str(int(round(vals[winner])))
            draw_text(screen, self.menu_font, name, col, (rect.centerx, rect.y + 52))
            draw_text(screen, self.tiny_font, f"{val}  {sublabel}", WHITE,
                      (rect.centerx, rect.bottom - 16), shadow=False)

        if self.last_match_reward:
            draw_text(screen, self.tiny_font, self.last_match_reward, GOLD,
                      (W // 2, 333), shadow=False)

        timeline = pygame.Rect(58, 342, W - 116, 214)
        pygame.draw.rect(screen, (16, 26, 35), timeline, border_radius=16)
        pygame.draw.rect(screen, (51, 68, 78), timeline, 1, border_radius=16)
        draw_text(screen, self.small_font, "GOAL TIMELINE",
                  GOLD, (timeline.left + 22, timeline.top + 22), anchor="midleft", shadow=False)
        if not self.goal_history:
            draw_text(screen, self.small_font,
                      "No goals this match — the defenders owned the pitch.",
                      (178, 192, 198), (timeline.centerx, timeline.centery + 8), shadow=False)
        else:
            shown = self.goal_history[-6:]
            if len(self.goal_history) > len(shown):
                draw_text(screen, self.tiny_font,
                          f"+{len(self.goal_history) - len(shown)} earlier goals",
                          (145, 160, 168), (timeline.right - 22, timeline.top + 22),
                          anchor="midright", shadow=False)
            for i, g in enumerate(shown):
                col_idx = i % 2
                row = i // 2
                x = timeline.left + 22 + col_idx * 530
                y = timeline.top + 55 + row * 43
                side = int(g.get("side", 1))
                col = left_col if side == 1 else right_col
                secs = max(0, int(float(g.get("time", 0))))
                stamp = f"{secs // 60:02d}:{secs % 60:02d}"
                chip = pygame.Rect(x, y - 14, 500, 34)
                pygame.draw.rect(screen, (27, 39, 48), chip, border_radius=9)
                pygame.draw.circle(screen, col, (chip.x + 15, chip.centery), 5)
                draw_text(screen, self.tiny_font, stamp,
                          (160, 179, 188), (chip.x + 31, chip.centery), anchor="midleft", shadow=False)
                draw_text(screen, self.small_font, f"{self.side_name(side)}  GOAL",
                          col, (chip.x + 92, chip.centery), anchor="midleft", shadow=False)

        # A small stat strip keeps the report useful without crowding the goal story.
        p1_poss, p2_poss = self.stats["poss"]
        poss_total = p1_poss + p2_poss
        p1_pct = int(round(100 * p1_poss / poss_total)) if poss_total else 50
        p2_pct = 100 - p1_pct
        summary = (f"SHOTS  {int(self.stats['shots'][0])} - {int(self.stats['shots'][1])}"
                   f"     |     POSSESSION  {p1_pct}% - {p2_pct}%"
                   f"     |     STEALS  {int(self.stats['steals'][0])} - {int(self.stats['steals'][1])}")
        draw_text(screen, self.tiny_font, summary, (190, 205, 210), (W // 2, 576), shadow=False)
        draw_text(screen, self.small_font,
                  f"CAREER COINS  {self.profile['coins']}   ·   GOALS  {self.profile['total_goals']}   ·   WINS  {self.profile['wins']}",
                  GOLD, (W // 2, 606), shadow=False)

        # The video button opens actual slow-motion replay clips captured during play.
        video_label = "WATCH VIDEO [H]" if self.goal_replays else "VIDEO REPLAY [H]"
        rematch_label = "WAIT FOR HOST" if self.mode == "client" else "REMATCH  [SPACE]"
        for rect, label in ((self.highlight_video_rect, video_label),
                            (self.highlight_rematch_rect, rematch_label),
                            (self.highlight_menu_rect,
                             "LOBBY  [M]" if self.mode == "host" else
                             ("LEAVE  [ESC]" if self.mode == "client" else "MAIN MENU  [ESC]")),
                            (self.highlight_upgrade_rect, "UPGRADES  [U]")) :
            hover = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (34, 47, 57) if hover else (20, 31, 41), rect,
                             border_radius=12)
            pygame.draw.rect(screen, GOLD if hover else (70, 91, 100), rect,
                             2 if hover else 1, border_radius=12)
            draw_text(screen, self.small_font, label, GOLD if hover else WHITE,
                      rect.center, shadow=False)

        self.fx_layer.fill((0, 0, 0, 0))
        for particle in self.particles:
            particle.draw(self.fx_layer)
        screen.blit(self.fx_layer, (0, 0))

    def draw_upgrade_shop(self):
        """Career screen where earned coins can be spent on gameplay upgrades."""
        screen.fill((7, 13, 22))
        t = self.ui_t
        for i in range(10):
            x = int(i * W / 9 + math.sin(t * 0.008 + i) * 18)
            pygame.draw.line(screen, (17, 33, 44), (x, 0), (x - 90, H), 2)
        draw_text(screen, self.tiny_font, "HYPER SOCCER  /  CAREER MODE",
                  (150, 177, 190), (W // 2, 28), shadow=False)
        draw_text(screen, self.big_font, "PLAYER UPGRADES", WHITE, (W // 2, 70))
        draw_text(screen, self.font, f"COINS: {self.profile['coins']}",
                  GOLD, (W // 2, 122), shadow=False)
        draw_text(screen, self.tiny_font,
                  f"CAREER  ·  {self.profile['total_goals']} GOALS  ·  {self.profile['wins']} WINS  ·  MATCHES {self.profile['matches']}",
                  (185, 202, 208), (W // 2, 153), shadow=False)

        accent_cols = ((95, 173, 255), (111, 236, 177), (255, 147, 113))
        for i, key in enumerate(self.upgrade_keys):
            rect = self.upgrade_rects[i]
            col = accent_cols[i]
            hover = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (22, 34, 45) if not hover else (31, 48, 61), rect,
                             border_radius=18)
            pygame.draw.rect(screen, col if hover else (62, 82, 94), rect,
                             2 if hover else 1, border_radius=18)
            level = int(self.profile['upgrades'][key])
            draw_text(screen, self.small_font, self.upgrade_titles[i], col,
                      (rect.centerx, rect.top + 32), shadow=False)
            draw_text(screen, self.tiny_font, self.upgrade_descriptions[i],
                      (207, 218, 224), (rect.centerx, rect.top + 70), shadow=False)
            draw_text(screen, self.big_font, f"LV {level} / 5", WHITE,
                      (rect.centerx, rect.top + 126))
            bar = pygame.Rect(rect.x + 35, rect.top + 157, rect.w - 70, 12)
            pygame.draw.rect(screen, (42, 54, 63), bar, border_radius=6)
            if level:
                fill = pygame.Rect(bar.x, bar.y, int(bar.w * level / 5), bar.h)
                pygame.draw.rect(screen, col, fill, border_radius=6)
            for pip in range(5):
                px = bar.x + int((pip + 0.5) * bar.w / 5)
                pygame.draw.circle(screen, WHITE if pip < level else (84, 97, 106),
                                   (px, bar.centery), 3)
            if level >= 5:
                buy_label, buy_col = "MAX LEVEL", col
            else:
                cost = self.upgrade_cost(key)
                buy_label = f"UPGRADE  ·  {cost} COINS"
                buy_col = GOLD if self.profile['coins'] >= cost else (169, 177, 181)
            buy = pygame.Rect(rect.x + 28, rect.bottom - 74, rect.w - 56, 48)
            pygame.draw.rect(screen, (39, 51, 60), buy, border_radius=12)
            pygame.draw.rect(screen, col if hover else (83, 103, 113), buy, 2, border_radius=12)
            draw_text(screen, self.small_font, buy_label, buy_col, buy.center, shadow=False)
            draw_text(screen, self.tiny_font, f"PRESS {i + 1} OR CLICK CARD",
                      (144, 163, 172), (rect.centerx, rect.bottom - 12), shadow=False)

        self.upgrade_back_rect = pygame.Rect(W // 2 - 105, 548, 210, 48)
        back_hover = self.upgrade_back_rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, (34, 46, 56) if back_hover else (19, 29, 39),
                         self.upgrade_back_rect, border_radius=13)
        pygame.draw.rect(screen, GOLD if back_hover else (72, 92, 103),
                         self.upgrade_back_rect, 2 if back_hover else 1, border_radius=13)
        draw_text(screen, self.small_font, "BACK  [ESC]", GOLD if back_hover else WHITE,
                  self.upgrade_back_rect.center, shadow=False)
        if self.shop_message_timer > 0 and self.shop_message:
            draw_text(screen, self.small_font, self.shop_message, GOLD,
                      (W // 2, 624), shadow=False)
        else:
            draw_text(screen, self.tiny_font,
                      "Earn 5 coins for a goal from the opponent's half · 10 from your own half · +30 for a win",
                      (183, 199, 208), (W // 2, 624), shadow=False)
        draw_text(screen, self.tiny_font,
                  "UPGRADES AFFECT YOUR BLUE PLAYER IN LOCAL MATCHES. CAREER SAVE IS STORED BESIDE THE GAME FILE.",
                  (137, 154, 164), (W // 2, H - 20), shadow=False)
        self.fx_layer.fill((0, 0, 0, 0))
        for particle in self.particles:
            particle.draw(self.fx_layer)
        screen.blit(self.fx_layer, (0, 0))

    def draw_replay_viewer(self):
        """Render a cinematic, slow-motion goal replay with a video timeline."""
        screen.fill((3, 8, 14))
        if not self.goal_replays:
            for i in range(8):
                x = i * W // 7
                pygame.draw.line(screen, (13, 30, 42), (x, 0), (x - 150, H), 2)
            draw_text(screen, self.big_font, "NO GOAL CLIPS YET", WHITE, (W // 2, H // 2 - 25))
            draw_text(screen, self.small_font,
                      "Goal replays are captured automatically during a match.",
                      (166, 190, 201), (W // 2, H // 2 + 30), shadow=False)
            draw_text(screen, self.tiny_font, "ESC  BACK TO MATCH REPORT",
                      GOLD, (W // 2, H - 88), shadow=False)
            self._draw_replay_button(self.replay_back_rect, "BACK TO REPORT [ESC]")
            pygame.display.flip()
            return

        clip = self.goal_replays[self.replay_clip_i]
        frames = clip.get("frames", [])
        if not frames or self.replay_actor1 is None or self.replay_actor2 is None:
            draw_text(screen, self.big_font, "REPLAY UNAVAILABLE", WHITE, (W // 2, H // 2))
            self._draw_replay_button(self.replay_back_rect, "BACK TO REPORT [ESC]")
            pygame.display.flip()
            return
        idx = int(clamp(round(self.replay_cursor), 0, len(frames) - 1))
        frame = frames[idx]
        cv = self.canvas
        if self.field_surface is None:
            self.field_surface = self.build_field_surface()
        cv.blit(self.field_surface, (0, 0))

        # Playback uses separate replay actors so the finished match state stays untouched.
        def apply_state(actor, state):
            actor.x, actor.y = state["x"], state["y"]
            actor.vx, actor.vy = state["vx"], state["vy"]
            actor.facing_x, actor.facing_y = state["fx"], state["fy"]
            actor.animation_time = state["anim"]
            actor.squash = state["squash"]
            actor.kick_timer = state["kick"]
            actor.tackle_timer = state["tackle"]
            actor.flash_timer = state["flash"]
            actor.stamina = state["stamina"]
            actor.exhausted = state["exhausted"]
            actor.charging = state["charging"]
            actor.charge = state["charge"]
            actor.boost_t = state["boost"]
            actor.mega_t = state["mega"]
            actor.frozen_t = state["frozen"]

        apply_state(self.replay_actor1, frame["p1"])
        apply_state(self.replay_actor2, frame["p2"])

        self.fx_layer.fill((0, 0, 0, 0))
        trail = frame.get("trail", [])
        for i, (tx, ty) in enumerate(trail):
            alpha = int(25 + 115 * (i + 1) / max(1, len(trail)))
            rr = max(2, int(13 * (i + 1) / max(1, len(trail))))
            pygame.draw.circle(self.fx_layer, (238, 247, 255, alpha), (int(tx), int(ty)), rr)
        cv.blit(self.fx_layer, (0, 0))

        for actor in sorted((self.replay_actor1, self.replay_actor2), key=lambda q: q.y):
            actor.draw(cv)
        draw_ball(cv, frame["bx"], frame["by"], 13, frame["br"])

        # A gentle zoom follows the scoring action, like a TV replay camera.
        progress = idx / max(1, len(frames) - 1)
        zoom = 1.0 + 0.095 * (0.5 - 0.5 * math.cos(math.pi * progress))
        sw, sh = int(W * zoom), int(H * zoom)
        scaled = pygame.transform.smoothscale(cv, (sw, sh)) if zoom > 1.001 else cv
        if zoom > 1.001:
            cx = frame["bx"] * zoom
            cy = frame["by"] * zoom
            crop_x = int(clamp(cx - W / 2, 0, sw - W))
            crop_y = int(clamp(cy - H / 2, 0, sh - H))
            screen.blit(scaled, (0, 0), pygame.Rect(crop_x, crop_y, W, H))
        else:
            screen.blit(scaled, (0, 0))

        # Letterbox bars and broadcast-style HUD.
        pygame.draw.rect(screen, (2, 5, 9), (0, 0, W, 80))
        pygame.draw.rect(screen, (2, 5, 9), (0, H - 108, W, 108))
        pygame.draw.rect(screen, GOLD, (26, 24, 8, 34), border_radius=3)
        draw_text(screen, self.tiny_font, "HYPER SOCCER  /  INSTANT REPLAY",
                  (173, 190, 199), (48, 16), anchor="topleft", shadow=False)
        side = int(clip.get("side", 1))
        team_col = self.p1.color if side == 1 else self.p2.color
        draw_text(screen, self.font, f"GOAL REPLAY  ·  {self.side_name(side)}",
                  team_col, (W // 2, 45), shadow=False)
        secs = int(max(0, frame.get("clock", 0)))
        stamp = f"{secs // 60:02d}:{secs % 60:02d}"
        draw_text(screen, self.small_font, stamp, WHITE, (W - 44, 43), anchor="midright", shadow=False)

        # Timeline with an animated progress marker and clip count.
        bar = pygame.Rect(220, H - 83, W - 440, 8)
        pygame.draw.rect(screen, (49, 65, 75), bar, border_radius=4)
        progress_bar = idx / max(1, len(frames) - 1)
        if progress_bar > 0:
            pygame.draw.rect(screen, team_col,
                             (bar.x, bar.y, max(4, int(bar.w * progress_bar)), bar.h), border_radius=4)
        knob_x = int(bar.x + bar.w * progress_bar)
        pygame.draw.circle(screen, WHITE, (knob_x, bar.centery), 6)
        draw_text(screen, self.tiny_font,
                  f"CLIP {self.replay_clip_i + 1} / {len(self.goal_replays)}   ·   SLOW-MOTION",
                  (164, 184, 194), (W // 2, H - 93), shadow=False)

        self._draw_replay_button(self.replay_back_rect, "BACK TO REPORT [ESC]")
        self._draw_replay_button(self.replay_pause_rect,
                                 "PAUSE [SPACE]" if self.replay_playing else "PLAY [SPACE]")
        self._draw_replay_button(self.replay_next_rect, "NEXT CLIP [RIGHT]")
        pygame.display.flip()

    def _draw_replay_button(self, rect, label):
        hover = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, (31, 48, 59) if hover else (17, 29, 39), rect,
                         border_radius=10)
        pygame.draw.rect(screen, GOLD if hover else (69, 90, 100), rect,
                         2 if hover else 1, border_radius=10)
        draw_text(screen, self.tiny_font, label, GOLD if hover else WHITE,
                  rect.center, shadow=False)

    def draw_stats_panel(self):
        st = self.stats
        rows = (("SHOTS", st["shots"][0], st["shots"][1], False),
                ("STEALS", st["steals"][0], st["steals"][1], False),
                ("POSSESSION", st["poss"][0], st["poss"][1], True),
                ("POWER-UPS", st["pu"][0], st["pu"][1], False))
        panel = pygame.Rect(W // 2 - 300, 428, 600, 206)
        pygame.draw.rect(screen, UI, panel, border_radius=18)
        pygame.draw.rect(screen, UI_LIGHT, panel, 2, border_radius=18)
        for i, (label, a, b, pct) in enumerate(rows):
            y = panel.top + 18 + i * 47
            tot = a + b
            frac = a / tot if tot > 0 else 0.5
            if pct:
                left = int(round(frac * 100))
                la, lb = f"{left}%", f"{100 - left}%"
            else:
                la, lb = str(int(a)), str(int(b))
            draw_text(screen, self.tiny_font, label, (170, 185, 180), (panel.centerx, y), shadow=False)
            draw_text(screen, self.small_font, la, BLUE_LIGHT, (panel.left + 30, y), anchor="midleft",
                      shadow=False)
            draw_text(screen, self.small_font, lb, RED_LIGHT, (panel.right - 30, y), anchor="midright",
                      shadow=False)
            bar = pygame.Rect(panel.left + 30, y + 14, panel.w - 60, 10)
            pygame.draw.rect(screen, RED, bar, border_radius=5)
            bw = int(bar.w * frac)
            if bw > 0:
                pygame.draw.rect(screen, BLUE, (bar.x, bar.y, bw, bar.h), border_radius=5)


    def draw_touch_controls(self):
        if self.state not in ("play", "countdown", "goal"):
            return
        labels = {"up": "▲", "down": "▼", "left": "◀", "right": "▶",
                  "dash": "DASH", "tackle": "TACKLE", "shoot": "SHOOT"}
        for name, rect in self.touch_rects().items():
            side, action = name.split("_", 1)
            col = BLUE if side == "p1" else RED
            active = name in self.touch_held
            layer = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            pygame.draw.rect(layer, (*col, 210 if active else 125), layer.get_rect(), border_radius=15)
            pygame.draw.rect(layer, (255, 255, 255, 230 if active else 155),
                             layer.get_rect(), 2, border_radius=15)
            screen.blit(layer, rect.topleft)
            font = self.font if action in ("up", "down", "left", "right") else self.tiny_font
            draw_text(screen, font, labels[action], WHITE, rect.center, shadow=False)
        draw_text(screen, self.tiny_font, "BLUE", BLUE_LIGHT, (100, H - 42), shadow=False)
        if self.mode == "pvp":
            draw_text(screen, self.tiny_font, "RED", RED_LIGHT, (W - 100, H - 42), shadow=False)

    def draw(self):
        if self.state == "menu":
            self.draw_menu()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "online_menu":
            self.draw_online_menu()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "join":
            self.draw_join()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "lobby":
            self.draw_lobby()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "settings":
            self.draw_settings()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "customize":
            self.draw_customize()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "upgrades":
            self.draw_upgrade_shop()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state in ("penalties", "penalty_finished"):
            self.draw_penalties()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "finished":
            self.draw_match_highlights()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "replay":
            self.draw_replay_viewer()
            return

        if self.field_surface is None:
            self.field_surface = self.build_field_surface()

        offx = offy = 0
        if self.shake > 0:
            offx = int(random.uniform(-self.shake, self.shake))
            offy = int(random.uniform(-self.shake, self.shake))

        cv = self.canvas
        cv.blit(self.field_surface, (0, 0))

        # Effects layer: ball trail + particles, drawn under the players.
        self.fx_layer.fill((0, 0, 0, 0))
        tr = self.ball.trail
        n = len(tr)
        for i, (tx, ty) in enumerate(tr):
            k = (i + 1) / n
            pygame.draw.circle(self.fx_layer, (255, 255, 255, int(70 * k)),
                               (int(tx), int(ty)), max(2, int(self.ball.radius * (0.4 + 0.5 * k))))
        for p in self.particles:
            p.draw(self.fx_layer)
        cv.blit(self.fx_layer, (0, 0))

        for pu in self.powerups:
            draw_powerup(cv, pu["t"], pu["x"], pu["y"], self.ui_t)

        for p in sorted((self.p1, self.p2), key=lambda q: q.y):
            p.draw(cv)

        # Shot preview: a subtle aiming guide while charging, with a special
        # gold pulse when the shot reaches full power.
        for shooter in (self.p1, self.p2):
            if shooter.charging and shooter.charge > 0.05:
                fx, fy = normalize(shooter.facing_x, shooter.facing_y,
                                   (-1.0 if shooter.is_p2 else 1.0, 0.0))
                start_x = shooter.x + fx * 38
                start_y = shooter.y + fy * 38
                preview_len = 95 + shooter.charge * 145
                end_x = start_x + fx * preview_len
                end_y = start_y + fy * preview_len
                guide_col = GOLD if shooter.charge >= 0.95 else (
                    BLUE_LIGHT if shooter is self.p1 else RED_LIGHT)
                # Dashed guide makes the shot direction readable without
                # obscuring the pitch or the opponent.
                segments = 9
                for seg in range(segments):
                    if seg % 2 == 0:
                        a = seg / segments
                        b = min(1.0, a + 0.065)
                        p1 = (int(lerp(start_x, end_x, a)),
                              int(lerp(start_y, end_y, a)))
                        p2 = (int(lerp(start_x, end_x, b)),
                              int(lerp(start_y, end_y, b)))
                        pygame.draw.line(cv, guide_col, p1, p2, 3)
                pygame.draw.circle(cv, guide_col, (int(end_x), int(end_y)),
                                   7 if shooter.charge >= 0.95 else 5, 2)
                if shooter.charge >= 0.95:
                    pulse_r = 13 + int(3 * math.sin(self.ui_t * 0.35))
                    pygame.draw.circle(cv, GOLD, (int(end_x), int(end_y)), pulse_r, 2)
                    draw_text(cv, self.tiny_font, "MAX POWER",
                              GOLD, (int(shooter.x), int(shooter.y - 58)),
                              shadow=True)

        # Fast shots get a pulsing energy halo for extra arcade impact.
        ball_speed = math.hypot(self.ball.vx, self.ball.vy)
        if ball_speed > 7:
            halo = pygame.Surface((100, 100), pygame.SRCALPHA)
            pulse = int(45 + 25 * math.sin(self.ui_t * 0.45))
            pygame.draw.circle(halo, (255, 220, 90, pulse), (50, 50), min(43, int(14 + ball_speed * 2)))
            cv.blit(halo, (int(self.ball.x - 50), int(self.ball.y - 50)))
            if ball_speed > 12:
                for i in range(3):
                    ang = math.atan2(self.ball.vy, self.ball.vx) + math.pi + (i - 1) * 0.22
                    sx = int(self.ball.x + math.cos(ang) * 25)
                    sy = int(self.ball.y + math.sin(ang) * 25)
                    pygame.draw.circle(cv, (255, 240, 155), (sx, sy), 3 - (i == 1))
        self.ball.draw(cv)

        # Online: name tags and a bobbing "you" arrow.
        if self.mode in ("host", "client"):
            me = self.p1 if self.mode == "host" else self.p2
            for idx, p in ((1, self.p1), (2, self.p2)):
                draw_text(cv, self.tiny_font, self.side_name(idx), BLUE_LIGHT if idx == 1 else RED_LIGHT,
                          (int(p.x), int(p.y - p.radius - 32)))
            bob = math.sin(self.ui_t * 0.15) * 3
            ax, ay = int(me.x), int(me.y - me.radius - 50 + bob)
            pygame.draw.polygon(cv, GOLD, [(ax - 7, ay - 8), (ax + 7, ay - 8), (ax, ay + 2)])

        screen.fill((10, 14, 12))
        screen.blit(cv, (offx, offy))

        self.draw_hud()
        self.draw_touch_controls()
        if self.coin_timer > 0 and self.coin_message and self.state not in ("finished", "replay"):
            toast = pygame.Rect(W // 2 - 200, 112, 400, 42)
            pygame.draw.rect(screen, (18, 28, 35), toast, border_radius=12)
            pygame.draw.rect(screen, GOLD, toast, 2, border_radius=12)
            draw_text(screen, self.small_font, self.coin_message, GOLD, toast.center, shadow=False)

        if self.state == "countdown":
            part = self.countdown_total / 3.0
            num = max(1, math.ceil(self.countdown / part))
            frac = (self.countdown % part) / part
            if self.overtime:
                draw_text(screen, self.font, "GOLDEN GOAL  -  NEXT GOAL WINS", GOLD,
                          (W // 2, H // 2 - 150))
            self.draw_big_center(str(num), GOLD, 0.7 + 0.5 * frac)
        elif self.go_timer > 0:
            self.draw_big_center("GO!", WHITE, 1.0 + (1 - self.go_timer / 45.0) * 0.5)

        if self.state == "goal":
            self.draw_goal_message()

        if self.goal_flash > 0:
            flash = pygame.Surface((W, H), pygame.SRCALPHA)
            flash.fill((255, 255, 255, int(80 * self.goal_flash / 22)))
            screen.blit(flash, (0, 0))

        if self.state == "paused":
            self.draw_overlay_text("PAUSED", WHITE, ["ESC  RESUME        M  MENU"])

        self.draw_fade()
        pygame.display.flip()

    def draw_fade(self):
        if self.fade > 1:
            f = pygame.Surface((W, H))
            f.set_alpha(int(self.fade))
            screen.blit(f, (0, 0))

    async def run(self):
        while self.running:
            ms = clock.tick(FPS)
            dt = min(ms / (1000.0 / 60.0), 2.5)
            self.handle_events()
            if not self.running:
                break
            self.update(dt)
            self.draw()
            # Yield to the browser so it can render, process touch input and update the page.
            await asyncio.sleep(0)
        self.net_shutdown()


async def main():
    game = None
    try:
        game = Game()
        await game.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if game is not None:
                game.net_shutdown()
        except Exception:
            pass
        # Pygbag owns the browser runtime; do not tear down pygame on WebAssembly.
        if not WEB_BUILD:
            pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())

