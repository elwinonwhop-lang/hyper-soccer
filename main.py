import asyncio
import pygame
import sys
import math
import random
import json
import os
import time
import base64
import io
from array import array

WEB_BUILD = sys.platform == "emscripten"
RELAY_URL = "wss://hyper-soccer-relay-1.onrender.com"

if WEB_BUILD:import asyncio
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

# Mobile browsers use a wide 20:9-style canvas because Hyper Soccer is played
# in landscape on phones. This keeps the pitch and HUD proportional to the device.
PHONE_WEB_BUILD = False
if WEB_BUILD:
    try:
        PHONE_WEB_BUILD = bool(platform.window.eval(
            "(function(){var ua=navigator.userAgent||'';"
            "var coarse=!!(window.matchMedia&&matchMedia('(pointer:coarse)').matches);"
            "return /Android.*Mobile|iPhone|iPod|Windows Phone/i.test(ua)||"
            "(coarse&&Math.min(screen.width||9999,screen.height||9999)<=600);})()"
        ))
    except Exception:
        PHONE_WEB_BUILD = False

SCREEN_WIDTH = 1400 if PHONE_WEB_BUILD else 1200
SCREEN_HEIGHT = 650 if PHONE_WEB_BUILD else 700
W, H = SCREEN_WIDTH, SCREEN_HEIGHT
FPS = 120            # render cap; all physics is delta-time based (60 Hz units)
MATCH_SECONDS = 90

# Online settings
NET_PORT = 47821     # UDP port the host listens on
PROTO = 5            # hybrid 2v2 plus authoritative sliding-keeper snapshots
MAGIC = "HSOC"
INTERP_DELAY = 0.105  # seconds behind the host; gives WebSocket jitter room to settle

MENU_STATES = ("menu", "online_menu", "join", "lobby", "settings", "customize", "upgrades")
BACK_NAV_STATES = ("online_menu", "join", "lobby", "settings", "customize", "upgrades",
                   "penalties", "penalty_finished", "finished", "replay")
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
    # The default computer should be beatable: it hesitates, aims loosely, and rarely tackles.
    {"name": "EASY", "lull": 0.0070, "lull_len": (22, 46), "think": (27, 45), "mag": 0.43,
     "err": 82, "aim": 155, "shoot": 0.0045, "shoot_x": 455, "charge": (0.0, 0.16),
     "tackle": 0.010, "tk_range": 52, "fumble": 0.0038, "dash": False, "seek_pu": False},
    {"name": "NORMAL", "lull": 0.0045, "lull_len": (18, 38), "think": (20, 34), "mag": 0.57,
     "err": 63, "aim": 132, "shoot": 0.008, "shoot_x": 530, "charge": (0.0, 0.28),
     "tackle": 0.020, "tk_range": 59, "fumble": 0.0022, "dash": False, "seek_pu": False},
    # HARD: more alert and accurate, but still beatable (no constant sprinting or perfect aim).
    {"name": "HARD", "lull": 0.0007, "lull_len": (7, 15), "think": (10, 18), "mag": 0.81,
     "err": 36, "aim": 94, "shoot": 0.022, "shoot_x": 685, "charge": (0.08, 0.54),
     "tackle": 0.060, "tk_range": 72, "fumble": 0.0010, "dash": False, "seek_pu": False},
]

# Desktop builds start in fullscreen. Press F11 to switch between fullscreen and
# windowed mode. Browsers require a user gesture for true fullscreen, so the web
# build fills the viewport immediately and adds an HTML fullscreen toggle button.
DISPLAY_FULLSCREEN = not WEB_BUILD
if WEB_BUILD:
  screen = pygame.display.set_mode((W, H))
else:
  try:
    screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.FULLSCREEN, vsync=1)
  except Exception:
    try:
      screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN)
    except Exception:
      DISPLAY_FULLSCREEN = False
      try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED, vsync=1)
      except Exception:
        screen = pygame.display.set_mode((W, H))

pygame.display.set_caption("Hyper Soccer 1v1")
clock = pygame.time.Clock()


def set_desktop_fullscreen(enabled):
    # Switch the native Pygame window between fullscreen and windowed modes.
    global screen, DISPLAY_FULLSCREEN
    if WEB_BUILD:
        return False
    flags = pygame.SCALED | (pygame.FULLSCREEN if enabled else 0)
    try:
        screen = pygame.display.set_mode((W, H), flags, vsync=1)
    except TypeError:
        screen = pygame.display.set_mode((W, H), flags)
    except Exception:
        try:
            screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN if enabled else 0)
        except Exception:
            return False
    DISPLAY_FULLSCREEN = bool(enabled)
    return True


def setup_web_fullscreen_ui():
    # Make the web canvas fill the phone landscape viewport without letterboxing.
    if not WEB_BUILD:
        return
    js = r'''    (function() {
      try {
        var root = document.documentElement;
        var body = document.body;
        var ua = navigator.userAgent || '';
        var coarsePointer = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
        var phone = /Android.*Mobile|iPhone|iPod|Windows Phone/i.test(ua) ||
                    (coarsePointer && Math.min(screen.width || 9999, screen.height || 9999) < 600);

        var viewportMeta = document.querySelector('meta[name=viewport]');
        if (!viewportMeta) {
          viewportMeta = document.createElement('meta');
          viewportMeta.name = 'viewport';
          document.head.appendChild(viewportMeta);
        }
        viewportMeta.content = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover';

        [root, body].forEach(function(el) {
          el.style.width = '100%';
          el.style.height = '100%';
          el.style.minHeight = '100dvh';
          el.style.margin = '0';
          el.style.padding = '0';
          el.style.overflow = 'hidden';
          el.style.position = 'fixed';
          el.style.inset = '0';
          el.style.background = '#050b17';
          el.style.touchAction = 'none';
        });

        var canvas = document.querySelector('canvas');
        function sizeCanvas() {
          if (!canvas) canvas = document.querySelector('canvas');
          if (!canvas) return;
          /* Fill the real viewport. The landscape prompt prevents a phone from
             squeezing the 12:7 pitch into a tall portrait screen. */
          canvas.style.position = 'fixed';
          canvas.style.left = '0';
          canvas.style.top = '0';
          canvas.style.right = '0';
          canvas.style.bottom = '0';
          canvas.style.width = '100vw';
          canvas.style.height = '100dvh';
          canvas.style.maxWidth = 'none';
          canvas.style.maxHeight = 'none';
          canvas.style.objectFit = 'fill';
          canvas.style.display = 'block';
          canvas.style.margin = '0';
          canvas.style.padding = '0';
          canvas.style.touchAction = 'none';
          canvas.style.userSelect = 'none';
          canvas.style.webkitUserSelect = 'none';
        }
        sizeCanvas();

        var button = document.getElementById('hyper-soccer-fullscreen');
        if (!button) {
          button = document.createElement('button');
          button.id = 'hyper-soccer-fullscreen';
          button.type = 'button';
          button.textContent = '⛶';
          button.setAttribute('aria-label', 'Toggle fullscreen');
          button.title = 'Toggle fullscreen';
          button.style.position = 'fixed';
          button.style.top = 'max(9px, env(safe-area-inset-top))';
          button.style.right = 'max(9px, env(safe-area-inset-right))';
          button.style.zIndex = '2147483647';
          button.style.width = '38px';
          button.style.height = '38px';
          button.style.padding = '0';
          button.style.display = 'grid';
          button.style.alignItems = 'center';
          button.style.justifyContent = 'center';
          button.style.border = '1px solid rgba(103,220,255,.85)';
          button.style.borderRadius = '50%';
          button.style.background = 'rgba(5,15,30,.78)';
          button.style.color = '#dff8ff';
          button.style.font = '700 19px/1 system-ui, sans-serif';
          button.style.boxShadow = '0 3px 12px rgba(0,0,0,.32)';
          button.style.backdropFilter = 'blur(8px)';
          button.style.webkitBackdropFilter = 'blur(8px)';
          button.style.cursor = 'pointer';
          button.style.touchAction = 'manipulation';
          button.style.userSelect = 'none';
          document.body.appendChild(button);
        }

        var rotateOverlay = document.getElementById('hyper-soccer-rotate');
        if (!rotateOverlay && phone) {
          rotateOverlay = document.createElement('div');
          rotateOverlay.id = 'hyper-soccer-rotate';
          rotateOverlay.style.position = 'fixed';
          rotateOverlay.style.inset = '0';
          rotateOverlay.style.zIndex = '2147483646';
          rotateOverlay.style.display = 'none';
          rotateOverlay.style.flexDirection = 'column';
          rotateOverlay.style.alignItems = 'center';
          rotateOverlay.style.justifyContent = 'center';
          rotateOverlay.style.gap = '18px';
          rotateOverlay.style.padding = '28px';
          rotateOverlay.style.boxSizing = 'border-box';
          rotateOverlay.style.textAlign = 'center';
          rotateOverlay.style.background = 'radial-gradient(circle at 50% 35%, #15334d, #050b17 72%)';
          rotateOverlay.style.color = '#eef9ff';
          rotateOverlay.style.fontFamily = 'system-ui, sans-serif';
          rotateOverlay.style.touchAction = 'manipulation';

          var rotateIcon = document.createElement('div');
          rotateIcon.textContent = '↻';
          rotateIcon.style.fontSize = '76px';
          rotateIcon.style.lineHeight = '1';
          rotateIcon.style.color = '#68dcff';
          rotateIcon.style.textShadow = '0 0 28px rgba(70,210,255,.55)';
          rotateOverlay.appendChild(rotateIcon);

          var heading = document.createElement('div');
          heading.textContent = 'ROTATE YOUR PHONE';
          heading.style.fontSize = 'clamp(22px, 6vw, 32px)';
          heading.style.fontWeight = '900';
          heading.style.letterSpacing = '.08em';
          rotateOverlay.appendChild(heading);

          var hint = document.createElement('div');
          hint.textContent = 'Hyper Soccer plays in landscape so the pitch and controls fit your screen.';
          hint.style.maxWidth = '320px';
          hint.style.fontSize = '15px';
          hint.style.lineHeight = '1.5';
          hint.style.color = '#b7cada';
          rotateOverlay.appendChild(hint);

          var rotateButton = document.createElement('button');
          rotateButton.type = 'button';
          rotateButton.textContent = '⛶  TRY LANDSCAPE FULLSCREEN';
          rotateButton.style.marginTop = '8px';
          rotateButton.style.padding = '14px 20px';
          rotateButton.style.border = '1px solid #68dcff';
          rotateButton.style.borderRadius = '14px';
          rotateButton.style.background = 'linear-gradient(135deg, #164b70, #12243d)';
          rotateButton.style.color = '#f0fbff';
          rotateButton.style.font = '800 13px system-ui, sans-serif';
          rotateButton.style.letterSpacing = '.04em';
          rotateButton.style.boxShadow = '0 8px 28px rgba(0,0,0,.35)';
          rotateButton.style.touchAction = 'manipulation';
          rotateOverlay.appendChild(rotateButton);
          document.body.appendChild(rotateOverlay);
        }

        function isFullscreen() {
          return !!(document.fullscreenElement || document.webkitFullscreenElement);
        }

        async function enterOrExitFullscreen() {
          try {
            if (isFullscreen()) {
              if (document.exitFullscreen) await document.exitFullscreen();
              else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
              if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock();
            } else {
              var target = document.documentElement;
              if (target.requestFullscreen) await target.requestFullscreen({navigationUI: 'hide'});
              else if (target.webkitRequestFullscreen) target.webkitRequestFullscreen();
              /* Android Chrome supports locking orientation after fullscreen begins. */
              if (phone && screen.orientation && screen.orientation.lock) {
                try { await screen.orientation.lock('landscape'); } catch (orientationError) {}
              }
            }
          } catch (err) {
            /* Some mobile browsers only support manual device rotation. */
          }
          updateViewport();
          updateButton();
        }

        button.onclick = enterOrExitFullscreen;
        if (rotateOverlay) {
          var rotateButton = rotateOverlay.querySelector('button');
          if (rotateButton) rotateButton.onclick = enterOrExitFullscreen;
        }

        function updateViewport() {
          sizeCanvas();
          var portrait = window.innerHeight > window.innerWidth;
          if (rotateOverlay) rotateOverlay.style.display = portrait ? 'flex' : 'none';
          if (button) button.style.display = (phone && portrait) ? 'none' : 'flex';
        }

        function updateButton() {
          if (button) {
            button.textContent = isFullscreen() ? '×' : '⛶';
            button.setAttribute('aria-label', isFullscreen() ? 'Exit fullscreen' : 'Enter fullscreen');
            button.title = isFullscreen() ? 'Exit fullscreen' : 'Enter fullscreen';
          }
          updateViewport();
        }

        window.addEventListener('resize', updateViewport, {passive: true});
        window.addEventListener('orientationchange', updateViewport, {passive: true});
        if (window.visualViewport) {
          window.visualViewport.addEventListener('resize', updateViewport, {passive: true});
        }
        if (screen.orientation && screen.orientation.addEventListener) {
          screen.orientation.addEventListener('change', updateViewport);
        }
        document.addEventListener('fullscreenchange', updateButton);
        document.addEventListener('webkitfullscreenchange', updateButton);
        window.addEventListener('keydown', function(event) {
          if (event.key === 'F11' && !phone) {
            event.preventDefault();
            enterOrExitFullscreen();
          }
        });
        updateViewport();
        updateButton();
      } catch (err) { /* Keep the game playable if a browser blocks page styling. */ }
    })();
    '''
    try:
        platform.window.eval(js)
    except Exception:
        pass

setup_web_fullscreen_ui()

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

# Embedded arcade menu artwork (keeps the game in a single-file format).
MENU_BG_ART_B64 = (
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUEBAQEAwUEBAQGBQUGCA0ICAcHCBALDAkNExAUExIQEhIUFx0ZFBYcFhISGiMaHB4f'
    'ISEhFBkkJyQgJh0gISD/2wBDAQUGBggHCA8ICA8gFRIVICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg'
    'ICAgICAgICD/wgARCAMqBZ8DASIAAhEBAxEB/8QAHAAAAgMBAQEBAAAAAAAAAAAAAgMAAQQFBgcI/8QAGwEAAwEBAQEBAAAAAAAA'
    'AAAAAQIDAAQFBgf/2gAMAwEAAhADEAAAAfjVyVWXV7SSYSSbVch0km1yTaSTaSVtd0bCtGaMvpq5PT9fy1Y9a5V4c3YfJ9GXVq0u'
    'rOkkwkkOkk2lybTdh6HRLnSTnrJL2l1eEkh0kvCXVnXJZWXHuqnrxHGuTmvJIMzXgZVHU5VZjLimpdA1LoaSWdClsLuWy1ZWyjDh'
    'AA6gVWdYhDmwQ62CjpSNHAVw9rrz77I3lytx87N0K5Um2rJdc1pdWjQhNl0/U/N8D0PJ+sfOvqXzvqhwk7Ec/dnjRlQCu8au7OGy'
    'mA6wyvLnYrry/SkkRpV1tJHbK00uilVWCXovOE6Nyeu8pgElyrUuAyXNql3j3surP6PGNHU6rpuydObTAOq4O15qGD1ZFKgXpi0T'
    'TLOhWOdlLoG2CoKMZTBdlWUbs8cEl15ZJCJJNpJNpJNrkm0kra5HsqGXn2aqrm9NU3YdeUap6BXL6no8S+d0Qi/Jti/P7buodclk'
    'Vcm0lwiVc2nRDP0wRJfNepc2kk2kubS5ZFXIRZO23irAoJ0qSc1pJNpJNpJNj2YDqj41VZ1LpTUuA1dERdw3WjhOkK7dasrZRpts'
    'EzQx0xX1ulSPmB+hAF+f7vT8cK5Hn1JbucvKMeqVdcvRKkBlSA1JAZBsYvY89PTyKXldTe09j8q+x9nB8uydzk22UHhy9SiMwVx0'
    'ITbN+TH5NyfP7JV1DpkkGltN1gBDrlWpu6s6XRbF6nyr6TxT2XjpPJdpSoUxqW8N1lbL9Dnwjsxo9XQqwjYATJKi8KHJ3L3ZJdMv'
    'cguE1tFOfXS0puGfS3KfNnux0Rdtm2cNLGTMwxWnHur7PJkt7LnvVTpmj4CiMFWGW4hD7zEPz1JvJIjSSbRinMtCYsBaqA9cOd0/'
    'Q5E4OguFMNycvRd1ZEuQiS4RJL26/G7fG6eapc5umpc2qXeFS7Oq41lV1+l56/Hp5EnN21JJVqXBql1tLq9pJDpVza9uIqo+nKrI'
    'ZdI0YLWWjs6zEyJ1EiKiCWvr15uA7uspz16nxHOY/V8XzDPN+759QR7LCh5uiVKm9VdK0G4pqroGVKBlVFN9bF27wLh1GFtUw7X6'
    '7xu/u4frfzj6j4K/HwF688+wW1oBVbjda851/J+fQZdcXpyr0nI0RLpYXEaSWDVy9pJZMuXtLl47dnH6NZcm+jgh0DZFOgOAdu+q'
    'M7VSvo45vnDQoojG1UCN6rjTMyiOjF6Vt0PXa8vz/s97MI+Z6wc9OHvGnFyl+j5XRwWfRFO0epK/nWv2PLHqxGr+Tt6/c+TLUNdE'
    'LDZndcrqbOlW3NRDyPZN8FPVy3qSKal1tJIDT06HQRMXAS4jVcrbqJw9Pu5subcmFM5Vcay5ZWQowqWRHb4PovP15BhSXWN3ewwr'
    'wGy9TTn5HTw8EwsLrm9OpdAyrgNSQaSTaS5tUubVcsipc2vZiKqOpy6TNttrICZdUrbjzsnZvh2U6/MXJVOBQc6ARjEKV5UGb3Ui'
    'mqugakgNVcBGWINDdI8MO7WbuLUrK5VzcjA6I3Vk0dEPae5+R/Yerz/mOH0Xn7ANWXRHpc4/FTliqTyfbpmxdEtFQEZcRqlwGrub'
    'Vd3iJXAZcMMBS8Y0ds7drjY9Opz7ZECo6se2T+zXo4at+cHm81qdy9Lld/Dx9PNm27Rxkx2KuzmRDsP0WLdyeqrpcz1/D1cnndq4'
    'WxP9J2+Pj+c4/rWPR+WJ+i5Oro8fzPo+qk/E9Tvzlr8Njg/SPzp8z06dpoO9Lzubh6OTk7Oavavzu5boyiLUo5UTLka1JBqlwate'
    'XdaaQaDAKKpsMKAjCrbpDz+p38uBfTwQoFy5UuXbLXT53ery8nMyCy7OAhDs4NvVfTg0+Ty1K41dR7ql0pqXW1S6BlXAZJMJJNrq'
    'XtVzS65pu0UnyS25FY9XMaw3JymQ4hcyiRW6CRWQMOHLptbKF4gpFwKViwVYIQo1VcBqXQ1VdAiBAlJJuYaMRKvG5Vye7qyCMTdD'
    'cptp6/Y+L6Xdw/Vfl31j5uebkbcrlty+AXU830cOpebUoSkqjZWCMYIYIc2l3YYLOwVx4q4Wwg6TK1NU852ylt9VydXl9v0zy3m9'
    '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'
    'UzXk5IPFpo1an83XkWa31Dr2rbl7fa9Py/Q+e9/vTm7fKc/6CIn89P2O20/E9T2Gfl6+V2+PUretweS6YT0zOL5SMew3l8Tq6+3X'
    'F0Wl3OJl3qV6ux6Tgbznp9vO8zj6CvMZnb2w+O6+3R7Hi/OWT6dj+TZuuHrORgL0en3PgMuO/Dq6fKR088pddXKyLhUhGmQquiti'
    'FMsgk8jXryYXKlE15Tf08+a5aNVkToJEbqJGTqva7L1cqCbqYZtPZX2cWLUZWk7qcbutP2betp+e9XzPsPNd5GLD2sXL1kjieX7u'
    'IeBfP+h8ffTCaHm8z8PL7HV08yPDFhbk8j1qXYcfSNgSUKQmFac/RcEAj28lacTFbv8AS811PU8l+Dqcsjo+++ZexmvvNvCf5z7+'
    '55TAlvceA2c/oj5bB3uB6PPy09FHL2rqxVqraohCNb1fA/cnHZzuvHn5RPezcXbyK7Vx6OFO3zuPqywweVXRbWM045Luue4wh2qS'
    '9qIbxaSBDPZlsHcrPtlbGNysKJ8FEzeSVxn3OMll0N35tuHVkU7X81pK2d7by+hwn6OWL7B576R3drBzeTt9Jw8ltJ4r9alfPatm'
    'aHT3R8ZjEfQo6Hqee/I5mjkFw2+h5RfznZ7XoY83muXeN6Whx35tfZ8KM1+pcbxWWcvRr88PWev3PPfSuC84/ouZ5d/na93G+n89'
    'oqPp5NSloZSFN15nLSVJbsTUkEA00yNUIMRjJUuitXUZblWyySys6XO7PTzcsiMOBmyirNzKzTtHqX5OajTs6J5d2tHTxijM5aZ9'
    'jVg9TZzetXn9V7n5/wB3wvU6mHm7JN00gmbcDxe3i/ReZnW7n0bq8/Bm5OggUfH27JUvDFi3YfO7hkHnuogudDg2Qe/nPcaKGdnM'
    'MEpvp6fJ39vH2Ehfoec/0Hjgm30PrfPvSbm7eVeTDDwuz5837DvIyFu5iHrOmK9eV0wN2dcPz3/UsHO/gL62jr5vKu7gy6eVzujh'
    'W+/0/hM/i+pv8j0ch2atbWXKG/JK2aXa4DZ1+Xt5A/UeF5fd4YNGf1/MIKvKNlMKKyDDbaWg+34fV8z1un0eLs8f29nick9nxelx'
    'tW68+GrVfTyZ95Cl09ff3fN9Tz+bRxKOhfX61efkbu1zOHs4F7Mff5urPybtzd4/Omrk12N59hGFkuru8TEuvCR32GXrHwkcXf8A'
    'ReN4ekl3+Gp/dykDxWiKPO0zJOoBesuhzdPW998mR5Xo/TvE8PP0RYgQ9XzytZ15yoaogCast1VZSsIyvvOVZyapSeSSI1kEIkll'
    'al2RRQmE7XIdfnfO/wAvogp2jZUc1uvuVkjB3dl+LhP+peXhTwCulzeuWnI/0en5fqcvNPp7weZ04970nl/RtPu9Lkv8+m3nD5+i'
    '+cRjT3OzHoyc3QpBK8/tt6HbagFVoryuz8PYFQeewyRXu6si3KZSbhgWSWFzbR0Obr7Obs7OMXby5gNXPXX2fN77Q9Ro4L+vh2YG'
    'ZA3HDp8zg9CxQUbdDueYd0c/svWfNvqFuL1vG7fB8rt7XF9BwtuLy/p/E6U+cY/f8ns5/H5fWgafP56zLzdmVmrkcnbx0dDmT1Vr'
    '0Tph93wNHN29nzW3mp0YV61V5FofolXms6CVfIOuFMnQ1FzduJu73fD18vpcXhed6XpfNen7ap8or1+L1uHhs9Fqj1eX9x6HZ5ac'
    'fzm/AnV0H8Hjda+x5XksPdw9XkC30/MRRDfmqVZS6gbEydeVeJuxgwaEFkO5dJspRHMoaGsLBWXKJARqENq0860czVZzbVA7KGsL'
    'Gqeduz6KTGrFloShCJKUXKsiXVkQqjruLAXRz1XStl5ttGVRsjdVk2MtOjrx9Tze5j6uJfT19q0OJ3fWJ4rNx69XH05sx9gN8u5O'
    'zyfv+R0eAtPJ6BWpkejQ3Z0uvk7XQUdOTZWJalvlej5ur4FRXD6OtIqXBnNXF1tbmZg4KEgEtVCwCVRqDFFjLYDAjumBgQvOpURm'
    'PzOsmpmVnRzsVFgt0Ym7dd3N0dnHrUNUkGXSmFsQmrj7Gvy6GHU7PmWdnJ7rseEbbm+y5PD9Xlf6L5oX8fR3Pn3rfn900O8tl619'
    'anzDlt2EYnLQZbUqvdm2eX7N81vP5O7Lxu2Znzsvp0cfZ5d3WI7EnTphfF6Dtc3yu7ib/ZdTl5uR57tTl7/N9btZKoz0XmMEub1u'
    'HxcrT2nU8l4m/N3vMZc/v8r6yj2cOtKapDQgVtNoVHlIEy7uhxtXN2ZAg9PJb88UsgszUTXz6MQbsZmu6lOciVW12E2uSDQhgJwL'
    'BOVWLIqzmhVESVWVj0abIFGJUautgU8AAlwGSWRLlssKjZbKiqnW0cVnRxWPc00l50tsemFzVnek3eX9l0cXsvQeC+ieV1cjq8DW'
    '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'
    'w6OXW1fPbMTKVrcGq8Vjqu0s+g1MsdjXRuvXFqw6SK3FeUXrZPn8lff5kOjKxNzs3RkWym/KxWCmLRrum4Uaj2eSWUUxkIDM5cnR'
    'DCNLg3tVSAyXNpdXtLlEXVVsUA9ql1tZDCDGTYZIDVSKZUoGSQGSTaSTa5VnSrrCSQG7lstQmMEkwSGFkm2nPUU3JYMurIhCREhU'
    'wqXBhlzEZdAiEk3uVe1XJtGLthclkWQ2ykYRld0OTTz6WAXNlJsOe9yRWkuyKKMYGwXdMI7vc3p4eZWip9ILilfdkzVNzlNDU3d2'
    'uji89p9mHR5nm0v5luzqH5m5W9CHCKG0pCp9FKJcLAF1z2qrtWojbREno13jg1aH9PO73/zXvdfl+0+auinmBfL4/WyGM8n0WUsj'
    'tikjRNTMM22u5kK94eLo6Ydc+U20t9JfaW6uv7Pq8v5fj6nGh6Ks7lef3rqxhW7CbMNNsOx1PK308fuq8OV+X0/Gmqz8ce/Ftwp3'
    'ObN87FXzVMs5rtDEMrPp4NGesRX2OWjKWy43yhrTJ1QorS6mEkraSXjJcIGQQSsC2ksdrlQaSVjUlKZDMhMfRCqMVapIDJJtJZEB'
    'bmUVVQcLXdI8kgNyphcl7S5CJcsirkOO1sdKlw4ZdA0tiUarkm8ks6pJtJd4HV1RZKg1yoNJdYwZQLQc608xOSQtl2DNKm3kW7Mf'
    'TzaOZWiTZ51iqnJzdtTPl6GHGm9Ezy5FPRc/n1BmUoZ9LVDU3uxtSwlsohW07SyK0hKijbZynZoC0udpUs3cMse1ixERp04NLrmb'
    'nqFqAwlRcOouDAmx3VMJVEpGzWdLkGu6twevFKT9Fu8iXVyekTkV1xYMXz2tNhGoU0J0CmipGSKSujdbIRdSEaVm6cMovZvi31x7'
    'aeZqdZN/ZEPOX6pw5vIr9DzE6eacXHq242x0zW9c6UrqYCiRbUrKjKUhDoYKZAVwwBq6EE6k2klbSSwTaD7yvPoFlyFdxquQgbps'
    'dAYJstKsFajCI5Dd4BRRWG7m1XLIkkOuxmBVK2sgs51CVJyroFa7qNZdXtdHbALKiKE6BExLaWy3RRxe0qrVxOzI1ZB12kLup1Or'
    'z/In9ARubyfV0cnH0mHyahT1mLzy59PQ54zl7rJZKxsHVeTg2N7+Ll59yObozU8IWSTx2Al3i88zqTa7mK27nJUubsSQ895RUrXR'
    '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'
    'kOL6c33P3mCtvcbW9QCWNz6BSZ4nxAdGbm/o3+DUAldbWO9KVvxnGduFI3iEM04CHxBojW5w0RtYDuLUZTiF43p9iKaNRqxFXXRd'
    'R0WbELcSmYRPcAqbgZa55Y1h5XaNTJxI9Ma129Qx8JLLrLn3Nzf5j/yvSf8AVqyLqT78WTten3SzAyFBHkiCf9XP4kfizrxb8B/x'
    'p01NTS8ZxI66iHRw8WsUHPe2e/fWVmWQt55GYuLXlXZeHTiOLmY11F5WzVulPda2qyuLYdDRNAQP/lsi0CBNT/I0WsCcGIGON6UQ'
    'sqxsnzxsiqTD26a8vMbIPtb3rybD3HM4Exan4VUZFjugUk0pC25wZo1DqeKiLYEa217bOLSlanvZgrkk9R+TUAgSComVpxnGLXuJ'
    'j7nsnItxysarTP4jNOO5y+7lNmJpolUorG/SKK+LKGX1KpaMnhygpna8doxkMNWgw4zc5kKHM5ktT5D12WTljUNmZF+ST8/6OHf2'
    'MrLo9tlf624lj1n39jTeHbPaPHcbmpr6OJI+hfvT6teE0o8maH0uVJmprU0dpUlcfJsyrO47si9jHd2d/M15w80YtDrRk46UCqLv'
    'WNiMtK1sGZaif4+rSYVcroVFC6nGcNzis5LC4A76NNMw9ukFYWBAIXCi80ZE54WPLPVu2HCXlMA2C3Hpx4MusVHMu3s7bgZXiu0t'
    'tVFOzOw2icZJ3iIzFpv6vn8OpqASqrm3arA4QV+OyYqET0zHW6wKoX1TGRGv8MamMsrHHj4gaKwia50eTjYhsbHx8nEj+pVquU5v'
    'twfTWvj+mdtbQFJMbcYQhYwjQxB9ykIve5Y9lNlUYkj/AE8j/k+m/wC0hgsaC1D9XJtfQPBcdFqdxrqo5FvPXU4wAbfjy10HERrX'
    'eV47WK/J3pxx2qMcLBi1miwJ3BUxmL6Tzqu7STlZdalSzBwQXvyWJ4loldkSizYRZoTwIbjO482J3NA9szuARrWEa8xTZYbcgUC7'
    'Ke0nI4SzIDnlsq3lfVaqq7q+8OXC114XKjWH2XaFjsFNtKzv2TfnfSyt6nUcm104nj0QefsmlnGcDO207bTtmCuCpYiURRUItrxb'
    'HivuVVq8r9L2mVgtW2Fd7e33VJXKruyZfj8JcDp+c3xmugitMU+fSAvYnqagWqm29OYdgkAZZBtCM5elhHrhWAbDqdiozfbKnmbN'
    'Co3cizOG0pmiPpClj2WE0BACZoj8OHYottraq3/XLATySfE+CRBsHumclM19WpqJxh1NbhRunEmH7VmoE3OJExMVL49+FQtllljw'
    'b5Cuwmqgs1t/24vp+yrrXNLGcX4j031mumlS/Jz2PIqUClEWCvIaLRQkTtwMx67Ea3kSY96LHzYHyMiPZwnd3FsOwPNt3tqXa6w1'
    '5FNL2PybkBCX15m2mOMlmsqQrdXhcPf4eNXZlX2t9vQ/PXf1AbjeB9GoJ5g3ACYgQIEECbi0NO0RMDQumcR2iCHwK+TT1asKMn5s'
    'aN0Bg1FEpsCzB9Qeuwer7W7KNlnp+KtynFr1fbaJrk+PSlNXqdKdl9E9kme38GhZavGEFjWvi8/43+VYOrKVbprrQktUmNWRASJ/'
    'YMuvw5f+fG/1fiE7mog10IgliIrdNkTnBoz212hTVGNawsT1/so6P4inx95mkm0ELmDkx7mKlJRnbsMJxWA6iiwz2dsoxa6JXW91'
    'gqx8SZNzXvTTcTZVkWBUVStOQ5XBqWKmOk7tuteUWL900FHIwsqR3NsssWlTZkZDMLC3CukWXs49xjGUV13JXivKaws9Ts7Lf8i4'
    '9mumOz5F3tM1CVAPuq64PUo+bluC+mDbV2DNPOt/RxPCAfT/AEX6NQCBYEiU6muUFM7JlKfdh4dQqysap6R9jUZFzz2yGZeP2Wx8'
    'o1OfU6gufnm2zIby3mMB010DRTMdyLbLCDXfPS86kVPfUi329x8bGttge3HTPymtlWP3bK/S9V5VBqJEuUu3aM/rMgA0OviKQylS'
    'G4wrPE15UxKWdWxIcbjHQgqoaWJo/XikMzqUf/T31AhE4wrNdNRKbLYcRlg9ok966Br7LH7nKcT047PAxdKdcTRl49Nb3tYzOSYA'
    'egrcxRjIqF2NdVrRzTQ9a+4g7NI5WOK6lrleDC3brfzK622uNcJXkU1KmQhH9iWVYb5yteVoWnbVY2RWkrs7kbJE0zR8kbv9RpDP'
    'n22olzUC2/JdeTtOUxjd3RlqIKrLFtwVvvycjCxFtz7SP5TKWO72MJ/x0ndO/ubpUjsW7Srym+pQhPrQaB8nrqARVlVJaIioOEWu'
    'YuI1pf0r7Ox23w8tRXYzXJfQ9bYbrXd+vUsmrT5Hmm0vZluWyHaMxMM3NwTj0xrCGt4sodlNWQVi5HOsfdMLj7OwqKrG22GAlgYM'
    'PU7FaabftiZZVxjiN/6mEK6mop3FrOzSJ7cAnEeJRqBrUleTuPrV3IRLRLSCv1/EztWfj1OM4zX0fE+eg6VrFpJi4dhDYz7ODcJ2'
    'sRJ36azbl32iE/QG4r3NwaPXe1jDQ1ByZkxWaV2YtFHNnspp26Y779xwlQqymbARQvp6bpwbOVWJTRGpttNuPUoNnp9cqyqHrb2t'
    'hHYWHLQQ5SMe7dKnUV+S5yvBdmirsrXoWWY2Ib8t7mybexitaXaq3sw3hYbDvmZULbbaMnAwKX9YRYvrOQpyfUsrJndbb5Nrr8/R'
    'ubldpqtu9Qyrq7PPUAk2Vmp+ikKXsawdUTkXbkeggERNxaxFCADZlabi450a9H0ziF3oZQ29Z4smuGfr2zWcT7xhXdkcoWLnHCV0'
    '5Np7sMPUQWMopFbNThqXs1CxUhkaYzMq8tHH9Stxnv8AUrchajzsx8VKq7aQFsr5HCxE7jVI65tYVzQY1OkauFJ2p29SrwC3E92C'
    '6d1dWO215RPNbVvLBxO/t5eQ4nIQnrxMcBWr+4QKT9Ovt6CIm5Vg2WQei5jTMwrMVj0J666ATExXyLcT0fHoW+vCpTO9Td45JYAs'
    'TqH6dTU1NdAORClXCHfAAjtCFyZ5njhjLyC0WEdmU4pZtuzV42ayUYdKC7MooLeqNyycm9qmNs7pEbJOxkGG/jFvcwW3vKaQp22p'
    'pjFqOqXpmXm3NdfzVqxqm61rbK8W9lurNcPyabBV+xZwXlNzc3NzY1N7m54grLjr84/4NdACS+lGumoFi1iKIq7gpYxaSJgULbcl'
    'aIuXQvOtOJROS5NCmuz7Xq9SahMr1B7YX5M9jOWsURGLHekv82eYTD9IMqM5Tgzs2DlVpS1tMDrYtyNoWEzDublj5ldyWNte3spS'
    'yy2ywLdXzaj0tO3nYfYlnHbEQmFpyMD/AGn7ZynKfIRgG7wELFq7FJYnQPz9AYze+tw+7Z19az0z0ruBcjCx6/UfWzq5uRMP0eTN'
    'TGp5Sj1SvDVvWMppbmWWR7Nwmb10ImumpVSXlhracTOJnHyJ7a0j2/aHp1b3y2jG7hx/PaeCloMc7UtUKaM7IielrUGGBjI/qtgm'
    'OltwyMxKpZdzi5Bx09xzhzbrJdcnYIOtRKeRpxHY1Yyop4VzmTFsp0M3EB7eLdYexXSvY5Z3sdepZCXNUt0a1KPRL8k32gszZQoT'
    'H39e+m+v/XrR9zfVqamumuympqKhMFRiqBAsVRKlG8TA7q5PpwQY3+C0WBg1RaGvzW6hcjJRK8m7bNadhWeWuta2OWgUmV1sI7aW'
    '1/uZix+uszc5kR/U856cRDklAEm/D2AOrnWBmFWrt7iUuOcv+6dolhaFX1C8Wy9NlmZZsGHoZyhHQmeSaxNjjyHcsGzr699P7L+B'
    'Dqd5iRkGNaXh1D0FbMeIE2ohckCNa7xTOU5TfTiTBWeD0dlDqeJRSLbL67UcqyxlZSncUIO5MP0zNyUFWBSNY6hae4bMbAsn8TiP'
    'D6M3JfQ79+2wceHOxKJZ6nkXStiqvc9jYxpVsn1G7jZcS5ApFmTbeeDLO6/Y++VWuDTT3ZXimBO2Ls7HqlvqrwNfcBKMf/Hdkoku'
    '9QVZ7/JM5nlZ5Z8ntrbbY53K2dCzbM3Nzc30ClmdGrs3CdmDyb60qu6o3Cy9eN/XXXU1KkCIds3GJVyntyqHUAEJVItheYvzhWr2'
    'r25Jw+7H+JYRu20l8rL29rbhsAmJU2RbkYNpsuXtN3PK2NGMsh/Ak3D0RtSuyK8uTc8qa8nzgZK2HnEyDo2HeOQasojs5NZJuZkd'
    'iGD1idxlg001OMH2wr4IiiARaSyWY3AvW2+M1NfgsHkVsZx0v1bm5yJghRQoMLE9ddRNzfTfaqLFjTcaXvyGvbUFcGzAO0WyeUOR'
    'Y8TGybRSKcOX+r5Dxsu9p37TOTz/ACaTvmIl1a25dah80xO5fYmPUleTmJFttsncepLcm618TH7YdLnUqtUN7CdxnNOBdbK09OxI'
    'PWF45HruQpOVm5Bf29UbKXfpvN1rREmfmaV7nufXhtRfksvBGRXY8io2xs30px7L+njXTn9mzCd/it+6npqampqalFPde5+6+pXV'
    'uAamzGZVncsc144gKgV27bFLRAAuQoBWzTGxuOzwy7FoWzIh208CJlNXLcqxoW3BBCZZD08fUmPca5voDEaI0PlT8quzjenZdYFj'
    'oFZTHOxXmWUWW5/NmtmTwtTgLIy31xilgfHgd0gKsCsUEHtiLVO0wNR1LAzQh41KzsidgsXwckF6XrPjqQRB4PcJhYt+Devo3ucn'
    'OLroq+CCSmFlOBjGLj8qbQivozYAvFM10UFiMZa0rwquNl6LN7h4iVKXLZDdtnLEdFGzTgVe2ORi1Q+pupsybmYMeXp2G2TZdjpi'
    '13WFlFWNypxaBitXybDwKXuyMWrFl9mflt/HZIgGDVP5GuqXZmRkFX4R8qxx3SsLs03MXEty7qMVKa2wrmOZ6VujIuQA70G1AZyH'
    'JvM3N9A2p3OQKn/QoHcwNTU1NQCcYtTO9/GpOMrp3OEsZK5yuuntQqpfUMXTkBVqmNpRXZxFOf8A43yWtesQkR7PtziGybKWWdzi'
    'rvC0J6LAYY0P4Fvu3v6EMQxT4bW6yNp6ndjJj5rvWOLDuMksNdgyy6qL2WV5tcuox7q1SndtKNkBb6xzDx6hustFq5TsMp4Ttxk0'
    'V8TxGrG8ajFEHqGHjV52fmZJM89EYoGLMehHnU1OPUam/rHmYPooZH9OwVer09lbIyfT8eZOZbkPVldrEP3FvnUCEzlXXUNuw7dK'
    'im10uetQzbPBmmPhl4xpSkmL9xaq1Rzxkld99hNWUwfuI1dbNHxmEC8YPWL6qLMq67opaNk+zpxasrMe3JxMZrvXdy71bMuUkmIl'
    'jxgVnKbm5ublFTXPTdbxwMc4tORn4qtmeo3ZRLddzfQ/SCROSmds6+nZI+v00gZzVlLAIFgSagi1+0oFW4mKxjhag1t1sWmpWezi'
    'ON18wsfmhyOEC0qhztRb3ZkZtUqEAeM0vt0mRZt+4SrmEwmE9FghMYw/gH0CD5SKY07mpzmNdopfBfzRozES4KDsiK5Ui8h+/Rdn'
    'WbV2SvY2oqAubA9Nx/b+oYVdU7DQU6Bx+RbHKAqNtPMaxhHsJmtztmATtoY6AHoB4xcO3Ksp/wDG21nV+lYkMP0gb6H54zFNOMff'
    '83XLD25N2RXLXay1VBjqFlGTVTj6BbiJ+u2Scb0+xouHRirl2va3E7rxy8qpRS1WTebcSmqG/Drlmdew3s+JuAyxhdC321seT2c4'
    'eiIzSt8Sie601mVkWzc8zxEdVJtDQumuIMPRKrXUUKD7ytKznZLTvMYbIWm+v6/CCQe4jw0kj8akq3qKD3YWBYEnb84WIrF67L7q'
    'sficbBp7PqGGlVlo4TdmqaEsicXC3+3Y5RUciYJiKC1W2IM5aBeZV/h28hoY0PQQTcJhh/AOhPVYkrHI241tat87iPqV2wWQ2cgW'
    'lgDB1KnzoGHcqv4Sq/HeVcUOPi9wot2NVkObmxsakUZy9qzizrZQY1UdNTiZdVuFYqfctK9tnxzjWbVt7nx0T+2P6jZi03epZmRX'
    'ZSoj1fd2ROypDUvXANwqBP10qXwZXU7TDwxjL36y+b6dWycxTSdk8YtbGdsLEVrGwPS2l+RTih7brmr9PuyYfR66YW9KrlnrPZOR'
    '6jl5E5fQRowzcKkdKsgVglN7nzBNGeJufPQ9dmfdxUoI2Veapubm5v6f11P4ASD3g89tzBBB+vUAhXveiBItcrqiYpexkWYmHV2s'
    'rFWuzHvYLmU2urBUssHuGubErj5DdRuIpZ8erSIvGAwvLbNS+yMZufoxjNwGb6GGH8A+lYrRbWE57jda2ivA+oxhMt0QzOenIwFT'
    'NMJRaRPS8utXty6VqqHft7bU12A2PRTWlOTXWtrYysLMWezM9pLMMh2q4RHIlh4vaOY0RFUvOwYlXGagBlr8mh3uFudadsTis4Cc'
    'JViFo4WY+NbkvVi4+JVm+otbFDcse69AmDjZ0u9JtW0YF+1wzFxKycb0ztLks3B8j0yuH1lK4/qfqOSLLUWWZLMC/mGxu1yE5dSZ'
    '8lQgmZnnMUg60Ix302JznKcoWJO5+20WMBAhOz+Q/P0Hx+EbB7/Me2FkZGRumpqa6CekjvUqkpoLRcYrMLErFeXjqjY9zCXUu4x3'
    'VLrbaUqzrFL232N08CcoupVfUtFOjKz45w2aCtuXvLWhPTlCYT9Z+jj9vUfSIIDNwmbm4rQPOW5yhhjQ9VYrKrkB7zsfdsK8D1MV'
    '3W+oIa8UG6x1KV/2bdK0X5Do49RWHLWe5rMdq3nbrMsxa3AwkE9rTBTuD01jP49AGGJVL7NLrZrqcs9Tq3CIiaTH5R9Fq8drDVje'
    '1ltjO+P6dbcRQmLTkd68rgxMatJX2UNWTXLKcl2OPUsVvT1L5deHRl+s5dzPazQt57mobXIZ9zi3a3PH0BK+2cTKx8c7J6LbYn4T'
    '4I1rc2fw7+ofP0kfkTMbj7OjIj1WVPqanHoJ6VkDH9SsBTM9HZA2XwK032d6yjuLW/bufKqCW5YDZOUdWtuMYVJhWaglSyldDlob'
    'hbZ3pLmljQmbm5v8B+RN+IIyOhjIUPnW/r39AMWA9TDCOm4uug3Kb24gqHS9iuNnvjXW+om2v08La2ctarkf2sIg8BcgKe6rRXhu'
    'InfMrs5u2RKW1LrHsnAx62sKdvHY5thnDur2Yq8WdrLDRiWWsy10Cw25LYno4rllyVRzzNdTvPY3xvZUE53p6R/W+Ms9SyLpVj5e'
    'UGysX0+rJy7cmzlqFjNzc3Nwn6fMUhTZk2WHyfpEVZ2zDU+j/ob+lP7fUfxjpVmWcfaY+RHosqYVkxqm3qJuZP8AltxQwZa62qt1'
    'j5VvqapUct3Z8huwzisNfYxbYnIidyF+iDcqESbjWwMSbH8WtHP5P108GBeUwxU2HmYaUOLmSvuu9cJ2foH0iAwMYHIGwehhWFdN'
    'Nzc5SsnbeRVa6Tvc1DvKMq7Hssz+6WKujVsp4mMGWcdz7gdmAykv3FqlWNY0u7VcYc4cW+LSxntMjdWO9RdRBVyRMQLALOFPpd9h'
    'ow6sdbhaQ/8AHVF/U8CuXevZOrcvIunKdyGxQaGVmv8AUrXU2FjvxuEzxDxmj9C11yy6ns/hWemej25U/wD4vp1XqfqVmYx/0d/R'
    'X8/6GpqARRAJhpk21en4fp7Xer001ZREUSk930ql1orr9WdKmyGttex7CNa/9rZhCv3TxezlCeoErWIAJy0C+l5eQ0dpYYx/GFLM'
    'cYit/LcDACYPlMy1bTl2Wt4MMHXRHQfWIDAYDAy75DTXOaz13Nxf6i7xzPKrkYyzukRnVhXe1LV2VWq6MhKmducGlVdZCYtjvXiK'
    'Ai01y7KZk5fcKtyplrj5u0rfJVqlvsC4VjEYdSQeySV2qxyvVa6Jf6rlPLMrlGunefZabm+lXEHlN7nxCROXXfT9flU6PubjGtJh'
    'b6Qddd/mr/Afq1NTUAgWCoxPS7vZ4GPivgYuW+KlAtN+bjdjDKYdkvVsaelu1yZjg2tYu+7FMNvi2+M+5ubm+tYEWKZuM24DAYxj'
    'mN1/XRV5TRB8a8QbaUXe2tPqT5NK7ssdtj6h56X4zU1KC7fhE34m5vqfo3EsIgcwOTGaf2grBlqV65WRLnUV3bOkgx7LBj0LjynH'
    '5CwJGpayJ6YzT+Lq4tgpDT6ak7/p1c/mVWP6ve89/PfM7r28dcr1hnVrSxdvu5wuZubm+ijc4GfaJyjHx039Q+kwwa31HzN/7FY+'
    '3rr6SNH6twNMf++ccKz07GyMu+jFp1mWe3wfUfUc+hsnJ9XyL0LlpVe+PK87hYUu6Cc5ZZ4sbzv6QIggm4W8b6bjGND9NWPbkMF/'
    'y20Klykodibbj5nMhSPGyB8dTvr8dGsLVqxUy5K0u8QHR6610H4KcfENV1tAXoIpimL5graCj7O2IaC8GEdjCznlXoeXKfTeC14t'
    'QF+XhJG9Wxlh9ceW+rZDlsu141s7zQ3Tuc5yO0xws/kFpVrOc7nguZyh6b6rrZtMLze5yM3N/j3+Bf8AYCkziBEsUD6ddT8TXXc3'
    'AIqSmoz0lcVlTNrwM7L9RORkW5FtjFobBDY0UbiiK3jlDrROo7wnfUmb6LF6bhP0uZ++jIVrGzKz23DDldXdXPJm9ALuHwBre5+v'
    'DQ1IYajCrCa31UFm673KrDXZY/du4tr6B+EwKpnb1NREdpRhZTn2ZqC00TeCoXI9PWe+pUfy10PqmQYtmVfPdUYwv9UvuLZBMa4a'
    '7s787vKBhO54LbmFiAPlZ1RuP3kmbm59s2kLib5RlRZoGcps9T/rf9fpI/OFYzgBNgQknqrlYjh/wfB3N9FXcengqiU1gQ5CrLMp'
    '9tYZ3J3D1BiQQGbhaNYAGPTc31EWCbnk9BCYo5s21jw7rlJHd2ISvt9mb8oVR3sZ5418kDw/yFdouK5i41Q6CxxEsDQVkxqtQ0iN'
    'U0+DpdeOlidt+jcdEnU/tLqXocRV3Ex7LI2FlInTxNiclncSC5Z7zS+9vjZmQ682M5QOYLTFtgcwRNGW5Fu+avH8EwkzlNzlA82T'
    'KyaobGYs05rDasJInIzc305Hj01Nf7J+f9EKzTgom1EJJ/Al81tfo1OAadvwQJw1N6gJaJ4jWR7NTmeu5ubiiCCcoWhMYwn6RBF6'
    'fJbSCfAPxhvxmTYpt2NMzGLpRNFjrc8Q63BtomO8WiJgWPHqppDZSiNkWH6FsdIMhp3wZ3Vm1aGtDDTDVYOoX6BORiEFsFvT6WT1'
    'U31ZTZdrflHLiuolh2X89467kJhjGeT04sRqfZO/wnfM7m5vqG1CPpH0H/XX5/OFLTtgQMiwszfUeo6qzIyW12R0ZD12Y58iDcVD'
    'AAIXjPCdnpvqBB03NzcJhP0iAQCaOlrZ2ZlobRidsYzOsrIZnfjQ52INQ/PxBuci0GPc4TCleCpntQgN/plIPq5EuzMrImprqJ9s'
    'FRaMjLNdQzCC1oMhZut4MOqxThWiMhWDRP0blGY1CvlXGGrni6M1un8IBMHLQA2bARzWc5ynIwxtTlqcjN9P6ib+jc3OWp4b69/7'
    'A+PyBS07ep9ghZj/AKNOQ9QFdd8M304bAWBQJuFoWhO/q8RR13N9DD1+ei/JA3rjKEDQ5GCvpNpU2W2KxJE3KSqyy0s2xP38xcPI'
    'YDDO1xqgDZTXDmoIc22NlZTglj0AJnbaELCRNnoJ252oAywziDComvoWyxJVnuhryPT8gH05LQ2Dwc4toZxr6arnq6czPtJIBJVg'
    'eP26nHZ4qJyUTm/Du2a6b6AwGb6GH6Cdn8PLlCNf/jqjPO0Fn+MQsx/GfxD5XJS2WUPXAsCxvEJm5uE/Wo+o9D0CliwECngPE2pm'
    '+TOft7uqQ4n264sQikltxMDLulfodzH2OPWWvx6Y+duNlWmM7t9GjOImhFawThGXQmoVBnbldXOk0mMgEZlh2fw1XvU38tlT3+O6'
    '1rTkSzBGmxDtqrVm+ghm5+jZ/jo4WHiNlDrHofJrsRq3+rcBm5voYejNv8gmv/w1R3PZCzlUsNrt/tU32UlOzkRtqW8gmCE/WIOv'
    '66qOUYNrj4p5i6ixEi2MYNa/QVlXxDP2tN1gr9MusNHpFag2+kYcv9cpBt9XzXju7n6dwGa3FWLVFoJgxZaOT9ucRBwctU6n05LR'
    'Tbkhi9fM9iGloa2E+PqEAE4TiYpZJ7q/QybhBlzu49kOPU0OK4hrsE31+OiuVgtsENpyX1HrAP0j6TD+bf8Atj6QCx7YE51LGusc'
    'fnP1/wDX6xlFlZftb5h+tR0AgTYOzNTiTGKlqblose+yyedeYEM7bTUq+e3Y8GC8GPSkF+LXG9Qh9UzCrW22EjoTNzf0+JqAGKXW'
    'VXJMGnDupyv48YDNCYwZUld1qWY2a+XRVk9uBLHt2e6rI84/YV5Q1CGsTtmcCJqAQJNGcmE5VxhXOEK9PIi5NyyvO4t7nAyJ/HYt'
    'sf0q4R8a+qbmpxMG+iH7lfT+Oj1vX1B+g9Nf/lAEzhqcqxDY7fiH+vvoHZSXR1P1gdNamJ6a7nLb/k/bx56Zz9x3NnUGoPMrwsqy'
    'VejWmD0/03HVvUPTcdbfUnd3yrmm99dzlCeh+jUCGCuCsRK1ICyx1amocpxtpwsPKqrr5YleWuWEvssZ2m4h0zfKWGoix9rc6VI1'
    'rochp3/8fgwaMHEntIZ7c6H2kU8gMc7aiMoWEwn6gSCmfl1xPV3iWemZYPpuLaH9OsQW49qH4M10Hgmx5+vnoPm6gIPo4zX5t/7H'
    'HU2ohdj/AKp/CPK/h+RNTj4nE8FHkIOIUEVIGnubOxvfQcZ4Vfucrh3tF9NnZwKp/IY1Ub1e8x8zKt67m/p1NQiaJnbM7YnECDU8'
    'Tc5nmNLMpq0s7xjuz2ZFpZd+DYWO/wAm9RLSq1Woqd0CpeXBt8fS8ihDdV6cuNkX82IhE1+IHRXMyUAz7Z7vHedvCsntSrPTdy0R'
    '18zc2RGvbsA+XFJwyOpE1Nf6wE4zj+DU1OM3xm4Rr/fB1+KtOTkLtOAY7MXROoqjkD4AXTMqv4MTEybIvpmQB7SmuGzDSHOAhzbz'
    'Gex5xmuu/rAME1HgM2IbFZjYIticCdxrrHWb8bgOhX5JVZ8w7nx0+PpKEL44/X8GrItpGDcr5x9SC4xpJY02gkzxNLCBNTX4fE8Q'
    'MywZNogzAZyxHnta2hxrVhWwEQTUBh6fMAXs630UbL1lG101/o7iww/Rqa6CahPUGEa/OPpb69fR+uoEPnr8y20tWNwCNSyzjPCi'
    'uq2xq/SMxwno3BnT0qhv5HFqj+r5DSzMybfpEUVcPM4w9dTU11EbwOVW82urHvLxnZj9J46mjCBAuhrkzL/m0eWiG0eOjDy6/B89'
    'AY3j6fkjruLaSoZqmS565ssPsIHk6Yj96mpr8q22rEy3WDNwrIlHpd8PojtH9Ky0mTXYtmt9FsM1xhC68iXWrcCNH/SA3NdCsIn6'
    'moIR1P0Awj84+vU19Y+dTU2BD89ApZiApiVWPK/S81pX6VahXA9KrjZvpWNLPXrZZ6rnWRrHfpub+kRU3FqJhp4hvM4TXQVuwdSk'
    'BWBwCW2K7ioHRvqB1P1Kq7SvGVVbbjH/ALa4t8HRIC+R5OyJynifbAJsFm1v9RkKD9T4lfb5jjw/UDanyNEi3+8bwdmcjOcB2f3o'
    '9BAu4RD+Dc3BMLOtwo3qmXzT1u0TLzcTIhFDSr0624X4d1OPptwbgIj1tW/XXTU1NdNTXXiZwmoBB4m5vyJoQicfPHx8dD9YOof9'
    'Fvy2Cr25aEwTjZExrSRjV1Vn2qxMjGqh9Vuh9QzrJh4XfWz/ABWPaWm5v6+M4wKInFDjNiCv1Ow25dgNadyoWtYCndfiHIXqD1HX'
    '9QEDoYAnACvRsPGtLVleM5XIpehCJsGcptjCsb0Srdno2RH9LzVnZtrUJ5Xwz8hCzOEYgtx5Jw4lRyHa7HF1PL7QCxbjyKrw+3Va'
    'tx6Ff8acYYeuvAJES1Vr5rrHqxGwEHcj0PSSqzgIVmvrUzHpqsssqw1ssFOyZyIJvtneed7c5KZ9soqW17KWrs0fxagSBIwnGa10'
    'PTfQATc3DCfwiampqH8YmvHEma/FozjEQwivfKoTvw3OZzb6BKzxPebTN+Pazag1mvj37DMvNfKX69Lxh5dficTPHQidt9mryygE'
    'ioSzhvByOxZ/MZUzsm28/ZxVWJXCy3lfpWWYvopi+uRPWcQyvP8AT7IjVvHxkeP6XhMX9GoafwVgj+kZ6izDy1VuShODKP7O1jQa'
    'NbLqsVVmoVAoKmI4WcUbcsLEcEBbXJa/HE6miJxPTfib6EkkkwMwHLyCCdjrqamuiNNww/Xud2zfcYznOSz7J4+nUCwARbeFXQw/'
    'Rubm5uOjrNfiWNVxrh/FqalNoCOp66mpqanifbOSznOZnJvxiE9NfRsa3OUDEQ7PVRuMSZs630/U4nn08mamoSZqaPHU0s0IiM5N'
    'LBGax4tTPQDXXK8d74MDKNa+lX6X0sT+MxCUxMZJ4UNlYyRvVMNY3rVQ+mvKyKovq+eoT13KET/yCuL65gGfyGBcR2bRZ6fiPH9H'
    'wjH9G8fxGQkswc/sotlScauBpKj/ACGpHrBR9twrSe3YMKhy+8qVUQr488YVQ16866/E+2eN6+jlAYD43sCIr2dCJqa/Bv6fMBM5'
    'GczOZgec4GSbomqjO0hnYnt2nt3nYsnZsnasgVxONk4vOLTi04tOJnEziZxM4mcTNGDnsgziZxM4maM4mampqaE8Tc2JzgyF01wM'
    '7hnIzZ/PrU1AOgoY4s3Nzc39QEAipyJUKP8AsevwdwAk8fH3cfBiqGY6n6A+1KucNflMO9x/E55FHo2Yp/guRHo+HXUnp+GgNdFY'
    'bKxkh9TwVjes0RvWbI3quY0fLyXhJP0bhi+YK524RNTjCNdPiLlZNcX1XOWL65kRPXK4nrGE0TPw2i24uRD6P6RkUt/41gst3/ir'
    '1x/QPUENnp2b2bsBKqVLLX94NhBmq2qNYS16lWrQjhQgG4PE10UrAjNAN/T+uuLl24r8xrxw8RQrOVnEn8OoBOM1NTjOMAmuh+nZ'
    'nJp3HndsndsnesnesnfsnfsnuLJ7iye5snubJ33nuLJ7iyd+yd6yG1zObTm05tOTTkf9vc3ubgbU3NnX1kaI8RADYdApsuQEDv3L'
    'N6666f8AUcmOvKL94xb2Nfp+UFX0TKsbF/8AGmter/xn09Qno/ptUP8AHYsyvWsMM/rWDt/X6RH9fyDH9XznjZmU8LFpv6tzlOQh'
    'O4Pk/KKxK2NW5vflz2eQnIRviOOJ+uvJyapX616lXE/8kzIn/kyyn/yDCJp9Y9JuTIxPSMxLfSsbb+iVGH0e1J/H5iA05SqV0v73'
    'okTx0+Qq7jCKE3AN9B8wDx1H0bIh39LDi0E3OU5TxNCanGAdDNf/AIwmumvrbQP1a6HwNa/BrU/etKKW1vVfiUU9lL7+4W/trUBM'
    'CuxGDkmL6ZbF9MTjX6Xiiezwq538OqH1XDEPrWOIf/IGn/8As3qAFnrvqdsOZkEtYWnKbm5+7kFb/Xvp+l0HjJxOiT91bWsbrOJH'
    'QrxOp5hTSzRJI4tNzc3Nzc5QNPtmh0FZMFeQqpn5qj+WyoPVmi+qUweoYTwp6dfMrArSHHWe3M7NinhZsiVzj44nQQkBfPHwZozf'
    '0UGoORNbOpr8G5vpznKcpv6T/wDiAbgGp8zX06mvr1oiATzPsVCSR186KnfBpx4nd1bPX2lhq/xcH3QO29791Ows7VYn+MTuVxL0'
    'S3+Th9SvMOdlGG+5pylNfesIKmbn63Nwk8dzc30J+siahXU1qNxM4bUuW6eSftpnlpwM+7SoOvBgvw3gdNeP19Iac4Hgt0tNy9jk'
    'Yp87E8Q6nibnNxO9YJ7hoMme4SC2qD2zRcfGsjYSLPbuD2bFVlsAcDn42Bs+JvogaxeDTjPGuJ6a+oHU303NzcBm5uE/6+vzA9BN'
    'CFIRAJxmofwAQ6C1vUs1DAQJ8hKb3ZPTfUGi+iZrRf8Ax9zE9BqVbcH0rHLZHptcbNrhy0hyoch53rJzc/Vubm+lLcbLG3Z+5yIn'
    '7h2JWj2nqDqA66Dq5SwBYa+1UEe0FZqfA1534HGa2PPHv2e2LCD7j9pABJsV601yJXR4OSylGoRrL8hG7sFbliOS+OhC8Om+oM2f'
    'yCxxBkXCDKsgyzFykYs+MDrCaDGoefxwn8XZKcDJovzaP83YyFgSeANbmvyD6D/qag6Ef6PzCsA10Pga6fvU1Fi0XPB6fmGJiZvf'
    'T0y3un0rm/8AGYST2/oqQXeh1Sv1PFdj639zeuZEb1n1CN6nntGvvf8AB41+E/hK+YPJ8AzU1NCdtRSgUPc1Xf7nK9n+7Ufk54xj'
    'zbUC+QsCzhuFNQrx6ctFtk+RNnkLLUnbR7SxEb5rfgarrFtY/d+05abXQeeo8zjACSefIjlOPT9fhEBlt72UgTjF8Rci5YM7Jn8h'
    'fE9auUfzqkfyvp7z3PoryweklzRgme0rMOFPaOB2nE7bzg84n/e301NfWOmpqaiiGBdxarIMTJaL6XmtF9DzCf4HIZv4FRP4jAWe'
    '09DrnP0GufyHpST+bx0jev2R/WMp4fUcwxsvJaF2PTc3NylihZ9szlpubm/wDWoOv/WBYTrrx1D8zZAHUfPTz0EDtEYoV47E4+DX'
    'wVfLGjUbU15K+PMTUB2PAXkYWBJG58TXkDxwhGiQhqDFT8mbm5uck4m0TxvjT22Gn/61I1tuwJ4MKmLSDjXIndhOxtp4hP2jW2cM'
    'COEHk8fBGoy8em5zMBm5uAzc30P1bM7jzuPO487zTvGd6d0Tmk5VT/FNVTjXCizgJwnGcZxnGampqamjNTU1NTXTU4mBTNGaMA6a'
    'M4zgZxnbnanZE7Szt1zVQn+CKcaG6jfuqxPe6hzrIfUcqfymZH9Qy2j32W1E7nj/AFFVmgIBZy9nE8eJ1CpAmjpdag1HCh1WN46/'
    'oa2fn9lfug2Z+jrrsz56DpuVlgS+4NmJuAnTJAhjampWIBEFr0Njss7cakiFfuAm4JYupqEagPFns5XADlx+60VBYgr0KtVzkulA'
    'LeVYQfYwKlrKfFStawptLcSAQST2uCkqpCCqVf4+nyLOAfj9n0CaME/XTXQ7H+tszZmzNmbm5szc3Nzc5HW5szZnIzkZszkZszkZ'
    'yabM8zXjzBAIRG6Drubm5ubnIgf6KKzNHQ1vjUm6VAJZF+0/J5aHyeg3qOxuYCLWTGPAb20100QAAR46gkHoIe3wirteMCQjUEEA'
    'izc5QHc2I1ez2/KrFqOwO3TY/wBrXCdya5R04qAdoss4tFKcGM3uWO1lmvEPXkeOj0Re471NXb44nUVipV6rK7cYy+1LHsnk9CpS'
    'bO/2CGsQ1KwvdAenLi48dB4m+m9ll1NkL8xbGSa8zX/4Gug6H8C9OPnXQw9R9Wofo1sspVlRmP0bInjU+Op1056SBmHTzP10+Ovm'
    'D5bkJRjs6OalXy7eJXw0pVTyHDRM1P1Cdkeemvtby3RATHCbJ8a6a6IplicDz4nluVOJ2oaItYn2rHt2tm2VqzAGEDzuRSI7icp+'
    'iNnU0SYi8iTucTKkqaDWtkjIx7MZps7rTmYFBdG4TFyDxuPOnkSN20gtud49wfd0+YNjoGIh4MOOx4CCa30E34/U86lnNj8wzXXX'
    '1666/wBEfkHTcBm+nHc7c4TQmpqah6sfo/tDrfiE9OJg+1p5g8hq+A1uHqAWbifwEea+IbUGjKnSq5P/AGW5PFGYmfPQXH2/Ese2'
    'UblxPHkrqIRE0r/vh4gZgdREBhHFdmKIZrzaWtcAAiWbMI8iAidyB9zce2cuXWzWyDvj5I4g+Zw8KzVPdZ3bZv7YjcDuH7gRrqOO'
    'umvH66AlWDBhYsZy3TkFmoPkgBps9QSCHPcE5r29rPknCtGGSSft6HXQN9wJM4ghwmzvXTX0Dprp+vzahEHzrofxjoIB4HTU4TWo'
    'Yev6PQnZ5EL07NzVTzN+NzmS32A4K4VWE9oe/wDq/MizmeR2ZxKjk24rso6LoH9a8fQq9HbkYjmss7WW+Nr4nLlO1CCvQbhgisAm'
    'prrXUbY9RRgpEIMQfcV+3jBDG1skTlNxNgM8M34r8s1QUWET7dMYPJWvzYwUMeRZNSqsMx+YBHA5RyCqozDiZx8b4ufubU8yxaqq'
    '9QoViKwrliTkdE76cWn71BPnoDqAeD8jqLn4fvqAPo1pgeM0uiPo4wCa6Hofr19YhghM3+ATU10XpuDos1NRvE+ZqNFAJ7zq/wCz'
    '8wjc1qWFWs5swVU4c2HT9ytAI7FyV2JrU1BrRPU9PjrrzB9rfEUdCYlZaFVCdErTt/IqVeOvFy7PHz9ykIDOEWudvya5qAAiqkFL'
    'q/JcAOzmUL/larc4a6FSWath9HNoWnKbinQZmI0dsPHb2RVqcu3GJMWtmgVOJ8TUCLw15BIITlAoMVWC8dxkKQKWhUCfMCb6a8+D'
    'CdxG6MmoAWbyISTAOTTRikBoq7OoE3PGvx7nEmEAA9OJgWanGfE+eh+sdeM1AIR0EP4tdBCJrpqAeR0UQCNqOYTCYfMP0htIT1JJ'
    '6eOirPJgGj+uPgrqEaJM+YE2dANqfJ/UC+f39ujFXfRjOPjfgKWLYNqYmpqKpiuBK63tLJxhQEtWROErVeQWGxTjlC07URADUNx6'
    'zO15TF5RKFUWHUZdztHTsYxI+nXjUQDZI0k7QM7Pn2xEAAF6+eIgf7jsnj40QXTR1NV8dQCIlTUcOI0xKJV3WCMaKe7GJKKFRf8A'
    'sV8BfP8A0JRX1HQrAvI6h3vQM/WoF8QISicAeM+Bw3GABnz0AMFfhlCjoi7OgIybnb8FYJwJGiJuGb+vU10E/XQfRv8ACIFmunzO'
    '341NTj54xVgm58wpuMkKTU1OB1qa6a2dan71NTWpqKkMUCaGwi8eDAGA9txSWhA4MBOP2/arJX3H1PO/iBdw60q7moYa3E+5a1Qu'
    'aGrrW2660cIn2nySmO5G+I0GBrIJr8shgQdtV4suMQDWunVTGEr5bT7oKVC/1h3AvONXWsvZgWMaamoqhiy8SNwKYFmtlahFqAVa'
    '9G0qEc7jL41AIvlrAIYeIqZPIqBNdBdrKeLen1f5b60tsOK6p2iperdbZKXYyIGutRw32LW1Z7b82DVdu06n3KCPDqVPbU1aAgVT'
    'XxHH46duKrEipwRQpDARuRjDiyjkwHgLuLGUiEGcfHGLNEFRuWJOJMWmaAjiFTCPB66nGcYOnGEdAJxnGH4/IIDN9EWMPASagWcJ'
    'rrucvEOoROIir00pXjCNH/sxBOtlfB3Erh8wIYmONMNRrBBwhqJVuPYRACayAa+AdJYlazj57Y7YUmPXWI3lVTlAI32wfN7c3VCz'
    'ldFViU84mIzK1OmroMA4I/lv0LfFfk9vYRCYUGtniVnbnaO0ogrAB1NgSzynF9lW26NplnGCudsbCR1iiKIOM4AkJ5WvYFICWpyh'
    'XRM7e52RO0Iw1AqmcEgSvgMStonpu43pVt5X0W9YfSrXe307KaP6VdyPpmXys9JyGdPS86st6Xka/jdB8epQUQTjub/xDwQw0SDO'
    'M49OOyF1Z2yT2GVEGipJjf2s5mHZnbnAwJNfd4M48oyTtNs1EQIZw3ErbfCGudtoymcdBoV1NTU0YIJx3NTjDP2F6bhP5NdRDFEW'
    'fMAnGBYY3TfQGHU+3jGbbMxaKs1DvT/e4Qce222UkGtkiVgwiIjiCuzkVaWiy1jQYtDbdWd15VnjHA12+cNcWsb7QB7Gh2Nwqu+I'
    '104bK0Ax6ApSsApQhi41Mqoqjk8BQu+0iq6bnZE4V67VM7dcRVM4LOKziJxnGBZxhh3CI/Ro5jCcPOhPtgx9rZVoKm27ACN4aveq'
    '13Kkl/JZsato5Q1kEKTFSDFYy3FIlWLyYYG1q9O5xsajHnvwks9UySf5G7X8haY2dbs5thhyLNHIsMa26Gw779qn3mSJ7zKnvsrT'
    '3O88TQgWcJxE+3rudxnnxFbUX7navkvZPI1HQTcCee1EqldQWXkMTuKpadqcdRJsQmExoRuMpnGFemvEAmpx8mGCE/RqH8OpqGBZ'
    'qcZqbiwHqd7+ncWMenmcjOc5idyc+mix7RM7WotESkA+FWwbZhBWTOXGF5uF4W2Us4zuzn93dM7xgtM47IrnCFIBE5bZCZXTucCI'
    'AxKLpHU7VTvRlj6nJodtPMG4NiDZgUzh4VJxgSahSPC5EY7BU61GHladg0FIK+RFBnAaurBlNKg3qYtBJWr7MekmcOC2DnO3pu1t'
    'Gx/uXF+0YcpxtR8Wsz/i0y7PQRsu1pbY5jMY0O4d9VBlNRZ8t0d2hUzgOPEzjOPTc8zU47nCETUCbnDiNRazK69ELBTHp2OxqJQS'
    'Rj+BSFjmFDvseVp1OIj/AD8Tc30MO4ROMInGcZxmuh6a+oQiampqampqcZxirCIEgXxqAQwCAQDqehP0DpqFZxnGcZqBItc7cSqJ'
    'X47O4tXjj5tMb4M+A3QzU1OM4wLucJxipsiqducJwnagq1Fr3EScIlMWqdrZYKodjooTOMCmcJxnGKs4mJFSducIVlh1DsxlE5AT'
    'YjJ5FHKInEdrkvt9MEnaM9uWIxyD2ORGH5TG8V0hZYnjt+Wo3BXOyIKVg4iNaYdmMm41E7Aj0bhx42OdnHOjjmdkwUNEx2B0OxZS'
    'TDQZ2IapwM4ThOM1NTU4zhDVudgxaDDQxi4xi47QY7RKGnaaClp7fcFJE4NGrczsPsY7TsNGqeGqyGmyGiydm2dm2dq2dmydi2di'
    '2Gi2e2untrp7a+e2yJ7bIntcmHEyZ7TKntMmeyyp7HLnssuexy57DLnsMuexy57HKnscqexyp7DKnscqDAyp7DKnscqexyp7HKgw'
    'cmezyZ7LKns8meyyjBg5UGFkz2eRPaZE9pkz2eVPZZU9hlT2GVPYZU/j8ufx+XPYZc9jlT+Pyp/H5U/j8qfx2XP4zLg9OyJ7DIE9'
    'jdFw7oMa0T29sNNumpvhovjY2QZ7S+HEvntLp7S6HEugxrZ7eye2ee3aJjNs4x17Z4lDA9owVGe3M9tBjT28XH1BTOzFr1NRoyTs'
    'zszsRaNTtTsCe3EFAE7UFURIKtw1ESwRq4ao1RhxzDQwnaMWrUWvyE8FJwn8l6ZP5P02fynps/lfTp/L+nwesYMHrGHG9XxIfVsS'
    'H1fFE/mcWfzePD63jz+cx5/N48PrVE/mq4fWUn8wk/lxP5YT+Vn8tP5Tc/khP5IT+Vn8s0/lbJ/JWQ+o3T+QyZ73MnvMye7zocrO'
    'nuM+d/Phyc6e5zZ7vLnvMkT3uRPf5EPqGRDn5E/kMifyGTPe5c93nT3GfO9nzuZ03mGf8maumnmpxngQugnfrnuFnuTPcvPcWT3D'
    'z3Fk79s71k71k7jzm825nmCcp3CJ3WncM5mdyG2G1jOUBm5sznO5Eu4nueO5O5O7O9O7O7OQM4rOM4WzeQJ3bhFyLJ7qyDMsnvrJ'
    '/IWz+Run8lbP5KyfyU/kUgzUM9yDO7O8s7yw2bhZpu6csqdz1Cd/1GHK9QnvcwT+RyJ/KWz+Vsg9Ucz+TaD1EweoQZ6me7Uz3G53'
    'XhstnduneyZ3sqd7Lnfy57rLhzcoT+QyJ/J3T+Usn8nZP5N5/KtP5Rp/JEz3897Peie9E96J7ue7E92J7xZ7tIMxIMxIM8T34hy6'
    'TPc487+NO9izu4s54ZnLDnLDnPEE7uJO7hzniTupO6s7jQPfOWVN5UHuZ/yJ/nn/ACJqyaecTOE4CdpZ2VM9us9sk9rVPa0z22PO'
    'xiCdvBE//mzl6ZO56ZO96dPdYInv8SH1GqHPhzXhzLZ7q2HKvndyWnHJae1yTPZXz2Tz2Jns0ntap7ame3qnZrnbWaAniaE4rNVz'
    'lSIbqRDkJDfO7Oc+2f45/jn+ObrnKucq5ySckg4zjTAmNAMUTnjidyid2nXerndqnOicqJyx5zojWUTnVOdUBon+Cf4JvHm6J/x5'
    '/givSJypnKif8ff/ABZvGnOiB6J3sed2iC2ic8WcsSccBoaPT57fEhrxhD7Of8Sbw5zxJzxJyxJvDnPDnexRPdVCe+SLnUQZuJBl'
    'Y5HeSd5J31nfWd9J30hsrm6zOOOYaMYw4uNDi1Q4cOI2/b2idu4Td6z3GQJ7zKnvsqD1HJg9Tug9Vafypn8osHqdcHqdM/k6J76g'
    'z3NBnPHacaDOxjw42LPaYc9phz2eHPZ4s9njz2dc9kIMNxPb2idu6cL5/wAmf8mcsmbyTP8Akwi6f5Z/kn3zuOJ3GhtneSd1537B'
    'PcNPcz3AnuRPdT3Tz3Lz3Vk91bO/dO/dO9fO5dOVs/yzjZBW87bztGCkwY5gxSYMSLieRiz2hM9hZP422D0xoPTUgwMee0xp2KRO'
    'CzxC5nMzmZyMOzNdeSw3UiNlUiHMSHLMN9hnNj11NTU108TQmhNTUFbGLjmClJ2p2p2p2Z2p2Z2lnbWcEnGucUmlhCiHRmlmlnFZ'
    'pZpZoTU1NTRmjE8QCuf4ZqqcUgRZxnAmCmdidgzsTszsTsT289ssbDQw4IjYdohqdZsCbE5CchNicpynIzfjc7ziDLuEGfbB6hoD'
    '1Cme8xyRkUsOVcLLOSzlXOVc3XN1wvTO5XO5XvlUYyUmdimHEQz2bQ4d+jj5WyjCfbNiaWcVn2a+3oHcTu2T3N4nu8me9vnvLp7y'
    '6e7ee5ee6t37u+e8vnvb5/IWiD1Fp/Iz+Rn8is/kK57+mDMqae5rnuJ33137Jv6dGeZxM4mcDFocwYzmeyu37C2ewfa+m2mL6PkG'
    'D0a2fxBn8SIPTaxPY0iezoi4mPFxceDGx528cQ9mE48540a3F3vEnPE33MSB8LXcxNdzEhsw4bMPibsONl4Kxs/BE/kMXk2XQQbc'
    'Ynnh7PshN4k/4Ot4U5YU7mHO5hTuY0N2NDdjz3FE9xTPcVT3FU9zXBduK6QWVrPcJr3KwZIEGUJ71djMn8hP5Fp/IWGNn2w5lxnu'
    '7p7m+HIvjZdohybTO687jTutO607pndM7pndM7hndaC0zmZzMFjiKWI+/XJxO/Ys95fPeXw5t895fsZuTv3+SIPUcmfyN8HqVsX1'
    'J4PUzP5LU/kjP5Iw+px87mGsUxrDDlT3yT3lZgy64cmqDKqnusee6xIcnD4jIw4b8Od7C33sDYyPToMnCgzcTXvsSLlenT3GC7d3'
    'Gguo1zw4HwSgbDM54CwW4AgfBI54AT/hcuWGIGxGYHHn/EedrAYHB9PYN6dgtD6VQQfTK9t6aFPtRPZmDAuMHp2Xr+NzJ/G5u09H'
    'y3B9Gy4fScxQ2Heh7JE4jZVd6Wa8+J4m53IbNznOc5TlORnFtcWnmfdPunIiKtryvCzmHtMpYKtTlipDkYAH8hjCD1gLP57KE/nc'
    '2N6tk2H+QtM97ZPc3TuXmByYCAFvi5RBGXuHIMbJMNx4vaDDb57zGd6Gzc7p1yM7yw5Kz3BhctPE8T7Z4n2zx01NTU0fq3PJnaeC'
    'kQIJqM2oCTFqyGIxc3Xs8vXtLt+1UA0UgdnD0i4Cz/8AniFsHfLEncxZ38fi2TjzuUznXO4J3iJ3bJ3ngvtneunevgyMgAZV891k'
    'A+4vE91eIMy6LmuInqViT+Tcw+oFoc8FffJPfV791j67+KYL8EwWenwfx+1HpuhV6eR7fBKnDxp7BDG9OM/jsiH07Ohw8xQy2rCz'
    'AgkjthocWGmxTog9fG/OvOvM+4nXnjAimcdThNeeR2uTasXLJgtqi21ND9kZWIHMKOehaywM5gs5lnaNdX299sCwdwu7NY/2dxjO'
    '6/PuckIp4PVigdlJ225auE79wgzLovqeUsHr2as/n8ufy4ee+wXnd9KacPTXgwKbJ/EZJD+mZiRq7FJ8Qzf0e2fRrx1m8JQMnBWe'
    '/rB/ksoE+oZxDXWGcpymzv7p56amp42rCCyd6LYdCwxLW2LTrnqLlaU5e4bQD3dzueWtUlrxr3ZE9zZDa5m1nibnieJ4m4WO9zlO'
    'U5ic5znOchNicugVoK4K0EEx8TIy43pNdVbP6ZXDm0bGfaJ7/KjZeQx7jGcoHncnMzlqdyc5yE5eDZqGwmbm5ynKc53Z3J3PHcM7'
    'k5mcjObTm05TxNzcB6bM89NzlNwMuuYB7wne0e+Z3mhuIPunnuGhyrJ77JWD1TMWfymVy/kFaV5fprBPTsPKrycCzFQusK0sTQNE'
    '6HcM5Tkd9ycpvzNicp+9icvC2mC067njn5FriDKs37xhPe7RMixUGRdyfIucc34i60QH/IvJl5kw2sw7hMNjg9+zS3tz7kLEnuED'
    'unXc5jY2VTXbWFPPFp902ZucoLGETNya4vrPqKwes5E/lMVocn0iyBPR3H8fgWQ+jsx4wCeYVIJUgQbnnemM4zj0+JucoTP3N6g2'
    'B92iYW3OWgG5TzsnUNi8jcYWczfX7ta8Tf0bm/HXU/ZYTxqfsI0FQg4rOc5idxYWEqyrqGT1vJWHNwbz2fS2ns8fRwLeP8fmk+0y'
    'xDXbs76bm556b8cvHmb6b6bm5uD53567m9zfTc308iBjOXjZmmM4sJxM89BvY67m9wbgrdouLkOR6ZmmD0rKg9MVR7X0xYt3pdMb'
    '1q7jfnZGRNhj+vMUAk8Qe2pZqzN6gnkTkdbnnpxM0Z4nnfTx08a2OncYBbfIt5nlqcm2bNzmnFSyWdzwbl5hxA85POULnW/JdjBr'
    'juA+Oe4GAgYaLhT/AIWhx6+D4ygtigQ0sFND8fa2hUxm5HEK1+2shxrUAmxv9chrku2sUzuKJ46ffCDNHWoQNfbCyzuLO7O6057m'
    '4HCzvQ3vy7jmbM86/XKb6bOpubn7g6/qbh6H53PiBSwFfkoyDi++FpfsXT22W1Yw8jYwMsn2OSJ7C8sMG4z2LK3tBDi1k+zxwy0Y'
    '6hWqWe6rUfyNYn8mk/kTPf0aGbjh1yqI2Rh7F+HO/hxr8Rh7jHZGvxjDfiFhkYyg5GMJ3sWe5xiBkYsGRiAHIxjO9jcRbj791RW9'
    'eTjpPdYxAyMcKMjGSDLoDe8xlhzsYwZ2MAM/FgzMYEeo4yL77BjZuCQczAaDL9P37vDEGZgT+Qw1h9WxAy+rULG9YoatvV6dPm0W'
    'TvYjkUYDIcbEgxcRp7Sgn2C8faEE4Tg/x9rRvTbq5/H5BH8dliD03Ni+m5m39KzAh9JzNHBzVseu5GZLkjY1yY4rtM88i3gEsxPT'
    '4gO54nxATrpuctTl52Zy8cxNgz5B+d8WP9eDRq2RCeVehLl4mfcbfPEfBMUciytzWtzO0Vg2x8bJQzmpoUr2nPKaZU7/ACU2dxg1'
    'MDVzdGuVU51wlIGTfdGu79veM7rQWvOTT7pqcZxnHxqa8zixmjODQKTBi3Fxg5RIwcmHDyVHsbYMNmPtVnt1hx6lrGIrT2lCEU4g'
    'rarE5cMIDhiAN/HbBwEPPBE7uKC2ZQyrl1LEydgWCHNdYPUclI/qOSSc/KMOZl791fFusBNjcWZyPJ6a+0z5abjEzeoNtNHWhrid'
    'gDZ1Oc3Dqbm5ubE3qHx187Bm+m9ANo7g89eXTc5dFIAnMiDUJ5ENobE5QeQTxUfcB4H62Zz8Dei05RtA70yskAGv+q/15coVbtj+'
    '33pBkXkjMvlWTlbN9hssycrjzy+37nP7vv8AL0M/M17vIeJ6hcrrmXIGzOQGUVJyF7a5Kz3GNpmxSP8AhmxvYdwrhGt0wGBow+HY'
    'xCBRQVenH32Ke4KgpVBGuV5TVXagwjzsxAKT6f2kbBr2uHQ9jY1PMUYhhr9M7Yr9PWt09PSLVgmOmE5swsaNUjwY6FBQxjUk1GnU'
    'ZCrLy51nRHENzorbUM3119AGzr6POv0ATOLQUklafLV08U7aQsqT3Tme7tC+6ydm60tyIB3y3peXTW4Z+/3vod9DuGedwbMSpSRv'
    'fI9dictwlt74t5gTc3PJn686IOv+wHTwB5J3NiAGaIhOoW2NTWxNwwzYhMBm+h1PBmpvruD58TYm4Z8zc39sVwBW33clE8kbm/AU'
    'EfB5kwHk22DzyANbgQsNjYJ1s7+yb4t4m/CoxikmtX+//NOQKf2nJeIdVHdBPJTOXh1AsNeoftHicwByOtmbgM5FTPOmV1ihZ52S'
    'YreBDqa6j5XxFudYttuxf9pKsO41lq8y4U7bkp8qvkgKxs7LQjaq3hvMTy327HCcNKU+zY0wCBK9pufM/c4kwEqeu/DKQQCTw2VT'
    'zwVYCOPLU8tAdT7Jo71xP7OoB9ngQ64lh08Tc5am9HfX9cp5Vh8+eXloBuKmpscz/XwYP7fEPkofH9EOjNzRZ3WBRyHKf1nLyGXX'
    'LwfKb1HP2h12Fit4P9WbcLbI0SQYN67jdubnzNzU153PInySPPX9s2zyOxx6bhh8Q/Jb7d9FbwrT7QW/r/2PKfdowBSWJJG+eiF0'
    'RPM3pnUpau+X9pxh2x46jNA5WLYVfl55/a+9nRJJBmzskxT/AJF+1tkz7eH2s3a+1vth+dnpvwDNkzfjrvz8jc5ef38QH7dzxP2P'
    'Kv4j/ZaXOu59vd2tLIRqsTW6d8J7zTAjZKiwO+wbGmwYC/JQTFqtWdomcGrJ6aM8686864knh9ukJ+wR35nlAV3ppx8+IRxg1tm4'
    'rz4zYILQtOY5c5sze4OOvsn6OgNbnGAbPiL8fM+D+t+dmIPv46SeYwbWmhB0STG2o5EnyzAgt40WWcyV3CSk+QG3PG9njynyZucY'
    'BoMZs9fOgfBgmvM4+P1DD8fE34/W5rXT96EM14/Wug2Yeh8QA7Hx4Ck7gM8T7gIdiNE4s3npsA8dEbmtTjowDcYaAhUiBRAA51CA'
    'YRApEA5T9eSCBy+IAsK6BrbgUIlnDapUzcDphoz9cpub8bnjfkT4m4ddPumjPM8wfHHxyM0297HbPEKvL+sGyRa21g1PtLhwBZd3'
    'aiCossfJsD3CruOTyYzdk9zesJgXZA0fHLYNjsCNnXxARPmfrR2NxfEJJncMb5WHyNGIDt9TyV1PG/E4mf8AXl4+5hvUOtcjP18T'
    'yS7BjyHI7IA2W1y5aTnqgHwzTbdvn9rCfM+IW5EbB5ePMZw0+B53vyDqEweBP3rb9PBjb67Ot9TB56HzP+3TXkf2/c1PAHHxN7M+'
    'ST02dfoGeZ8Tc2Z8RGMcgztK7nZDaEBMJDVjjxGjARxQitxA/gb5fbvlC3+RtKwdkhKu4QJb9mgwVAVlgL16ALB2MG4/EzjqeeP7'
    '7dhSzaw/11xfwDzE7fM007c1MGK6I8GMeTHUOidaPz12Y0J5TkYG87m4HMDGcjN6m9jYavxP8fI+IHOy33c9Ec9r87aF1C7ELCct'
    'wz4M5bh/t0FZczwVIE2NrYVtZVd2+0r5HH7f6jkOXcKtsxfM49AA0CsSzTxtNb/W/P78A78786n/AG0SfHA6EJPb/wDr57m9Ls6+'
    'Z4gg49otsqJ8TxBubHT5M1BPHQDwNT96BjHU/Z6fA14h6am/PxPO/mfv9am9dNQCeYYf7edDiZqfvYMb41rprzoa/X/f4mxyZiW+'
    'IQeX2gHQBUGa3PHHX3+RAdtoqjf0YmLZ45Fho8gfC+Yy8DX5sU1c1HCxfvgZgykGEAwWJD/6kXuPsoxP+Ltln03JfCKK2YMXbfN2'
    'sbshi1Y4vK6hyWsmb8zc+YfB3qD7py0JqCb+34OxvQB0YBPGvHH9fdNTR1qE9A3jm2hZCV4+YogXyG8sdkTiuln9oBB861OPhj9p'
    'M/YOi39tic5szQ6AedaG4dCeN8pqcBx3o6HUHRbxGXjKhwf4bzy8zcUjZPIhtKW8b8ctqBNbnLwDNzwZx27cdkbgXz9s/wCvPQ0Y'
    'uuI8weZx5Fl4vNzcBn7MHQT4hMVeRP8AbXnxC0ME+YnlwdTc2RCS08iAATWzs72dj4+BP38CHxNwfIP3CDi4uXk5IR4SzRTOTcCD'
    'vya/Gv1rc2wTamc27m9lgRPmaUo2jN8j8sG0eUFmm/YKJPu1y2VtJLpBz1zPEu03Az9vkNfbwBUBnXnz4qtnBygY9s9vUBinTHjN'
    'zwYeI6+NEweegJUbmhBrXHp5m5ub308dD8b3B8fE7h140uuP/b4n73AGM/q3FmB6b108/RuCb8bM5dOU/c+Z5ghH3Fp8Qbi8uW/8'
    'nyGZSnIw7acft870eK/2+Iq+WXRDlWJnifsDSze5x8EDtryaa8fDE/doFdbYhtWaBL6D2Fh04/b8TQ35JmvO9FfubiCwH3+SB/b4'
    'm/H73uACfE/c3NiKY55E7HQnz4m/tLef3rpra6E5QmLsje4u+j61vyxHDXgNpOQ7ZPj5KFRWrt3QoMC+D/XTFS/n4ldn+fQ5NWYq'
    'M0+3lB9x1sLsQr5J0wt4HmSdkMePArSbGQxK+bgMlgVgti1pYf8AKwUzXFuZEP2rxjq1b/8ATxs6JO5+wTCBoL92oevzNzn9myIW'
    '5TW5/wBeIgWfJ3DszzOU3tp+jFP3N/fW4UUDlqbm4TP3NzmQfmAeD8QaBH9iPDpxPX9Q9f2U/wAX9UXwT87OteCxJRir7IXwYpZQ'
    'STOUPyBzOvt1P+2g0I3OI5GD55ET9KsMOyw8wcQNz5j+Z5mp+/0DPM5aHzOM1uL/AFEB10CmHU1OEAnmfBBnHkdeYJ5gXcO54mtz'
    'wB/Z+RJAJJ1o2MUPma0fAmzrzF/9X9EOncHnWR9oH3/M0QGinlAml48TyHb+WrbTMGE4vw7jCfB/Rc8Qx0eGv6whhORB2WnNQu1a'
    'PWVsICIs8zlF1WDxi+W8sEUkgaikw+J93H4IltX+Tesfi2vMWGA+SfOtt+9TzP18wwDyfJ4kHxvWj8Hfjnub8qdxSVHzN9CPCzmD'
    'C25uDyehghE/U1P3ucuuzNzc+3r8jrr7QNnkYx3ANwgA6WDbOdB0LAtx4n41th4hM/Sj7SdxlWfayM6lvLFTpAm4ddvW5/8AVyPL'
    '9N9p3ybQK2a1yIeAbnkwz/rsnoDub87In70RPiaE34B6nzCmjz+0Hx5DfoEz9+OPlYu5uEbFbEHzOB3o1t5M/Whx0NwjU39v2iL9'
    '13Px4A+I4hOjoF/JCgGsKdEH2+MVhRqwutWcOz3GU8tWarCdvZ4mEP3KmqgJUgpxZmZvknXY4/Z++ZVq3XkoUt9osPhl0eilAwUk'
    'b2GZzWLHUIz95eSxuCR/Edj3VfjOX32BJ2/8dNfcsmjqeZ/13ARyU+R4nLcZSxOjGB1o6bRB2Tw1OH2kcZy0SdQ+TN/R+/3D89Pl'
    'fmfrzN7E3PJ6KpYz5IhOyeqj79bbiWEHJZ/10UH3FmGlUnbABuXnpubBXVfa6JqbLH+qIOTbO9yt+AbcHFW5HaozKJZ/7j889IZ8'
    '9Pg70d7JmxogGvoN7ELeN7hI4g6h6H43GfZOt7m9gkwvvp8Gz50YD5b5n/R4W5Wb05O286B6bMB6a7bbHN/tg2aGP3Ehl/7P86cw'
    'HlCK9uhSCzUYiyFdWHazSIzRWaeXhs7zJWzhm25UKxHFm5hhx9ui7A49tl+0icWCcWWLx7L1sqeAzNo1/wBk8AONKimMSUcDtVFe'
    '66WLf/XGFfcsrpPcWpnGrKQGjJyiqfbtqKGc/wBTvp5WDyFIVe5o/smBk13PLFSANjcPxLF00A+j46H5/eofgQ/UNF/iCHoCV6qs'
    'QcbB5PyX2JUy9xlCmz+0J2amKTc8hf1Vo2cjvwAYeigb+WnLwAXJHnfj+0G5y8V6MHlj/wCo/wBlHKMV7m/EB86n/b6PmfE/f7M+'
    'TqeNMvHprxOPTfgT/qfgHifmfpiTFdk6edfZ2v7TZ46+2c4ByOtnkRB1Jn6DefOt8kAZXb/2f0C2Nuw/dr/Dva+df9Qx4MwaMukZ'
    '+NtaoaDtIi+Q+lTjZGVuV/xtVrZ0ccfH6VypBXhsFhtxy+wt/iJ3Hbk6kzfkdo18wkqYFk+8KyadgCLiliIrY6My2Wf+xNuq8ebJ'
    '2yqlk0HHA1q6nkPll4MXnjfnXyOR4jzA33t/acpuVDatx6MQIOMM/UPwZ+2/u0/6z9w/H66n5h+n/wCq34/QjwdL/wD3SoAwdLP/'
    'AI+R/wCzH/tP3+4If6/pOlf9m6Vf+xPj9j+tf/ss/rP/AK+rf3/+vofpPyOi/wBj8T//AJl+P0Iv9Ogg6N8p/ez/ANv/AH/U/wCn'
    '66H46LP2flOtn9h8Rf6tP1f/APIX4Myf/f8A/QkSWf8AsH9D81/2Pxj/APp/+8/0/wC8v+X/APQP6XAaWftv7n+g/tP+3/Y/1X+y'
    'fCQ/MT+yf+5v7/8A0tK//Ufm/wD9w/8AjiP84v8A70/92R/cf+v93fHRPmv/ANnRo/8AbrV8DqJ//8QAOhEAAgECBAQDBAoCAgMB'
    'AQAAAAECAxEEEiExEBNBUSAiMhRhcfAFIzBCUoGRobHRM+FiwRVAQ/Ek/9oACAEDAQE/AfsmnYnTcX5yDtqiMsyv459F9g3YUXLc'
    'tbhKN9UJ/YXLly5cvwlOMfUznp+hXPrpe79zk39buKKjtxnKVWV4aJfu/wCj0zzdJfLIvwyvOXLj/wDiIxUVlXG9jfhKNyE76Pfw'
    '0l5FwjBy24qJYydyxsZmaWLFi32DdjViVh7DipKzJQcGQllE7+Ler8F45VNcsdWQp21lv4ZRvqi/juXM48TFdSWKUegq2JqeiFvj'
    '/RHD1Zf5Kn6aEKFOGy8VRub5cfz/AKHFJWJRv5F+Xx/2Up3QmXLk6mRFCly467vfjft4ZwvqtyE8y4WEinTekRwa3NeCQkODWhyp'
    'L1HJfRHJl2I0H1Q6bjuZGcu4lKPBysZzMXG0jViilxlsIavoyUMnwISt4qTvOcvy/Twt21Yqkq/+LSPf+v7KdONNWj45RvxbLjZc'
    'qYiEPUx1pz/xwf56HLm/UQozWzt8Pm5CkoiXjqzfojuRioqyGVo6aDdp51tL+epFjY5W1MLDmPny/L+/z/jg2kavxzg754b/AMkG'
    'pK6FEaFEcGtGZTI0ct2uJEE7lOlr5yNKC+6VGlpTSuTqVeqsedkKbtqKnl3IKz0RmTG7sjLUk11Fnewmoifglt4JRyarYjLw4TWi'
    'pPrr+uvG5WxEKK83+2RoTr+bEbfh/vv/AAL7GUblxsv2HGb9x7On6ncjShD0qxYylvsKk8u25GNuDJocL3pd9V8f9lCpmQyNPnzy'
    'fdW/9f3wz39Il47EIrdksq1ghIykaI6Y0SpTyLsZGKm2QTh8TC08q50ynKp6mcq+stypVcXlUbkcXH70RVqEvvFSrh394jJJXUdP'
    '0LmUk6l/KU31YpobVzLbwVPSLwTi4eaH6EJqSuuOJlloyt83I2irIuXJ4mUpcrDq7/ZfH+ihhVTeeWsu/wA7fYuSW46q6aicn0sS'
    'hc5dth6faIlLKrkY/ee/gZWjpdF7VM62l/PUnJtqEN383IKGHiqa/wBss5evxIymUSFG6KWGlPYp4NRjmewsPJPojkomoy0FTa2R'
    'kc9yNFvYVLoilQ6js42ZGpG7kTrks9T0oqYeu9yngnf6y5lpYdKyHXTflRmvsIlE5ViV4anNu0KWmonxren9P5F4atOUXzKW/bv/'
    'ALKNeNVXiXMS75I93/Gv/RmJ1YwWaT0FzcVt5Yfu/wCl+5TpxpxyQVl4b2PaKfR3+GpzJP0xPrH7jJ3YoRWy4sWnBwTHTfQd1uhS'
    'vsXLly/FGxu8z8LJWLfc/NfH/Zh8TG7lmSb+bIhiMPHaa/U9so/iR7VS7ixNPuc6JzI/KZzI9L/oym003/0yHmdkv2Y1GGljQRhq'
    's+YlFaFfPfLa6MsIavQlWpy0v+zHOgtM37MWVryq/wCRyURw9zkRijNClG8jEYzOslLqU8HJr6x/oU8PTp7InJW3HWhAni9R1IT0'
    'ZWjShqOIolhk/eQpty0Iz6MW/Gt6fzX8+K5iKMr82jpL+fiUMVGsuzW6Ks714+5Mq4pQ0Wr7FLDSnLmYjV9ui/tiLksXRho5I9rv'
    '6IN/t/NjPiJbJL9/6/k5dR+qf6aHs1Pqr/HX+RJLbxvgnfwSpQl0HRf3WNTjuiM0xMT4RPV4GMqTUVdjlUqf40LC6XkWnh3pqijU'
    'jUWaJEtw6ERIhGy1NZLTQhRu9GSgmUqFtRKpfyFevOnvMjWrVXaBGi27TdylTgjPHox12tSX0jBfEljJTe9idaN9FdmDwzj9ZU3/'
    'AIHNIlUb2JSZUqXeg5jruHpJTc3dli3CRN2ZRjbUUV4MT6F8V/K8NxyJVCs6edVdpIxMq0JZrWvbUoVoUvRFyfcWKry2SX7lq0/V'
    'U/TT+xYWm/Xr8dSEIx0irC+zb14beNwjLdDofhZlnHpcVRbM3L+CTtqxyqT0pL8386kcHG+afmZyxw0JU7ksJOEuZQ37dGYBxxCe'
    'bytbplSjBK9zK2JCRGNuhGg2VKVlfcp8iK7MVWgn6kc6L9JXx1vJBl1cVZpWhEzVH1RlxL9KI4TEy9crEvo2q9XK5ycukad2QwuI'
    'TzZDC0OXLmVfUOtHuZ7nMWXTcxE2/ujpyJW2Y3HaI6qj08GW+5KWVWKazIircL8K/p/Nfz4LjZOqkZ51v8e3foJxpv6rzS7v/pCc'
    'uYlV1v8AyTwN9acrHKxFP1Rv8P6IYiF8r0fv0IsTF9ncXCL6fYvsZUWLM8y6F5N2iiNFby1LCXQse4sYempT82xOUJpqCs+/+hV6'
    'mbLW3/Z/PYjCUthU5LRlGDvrsQpxk9hqN/MyVeMp+5FSWbVk67WiJOctyNGTKeCa1k7FHCUUs0tSENNrCaWhn7FS0/LIlXhDREsR'
    'OestipieiHVuSnKGg6hTquOtypi5yOaxVWtR1C5czIZOlfVmflPcnirbFPEN6S41dv0/ni2ORUrfdWrJRSf1ur7L/tjjOr69u3Qj'
    'SSKtHPGxh6nNpqYkTpQqK01c9hiv8Tcf3X7mSvDdZvh/T/sVaOz0+IvsbiZHh7/sUuFixYyaCgx0mtx08oonKt0OWyMuVDLbVmHp'
    'Xl5loSgsjg46Mw9OUIqX3f3/ADFh4vzRHSsrsrVciUae7KsskLbyZzI0/LHVkcNUqayFhIRI4XKrkKVOnq9yVe+kS7RGs2siZmVr'
    'OVyVVRHibaJFWq76nOb0Y6hnHNmYczMQyuXm2J4qlTjlpochq+xdod90Z5PRknO1iopS3IStLzkJwkvKZ+jKtaUdkPE3jdohUU9h'
    'k52JOUtdl87Ci7Whp/P6kKKiKBYylL6qs49Ja/n1+fiLwNJ6M9nj9zQy1Y+/9j2iKdp6fH5sJ38LK08sNCLI8LCdnbwpK12+C11L'
    'cLGUULipnLscq+onpYjBy9IsLNsdBQ1aFSnUd7EsPDLZk0uVuQjBK6OdCHpKuK6jxK9T3M0qs9DD0YUloLLbMRjeeaRz49CpK5Oo'
    '9jnW6ird2e0ZtCOWPq1fZGJksuujLjLmYcjMXHOw6hfhvsOXccuxKrY5qZzFezKkYzFJw2Fi5jxMnoKtJKxh7p3KteMdOpGE56zF'
    'T6iiWLFixXg5RvHdaopTVSCmuv2EqEHtp8DLVjs7/Pz0Odb1qxGpGWzMxe5iOi95TV/BlctEK/XwvXQUSxYSIIpUb+aRTdJ/Ov6D'
    'w6Hh8/uFhoXJ0srtDUp04yXpI04x6Eq9OPlkydemVK6k9EKb+9MeJjH0InVcnfcyveRh8FkjruZKcPVqTrdidRk5Eps1Y0WLntU7'
    'WuSqXHIdZ2yjkOQ5DqDqaXHVuKoR1Iy7Eosk9NStWUVoUMHUxNPm5rdhSnBtT6DrJmdX3IWY6N9iNCzJ2zalKdWcvq9F3/oo4WnS'
    '1W/fqWLFuNixYofV1HS76r/v59/2c6FObu1qcmpH0z/X5/sUpx9cf01/3+xOSqPykY2Fwtwas78LFhxsRhYtwymUp02ylWjFXsV6'
    'nLitNWXbIU01coUpbzK2Ijd5RYqFvrCti4WsiWI7aHMHUkx5/vi5a946jexhIqn5pRbkU3VldzViSi3ZskorclK+w6el5jS6InPo'
    '2cxXJVGy5cbMw2OQ5k6lieJ7DrXPPUkoQ6mIwdTDQ5ma5SqXV5EJK2g9SpElRdfEKlexiadTAUfqJae8wdJV6yhUeh9J4OlQcXT6'
    'kdCn8SnLU5i2RKnrqU4y+8J8XJIv4aytaot4/LE7q68VixYsWLFhQvqcrsWa3EXvwy3IQ6McNNEKL6CVxQZGg2SpqKsKBCEnojkZ'
    'vLEjCNPoOMqnqFhiNNRMViHbLHQ5kKatBFXESNSNLuU8NKXpRHA62vqL6PtqOFvLBalOhTpK71ZKpZ6HtFinKKbyrcna92x16MPe'
    'ypiJMlNvdjY5K5cbJS6cG2OTJSZObROSluScT6OwdOveVQxNP2evam9inCeOpXquy9xy5Ua7pPoUo6ajZNGIofeW6KssRVis8rmC'
    'hhfZ1mtfqNSrVLR1MVVo+z8pxs+xQw9Sp/jQ1KLsynKyF6ritJCl0YpFyc3GWZixKa1IztqJ38GH8t6Xb+PAixYsW45TJfQ5bMth'
    'Qb0R7N+LT5/UcKUOtzmx+6jVig1qQyvdlVq9osTLyeiKUXH4/qLBq2aRHB9U9BYePUdeMfLSIRyeeerKuJd701cniZveI6lSpuWU'
    'USbn6TkyvYhQ101ZRw+X4ku19DmKOkSc6j9JTqRjUzTZKvFK9ideLdzmye2g8RK1r3JSlLYlLqxzNS6LlyUrCGxyJ1CdRs1ekSrS'
    'qQ0min7O8Plitf3uUc9Oqo3sfSFGjCjm6lLFV6EXkehQptvmSd2yCGiUX0MTOEY2kUY3VjE0LaowNf2epmauYzErETWVaIwtKph6'
    'dyUJ16vxMRhZULaiZCpYdVMc5NnMqCzTepKCiQSkrFONtDXglcnHLJT7CV9uNiKKODlU1RUwmVbktOCRFFKlTpRz1epBU6kbxiTc'
    'U7JEq0rWGywlYSfQsxJ7CokYrqQjnaiQp5VaxJsqYzlr1XM2KxOysihhajV3KxPBwa1bORp6iOHh0KrjtEcIvcnUyrymHwkpa1Hv'
    '0JuEFkh0Nd2SrSYqmuo8T2HiXuOvJ9SUjMO6ObJKyEy42ZrDk3qxsvfUciVSxOo3ww+FdbXoQpuhV+Biqcq1O6MHXjh5vOYyqq9X'
    'PHYhQvuV46ZSjFKCIx4WKkdBRa2JQnl+sseiWhKHUhi5SjlkYalFrMYmLnKxiKdCNLy7kFmErDjcUe5lJRRS02IcbFiGmnBcKW4+'
    'VVVpS0K9SEY8uktCSMjLJdSm4x1ZTxS3siti3JWG22cuT1MpDDNLO1oS11aKeH5mhTwcL2vchhlTeZaFSFN6tfszlUl6mQUErwX/'
    'AEWqSW9vn56Cw0bXn5mclXz1vyRWqRgsrOY36kKV+hOcKfqJ1qlbSGxDCt+onhKcVebKmG0TnKyFGKlmUmZ4w/Iq4nVpDq2iZzOO'
    'Rccy5JmYcvOXLlzMSnnduhKokPENvQcmx36kaFF0L9TBtxeQrUo7k8Y4xyoy5jTPaT0KavHyjpty1KUVYS45JTXlQkSjdFaiUXpY'
    'mlF6Ear6FLEKlK7MTWVaV0RtuRlffVGj9IpdGKVjOmRm0yNTuQvN2iiVCpDWSGWFFb3PL0LcLnMYpiknsasyEcPUl0KtGVJXZ8Sp'
    'e+UjOeXIQ+j5byJONPbVirVJvLcXLo+9nNm9tPgU1OWrYpRp7yJY9X0LylJKTK1SUFaLKcXl3uymlTq/Wu8uhUr6+keI7s9pT0Wh'
    'npR2X/Z7UUqs280jnU/Vm83Qq1LPXVnMu7jrdRyvqxybZKcdjMZhyLly5crSy2l86lxscirVfojuzMoIdRzdjLGPrY5PZKwkjCVo'
    '0/USqKc7xJT7jab1IpvQp4aN72LWR1Ke3gzSjsy3CtEy2ZyLvMOOVlynbZnI6xLTg8wvNqyVRrRkqVSNPmPYzEVKS0QsyRRxvLWW'
    'ESdedR3kXFNtW4Yek6mw8NG3qJK3CwkWMLQp71HqKNOMb0yrXnVeWJPzeWTHTuyNPL6dzD4WUNZblaeXywKeCqVtZHLp0Y5YkqkI'
    'vceJ/CiGL6Tv+o8kZX3RzqNs8VqVMVUnuynTzaydkSxsc2+hP6QqT2Oa5PzM8ttGNtEZNlNa+cliIyjlvZE8RFaRJVLjkZjMXLj9'
    'xzLeouXL8LlaOeDj3KdXPBSZKZKojNbUq0Jxipy2E9PLoiU1S9O5KnKpK7OQl6h7ilYlK5y7opoiiQokF4GJcKiIxivUriKtMcRI'
    'g3JGUqUlIVNZ0pGItpSpu5iFlpqGWzKlCUIKUmZrCqCqkK2VeQjqZkijWlDZE8Q5KxYUYtHLsjI2UsO4+aRRoZndinGKyxRVhlXM'
    'PZW9SGD0FKEZWg7vv/Qq1OntuSrP1NpfPv8A6K+MVrLX57Dqt+obXcuX6Cisur1ITnTd4kpa6HxLmYuz4mawpvoKRnMw5DkXLly5'
    'cY4teg5tvXoXLmYlIbykpjw8+XzGZIVKNoR1KcVUo2nLYjTcnoUqKj7xolNrpxgrkY6EYkUNCRHgy99iUWtHxkhxEiUScCxAQ0To'
    'pvQyyg7o5znNOoVJRrVFCBiW3JQ7Co3PZ2kRoztcVKbdkYTCwUrT1JZfTSiQwzk7y2PZoNWiynhrPVDpqXlginhYwWYzKUrR1IxU'
    'Y+YVSkvSVoqpv+7IJper9EVsn3ieJsvLoSrslWb3ZKoORchKna8tGNik1sLUhRlLYqUpQ34X1L8bly5mLjZcuXL+GVK2tN2/j9B4'
    'lw/yr8+n+jmrdMzJlV2MLKVWk6JRqQSlCsyliZU04oScinTEpDKrLFilEUS3B8EIa7EMNWp1XNPR9C7ejLcGNCLEojgKJFpG5lHR'
    '6snRu/KciSKdJp5iEZdrEItsp4ZydihgnmzPSwqSXpRKk2Rw1neJkVPzMliqSHjbLywHHF4pXl5YkaUaKtn/AE+WVKtNbL9dSWKF'
    'WlJ2Pa3FWRKq92OoOY2XObZWii/ghvqc+lltd2/QxFXOy/2TepcuXLly45DkTqJFTEroZ8k88f0ObKm7TjYqPNTzrYouSs0WsZWy'
    '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'
    'KhUfQ5UV6pf8n+ku7OZb0odSb3fGOw9deCqSRGrHqKz2ZlsWLDQ1xYld2Q3lWSPgSEQuT8rVX+j+hUhm3JQkzlM5Zy2ctmRii+v7'
    'okrNL/lE7Qjmk1+aKVSde8to9Pct7j+pVo01BuW5RyKOa9ipjIR3lcjjaa1Z/EKe5Vxt2nAWLpoeNX3UTxkrDlfzS3JPNoiNIhSS'
    '6HIlJaFPB9yNBJClVoVHHK7FGdSa2FIci4in7E5pR1JU1uh7caHq/P8AYfGxYsU391jp2ZCGhktuTl2Gixy5Pocp9TJBbszQW0Tn'
    'T6aDd9/GthaMat4I1Zx2YsR+JGeD6mUcRrhI9Ct18CEQjcuojqq9jSSKkbD8D4Tbb0JulT81V/mfH0Z+RakW0VavR7GIquTyUtic'
    'pp2vqWX3txEIxb8w6i+6c5roOcnqzNfYis25GN/SiFCRCnl1kJLoRiZTlqW4llVi5fhC5BaFeTeiHOW3go+oYyxYSFEjTFSlYhWg'
    '9I7jpykfD9zlxQ9NiTGP5VtBlrq3jUmthV2tzPTkSpvdG2pbiiKvojyw9Q6/Y5gp+YhUObF+oxlWOGWab0KGNVfWmtBuw0McvcrY'
    'mrJ5aC/qV6NWLvUepCNOKvfUderJWuSm9jPLoLVG3USuRiKnBbn00EtdxwjLZiozekY6EKVS21iyh65Fa8v5Zh45VaUtRSjwSfU5'
    'd+vFClbYjHM7lV5WSlmLFixR3/PwJCRClcnUp0d9zl1a2tXRdiVOEF5UKs4ixEXuaS2JIkhofyraD4TXX5K01FNmb2FKPU8r6iUY'
    'q7JVnstC431LncTK9SUYPJuQwnmvXln9nsKnDL/p7EpxjuNxbzFeWnl3KueMVByJ4iFPylWpmlcbuKlm3IqjT9x4pb6E6ufcpQzL'
    'QhC+r0FQscnuOhnllRDCk1CivKrsw9Ca81V3f7GUVpbCiVIKXlaIYWnHVIyHKuKmZSwovcjuQq20MnMWxDCp7lXDpax40t/z4pEY'
    'kYKKzSM86ulLRd/7EIU6Wq37kqlzNfQnoxsztCxEuoqsJexy29VqP5KQ0S4LsPTxpXJPt4c9noZosjUjPWOwpZkNnMUldMUiUOZU'
    'U29FsYitlj5XqTxipSUtbr+hzXi5Kd7Pt3KmIcPKz4jTUrVs4mlqxJyVxtLYlKTFQm1dlLB21ZyOhCEYq0UVsNKWq0IUp013I029'
    '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'
    'BatCw1ttPoY6pTpR5a3KLhnzTKcbrawonLvoWtsJIUJbiRlMpYsWLFLrEyiiKBCBlzMUVFGdv0oSW71G9DFUZT1icpwj5iMexRhl'
    'iSaROv2M12X0KvG4knuX04UZF9CVSLWVjinqiMSd7HN7nllozbYjBbixNN1OWjQukOzMT9mwxDvWk2u3Qjh6VFZaSsjIOmk7mxWq'
    'RprMyH2jTqTyU9ReC5ipV5+Wlou5OOIdoOX5mHwkKCzS1YrQvKCvczDae5XxtO+VFJZvNIniY01ofEcyXmf9ELPLaP5ipP7zHQ1v'
    'H9jzNe4oT2ZDDUqesUTlbRK7FhJ200b6kPsqjHWepGjCkvJEtK4kOy3Kk3a1NFXATqabfqYf7PhS16igJFixYQmn6jlX1jqWLcLC'
    'RDR3MhGBltqJWWpSxUJzyIaW71PVuKSgrGe5LYnG5SpajnYqSJMiOWhNj4xLlylIcr7Mb1KdQuNk0oszlOo0VJS5d4FG+tSaKMm6'
    'jnfQp4tOVkhVFIaTHRKmHTfm/cmrMyNlfB062lTUp4WnS9KNBl23wlVTeVGJxsaXlWrPh51fPVYsS6Cy1dURx1JrRk8bExGNlU8k'
    'dCjQmvRC77sjQrPTNb6FL7OjvU1I0owVoIXFylmSS0JRjLRiWnGw+Frjpxe5lMpYsRRYsWLFhCnf1q5yr6wdywkZSMSmuhdRPiou'
    'plOZONW8mNuFS8UZrLUqVHL2EyMbjMh6USlqSmiTFIbJcIji1uRfGLFIciMiEy5MZFkKvcahNWY8Llg1TIU5UoOUzBwjZy7jsjmI'
    '5kb2HOCV2YmvNxvDQipb1ZE61tEc6a1mrE6umhzMizTZPFyrabRKmP0y0SlPI88tyWIlV0TPhalXZCwjpq83YoYWpWd9olLDRhsh'
    'U0KmlsKPctwlGpfy7FhxT34OaRGalt8mxYitCxYt4EITvuKn2FTMjiyC81zFpQq5ydOTalSRPB52mxRjAnMk4i1ZTVlxqy0JSMwx'
    'cGhkZK/mRKrRkrNjVteKExsuRkKY2ST4KRCr0RCr3OZF6EpxSsSa7kyddRVyvjoxViWMnUdoEZ2WpVxVT0qNyriKi0dj4l20ROq5'
    'vzM5alvqQwNyl9n0/vIhQUdEctJHwsZSzSQoGUS4JDpJu7LeBk8JVqSvORQpKlHLH5cVoWLcLFiwokYEKTZeMI5idOTUtbFKanBD'
    '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'
    'ixRvQDHuc7iF7RmMbAu6awcFlCm5KIOaxmw2TtUAJtY4KjtjHX9UXO27VMhARlo1RJ8FPxuzUqGhYNgz0aohSJXtOUMHCZWo17/s'
    'u6HkvaVWsCvdvFexARk5KXeSzWtUw6brd+SreXV81VbjonNu5CtSPOUHZO6VZ3+bUDfTohrQSTsCFf8AtA4n/DRC1tWmMmDIfkNV'
    'hPkteGfuK16+L9oWrRLv3Faoa3wCu89PiOhv8VcFq1XAq/5WXWYMytzRkOtZU2ZHwTeU0+xUGaPLKonDam35nJ3KuUPwMcZNR23w'
    '3os5I0s31D2j/wAfkoY0uPBFlSpgeNkT0eZou9vUvUcPh4LC50u2KahUipfiFBeHP/mg2Lo1KhA3DepLPKV2G+awuP3Qm/AKnylo'
    'qBrrYJkotpMFMHdn6rWEaclCxu7f8ltK4rnH5okNsodVxu3MUUKLW8XXWvUc7Rgb90WxjI8lnku1AU4vNY8OYupmKfzFDDUbUn5V'
    'hn0V7K35Sv5dZEY6Tu0w7V+K5GcdA+rOjyKltM1D0MNJvi7YEafJYrcp21Dk1GpUcXOO09ZDWl3gsXMlo/VZe15UwcG3WVSr9l7L'
    'k1Nn3V6h8rK9+rlcD0rOkbjda9OOLVqVB4Gy1mEfkYWBvZHXv5HUs5mRQLeTGpgsxp7Lf+SsdVmI8XBd2PrC7DfrCypj/wBwLXqU'
    'GeNQL3rk3+ove+S/6i995L9a985N9a985P8AUvfKHqV75R+698pfdVKZ5ZSPOfoNl78z6CvfG/SVSI5ZL3CSMGS94/2r2bqhaM3Y'
    'LBO5NyWrirO7VXCu8d9K7TvpWbj5KZdi3QphynC71WINMN2yrMPkoDKiAa4yh+IqDEPlzWJ3KnlW5QfRWrPP8KvW/wBqxfiL/qC5'
    'ljx4kIkcopKX8oprXrudwAWrQJ8Srg+ARcWQdAikAN5spqvk7mrGWwNm8qHOhvyhXEjRnAW/TE2UgQrj0XNVGy3cVeoAPFFlCkW0'
    't+UrC1tNp3gKT1hPU1/LrcbLtPaacnL8XyDs/FT2t0wm0hlTptbp5/lTuaoDadq/DciHM0Pu7qbXWryZ/nZf3jlFGj4ula1epWP6'
    'BC9jyFvjUMqGvFMfobC16jneJ/I4ep9nUcOC9vydruLNUrU5TzR+WqP6rFhxN+Zlx1sBc23zPXezZbfsXtHfiavyt7IUscKQY0kN'
    'Zku1zHLPGzkadZpa7TksuoJm+7oNq1QcL8p2pnNPxPG0iy5p1U4NwsNEuph9oghey5xpPw4VBEEaAa4yvCwmQ3h/wsFJq9o5o81a'
    'rPAKKbPRaxDQtd6hrMXirOgbgr1CCvZt81m5x3IahbouUOFlDGE+CxV6gHBt17KlLt7rqAjWrumFiNhsG5XCgXWtd3ypzHQCN2gy'
    'Vl56L5aNWni8Vw3BTI8usnTHUco8W9dzlM+I3r8TyPVqjtMUEQVRZvcFVfvcg1jZJQq8r16vw0wpeYbsYMh0bXWpyZ/mIXt69Ch+'
    '5y9pyx9bhSavZcgxnfVcoospUR+hi9pXe7z/AC+L16uaVRzDwK9uxlbxEFDXrckf+rXasfJn0+VN/wC07+iwvaWHcRHU4RntPWxT'
    'ZPHYvau/E1fkb2QsE83T+RlhoqH9BQIMFfhf7R/hrblfWpnJ4yPU5KBmso05poq1MQYICgbUC2lE7XWWu/6Qtcy8nzUiyyQLBhcP'
    'iUhCvXz+FqgaoWJxIZvWFowMW8qGavFXkA7Str1LCG+CkuWpfR3ijmudPgvaMYxXGI8VDG24WUuIaFN3IvdDGqcmjISjreisPVS1'
    '0eClWbbei0kW3FazgA1YW6rd3QwZabzP5blX7mdeKlM3/mvxfJO/b22b1jI7DSVYW2lGlyYB9ba7ci+o7E47StUE+C1eTu87Ka1e'
    'lS8SvacsfVO5gXsuQ4zvqFRRZSoj9LVr13nz/MHocFHW4mktO8LC+oK7PlrDEvbckfyZ3zUTI9Cv7ryunV4HVcvaUy3x6P6j1kUm'
    'Fy9s/wDEVPkZl6rBIp0/kZYdCp4aeYrt57k5+E7F+K5C7naG7a3qNpOl3tAzx2o75z2K0h2VkKvKDzFPjmV7GkJHxOuVAAPHNFmI'
    'rmqj4Owqz24d6LXvafAXWEMEFdkA7lJKxVThpjPiopU8liqusNi3N3IaswrGOErJpV6AUc24ea/5Wu9XbPioaz+i38AopsWKodZR'
    'SpnxcjU5RVUMswZaMj4ol1VttkrUaVbCEKIqYg74U6nhaHjer1B5K0nRrfbQSBZt9DnPrBkZCJlF1XnHP+UW+/V26vlX7mdfkhVo'
    'GHfzR5TzZpOqNh7FzQqt5NT+616r6ngvZ8iaeLl7MMp/tC1qzj5/4FxH5GGVnRuNwvbcmbPzU9ValfCd1QLFEjeLrFt2K/VYabZX'
    'tnc+/wCRmXmVzYilS+Rlh0j0MdJ0bxsK53ko5uv8VLf4LE8c039SmvVe92xrdqIocjaxu9wxFZIukW3nojVwg5F1pQps1nEwAFD6'
    'fP1xm/YDuCMX/csNRp8kJXOU34HbRsXeMPmoaRHirFh81q0771emZ4hYqs+CvYDYFDGwvaX8SrBv81ZpWq0+i9rygM8XLv3v8ArU'
    '3E8XKGHAP0hS9xJ4latR3kVaqT43X96p0v6rVpELuvUq1H7rC+m08JVqH3WrDfJXqz4rvGnzUBzR4uRbV5Q0EbG6ynkzXuqjJz9n'
    'kibvcUGPYWuOxa4hDEw0xsxLerAK5UDqZ6/lP72ddYKYhu8r5qn3RpOOFjhhEbE6lXw1sJjXC9rRdQdvbkp5NXZVWuwj88OlIyP5'
    'OQSAsguwtoXbGjsn06EMbK13c8/5WZeqwdhnyNsNILxibulF2EN4DTcwvNb1lGjm6Q8TsCD6tQ16o+XILm+6J7L80eeMk7d6z0tf'
    'UoNqtBycuefThuQaLWRIYB5Subpu1GXNoWKhWYaPw43ZJ3KH1WveBDMOwraVI2IEiwuuaot8XHapKim2TvWs/Rcwv+ehNRwB4laj'
    'S8+ihgaxa1V5Wu6eAWoMI3aM4X/KzWKWFzthFws1i2K1yolO5TXfAAsFDdVvQ1c+g1z6r7bRmi+mwOefjqXKx13c4eOiXNxcFknY'
    'gcrRoECOrJ6uv+5vWgNbK5zlLh4LBycYBvUkqdqpctb8Wq/x0SDBUc7jG591/eeS4D81Nf3TlTXH5X2K16Zjf/gOH8lCwjIdLVe4'
    'eavDvELWoN/hsnF1Nxtqgm0rAdVnyiw6VwT4dAdB9YyKTf8AcdikmVx4rmK4x0vu3wXOMOOkcnaBqX3ItIw8M0IHqhCfB132V9ib'
    'TaO1rFcEMNPzRLu05SB6rerDTvXy+Ku9exieKw896KRUa9dnC3aUCdZBoGHgMlbRdQxsBXWOqdRonxRc45oFXESoFyvxNLkT6pa2'
    'S+rZrVNV88Ng02UugcJ6ABMeKimTWt2jZZflLLJTFunW/c3q8lznKPZtXNckaCd6l756FXkTzaqLeKLXWIsej7Ou6Nzrhf3vkYn5'
    '6Vl/deWNn5KtipdSMbxcfn8Xr+R4nq4OXU3smuNRsEWG1ZqMkKTRPghQjmms7LRocRZozJUVMRduXs4jKIsViogs3sdsQpseTWHy'
    'qS2AmwzEflRc6jH2hTtWJ/Z/mpyag1sF29S4nC26vs2LVU1LuVhA3ldrEeChoDeJV3krXepdPgsLdVqyRfWLm0m7hnwUg4GCzWg5'
    'BZrmj2tiGGlhB+M2WFtfnK22Mgu8haxN8kCQm6oAaIAGxe1dHAXKPNiG8Vcomk3XIjEdngsL6znDcXaLnrIhB9X2LP1Zrm6ZdXq7'
    '5sPyEqIWNnSq/uHVThgbypOvWRGLCz5R0g9uYuFT5ZT7Fceh6j2VdzeC/vXJWVP1N1SvZcoNJ3y1FiDcbd7LqD+b4KOvxHIKT1IE'
    'x0IaJO5YuVHWOVNpv5qya3BhcBraZZY8FhrNwvN7lQL6XCnNPGLnbCzWFoLjwWOtWbQEZOufRAGtUquJucgsFKjiPzFYaIDf1Qoq'
    'EB+/YU5uAXQLXBYqjvRBlPbtdsXNtfiAOe9NpMsVaTKwDPasTlcho4r2bC873LXd5KSCT9li2IwLKpUpYdXejjud6xQcMxKa6p7S'
    '/Z2ea13Odw2Bazx4C6AbSk8SgWQ0jcEHPquvvK3qTTxblJOnC0SVBEHSYi/BCTl0Mup5xjWl2zEJhe1rOI3dTZZdGJUhcdBA0201'
    'P3DqA1jSSVz3L3j9q5rkg5tm9ST1FbkJz7dPx6uadRzfBRyikysONitV7qJ/VcKWRVG9hUEQeP5B36Wz1PFvXQoGQ/I85zYe3fUy'
    'Rio0/pao5oM8RK7RUm50h/N4R+uwXtuU4j/2xK9lQxcahlHWbR3Q2JWJ2sTtlYp1yiwN1t6cyRhOw3Q514jc0LDg1fuhtaMoRmVD'
    'WwAudcdbYFcSUHuUkT4osYdbepJnx0uc5kM3lczRsOF1L3F3BdrCNy1GTG9Q5/kFLGgHjmjiJJ8VmtVscVMB3jsUXdOcJzGgETnF'
    '1npinSLvALm6owu3aJj83lov0IUjTBsVkrqCFKfhjtBWbCg9HneUeyp8VzP9nsDn7XrFUqFx6plVubTKFen3VcY29bLXFvgsNZrK'
    'zf1Ba+Pk59QsXJ6rK7eBuoe0t8et5S/gG9TKxN7Lup1suCwNaGtmeOmPiOm5jq7aA2mCXHKE4Gm19Xe66l7i7RANtyuzD+1eybj8'
    'kTyxxLv8tn/K/u/J6dIDhJ9VNRxceK7DkDUlztgCuJU2Xstv2Rc9rpiF2sPArMKzTV47EJaxrVOakjVWJ5WqIW/iubp57SrrVYva'
    'PHgFjpU9X5nI0afKm49rv+FFMB5/Tdc9y7lVOh+koPpmo9wO6AnjmmtbUOI496kPDBwEKRa0ePFXKhtOXfM5WWs/0WozzcVB8tEU'
    'm22u2BYuU1W1H8f+EaXJBzNPeMyp0NicXxT+Uur6LKD1UTotkrBSslBGh/71Bseh7NurtccgtY/iOU7t3/ChzsNP5G9bV5NnUo+0'
    'Z4bR+QkGDwUOIqt3PEr2tB1F2+mbKeTcpZV4GxXtKbm9V++p/IdVzR25eKjq8bsgpPVSGhvAaMlPNO9FkobTcfJcxTM13DXfu4BW'
    'puPgFq0Xk+Cl1MUm73mF7blg8GD+q9jRAHzuuVDXH1RNSrhG8rDDap34Fq0mMG8MWHtDiFIcPRXaD5KAwA71IcWrC2fJY6is2VbR'
    'L3LUb5lS65UZqJ1itpXwj7lRTlOFU+0xZIsZiLYjCMlhp0h5nJczyV2Kqe3Vj+SEt19rsRMqYw+KznqIFyr57VzYquDBsBVz0ZqU'
    'TVO6YCAFKnSaNjAsUjw29Vl0rK61VkrHy0W6Ra4eB0W0ZqDouOgf3K+xEINY0uJ2BfiP7TqgbqY2rmeRt/D0eGfXsrD4TfwRwd2/'
    'XZ4fk9WqY3G69vyYA/NTsvYcoE/LUsr0nRvF+nRZuknqrBCpbFk6OqwhYW9kZadUQOibdDnH6lIZuKA5HRD3/ObrnOV1MR+WVFJj'
    'BwCivTbHgu7IPkiaTqxO4OWIYj4grWD/AETGnVb/ADXNNDiBZS1rsXFGTbZGWgONoRc/UnaArkRvJXaLj+lBuECLrXuVDKa1rBcF'
    'K1G4eJUuN+OiKaL3/Dmi4m5TiXRCimEHvqYj8rSi5jA0HfcqJKBB9rynPg1GpUdjc7dZBrQGxuF1rZrgraWyGjCIsNO/8mGNEuNg'
    'sLXYiM7beozVtGqVcKw9VKsFLqZHiOllotdRhUqxWGVhKAnbo5wkUqW1xRpf2ezE7bVcsdV5e7efyMf9Tkt/4fy3sqrmeBX965NT'
    'q/qGq5ez5S6g75ao/qsTQKrfmpmVB0gcOrvkbFR1OH4nZ9Hta26NF+j+M5T3Q7LfnKEkNYMmtUUnLCXku26M0ymaxZOZhPZ+IxRl'
    'GZUYMRWJ1o+FAtOspdbjkuCwPAcOKsAFicznOCxRhb8LVNRxe5WaAtUwPmXzFREKVvWs4BRTbK9q6OCgDzKLnGwzKgWYMgjUw2Gz'
    'avhbGxWV0XtsRuUgHxciMeXzf0Vm4zx0WCwnYrmfBBzWC2+6L3mSVMWTGVXlrCblokp3NzGWt0I/ISOhZqyWtdZ6LqRntVgStgVz'
    'KutyNWNYKHCQnNbkp6N+hKmVdMbTE3K1zz1UbBkFDzqfKPybXO7B1XeCfS2DLw/MTTeWngorsZXH6hdZvoHjrBYqZbVb+gox0yQL'
    'Do4drcunmsUeCk9LUZhHjPQiEKtfsbGtN3LW7Is1gyC5ukOCJwyR90XHM30mmKALnZv2xuRqPpuoP2Ws5Yp1uCEG6FUtJqHsjcsV'
    'bD5lRzH0uU43N8Qs3FYYC4rJX0WUmwUNOJZx4LatWyzlSTCwv5RbcFAIB4NunNpDPbmVijC77FDBQOIb17Y4n/K3YnUqbA1xygKb'
    'eizWqD5ldjO6FOjFs3j4tE1C2kP1lWx1T9IWo1rPAK5n8nuCAYw+J0Rp1shdYQLbliaIBVlLrKylttG/RI0AMEzsWINxDaJXZOLi'
    'i45lTkN6lutpzWa7Sz0RoujRxljXbQt/gs/ylOv8dD2b/DZ+aui4Whb1fVVr9GJtu6MhYhkdBIFhtPQhWy6OtYLVBA46ezKuckaz'
    '2OextvE7lLs0M75qGthVHVHRTaNaERTs3ZKsvxHKago0N+0+Ca7kVFtJjfifdzl7VznKFjeyBx2rBTMDgtYmUA2fJXstmiclqt9V'
    'sVySoFl7QkqKcAK71aVaVmtZyzUiZ4rirkN8U2kJdHxDYnPpv5wfyTbZFObuKgKaxw8NvoizGKTDnJuVZrqnjYLVhn7VO3TheIMS'
    'gJAnfpxbNPDatq7f2XaCzHqsllozCu8K5eVamT4lWho4BZq4WSl2qr5aJnyWLAQ1ZJxnJbCslbTdCLpzvi0WAyVlg2gqSiW71YK/'
    'R1rLVV0Fzb3RHZduWGoJVjHj0rLWss1YdUaVTu6wwOTqb+00x+YtfQGbtEhWMK4lZx49TgJsVGGNGWjJYdpz02BK2BPdVrilTp9p'
    'xC/ulAmp/mVb/ZYnuxHisghgGsuwV4XKFCjUcKIyGS5zlGq3Y3aV7Km3xIlYq9v0hVKNMAA5CEGFrR5L2mseGxYQ7UGQWYCiFqtx'
    'OUkc22IuYWtVxH9K1aXm5Roz0ROi7lqhWNl3mJZnQIU/G7IIu+5RxRVta21SZWRVgs1tIQNFrp3hTy1zKbvmBv6JtV3K2a1uNuCP'
    '4cVKtXedUBXfE7rK5M9bgHn1GWjDHnpyVwm4hadAG3RLtmjnAM1dW6FtOq5RhGJElc4/srUGA7wjTe82V00MGzNc6BBUabZ9Dz0c'
    '3UP7XblhOei46E9C/VUuV/F3dTx/LX04t3Q9m7EN8RpsrhWN9ykswje6y1qpdwYP6rUpx+4yrnTi27ehjPlo1nE+CsNEBCm1hqOG'
    'ZJgFatIjgAtZrh5aLWUa8O2b0JbB4oVH61T+S1W5/de2OKp8rdi2DgFqT5L20uw/ZDVlHmKJY07SprcoHgy69nyVz+L1YCmNzQtZ'
    '3rogW0y8rc3csr7lDbBYWNLuKl8VH7tgWu8MZ6BXefFE0qgcVcKSckPje5ZlTWqCdyw0W+ACktjxcvbcpHgzWWpQa7i8q3JaUqHV'
    'nNbuFlYzxKM32qQ0N4DRii3QzRfsFun+o9TicstN02o4YiU52EAjQKbStYknep2FWXZOLci1xjp3urHQHBa1wuZccO5Yi8eSJ3lS'
    '0W4qHtxNG0KIhqtdXddQ4dG2nA/+E7lB6MBDRlo49S7kz+xWEeB2IsdYix/KW6GHd0vZ03P8AvbVKdLgTJWVSsfpCigxlEfpF/VY'
    'qjsZ4rONMC5V7LO2hwdyVtVxyLtiya3wCzt0JAtvWu9z3bm2C/u9JtP9S9rXL28EQxpLt5V4HkoEOdvIUNm63vQfXdhH3KI5OMHH'
    'asvurBYiObG9xhYTW5zwC9jTwjfCmo7F4lRCtZHCYG8qAMR3r2jp4KG/ZO2BQxc5UMN3lYaVuKi7lzQAA4JxJOI2wBS6wZbdCyLi'
    'roNozJTaIl58M0NidUr2YLC6iiDWd42WL8NSDf8A8a9ngp/tYFie4uPFXsuzz3E2C9mG053IkmdEtaSNsBfEX/ZZR0GvMQ7j1GN2'
    'Sk9RYS/fpgBapBOgU37MkW0m2O0q4hNxKUGAzCtkp3Iwta56jeOK1THAqCs0HKQ+eCp4U7FlGhr+KkGyAGxWWXTwu8irqFkpUkKx'
    'UPsViBUrLqbKnypv/UGt+78lfo4lkuyoDCTwXtA2kP8AuGFr13VDupiPuV7LkzPF2soNQxu6WrOJaw81Y6fDRGjUbfgpqvbTHG5R'
    'IoYquQe+/wBlidrFQaYZaclILCOKjCFrU770Bja0FarmO8Cppt8yg4jE9TEL2tdrFqh1U+icGNLI+Wyl9ap5iUNWeB2rCW5bFZhP'
    'gr6i1aZfU+YrHWdHBRTbAVyoAWH5hCzxv+Va7vAIODvaPyG4KXXKbUpuLao27k/4nHJx2KSsym0qZJJyTqdR55RUOZavYcnw+LlL'
    'A1q9rVJG7Yu0Vhe8uaNmxZdIVA1pI+YSuadUhnytsg7eNMBYHRPAzpksDuBQBiG5ADocNqtkMunlpyWScNqkpxGgRlCnbKuV2jHi'
    'plWRLzJ3BGNXp2chzry0cAi7k9dtVo36pUbVw3LPAfssLst6hYQ5YcVtw0CRLkXMtolwlYXNCLQenEq+i/XAnaoDsQ3hOpH4svHR'
    'bo4ujqsJ8Arcnd5rDVw4twdMabdJtGk3EUDW9o/dsWOowBo2I0+TAUKf6cypJkqAJKt1WayUgyrBazx5XWqyf3KJtwV1hOxRl4BS'
    'TmoDh6qXxhC9my/goeDh/UYWJzg5YJk7gsNCkJ9U1oqOL/ijZwV2O81hWa1iruK1WhAbT8ohYn67tOSl7hTbvcsNKT+qEaNAGN42'
    'rXGsncqqj2bP9x3IvcblNqCliadqwPdrDMcdDarmEMdkd+jUf2hrR1bjTBIaJPh0P2nq4C5tvmd/RvosNOHYoaIUgaAXGVLREaMJ'
    'hw3KXO8tFrNC+ZcNFkeqhrZKxvoPaBthA3AP3W4rELwoUuvCByKgaJDrqMtEvJk7lvB0ZdDC+4/krGehdW0T1fOD4lGzqRW5U8Ua'
    'WwEwXIMZVptaNgKNLk2qPm2olX6O06Occ8MY34iub5FTuc6j8yu+ctd5d49Sb4WjNx2IClTgARO1yy0RdRhQJEA71NQF3AJzHUW8'
    '2d4sEW4X01qVWu+y7BWSuFhos84Wq1zpU8pr02cJlAuBqeNlh5PTbSHALnuU1HEfKoZrH7BFxfefNPLfqKLn144JtMOwtCFABjiD'
    '24upt6rNdkuVhhC36JDFrVWDzUS88cKxfiHX3hcy14bvk3UNcCeC9rWY1wshSog8zT7I/qgW0msb8xCqc+8FznaoylGo+7isLdqo'
    'Np8pNZ98d7N63PoOZ8w6v/uO+3U4jZqxg4gsQWoFM30YSYRvJKOzRrGAobdXOjJXVlJ6qQYXNHlLyzci13KW04/zDZYeca6NystY'
    'eYWoZ8FgJU7VfRZZL2llbIIwbrXCt0bZdC+iOrLPTqpLpWeizrrPRDQoc4eSs31UE20DEcsuHS2eZQcC2/wzdHnw9lTY2FYQrofC'
    '3aSsAbqbIUOBBWsCFLWOHGFLQS9YnjCzeQsMOLvmXsqd97lr1mtaN5WvXvvC9lyuf4V7zTA8VPONDd6ivyg1XbmL2XJ2g736xUYz'
    'G7Jc9Vv8oWJxklY6xxEfCobDGOGTVTbixl+wHJYiJWDZ8oXZJIzQpAQAZy0azGvneFIoR4LWHkrxT8Vd+I8EOZY0TltRdWcT5qAs'
    'bzChhwgfEvZjEd5UCoR4WUE6Ayi90bytc346BUbbCc0T0MtIa0STZGm8YXNsRovohFjKzawHxty6DXbinDz6n8RUFvhG8ouOZ0tc'
    'RAOSjRcrVCusBOSwNvojRZRsUDIKXnCtQeZQE+aeGXDdqwucD+1WWf5KVIQ5xuLjtWo+f0nNSs1msSupY6F7Qea3hSwkFe0atU9C'
    'Rl0ZbmsurkZFZetlM33dTZXcpcCfsjhDWwFe+mT06dYPHOTZv9VJzWNuaxP7W/RrLC0RwClz4dwUuGM73LNYrhvzONkHd6/e7shW'
    'qFdv0UFxOgGVqsKB5Q6nSneJK7xz/EwtQ+gUBpc5S+phd9kG08m2XyhQ1RjK5x2ZWoWQjrS79KiwCgAqYtvU1+Ute75WXWHknInE'
    'b3LDiaP2qZgbzYKalTn38MkcLI8095Jw5LHUy3KfgFgAv5BXN9ysI0DepqDEBs3qUGyB4rDMNGQ0PLIhgkkmNG2dIbhHjtWaknqq'
    'NXeMJ8uoM2ptu47lMQ0WaNw0SdOsVFMRxU1DiKtAUMbKurIOG1WN9JD3XOwZrUGH+alay1Dh8EZeeuLxTcWjh1Ta/NHCoqN9Vqny'
    'Kg5qMS9o6FmsJMFX1KgzhT2hwTZMnFkpp2UVW+atpkZabqWrWCnRDRJUfh6k/tWF4g9C4hTE+KtDT+laxnx63m8IwNdMxfTLvTRi'
    'FF0bzZXBd+0LC0Npk54jdRTcXjfEKTtW8ppovLpF52HTAElNGJrqjvsi+vygNARHJzgA9XKXFb1uamtxWblOxXM6YTn1X4I+a0rC'
    'Bj8F7JrWeS1nHRBpau1yLeTOEnNyDH1mYW5AuXtOWMHAXXOsLHD1WUhAEAb0arhI2NWGlRLWbmqaz2U/3vXtOUmsd1If1X915Kxn'
    '6n6xXtarncFLTC16r3DdK1AGrWcT46BTpjxO5Dk9J2KMysOr5lCpyisKbGbRdc3yZnN0/wDc7xU6ZIVhHRh1vDJbx+Qr09tOKg/r'
    '0wxolxsEOSUjIb23fM7ROjWd5L2TcLd6LnHEUywJjJYg3AOKv7SocpW871KjOFE6LlWsiC6FOYUfkZ51+UZ9VhpVDKhzsXirKM+B'
    'WeA8ckJHmrOhRWpxxauc5Odcbjmjied4JOxAU34pC1Hc40+qwy2dzhClrgPBawVtFuhcToDuU14HyNF1HI+SgHe5HHVIG5tugY28'
    'FLiXHqbnqed5dV5gRqt2lQzFUO95Wym39IRGDnHj51c4W7GhVKbaTcTvj2qYAVtOFrcTjm47PBQM1hYJdtcgX6rOKwjIbFYRol2Q'
    '2nJFmDE85O3aIawvK9q5tEcSviqn6QsFBjWftt90ZeD4OWtKxGzfmWIZRmg7skbSuZpOgb4XtKjneeiAhyen24lxKD6jnc3vU880'
    'EbG3WrS5zjUKw87gbuYIUkytRhd4BXj1VrdGBAAuXHIL8PyCmcO10XcjW5W8c4fmNmo1HVued8jMvVaxhgyaMh1llrCOIUt1hw6U'
    'Tl1DWO7NSWHzTmHNpjpB57+qNX9LdGSuvZDA3evaOxO4rtBvksyG8f8AhF7XQ9roujTqUtfxsudqVQ4lYaTY4lDE4klYGK9z0Co/'
    'P4DosVMR4Kylhwngsb2h+2QmVGarRTy4rUEA/PZB1Wq2p+20KGP5xnEQnNLYLjJlB9RmIlAsyKkCdFgtg8Vd6t0rhblY9DBRYXFe'
    '3rtbwAlFlPHymp4w0aLdOwto5xzMdTZPwqY8UGgZqGNMDanPeZJ0Zqoz8Mx9R2VR18K4aNWwOiA252rHUuUcNmrKVOQQOHFxK9nR'
    'dG+F7flTGu3DWK1KBqHfUP8ARYWu5tu6mIVyraM03WMxBLysOfmhjqwAjBOHjp3DeVOI1anAWCxMpNn5n6xXtKzjw6F2rWqOjcoa'
    'wBWz04m03OExYL29UU/0i7kKXJ+TtDd79YlRzzgNwsruJ6Q6qQYK9q3+IKaR5wcM+sDhmLoVm9ms0VOia9Ueyp/7juRqvzK1kC8T'
    'iRA8lqDW3b1FR/N+OaxlwwDZN3eKx71yimDBL81hotwcTclSSpNlzmfRP5uMytfC3gT0Z6Mq2jWY1/8ANQWN9EaYgtfdo3FC0krY'
    '8Ba1kDgBJUUwFb0UwstOIaLmFi1neULmhyQB/wA+Kehkhmub5JTZTbvNyVzb65jc0QpJWazVn34oY2xOWjO/8uhidty0YG5lc44a'
    '29YTC5ymPMICmAH7ZF9NlvUNasZbJ37lhp67uGSkhdzPGFir8op0hxKzfyiN2qEfw3JqVLykr2tZx4TZZ9CD0LjRhNJpYc+K1ZhW'
    'CuZ0Xst63dPWsOKyxLmecIp/I2w6odZIMFRXZi/UM1PJ3c5w2qCIPVcnq7aDzSPhs6Aa0XKZQp93T+53oPcJlAsyKFPDi3I1Hj02'
    'I7LIT2RsUFjXHcAopyxu4HRdWCuo0TpP5uxjqoF+KgnRvW5cEMWtwKHOSAjheHE5QsLVqPsNik3QgC+aLYUjTdaosuyrW0TpyVho'
    'tZcOhhdsuERhz81t04nCGcbaMNJviVsLtqwMNgrlWuOKmpQwO+YIgDU3ldiYWu9rfC6hlJ1R36kH1qfgxqirVZQZuJhXqPrH9Ihf'
    '3fkjG8XXVqjsPCwU1Kpqu3N/5WHst3DTzU6kzkux9+huVlr+gVJvNNYKTcIwqYhZyrCANGXQxEydGa1Z0XEqYA4D83IMFRXbznHa'
    'v7u/F+k2KwvaWnceo5XyP56eNviNGSuIXOOEuKa5giVgbrIuLhO5XRxuGShpUF3lo36XU+YBccnbkBgjRbRKP5GZH5qxWszzCBpu'
    'xAbljB8Qpc3OyhgN1GxEsJEK62YYRLII3FRUbg030X0dlQ1qkuHldHFVhWDqh9ArCMStdQ6m+OAUOGHx0axM8ETEAb1qtAAUQudq'
    'Bv8ANZk+KDqgwMUNbh4bSsJsPlaslOG/EqYlQBCJBtvXtuVN8BdQ2m+s70XOPpspfKxuZR9sWt3NspJJV1Yequ4qSudwnBMToz6E'
    'msMXygIcrfTwN2Ytvkpz06jsM2t1NjKMujdx0Z9ePyXN8oYOUU/1ZjzU8iq63+VUsVgqMLHbj0qFQ5TB81Up7nFEGMRyQJzCgfFs'
    'V3kuQcdiJBlaqwTLipqHCVqt9VrHpz+RylRphzY0QVP5bKVbRhfrDitV+E7nIB1lvChsAHinOdfDsQjVJW9ZkeKlr/8Ahe0bKs5Z'
    'qMWgNjNYWiFJd5K5WJ2SA1Wt4qzucPCwUCGD9KxBnmTJXZUgRC1nEoWttK1bIU2MtuQqVonjsRFOx+Y5qXOJWq0la2qOJXtuVtnc'
    '261GOqfusootDP2hWxO8Sg42asNKKlVF9R8lSM+lGzpSpdc7zfqMlOEwP8K5uu0cop7n/wDKnktTA7/Lqf8AKw1GFp46Mlkp2qly'
    'kA+2YD5oXQlsytX4ViDbouyCgZlYnGSjFp3dVH5DLTlHgrESqVPllPHjnCW3ICmlUFSm7IhPptyfYymUn1DzbOyN2g9bE26JDrEd'
    'POFreoUTiCBY4o866+9EYpRvaJyVm57QtYIAFQdOroxYbbSVhYMZ3lRIXdkrWovPku5d6KXMPgVMKMDsW9S8LBRo+al/3Wq2Xb1d'
    'zaLeJU1OV4jwuvZcmNQ73KKeGkP0hYqtVzp3lTKu5at/3LFWqQwbBtWBuozcOhYK5VpQtn0PaVY4NElczR5Ph3vcZcer5x/sqXzO'
    'XwVHj+IlYRFOlsY3/DHS3naLcw5FzsvkcnCj2VYaG76L/sUaz3DV/moadU7SsRdZQbN4resGNrRxWDG10blh2LKOnCnrY0hrduiy'
    'vq+KtobWY7C9u0Jxr68+Sz6MdbcSsrptMu1W5DpY8YEHLatX1V81YK5AKgnEt3ioIlq1H4TuKjJXCyWSIdnsKhoJG9QLKzMZWEkN'
    'buVhi8l2VrPdG5q5ulThqjET4qOYmdsK7Ws8Vr1x5LPEopUVgp+0f9lethHCyu5zlZZ36MvEtVtGXT7Xl196rj4np2/In8p+J+FP'
    'xMGLaVUotbjmyDOzKxuisNrXBezfzR+V+S1mEjfsVWhMY228Qm8lpdilnxKu6w2BaohSfys6QBd5MAIgi4XFFWuseFrzHouUOexg'
    'tMAIMDg2UGwJG3f08lEqlUxBwqD0O5YGiXHLq46zZ6K5nTmhzQc3xOahYXPc5vyrDzZ8lnfchGSxYMb95yC5yqYaiGi3FZ+gV2eq'
    'lpv+qy9pyimweK1uUl/7QtWg6of1OXsqDGeSu6PNXf6LDTYXE+axcsqa/wDlM/quapRTp7m6DB6crcFnP5Gyvl/iALskzmg1r9wX'
    '4Oi2eK/D8oJaNoTCBqLFQCFJztTRq1oHym49EKlCi2m/fs9FJ1p3fmnCi0EgTCDHOgTBO5OZSqc8Bk4CxWPEslwKlFs55oGQeCPF'
    'XCtok6b6GsPw7VIz0FtNxc39Qhcejfquc5RyvD/22NlydT5NRwg/E+7ul2dGLRCyLuCw0eTuYOAU1AG+JV+UsHnKxPq4wFrOLuAW'
    'pQn9xWq1jfALvXLWrELMnxWauJVjf+aiFj5ZU5pvy/EVg5HT5ofN8R80S967Pnoy6V7qzWs8As5Vh/h1grn0UdT4dTKe2u0F3FPd'
    'TOJuXinVGtwrWeSVcres+lP5UVD2XGAskHYrt3KcPrdM5w9sYhdQi07Mhu0yb8FGjesoVisuhAIHj0W1AJwlOqGAXGVMSOvzWY0a'
    'rXHyXZwj9dlevyceNRa/L6I/bdQeUvf4NXcud4lez5NT/mtXC3wau8d6qQYb8zjZSSa7+PZV3W3BXOnsgaMla2gV+WRSojY7N3ks'
    'XJqWE5YzmiZk8ehdy/5Vgsl28Z4ZI3DY+/5vx/K2C1nei1W+quehbPd1o36JcoChphZqy3dTYLPqoHQhEHMbNFNzCMUfCjjZikEX'
    '3reg24eHZbNPtGYrZLWMhowhEOJUaIWq0laxwq8u8dGcq9lqkFa7I8QrFb1dAznpwktPFpnSHMdmezuUaBCDKkTE2OnUYT4LG+i4'
    'N3noZLs/dd3P8StRb6rD+Ho+JbKs4N/a0BBprO9Vck9K9l7KkX8XKHOyWvPkrHqJGakkk6O0siv69EtBsc/8PsJWs/ybdarPMq56'
    'iKgxDftWJhxN6ix0WV9Ns/y8ALAIJ2nRY5rNO51k0gnxAEyANiyWeWxOJnFs4aIA0bZVhPjotdXEK5Us5OTxK9vyum0/K3WK1Gk+'
    'Kzjw6Gq5bvBXa132KyIWYKyWq5dnTmOjmhLLcLLFWD67vkGSwf2fTp0qmxhGaL+W85lqzkrdbkI3lZz4LUABUk4lmVlphW0arDba'
    'ruAXxFQ1g8dGfQ4KRl/iFhK13RwF1anP7lc9ZiaYKip7N/zbCtYf+ejM56I/N4WgyiKbtfa4bFa6qGr3tg2di2n7KDDBviVzRJcS'
    'ZKHDQZ04pUfZdmPFa7/RatIvXtatOkPFXc+u7cLL+78mp0uMSV7Ws4jd0ty1C13moc0joWKvdXkLYUSCWkLVIctZpC3dJ4wh2IZn'
    '4Uwc6YaIaNwQ5R2RiwndKs0HwuseJstOHDt6qyIFPzK13t9VGK24BZuPSyW7TO3Z1NrHd/hlhK13AfdWbP7lc/kcNn0/kdkp5MST'
    'tpntD/n8hlfq402twWvItI4ol5wUhfEsXJmHnJ1pTn06cDPfCHNugBonZfTrGNvmp7NoRW5aqxc0QN7rKXv9FlPiu00eC1WkrVDW'
    '+Sh1d8bpVzosFe3iu1PgrDpWcVdo0dro6ritZgd9lDyaDuIspY1tTiwqxII2OUls+C3KehqujRe/itrUcJncriPFA/bREhXldj1K'
    'sGgeCjGY62Tl1et6/wCEarSfBe0qBvAXK1Wz+5Z/lbLDyvP/ADRn570HWcw5PbkfzENEkoxlxUgE3V1/8CwsaL2yuiycV5lCmHWz'
    'I4retuLasJwiLqVhGa1KLvE2U1qzW+F0cUu/coY9o/avid4q0N8FrOJ6OayRwnDNrdHLQ1yyV1a/VYmGCtfDUG54la3Jix29jlDH'
    'A8HiF3ZHFq1Xz4q7OhCPFSmAW8807GIhpuFY+qB3p1EMGNt5NkWOEOHXxkOs4f4JDGl3gva1Wt4C5WpTxcXqC624fmtQ2ObTkV7H'
    '2dT/AC3HPwKLXCCNh6/+XQjajSaDGZtmtia6jiL23sqnOCDBggTdEZyI0RsUjtEX4K6Gi1M+Ku4DwuprH1MLvWYt1NsqOT0XO4vK'
    '1XimP0BS95d49XloOEK6yTubeIGWKxKwuYQUGup6j3apKc2mxtjE5qXElZqyy6vVJCjGruxeK1mei1o/iC1beC1XArWYejZGNtkd'
    'Yr2rnOqRmrOBR5t3ONG2Mv8AGtUSvaPDeGZWrTxcXqC624WH58MrjnAMj8QWNhxs37utJOQWJXGxZYfsregVR1MRLbHcjjdikySV'
    'wVluBQ2A5ErtCM7LEfJarSpfUA8FLzP7irR/CFqU/qKwtqCmP0BS97neJ63JXEJ1R1doDRJVV3Jn43jMacZacO/Q17HkObkdydyf'
    'lZFRtMYm7CiIzK9k9lZkfAU6k5jmubnKdB7OaxAyDoy0WWXR2HxWtTI/aVquPmFv02MLtT4oEsy3L2gaD+oKaTyP2mV7N7XfZe0p'
    'OjpCctqxCx4LP10DGIkT+Yv+bstdwarMxfuUTbcP8Dlpgq4wu4ZHquO5CrXaW0vuUW4RTDbBrdiOzKxKbidq5kNsi5ggHzU7T0MM'
    'SdkLVon+Ky9rWA/aJU8ofP73QsPJ6eL9jUXNpgTvurv9PyBkxAtx0CGAWzG1WEqs90Na5m11yq4rYsL2xqosecdKAQ4qoeb1HZAf'
    'CiSTfRZSpFkypTMuG8Iw4ic7p1MZOTmg5N3oYbLPW0W0ZhYm5KHhSFllourdOQYVqpP7rr2tEH9pR5wtpu/WIU0av0uxKzw77K9M'
    '9GVrOJ+6mEJMDipGSug+mS+mfi4/4ZrGFYT4rP0/PeHW4jloDzkVsCJk57AvDeV28GDWlfhm/NizzUojJXzU7VqgnwXZw+K9pV9A'
    'tZzSRvMr2VInwEL2dNjPuvaV3eAt+QvossKbjrMAJi2tC5uk81BFzkmxFtm9GCRNoTGblCGM7I62yITw4OxHIhWOsmvBsTFirrmq'
    '9LGHbdyqVWVZwnCQiKYwt62RZQKxjcbrXYD4WXtKfqJWq7CfFB7HgxvCJLcXgr2UdHmmk4Mz4q4VEi1S4cf8J4qD/hQlwYD8RyUM'
    'M8YU1JI3Der6Riy2wojbmnS64yhRh8p0ezouPGIWKoWN4ZqalX+i2O8pUMpeqsQ3wC1nk+J/JGG4Y2aHY8WL4Y0AH4d1tHDTKk9H'
    'JTonQ11tZcepcGPIlYuU4cBknZCqcn5vvXYsU5LVezzMKMBPhdX63PTquIXaxeK16ayw/Zezqf1UtI8lrNI6EdAk2PgjGzRG9Frh'
    'BH+Bwcv8IgBMYXYy3bu4aIjEZU1AW3hWWYmV7Kk987moSwMv8RWOvykCLwBCvU50+Mr2HJvtC1GsZ91D6ziN3SvOJbura7eqbQ6C'
    'TrE5BYBUFYYZltlZoCmcukIBnbpAbnobTHxJ7KT9XKTaygXKjasWxb9MKNMKx0xozUDocViY4t4hPyOLPEJTWBt942qC4i6ABBUx'
    'b8jaoVdod9l7fk0cYlalbAf3QvY1g8cV3eL9pWtSczxbGkAmIyO5f1QjNH0TThwuaIn5vFQf8D4Lh/goa0SSoadEU2uf4BCKeD9z'
    'l7XlLWtOYha9bnC39X/C9jyXEf2qKNBjBxMrvy39tlL3ud4nqbaJPRlrSRvQxRfijJVxIWUJ4MnEIU7tGc9S+qwWp5krWdZF2zZo'
    'JKh4Phola1hpgrsrapzV2wFq5cdIJi+yVloK9oSBwRmcWzo29U6W4TuAWXkoOgXXZWcaMvyBNGphlSKs8CFFWg13hZN9gWHbZWdC'
    'xMe2OKGPCSDaCuzoKuix2fX3/K2y/PUnseHOiHgbDouhDZVmZoHVb5pxq1hiNg2MlniUto4ncQvZ02N+678gfpsue5VXws4mStR3'
    'mFeD1khU6z2yS7s7I8VhZRwNmGiM0HuiCYzRDnFzN7FGG++Vhm3gnN39DLTbomWzb00mZxbFB9Qg0ANG4JpZYusgGUyfJS9sE5LN'
    'EwSd6kNA0Zr2dd48QtWqx32Xc4vAotqUnt8RoLVnZXgowwLItlEOYZORnJTiz3pzcE1CbPxWCyKwiPFQBKsIHipBgrs32XRMaozK'
    '4I2BRdFgYlRYcT0ZVintNMOccidi7EGb3VSt+ILHzhDXBEY2tj5jmhzrYm+fWAVOUNpjfEpw/EOcAdjc0cOI+Ks0KQY8F3jj46Lt'
    '0ZrAaoZO8JzD8Jj/ABOeuw5zsV3LKVqt0do9GYlETn1NtN3Qtp+yLntQwnC1ptuCpYs6e2c+oGeLRCy0jcdMqMKzAHErttv8uxdp'
    '/GQtVjh4uTqnNAnIcFqw3wTTVdJV1qNJ8Arcnf5q+FniVr8o9Gr2nJ/pctYVGeUr3poP6rL2dZj/AActei13i1TzGE/pMLVqVG/d'
    'ez5QP4gtVrX/ALStfkz7cFBBHinNdZ3wnRJdKl5kjsiFja3DfMHNc5jcBMXEqedbO5At1p3KYtMeegE5NELDWDgZvGwIwE5p1XgT'
    'rf8AzNYiLb9MxbfojoXKgGdEq5j8nJeT4rYslloz6hzMLTPWCRn1jX4gQd2zrnUzTbrbSt/Tz09lbFn+SM57NGSsVJ08NET0cMgd'
    'C9uhFvFZraskQ0Jxc7s2hEudKdUsA1DDD38diqVHNqFxyhuawtoZ5ueoLmNWvWPkFL2l/iVqUGDyWxoWtyhnqrPLvBq1aLz4no6l'
    'eo3wcveCf3AFa9Ok/wAoXtOSkftcr84zxapbypgO42XaY/zBWtyZnotUOZ4OWpyj1ajhfTf9lgPJ8W7CUadai8Di1G5xzbwQe10j'
    'enOzbtXc4j+5Q4QruGI2aC2yhr2uw3lrkxzy5wdnGcq7h7OwBTw7WdsIQXDQxzTfIt/qroxl0J45dLLowxpceH5ntrvV3oXbC7QW'
    'xbPVdldlThWRXZK7JXZK7JWRWRWRWRWRWRXZKyKyWSyWXV9ld2stGf5M8oF2tdBG5ZjSbdO9hnojdt0T0J0QBJRQZisLgKS66tPm'
    'o2oDCFlZO1VAuop0Xu8Gq/JXD91lJdTZ5ypq8q+lqwuxv8SoHJ2+d1ZlNnkAtblDPqXel3g1alJ7vstSg0eJlWeG+DVrV3+quZ6/'
    'Ur1G/wAS7/F+4StelTd9lr8ncPByuXs8WrV5UzzML2tLk9byCNT8JzY24SQvZcqqs9CvZcta79zIUtwVPByLX8kqTwErDMviZy8k'
    '4NsYuUDU12yoyM7kGYmgtOIk/FwXZJZs4ppk474gVndMIOt8WkaIfOG+SEXUDojoF1M9oQVkp0BpcGztOxEjJWH5jMrtFdsrtldp'
    'dpdpZrYti2LYti2LYti2LNZrNZrNZrP87kjojqIRshjktm8IltgchnZDC2+xEkADOy3Diu1sjoEQrNvvRKhYVqUnu8l3RHisRcxn'
    '3UOr22kBQ91Sp5q3JW+d1ccnpeiwt5YwNHyldt7/AAatTk73eJhalGm3xuu9Df2tWtyiof4lcz49bZawlbFfo9oHw6j2deozwcVb'
    'lRP7hK9pTpP8oXteSH+FyvzjPFqh3KWfxhTS/DY+BF0Rzbm/tctWu8eN1LKzHWi4VmydmFycKlKoN1kJa4Hiu0th8ls0Z20G7W4R'
    'N9qzkcAhjmNuHQ64sJXFX0EyLdRY9KJB8P8AHYBnj1V7ab9EX0HV80HEap2rAx5OJ1xHomRinapd2v5LV7H80Z+yBVlAZJK7AHiV'
    'rVGhBrqptuC+N3mu6YP3LvKTfBd6XeAWrSe77LV5M3zcop83THBi1uWP8rKTXqE/uUkz0S0OxceqhS4SN2jgoF1DhBWPC1v7Qsui'
    'DIvogKJnqs1mrOWKnXcCNxXvDj43Wtgd5LWoDyK1mPar1fqav+iViYNXgVmV2laCrtOgk3Dc1Ea2eeaBwmHZJmG5NkZAHiuCCNss'
    '1u6Htw4t/Tojb/6L/qvKE4Ob7WfJqjoxnGiHZhVgKQZiGs2MgqbucBm4hb0ztTuiwCmnTwSsbwJ2QsAOEbVckrJfCs010EwtWj6l'
    'Waxvku+I8FrVXn+LRgxBtpRB2dKNmfWW03UhTKurKSZUar3b8wvFZLBi1dERdQstU7VdEzfYrqeq4rE4hp8enZdorNXaFdi2rMeY'
    'V2N8itV7mRxWpX+yGs1wGwo6gJ3yoFIgRfapDCBuKylWz2KYRsL6CGguIvCs3zUBq4qY4/8AoSNOSAiDtU1A/Hw2cVmiYj+imB5q'
    '32UsoPP8C93cPGyuadP+Ja3Km/wtRDuUVCDnFlr4nni9anJ6PndWcB+1qycVZn3WQXaXaPVk6Y36YK5tgk59U3BTwQ2/HRrscHk7'
    'dyOFk4BJ8OoibL8OTLJkLsqAjJwkC3FAASVrwLxhm6siNygNMotMSExjO0SnucGgzBAOgAMMuyEZqbDBaCbq+hsOk7fydnFdr1Vw'
    'Cr0/uo5tyio3CdzmK2FWd6OWrUPorVB5hMqDC6DsK5zk9F18wQr0KnosNXE1ovl/j86IVtGa2zshalF58Gof3ap52XPYGtd+sysd'
    'R7HbU59TlB1s4avaVj5vAWtUpnxfKsGO8GSub5PQe47oDVhZyUk/uWrQpjxuu01ngxX5U/yWvWe7xd1B/Jxoha3RY4PlxzG5DGJG'
    '1YqDcLOKFSv7QTJbvVQUWc2x+zRJ0SenIOiyxK1lO1Wf2hGexRTJg8Mlha+zTZSJ81MXhY+cgxE5wjF/HQ/BNhfwVugNMDNAYe7G'
    '5OdYcEJtaeuAJu37jTZx9Vq1Xeq72fEL4D5Jo5lhjivack9HL2nIz9IKvQw/wL2T4HmFq1/9ytVKtU+yiWlbFkuysv8AD7Bdh3or'
    'UXLuY8StbAB4qXV2DyWvyv8A2r2nLT9QC1uU4v8A3FZod/CSvZ8ln/21qckP2C1OTNHi5ZUx5Lvo8Ar8of6q7nHxPRxtMOBsdyJW'
    'sZ6sz5aJnTw6QlW0RsV8tNtFujIzWsYWSlMfIIcrLWVuhdRFtN0d3FQctEaS4GCNikKdMbNDdW4zM5qGMwtOYnNblTu7GTr+CMAg'
    'bJRl2WQ3oMa3E47AiI257lq3CkZp1XnmB0xg2lNFHFBHx6MMA7jkhfLQGxltVxK7AG7wUOFzourrMHw/I5ldt3qu0s1sWS7K7KyW'
    'WjNZ/dZrNZ/m81ms1ms/us/vou37LVp/ZWpK1L7qzWrNo8l358gr8pqeqnG+W9o4zdXJPisvyhDWztQJGLgi47UHbCpi2gEizstE'
    'xZOls7tAB9UcBJbvKk6JzWei99JDXYhv0zKt1OJtsPSyQEabLmcWpOKFdZK9uolc5hAQxGBtUSm82HA7ZOeg48WVoXOO8o0XEnxQ'
    'xGArHz0Zz4KJUjNOGfE/CnANnBmjw7XBSfFSHHFGXFOuNayjCceczoJdYxulQhEl25ajnG20LFiHh0iRkEVP53PqY6nNZrNZrPrz'
    'x/Jauy68UWPsQqkNBwtm5iFfW1dhz0B2ggZFZaZHZ0Pqvz4WRJKxO0ax6EwuPQtpumhrTi2nQequrdDJcVOjepW/RfRhi6hBF7s+'
    'Cno4ZtpDRmUabhrDcpm+5WnzUppzJ+y5yn6IFtLm7QQDmiGBwpF2qChi0a2alEzdAVXFo2mMkHPGMbspQDNWCYIzRhxM56NU5IiY'
    't66LjTl6Ig5rCezMwtwTgDquEOG9QTH/AKCgItdYhENGQnomNqyvv6I++iAL79BgxOiR0I6GUq/ZKGKzcwE6Hzhss0ZzTucDuEb1'
    'Lm4/FFuDTELJTplEtbA0zGrtWrMcVbpEHPTfohu5R0raJHRgKIjQ7nH4bWXFXTW1IlzcVjOjNRiDfHQGzA3lSDdFh8kWtAzxLCUa'
    'ZbhxjbuQ4IVMLCeIzTrgRdCDonQYtNisgDHw7Va53I2OLR4aQjo4aGPqOmW55oAC/wD6A13WnzUA2V9FghsBVj56ALb0WxrHJa2f'
    'RwhGxtn1JxCbLLQHPpioBsKxEWnJWzKkqw0cxAiZUKHWKsoVtAdExomLKFq6L6I0ZaMbvDSHO6rJWGnMHRKDxsKdUgNxGYGiNEhZ'
    'KRnuV9JxbraZV/LoSsTVrEnxWSGFt23kjTnKzUaZBgrEYcf1XWUqA3W2lDV2X0DllMy0G/BSTJKNjOzQI0Bw1Y+VYYBJUBpxhahJ'
    'HFRszj/F5Oi6kmSsNs5mL6XVMBwNuT0N6EugEYTh3IhVK1cxWGwrHUZib8qGqLfdBwiQnOtrcFdByJxG+fHQY26ZInpyeg2oyzmn'
    'NF7zJJk6JV89EaI26YOsNynoQoKmECdGHTfoiRnphQr6Lq2m2jgclrPwN2lW04W3jQ0RcIxsudILdimAPDS6jhD6uLvGutGgSCCs'
    'fw6JChZydEx0rdLm8RwzMcejcx0LjyK1bWhbZ/xW+SJbAkYYjZo36MQEKUXMbgbu3IBziQLC6Je4gjJsZq2zoYnaJDYGRPQv1MaM'
    'p0SdJghEGcc6S9zvABQr56JOiRboZaLKMN96xKUGgeqh2lxLumLm3U5I6uiwRDmy5EaMTnX3aLWUDNXMKQVAOaEHtDRc7EdyvMab'
    '579HDRIVkQrlAb1GiSJ6OX/oG3TLTMbNPFXM9CSuGiNispyV89MK1xpjRcxoMzOxWUnRClRCgC6/EuENmI26RNpUIBm1Q5ao06+W'
    'htIUxiHxdHeskTC46Z6m6toyVlMKTpkADoWnQZGtv0XVTETzg7KE9pS6fFaxdh/TmodqhotbPxThia3CJumjcg99OdonarWM5oRs'
    'GwI4rWlDJYGuxcdEjLTfZ0J0F9oCONhdq2vtUQiEJsN6O3omejb/ABeY6mDonRJAzV7BYi7bkgRt0B42GyHFCAAW7tqspTXOaHD5'
    'UQ2BtudGIDRay4rhojahLc7hc2cjdQEcVFrzmCdicHPmdmjKV4KYWHcrIRpkBXEoOdkclnplXClW0GTojLowTCiR0s1KOiTp1kI0'
    'B2LXJ9FI2oNkCVhcdVqs04TlKxPGpEXTWNpYWt27YRbUcWt7TRGaC597sbhmHHNUOS4AzCdZwCwAGpsAG1YX5ttG5ZS7ehWyY4lq'
    'DnX2ArCZjirLWHno4LHjgjYdp0HYf5oznsVtGagKMJkKSbi8KQIcESQs5UFwaDt6i2myy/xGNOsYb/NQEWHtTYzloImeIWUqQ0Cd'
    'F7RkipKgILE92GN6M7FACfebWKFVzNTKyFNrJi+Ne1ByUnagHPG+2xARCik4u4kaA8HxVlqvJ8kXWHALhospQuctqACgZKUb5KA0'
    'nTfSQrpyw7EAEATlpyWWk2lQAslmFMjoXPTy0mFfRkF2V2V2V2F3f3WEB0HZK+MKzneiadbVEdlAhqDnNg4pKDXCWAzhR9iYRIYU'
    'XcxhlHDTgxGaOJ1IeNQLW5VS/hlyj8QT/AV2yf4VYk+ScwRczMXWcq+jNdpRiXaCBxixROIXVyL5LtBdoXWYUucMoUYh6rMLZosF'
    'loy0ZaBZZaMtGSv/AIdtxaJKvssjM5I6qiCsQp4BuCdLJJFjuXZTQKcQM96E04kbVrbFARAAusbWweCdIGI7ZWJ0TEZqJb6oazUS'
    'ajY2CV3ovxXeNWHnQrVBbgu19lhxfZdpRiKzWZRF1ksltW1RdTdXDvVXDvVarT6rDeF2VkslkoeF2QrNC7IXZCyCy6q3UZK+idML'
    'JYuhIuEVGSuYWqV7V5J3NUUGBnE5rvSu9Pqu8Pqu2V2ypFUnzXbPqu271Uypa9zfAq3KH+q79/qiOedda0HyWXUidgjpX6Mlaoj/'
    'ABzPRksllpE9E6J0DoZLJYoWS7K7PSzQ6iFmr6M9Gf5S6toy0W6GSy0WCl1hxVm4vsop0gOOiXmenZdlTTZgEZaePQ7DfRZDrsll'
    'pv8A+hJ/P3/JxGiQp0ZdLJZLLoxourNUDpZLJZLJZLLQGYctGXV5LJZLI+i7J9F2T6Lsn0XZPouyfRdk+i7J9F2D6LsH0XYPouy7'
    '0XYPouwfRdg+i7B9F2Hei7t3ou7d6Lu3ei7t3ou7d6Lu3ei7t3ou6d6Lun+i7l/ou5f6LuH+i7h/ou5f6LuH+i93f6L3d/ovd3+i'
    '93qei92qei92qei92qei92qei92qei93f6L3ep6L3d/ovd3+i93f6L3d/ovd3+i93f6L3ep6L3d/ovd6nou4f6LuH+i7h/ou4f6L'
    'uH+i7h/ou4f6LuH+i7h/ou4f6L3ep6L3ep6L3ep9K93qfSvd6n0r3ep9K93qfSvd6n0r3ep9K93qfSvdqn0r3ap9K92qfSvdqn0r'
    '3ep9K7h/0ruX+i7p3ou6d6Lunei7p/ou5f8ASu5f9K7p/wBK7l/0ruX/AErun/Su6f8ASu6f9K7t3ou7d6LsO9F2D6Lsn0XZPouy'
    'fRdkrJZLJZflcuoyWXR7x3ou270XacvjXxrJyyK7JXdld0fVdyfVdyfVdyfVdwfVe7/dW5N917r9yvcx6le5D7r3FnqV7jT9Svca'
    'X3XuVFe5UPRe6cn9F7tyf0XcUPpXdUPpXd0PoC7FH6AuxT/0wrU2/wCkF3f/AOsLu/8A9YXZ/wBoX/gLP+S7f8l3q94XvS98+697'
    'Pqven/UveX/Uvean1Lv6n1Lvqn1K1Wr9RXarepWdX6l2n/Wu9P1q9c/UV70fqKvyp3qveKnqu+qfWu8qfWu2/wCtd4frXeP+pWNQ'
    '/wASyd9SyPqvi9Vm71Xxeq+L1WZ+pZn6l2z9S7f3Xb/3K9X7rvPuu8+67Q9V2x9S7Y+pdsfUu2PqXeD6l2m/Uu03612m/Wu03612'
    'm/Ws2/Ws2/6i7TfrXeN+td6PrXeD613rfrXbZ9azb9a7TfqVy31XeR/EVav9ytWv912p/iVyfVd5/uXbH1Ltj6l3n+5d6fqXe/dd'
    'v7rtf7ldx9V3rl3/AN133+5d9/vXfn6170761bljh5q3LirctCtyofUu8n+JfH9SyqK/OLtVF2nrtO9Vm71X/U9V/wBVXqVPRd+R'
    '4r3oK3KQu/PoveP9q95HoveG+i75vou+b6Lvm+i7wei7Q9Ff+S/8LtN9F2mei7VNdqmu1SX/AEVlRXZpei7FP0XdMXcsXcNXcMXc'
    'N9F7u30XcNXdMXYauyPVdj7q9Meq7v7rsf7l2T9S7J9Vk71XxL41/wBT0XaqfSu2/wCld676V2Cu6KtRPorUD9K7qF2F8Pqs2eq7'
    'xivXp+ivylnoveR9K94P0r3h3ou/qrvai7dT1Xad9SzP1L//AKXw/Us6fqrvorvKCvWo/Su9p/Qu2P8ATVif9Ndl5/hXdVD6LV5M'
    '76lah/uVqTfVdhq+H0XaH0rtH0XxnyXYcrj7q7grv+yvUKzdoyWS2rMratujNdoLP7KwWxZrtFXJXxLJy7JXZK7v7ru/uu7+67r7'
    'ru481efJZVF2X+iyd6LJ3osj6Lsldg+qux31LsO+td27613bvrVqZ+td2fqXYP1K+NZ1PQLOp6BW537L/q/ZZVfULKp6hdmr6hd3'
    'V+td1U+tXov+tdy/61ak7613Z+pd1/uXdH6lZh+pZfdZffRdWqvaveH+i7VQ+i7Vb0Xaqeizqei+P7L4/svjWVT7Ls1fVWZU+pao'
    'f6ru3eqvReuzHiFZzNG1bVkV2XLsldj7LsD0V6LV3bV2Y81Z7h5rv48las0rYfArJyzeF3rl3i7f2V3D0V2tV6f3Xd/dXa8L4/Rf'
    'F6LM+i7xq7VNZUSu7pei7in6LuWrugux918XqrPqD+Jd/U+pW5VU9V729W5Y9e9u9F7z/tXvA+ld8z6V3tP6V3lH6FnR+lf9D0WV'
    'Bd3QXu9I+a91b6r3U/Uvdqn1K/J6vqu5q+ujtrvPuu2u19lt9F8WnYsx6LtLtldsrvCu25do+qzPqs12tGSyWWnsqzV2VsCvUaFe'
    'oT4BXxeqtSB81ai30XZA8lErasgvhC7QXwr4V8PoswswF22rOfBWaVZgWau7Tms+hms1ms1mrSVcwt/UbFkFkslkFsWz06vtK77L'
    'vF2lms1mFaFkF2QuyFsWxbFsWxbNGxWerQVrM05adq29Cziu2VsK1qfoV8a7wrvbLtrNSYhfCrwpwLu1ZgKjCuyr0/srshfF6q1Q'
    'q1Vqs5phdgnwWs1w8ln9lnog6e191ao71U86/wBVao5dtZrtLZ6K8aLOXbXbK7UrYu7C7v7q9L7ru3eq7Dl8Xou19l3gVqjVZw9V'
    'n0slksisl2SrMJ8FIastGasCfJd270VxHiu236gu8p/Ur1qf1L3il6r3ml6rv2LvWrvGrvG+i74ei7/7L3n/AGr3n/ap/En6V7yf'
    'oRP4lw/gU8+/6VBrv+hRz7x/Cu+qCP0rvKk/tQ9pU+hd/U+hWfWd/AFlWjyUB9Ufwha1blH0hdqvHgFZ1c+QWdb7LPlH2WXKPVqy'
    '5R6hdiv9QXc1v9QLuKn+p/4WryZ3nV/8K3JT/qK3JP8A9hXug+sr3Vv1le6s+or3Wn6le50/ur0KXlK7iku5Z913NP7ruKXoV3NP'
    '0XcUvRdzS+lWpUvoXZp/Qr4PoCth+kLtD0C7f2XeLvF3iu5Z9bmrX0bVYrtLtld4VaqV3zl3v2XeA/whZt+kL4PpV20/oXYp/Suw'
    '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'
    '7qMafc//2Q=='
)
MENU_BALL_ART_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAUAAAAFACAYAAADNkKWqAAEAAElEQVR42mz9ebRlWVbXi3/mXGvvfc65fdzoMyMi+7Y6qqE6iqKK'
    'xgIRFGmlEZ+oiALyBMSnqCAOEUFFRP39sH1PBEEFaRRQUQGpBgqoyuqyb6Lv7o3bnG7vteZ8f6x1I/mN8csxYlRUZsQ595y991xz'
    'frspvPUXAJDxOqyehmMnYCXCwRzfOwQR6CawtQorDQwZSQmagJyOcE8Da+AH4NcyTBOMHU4LXADuE+Q4oIIIBBe6oLTiNEADzHtY'
    '7jjL285wkCELiMKWwApIFpgBO8AecNPwO0tkCXq6gzMNftHwiwuIIOuKjAK60QAZYoAO1BLuGQvGmZPKNzwS+NJjkTMB5hF+5hOJ'
    'H/43S577zwdwa44/sMnkawMcy8x/6ir+kY9AfxlyhibCeAX2d2D/WVjswWgM6mADhAijLVjZhmYMi0PYeQGWl2HYB0sgHXTHCSun'
    '0NEm5g6esT7hy9uwvAE2Awc8gxh4Kn/XG2jPoCsPETfO0aydBWkZZldJtz6GHzwN+SbCIYgh6rgPWJ4hBB6573V89Vf9Cb70K76Q'
    'hx4/RWgVzzCfG9dfGbhxfYG40k5agoAEwc1xDBUhD8Zs1tOnjOUMAk0MdF2kaxtCa2BC2woc/V1zHIcBhj6RhgXLvICcEXGCQlQB'
    'IA0Jl0x0oemUbtIQghJVyTmznPX0iwHBiFGJTbm3mkZooiI54zhDnzHLuDuqAiRUlRDK/Sg4UQQJjroTQiAoqChKRlQQEQQDAXdH'
    'VEABAQ2CuwOCu+EkPEZ0FBAE3HA3RAAzwCDlcg0VxAzygOUBRiv49oPQnsKlA4EQAnl6nd/6if+Hf/J3f4wXX3yZd7z2Mb7w897C'
    'A/edJkvAJeK2ZOPekxz79LfCyQfwlPA8R2QA9/K++RCb3gIMHW3iWu5XkYCbg3i5x0jgCc99+XchImEFdIRIC3TUm7L+PgNLgowh'
    'rEDuyMTyvloeZezo+5nhdgvYQ5mWzyhC9gyScc+UgtQCK8AEp3z/Tr3/uQN+A7NLBNkH78ub6BisRcIa+IhykZb1F+A3kPRJmD6H'
    'Tg/JYYLwWf8LcgJvYXUDWT+BjzvoE/Q9xAhtA2sdjCJMIrom6GlgU/FFhh3H7zgeHD8rcF7Qc45vGd4o4kInMAFaFVxgaUI/d4bb'
    'iXQLfM8RU3wCMhFowAWYKew63AJuGewlOBgAQcRgZYwc73AF3xsgJ3Q9ohuKxPLV6SigAmnoaVad9zyqfNN54e1R6Brh6anyTz6w'
    '4Kf+zZS938k0B/v4a5XRV24z7yPpg7vw3FNw9XnIu9AvYT6D4RDSsnxHm2dh4yTkA9i9BU2A1S1IAWZ3YO9lmF2Bfg9UkckpdPVe'
    '4voJQrsGLvSLPWy2jw8DDHfwgxfB6iFkBpLBBHSDsPYadPt1NBv3IW6k6UXSzjPkw09Cfw1hjugCVQd3Uj8DnHP3PMbXfvnX8jVf'
    '+0d58MlTxNZJCZYz4datzNVXlsxnicko0nUBoxQ9zMkJUCeosFwMLIclLqAaEFcRcRXxoKLq6gRHmlGkDYEQhBAVH5zsA5YSy6HH'
    '6u+1FkDHyCljGBhEEdoA7ahxDVqqSLacDcPNsVJcRLwUKYdGBCklCdVSdN3L64uAailkIUBQgFKcxY2ogRhABUIQVByh/B4p36UD'
    '1ELonpEgSKgPvCQcKQeZlWdQgqNQHuRYXg91yAnPGbwWRQwZtfjKcfLkLK5ruLQ0QYgt3P747/Dvfugf8eP//udZNeXLv+AdvOMt'
    'j4Mqy8USIpx99ALH3vRW5NSDEFrIPW4ZjYoub7K89BEsDTRnn0BGa+Uz4eVnEMPNEDHcE1jG3cCXII5oQMIIwjoiq7iMcRNEMvgB'
    'gWUpZLoKsglMENry/aJAqIUoA4e4X0VkB2GJSiJ7xumBOeY9Qgfaltc4+t4p1xB6hClwSOmOetwHRJpaNFcQJri3IBFcUMnANbBn'
    '0HQbbIrwxR8rhW4YQNtSwUdNPQ0amExgFKBV6AKcHaH3KTIB9jK+7/gS/AToA4pcUHTdEHHUYYSxIcpW7SJuZOXOMrO4beTrBlMr'
    'lS4otMBIEBd8z+EmsGuwl2FngP0B+qF8gaMR0sZyDI8jvj2GEZAz2go6ErSFtgMbjEGMC/cIf+JJ4avXhDPBOQyBX7mS+NGfOeQ3'
    'f/E2enUCy470jsy9f26N5enIrR+4g//qr8Hyo3BwqxwmJhCl3PDjVTh1L3LqHnzZw96l0g1qKJ3s/AAOb8DsNpCQtkMmJ9GNewij'
    'ddQG8nxKnh/i/QxSwgW8P4Dpi5D36k0D0CKTx4in3k577HE8BIaDK9juM+S9Z5H+EiL74AOIEEIpfJ57jm1d4PPf94f4lm/8Cj79'
    'HY9BTCyTsXvLuHF1YH83sVgYKoG2EzQoguPJMJCUTVEP6q7JDMdExVFRgjaScgrJUhuijDxbCxo0IOaJRiNNiGTLpauwARdD3PFa'
    'VCATVQk42RLmIKLlwVTDzT0gOeB9bMJCRHrFs6p4TrkUMsE9OZazhUDWIKburkFpQukHwGnaUgDNjRhKabLBSjcEpeBoKX4xQNRQ'
    'O19K8XLDpf5cTj2Mpfy8evdilc+oUkqfACGXRj7W5iQnLCXIVg4qoRSh7DAZ4d06snKGrJu4t2hs6Djgt3/2p/n73/v3efbjz/BF'
    '73krX/xZb6adtMzSgqaNbJ86zfG3fhrNucfIYQ03LcU1GD6/iaQZdCsQImY9itVCl2qH9fuKomdcEuQBp04hEtBmgug66FapGzav'
    'vw5qUW0Q3UL1JMgYc8UllXvKQ/mumON+FffLwD7iS9xnIEvcDxEZEJY4CXzAZUB8KJ0tM5yE6hroJmjpmCSOgAa3iOgqbitAh/sA'
    'ZhiHBNkFu4PYDsKXPAeLoX7wAB6gUWgjrKzBSgetwDjAZoAzDbJhyDTDDGxF4P5IeADCpjEGGoHOlC2FU2K07hxK4JUhce0Qlrcd'
    '5iBukOvtYoLMwXdBbju+48jC8IMM+7PSZQ8DSIBOYTJCtDwg3gCnOmQrInMvhbQRugaG7IR14/MeE/70fYH3KkwCPGuBH/vtJT/+'
    'L65w9Xd2aNIaunKK9PaON3xLy6PnlZ//5YH9b30/vPg/YfUATh6H7XthfRPaAIlycvcDpEPYuwXzw/JzhYibwCKXYkiAztFmKBcq'
    'D8hyF1newYclnofyWVCIHZ56fPYiLG+CR+guELY+nXj6rYTxFmnvIsPOJ/H9F5H+FqL7wAGoEYMgecpyPqWdnOE973kf3/C1X8b7'
    '3vcGVjeUTGJ2YFx8OXH55YG8NJpRoG2CBBU195A9qzmooBkPlr3VICNzb8ECmARVRkFZ9EnNc4vaWs6+obAmQVo3UVEjipDTwGKx'
    'QM1o2jLahUYQK+OZiBDqOBkwPBsERbKRMMDN3PtG9aBR9oLKAe49gtUaA27upfXqRWQB3otZ1oA1IdA2aiGQEUzVXCnv52KlITMj'
    'iBCkdAuKo6o0QVAM0VoApY7yGAK4GoLgouW/l8e8HCK1q9Vg5WATB1dErbxOTmBen79SSKHAKGYDrKxgK+egO4t5JIRIN2q59fEP'
    '8Q//8vfwM7/w3/n8Nz3BH3vfO9k+O+FwOiclYevsJscfe5z24cfx1bNlpHat3dMSz0sgI9KD9bgNYAnnaGT3V0dnvI65uXSGnnBf'
    'gBga19G4AbpSIB0PgOG2LAVM10FPozrGMBQjZ0MkoqpgC8x3ML+G2WWE3drd9YhM8XyA+B4wR2SJ2wLPe1g+AB+Q0KBxA9dtNKyh'
    'NOVnYQ1wcj4AzeArOBOEPRhewRe3ynvwhR+DrBCkVPKmLePbyhhWu9L5rQhsBWQ94COD7DDJcEqJp4WVe4WxKo0lRhirKMdUGSnM'
    'UW6mzOW5s3to+MzLRTbw5DCVMuJeMbjhcCfBoRe4K3vB28zKxegCdF2BHaLUhtigBdkO6BhYODJRJAkDztYF+DNviPwfx5T7AQuB'
    '39s1fujn9vnZf3uJ/oU5ujWh2dgmvf049/2pyHvOGc/38Ou/4qR//TJxaxd5cow9sE04tY5MGlDBZgF/qUde2IU7+zD0aHBCjEin'
    '0CgeBR+3aFBicuYv7zJ89EXk6ouw8ywcvIwt99E4lBstjpFmDcuCT6+BLZC11xG230Oz9QC5v0O6/lFs/2lkeRPROcgSQg+aaHzJ'
    'cnYTZMIb3/Y5/PGv+Sq+4kvezanTY2DBdAoHd2D3lsntG0ndCd2oURdk6FPMg7emjBxvzTx4gdZaxdccNsDXYqQdkmmIga4RFoul'
    'DsMwUpUNFbbMfAMYqaJNGxCH5XxK6ofSsE8iTdAybqlDdmIUxAxXQd3JgOZMjKXqWE6G6qIR9sxs17E9FVkIWBlTBcvZgD6oHrjZ'
    'nmMHIvTifRaJuRs1fdfqQtz7ED1JmWmtAk8m4CIC2QhqZYQWUJwQHK2dkUQph7eAmxVsUY4adQNRRAQHRA2JEcFBHQ9SMM9QxuSC'
    'rVoZh+s473XS9yHjZKzpiMfOwfhezAS3QLsyZrj1Cj/5936Uf/tP/xUPrK/xZV/6bh68d5P9gynzRWL77Db3vvER9NR96LlHQNbL'
    'M+cJkYQzK9OCDbgtcesx7wkScBGgFMyCe5bPJpTR2FhieQZ5UWCmZoy2p6G5F2GljL2+X8bMsIrocWBcDvOjjlMgVLAiMwWukfPz'
    '4NcQZqj3uB8g7GDDTczmqDZ1lA6IRoQ5+B1ACM0qySdE2cDipBT0/grkQ+juwcNjBbNdfAQ/fBpJU4TPfwraMaxMyv+O2tLtdQFp'
    'wSeKrDmyKXgE38jIPYG4paxuZlbHTmNOB2xWUsNU6F24DezMjf1DyL0XrATwmeO7ApcTXMxwM5VRd5rLQRObUtjMSqcV6qk4aWCj'
    'KW+CgRXwXTqgcWQV1A13JavyhieUb31Nwx9aVdaTM4/wKy8bP/ITV3n/f7xI2jX01CZxa43lp5/k2NdMeOc9A/Np4lkTZrllqops'
    'gDWQe5BDkAOwPSNf3Ydn7iBX7xAWCdGARic0EZk0hI1VZHMFOT6hGQdsf+DO710nfWqXkCBwiOxehpuvYDtPM+y+hA9TkFVcT4Ct'
    'oJsPoeffhqQWu/Zh8s4HYXYRpCdoAk0YibYxfLhJ38956DWfydd89dfxZV/82Tzx+AlgkIO9QedTwv4+upiLWPIYQmgNRst5bhe9'
    'NZ5yZ87akH3DnTWU1kWiYyOBDZAtEdsARgTRdhQgw/xwpu65VWVNnA1X1ty9jSqqKjQKy35BHgZCDMRGUcmICyKO3e28nBAVszIW'
    'iIBaeVDMzbSMvQcCe6J+kLP1KmJHY2lFyRcIe1Fk18X3LOWFSk4ofRfbgxDYa1o5CCJLwYcQpBdY4N6bWRLwoGJulhU3LS0qUZ0y'
    '8pcOUHCkdoISQNCKz+aCi4ZYC2AB/0PQgocXlLPihaUrVK/PtBtuCXNDRRGJ2JDx4ITxGnQbeLeJM8bd6cYrYInf+k+/wE/8/X/K'
    'Sx//BO/7rE/jzY/dQ+5nDDlx/uHznHj4AnryJHriHLKyUTBKARiwvATP5H5B9jnmA6FpCHFUuisNmJXPWlif2jVTpkZPPe4LPA/l'
    '77THCc1Z0E3clyh7tXCNMN9EZbVAa/WfQjXV12YAbmH+PAwvAjuILBCmWN7HfEA8InELiccQmSB+iA3PQb6OeAIZg45Kx0soRRQw'
    '2Uaah0A2Eb8Mw4dhcRnhy14pI93mqGB/1NGjA+kynBDkpMOmoMec5oSwuQaj6IyzMclWWDuBcQjMVLiZjL1DZzYTzAIhG9pFbN+w'
    'HcOvGtzMcDXDrR4WDtkQUdzK14J6uSliBW+6ABsRxgLRwUCWCRqHzmCsaHDy4LCufNGnRb7j/obXNpHGMtfM+Zcf7vl3/2GHZz+6'
    'w3js6NoKfW7Jb5hw31dt8q1n4B7J/IcoPIVySOTGx43l+1/AX7yM39qFnR7fnZdxd+8WHOxAv1Pa9jzUiwgaAtJ1MFpDxhtIHGM5'
    'kQ53QVfR1dOElXXCyiqh3cZDgw372K2Xsb19mDyOnnwM746Rb76CvfBfYOfDiN2A2JduRA0HmphZzq7RbZzhj3/Dn+ZPf/3Xypte'
    'c4+CBcvLMD3UuJzRpqQjz9JqpElL6aYLW0vZN5azvDbv+1EamKSBjeS+JaIbqjJKniMFVFgD33B8TaANE9XRascwzUz3p6I+BC1H'
    '5kiCtFFDcDeJUWgElnnBsOxpNEA4Gh/LqEhOqAhtE2hiwFIqxUUVHRJZHDV3Vc0apMds4W69KFndvTyQRlAMl97xA5w9VQ4kWx+i'
    'JlUWguyFRnajsBdUZkFZiHKgQpmpRJYqMni2HvEF7r1iqYma3VOOKia4H7HHkAkqmDgqEcGQcHdOLkyKlIIhUg5I2lpEsMKOu1du'
    'Jd/FRN1BYyzKiRBxPWKUwUNbiYgO4gjXVWJoufPyi/zbH/5Rfub/+UmevPcUn/um+1kfCxubG9z3+L2EUYOMWpqNTXTjBBw7CaMR'
    '7gl3w9ywvCB7D0FpRmNC6EBLj1aIbqVW+zK+ex2TvWC7Ql/xwS1c1xEZgfd43gNJ4BEJ6+VWkq50hBgFYbUKK3iBcuwlcv4Y2Itl'
    'VA2T8t89ABHCBGcDIaByFU/Pw3BY+eIM/V7pqLuTaLcJjEBP4rJdulieg8XzCN8+Q9YbiFIuEHXcXAe5B+QBCCchrJbHYNwIJ5Jx'
    'CqNF2FdloXCAM+2Nw4WznCn5ECQrEgKyBG4k8sW+yFhc8TteyI1lhsWAuJYLnAvwRKvlV/Zy02x3MBJovUpNHHUjhIRGsBEMBNZP'
    'R/6P1wl/6rRyLjsuwosL4Qd/bcZP/9yMYX/gde9ZZ3J2wm//4kX03BoPftMxTmwGngR2X8n85lNTbvdKfzux/NkPwm/+DMw+haQB'
    'spablzqyakIax72HNEdYlBvC+1f/DM6RbkJoKf1yBcvbVbQ7Bqvn0Mk5tGkJKw8weuMfgkfu4fCDH2X45X8CB/8L5Q7ogAYrUo1o'
    '+LBg0WeefOvny3f/pf9Tv/gPviuOWm2g7/Zu++il5+ejNNfxfY+ur6+ss7F/y9Z2d4fR7VuLyWKeN0xla2XcbGiUyXyRRkPyNVfZ'
    'cGdN3FsXAkKwTCvKSKK0joTYiISViPUD8/1e0nJOkKwqEkIIGmOQRoVmpNjgzOYH5JQQL3h1UC2kiJdOX1RoVWkDuJQuUBHMcx3D'
    'jC4EF8XcPStu4o6KeDk1HXdzUc0q2uO2AO9jICtklVIYJcheEDkQZ6HKDLc9EdttouypMFPRBe4H5mlPYV9V51F9oeoL3JcCA5KT'
    'Fv7TpYo0QgyIamFQcUS1PtBScD+zUvgVJNRDIEqRk6F46slu4IrGiAQt3WGMiEbql4CnoXSRonho8bCBxA3adgLDkp/7l/+Cf/A3'
    'foBVFb7o7U/y+geOc+HMKu1qR5r3SNMxPnGc7v4H4PyFAilph2sAyaUjJKNKeV8N9VNoZb+5O+7DUWXUgifexQuldpmxtLYSEPNC'
    'ZkiRzohs4qyBQAQyVp+II9xxCXYJy+/H08fLNBC2QEZYXiIS8bCNage+h3IL8gxLPSJz8uIyfngL1Qm6tgVxBcJxaO4tGINfhf4i'
    'kRMNHhzJlLZ2BLIZkAeU8IjRbDhNKERtWmaGAVZaZUuVqwgvunMwhXSYyb1iWdGFoEnwueK3M3Yrw02DnVzq6wjYbArZclUK9+IF'
    'B2HUlpMmVJwvApMII4WJQwcyNzR4kRQEITlYq7zz8cg3PtjwuWuByZCQCJ+cw/f+wgH/+Zd20Njxh//EMR5+4wo//f/5MP3vXOKe'
    'L/9CxtMZv/2Dn+T9Vw7pL+3iNw+RNiH7+8RrH4bZ76G6hK5DXHEt4w1acAhLhdjQUYd7wFK9QOJlTLdUTkuhtP8DBcCVjPWHWP8S'
    'HHwMowENhPYcIRqRz4On/zsc/Boi19CQkJBRDQRPLKZzadbO6J/5pu+I3/bNX9c8+sB2B3myf2e+evOybd58edi8cXW+Ab5+uNtv'
    'hYlszee2YQOTxTyPDg5ma6EJG/2xtbXxuOlQbVStzc4IpzX3IFVIgqBoCMlRMxNaRRDyIJhDMmPIiRgczcqQmiKb6iFbJvvRTEvV'
    '5R0RH0WLko/IDpcyEgKpKl1QiKosc5LoIUSRYOplTFbKNTHDEdTFRcXqHW1DTgQNpiJZ0Z7si4T3bj6o2hLsIAh7McQDcxaIz3Df'
    'c9FdVHYR33fYw+UOInfM8qHgMxNZBgmDuSUVMXNcqx6wdH21FFT0RjSUh9sKBm6DYWQ8ZsI4ol1HECn3Da+yzWYGNhC0dF6iBUNk'
    'uSz4b9cjCvNpoh1N+KI//WcZbxzje//id/EjP/drfN1738gXrz/O8bDElgtstiRGRWNAgxIefBjatbsda4gZKIyvVwywHDBS5TtW'
    'ZSyvfsDCIEvV7qVKAxlu8/JHwjEIG0U6xILCgM4KUyyrmCYCSspeS6AgjBC9j6AtWRp8+DCWr6JxC41dIRJFawHuy9uHFaKskBmh'
    'o4Qv5vhiCr0hPgMWhTAN64W0zHtEgkHveFNQHs5H9EGlOQWxUzoFyOQB1JXVCEkiL2Jc6p3dXcf2HHpBxgF1xQ+BW+C3DW4Y7Cbo'
    'Bc8CfUYe7Gjf1jA8n7FeYUdguix6Q1EIAQmOay7Fb10KqRMdcSeOquzBnEWMbJ8M/MnHI1931nk4On0/oFF5JkX+1q/O+MWfuYH0'
    'xrv+5Ane9ukr/MK//Rgv/OCPIyvHOfjpVe588veY/95LxDxjnGdIFLJNId/C/RAPGfEGz+CS8aGOn6low1S8nPw5EchFM3Y03oUA'
    'ErEkmDmWUznJpS2npCY0rII7lnrwRF48zfS3fhD9xK9iy5vAdVSXhBCITZTUL3TWW3zt67+g+a7v+q7uj/zhd03GI1aHOZu3rvTH'
    'rl/NJ/p9TkSL2w88vLElsH7t6nRjb3fY6MbN2sZm242iNT5IO5vPRwfXD1u2JjE2QSy7ykRD0wVFVSw7g4NEIWXjYLEku7DVjojJ'
    '6OeZtMik5KUImSPqxOjM5rlgfXW8SZZpVKoeT5AQsPrwNLH0ATmX77Y0PFIYdZycCmFg7kUnXynqnKnfv5bhx7KYWVCRQJBCWIuQ'
    'szmCuaUMahrch0QKgR5hsVxa33UyuMvSvOCM2WxPVPZBdrPn2yrcBG4iYQe443AoIjNzW2I+mJNCiFZ4A6lESK3mR0y1CJasiqu1'
    'yIwWBsEITUuITe2jMqQCDkrttKwKxhFBohbyYr6Hp4yOz7GYN2hwPvtLv4LVzQl/7S/8Ff7xL/06BwdTvvLz3sCZE4H+YGB2cxcJ'
    'gW6twzbW0ZMrSFyrQvUy6pZrxt2DqhAXfSnmruXnwxGXu5/PPdXm0O8KmkUybru4gspa0ei5FecEc0S2UFpydoSIe9HsFcmNInIP'
    'IX42plvk/jfw/iahPQ7SYWaINCiO9TcIGrFwArcJIseRDSPrJfJsjk56JB7iy+tIY2Ukl0TkcIAtQe5TeFDRs9BOChEslrEMnRub'
    'QcrJIXBA4vZcmd0BmQoaBCaCzBW7CdzI2PUM+yDTjE9ru48AHeFkS3sC7FMBa4D1pkoB6gnTlBOUUYSxIpsgo4QucumoG2VISo7w'
    '+seUv/h4wxdNlI2cGHrDRLjp8I8/NPBffvwK8vFLbLzzAusy4hf+4e/xoR/7aeLBs2h+jum/+lXy/BAh07OgJxdsIkRiDIS4SdS2'
    'gNKhQbVFQ4RokDPeD1hakPMCzz2eF2Sbk/IMI9V2vpygQYW20SIITl7b/obsBX6IYUK2BWXAuk4++B+oOiEuRcQUQpxPD5tufKL7'
    'uq/8c5Pv+kt/ZvXxJ05uYhzbv9mfuPZyOrF3w06o6InVcXOia9garfq6i4ybsDY6PEyjfpHbaMSEy7hR9RyDICrJJeWeGBvEhCDK'
    'sMyklPEgpME4mC8YyKyvroLB/KAn54SRaZsGd8HygCrEGPGc61hXQH9VISVDmlBGwpyJbSjThdU/A1iVxsSg5aQHsgrqgmjpKIMG'
    'Ym2q3azqCqukyo3sTpBAjBERIeWFZPPgSIjqRXallYkwz6Zmyx5vgqYY6MEXeGlXDNtXfNfhpsBNkJuG31TkJrDjInfM/VAIs2xp'
    'CQyqMQli5T20dn7cnQTcHFVDmxYasOXAYtEjoq8SLSKEtrl7CCi10VIpOJg4YhnSPgw3abpyDXI23v65X8CP/MRpvvdbvp3/76//'
    'Gjf3d/mGL/x0zp85BsPA/M4euhIYbW3A5jE8jstr8vu7MCkuEQaEfLfbK8WvFPCicdQC+3CEf5ZRnkqciCVEbhVGV1YQQiXfdzC7'
    'XuU/jutJVM7g2hQJ2V389DghvBPttrD0ATxfQUKLqoF0uG2AQ1peJTSGxGNFBB5OoCuGcRm3VEgSn4MfFixTO4R/d4A8GNDzQlgL'
    'xRYk0CJ07kxcCu8QhYRyK2X2ZpAOHPda1AbFr4O/kvFrA+wZzBwOE8xT+VJCW276zmEzELcb8u2EL1t0NcJ0js1yEV07hdjYDLAh'
    'MAb1TMCQRunngdGJwBc9qXzH/cpr1JDkkJxksC/Cz78Cf+MfXebGz34A7ffo7jtJJzMOnv4A/f6ztVWfQkisrE9YXTnByuYWx08d'
    '4/SZezh971lOHNtkY3OV9cmYcSPEcUPXjGjbhhDKS+R5z3I65eBgwTCbszycspjO2N3f5fr1q7z08stcunaR/flV9g+vMZsf1Pcu'
    'I0gTW0Rbgowwgz7NydYjuIiiQS2CNSrWLZfLyf33v3X127/juze/+qv+wLGNzXhiOetP7F21E9dezCfmB/lEbMOxGMJm0+hqiDbJ'
    'ObcOMWUPy/kQZodJLbt4dIJHsggZwwZDYqBbaTBx+gSpz2gLRGXIGR1rGddcWfY9i9mijm3FRmaWKxMHKpEYMtl6LGdyzsRQdHIu'
    'TpByoJbJ2BHzghFWRRYKrchd5YBU3Fe0MLFiRaxcHGYJJKMuqByxyEWeEmO5n9wHcCWol6KqEMoYQWwKA63mNKru4oZ6FjwHkRRV'
    'eiHPVDnEuSNBdkQ4KoA3gZuC3xRjRwJ3nHSoGmeqLEV0ECHh2YrssNRDtyKnISgaFVMj9amwvpYRLVKRggeWiUhUCG2orhNKF5gz'
    'tpwXDePaCXTlPrK1uEMzGrFz+QX+1v/5V/i/f+onee99Z/gzf/DtPPbQadJ0gbYNK+dPsvaaJ4n3vx6LW1XknUtT40IQyNYTZCCT'
    'S3dmtbMVKcXaK+7J73PKVPfNES4okjArNkQPk+LyICG2h+cdkIToGPQErqcQ1jCvtaAWyNJIvExOH0C5CDLG5QQiHQyvYP3TiC/Q'
    'uIrHDYRY5EXpKvnwMhoSYXUdjxugXREMyKUZvhmIQZiIsIoQcEYixVIkytJhuTT2emc6d+wQ1KQApDfAX0xwMRVnyCLD0mCZYLGA'
    '1Fewt+IMUgS/NB262sKJFWRV8VsLfJnKjN4oMi6yFtacIllVQggkd86ecP7MGwNff1LYNvBsdFqMF7MsvLJQvv8/HPJTP/g/GF15'
    'itzfpJ/vVtuMs3lskzNnznHfQ/fy2GvOcP8jp7hw/hT3nF5ja2vE+qilGymThvLA3J1fjv4J/P//x4r9qRI6w9LY351x89our1y6'
    'znMvvcCnPvEpnvnEc1y58SK3b17h1p0dEsuqawq0MYiLB8vz1p2Re5io+lpKs803vP7zjv3QD/69E+9975Mnsg0n+kM7sXMxn7jy'
    'wnBsOfXNyTiuNl2cmFiH0ohYdEdTcpnPB3xwUsVzvEoQvBUs11M8FpgiWyKp0ExajMx00TNZb1jdHrEcEjs3Z/T9QBBD0VLIUgbP'
    'hFg1cOaopMoygnnG00BOhgQYdZEQI7iR+gGtYJlbJmpAFdQdiRBqoTsS5waVCrsbihAkI0c0k0v1THtlL72IjoFWm2Kv9IxUXBGB'
    'rlOCKI0UO5x5weeKDVZcwBolBWFwfIkyE5FDXO6osAN+U+BmQG6i3HTPN0VkB/xODOGgGLqL1Ka8uZR2DsMDaAwgerf3suoZ9iOs'
    'Da9+2gG3VAiXJqJNtd8NC/JsjnQNsnken5zHGGE50XUt870dfuivfg//4J/+U968vcE3ff5n8PqHjpPTgkUS1i/cw/E3vJHxE2/E'
    'RidLAZahiJ8VRBLYFNICiRGlwyTU7r5aEY8IEbP6HddO8EhQLdUjT19G4Dim0S0SWnBBm+LMywGqYyRs476NeUfh4SrgC7jfAH8K'
    'txfKwVgtd257SH4FT3dwaZGwgYY1nENseQnrLxVf+2QT4qQw79xecHISuD9IYWNcmCrsuzFPUurY0kj7Qp5Xh1wS2BW4rfByj18q'
    'UhZJ4Dnh8xmyHBBLhYwbjeD4WbwVOJwXZnfcIMcn6H0RRobvGH44FNB7omhraMiQDWsF9Y5E4MlHhe9+UnjfukMyshff8KVD+N2X'
    'M0vg1jzyr370o7zwk79EzjdgMnD2/AaPPHye1732Qd745D289jX3cP+FVVZXlUbqoGqZZEWGMCRIvWGpaNLMrAyyrkgVhlJ84gSV'
    '4ittpIxtUkcHK97KdtK+WiIT3Lkx5dIrN3nh+Zd48YUXefZTF+WpZ57Wpz7xO3Fv9mITQhqryHrKvq3aHc95dvKRh9964l/+8395'
    '4h3vevzEYjE/kZfh2O3n0+Yrz85XbclkMmk7DdqgHjWW2mFW5EKZAqYPmYKxHfHSoRY8nNAWMmPojYQz3hoRR5G9vRl9yqxtjiA6'
    '88WijLEmxKaMQQXTqgygAZJJg2F5Wf20AmRSdT0YdjdwQDyhKrVwFQGwJaPtQhHf5oyqF+InKEGqPa9q8rR2hM0RFOX+6lhGtdtR'
    'MMdGtbgXqoDZgbaLRIW2Kfe/qjD0PckNDUKU4idWoFF1UTGwJMggQZduNhPxQ5A7DbLjyk3MKlbIzaByQ4VbLuk25vuCzEV0QDwh'
    'bi7iLo40isRqTq5kkVv9TsUJIeKeSct5KUQ5oW2sFjzDhtJpEztk8xwyuZcsI3JvtKMOWx7yI9/zffz9f/DDvGZ1lT/5uW/hyQeP'
    'gQuDBkbHj3PvO9/I6NE3IZvn8BTwNENCHR2ZwmKfvHsNHwb05GkYH0c9lO76rkf31fvA68/uXvW6bsXSlhcYAxJGhGYbl/VaMBP4'
    'tIyoLBHZhHC24obgrmi144jPMHsWt2cR2QNZRWQVbIanK+C3ER1julVcJ7JHXr6ED9eRGNCu+phfczDw+SNlS5yPOnzEhWu9MZ1D'
    'v+ewqAwPAglkWtGQS8ClAfaWSA7QO8yW0M8LLoEX/6AN+LEtuO90cXDs18QYvOB7xyJsK94JGr2o35MjnghiNDmTl9C3gc9644i/'
    '9mTDW8n0gxUkohN+47rzz37xkN/+wB26oWd+Y5/rH3uWuLnDm954ks/8jAd496fdy+sfOcbJrZY2lAuVc2YYSnHIXnCh7MLhXLl+'
    '3dnfdSw7TVTaCriTIafCYm5sBo5vKmvr5aIMM2eYDUXqmp1+OTDMB7q1yPp2S7umNJPAaBQr3lLAgWGW2yuX90a/8p8/NPmZ//iz'
    'a//7d3/p2P7B5dMi43tV52dWJidO/ciP/IsTX/fH33dsNj/clBRX9y8y+dSHdrvpQWpWVkdxstqpBgTXwuq7UWsdGsohnA1SNqja'
    'cnMlDU42I6mTkxMnymitA1Hmi8S8HwgjJUjAJIMaTYhgQp8GhpTIOYNlgipuTkrLomUTryEFxUlBCMVjC6Q0sJjNMYfJuCEoWC5j'
    'tGopRFEUJ2G5FK0QI6pgNmDZaGKgbRsat2qnM9QDuToqqIVLj+z44jThiBRJSB3Do1I6wLb4f31ImCfQgsfF6tMNogiV2JHgImIq'
    'ORkyqMalODNRP8T8DrCjwk08X1eRq4Jd0mDXxMOOqB642wyVheO9Kzm0jXsonTlBarNTcMDc95g4zWSlfJhhiS1ndZysMIFnbHkI'
    'i8q8rpwgj8/A6AyDNaXQpzn/6vu/n7/3/T/EfeMVvvJz3sTrHj3JaDzBg6Kjjs3H7uPYG9+Gbl6ApsMz5L4nNE7IB0yf+iC7L36U'
    'zbe8m/F9b8Gyoyzxmm5TvK1WOmnLtSgeeb6p4vG+4OWk4ubQVUSPlU5OpIQq2G4puroK4QzYpJBiSJHVuBRbHhdx+wRut1AdQZgg'
    'PsWGSwgLXArBI5LwfBsfXikBI7FDVAlf9r1/nSdE+KTD/87Gy/vG4XUj33KYlXGJqcBCi1XtRYdPJbg4INOMDI4fDtAvkH4Blku7'
    'moq+m6aDyWpJk4n+ahxHNmRI+MzAFFYFWT9K3vCiQxIhz4RhDF/9joa/+xrldQFmqSR55A5+9arzj37+kP/6H1/k4Def585TrzDt'
    '5rzvK+7jW7797Xzr172BL/us8zx+bpX1iUBOZHOGnJn3MGTBCKCBjLI/i7zyknH1pcR8R8gGmhTrldw7w4LCbqqysRVZXQsMc2Hn'
    'RuLGxQV7NxbM94z5fiItHV8K1guz3YF+nlnsZ2YHvUj0GJswypbXmi5uBw33Hjt29v63vPUdjz7+5JufuHEzPXn9xuXX5nz4xFd9'
    '1Xc8/G3f9sfPqfanzfxYOpD1Sx8/nMTOu3ufWImxCzrMvISh5CIGT1YwrlCNskGEpi0PfBOVoMqQYciZlEpRnGw2bG6NkUY5mPbM'
    'p8WaJjXJJTQFC5wveoZlz2I50C9TKYKDkWsxfNUPGwqJ4sUXq6oMy8SwXCLqSIw0TdG4xagEKjangYBCBHUpN34oVrkyntbuyAWr'
    'pECgRK6Vmc0xd5TK0lfJtdSCUhjYwlrrUbeVi6TKUkZjAeDNqLFZ1bFSXXMmioqI1E+BSOPmnYiO3XzV8U1Hjrn7SVE5Icg2Ylsi'
    '4ZgG3ZQSpTISRCWISJFVORJctIZsOOU5MfBhIKUMsSGOJ8Va1zRIbImjlRJXR0ll8TSH+T42u4rNbqLSE9oOcyeMRrzpM97BsXHg'
    'v//33+DZizfomo4T25usrYzIi8zi9nXytZeJeZcYlxAVmjEiE7TZKCTUzk3GZ+6l2bwfq527aPh9kplCSL36/+tRX3AMJMSCe4em'
    'TgQLVJc1cmyMMwJZLbIam4L3CGMCEa2y6YJPtARdR2WlWvSmtQMFYYA8q1FYi5IUQ0Y0FXE2GVQJw1/9bj7izm8s4PKukXdBhyI3'
    'YSnIgcAVgWcHeK6HS8uSzLLMkDJyOCs4X0pV81Z9fjZCujE+CsVfbCWpBQyWpUAWssuKL3KkRSSrToxlpFnOlXZN+NbPbPnexyL3'
    'mtMbdCPlUlL+zUcTP/rze/zez75M+ujTcKrnXV97H3/1L72Ov/BlD/K5D65zciT0s4H5sqSfDCYMWViaMk/KYAEnkly4tS+89Lxx'
    '6+IAA0wmyvo4MG6EJpafS8RZXQscPx1pg7OYw80rc25eXzLdm5dMuig0wYlB6dpI22oZ8xDp5x5xH61tdWth3GxH1XNXntl9+Nd+'
    '5bknn3321msmk+7JEyfPPvGJZ64/+qlP/a8Hzp9789nv/Z6/uv3IY8fX5wfLiVrsbj6/jMuZ6UNv3ZTTj6wwmQgHNzPzw4KXZiC0'
    'ehc3i02oIv7yc1iGxTKz7DNDSqTkTNYajp8Zk0y4fnvOfJ4RK/q+nA03Ydn3zGYLhkViGBKuQvDK1oniSJUmlBC4lHPRwmIMQ3md'
    'WAMCDKftOpom3LXDlYiqUng0CNpWMXC1XxFDsRlWCU2xiWeSZSQowQuemd0xPQpXkVd/TxXbS3lItGYLqgghVPF1KBCHe+0Gq+7+'
    'aIwuIH9hdVWlYr6IuCg2RFFp3OkEGQOrgm2E4FsSwnYI4YSonhCV4yK6KTBxl0ZDEA1BaiyXI+7iUvG1IgXSrkGbBpfKrooiscU1'
    'FpZYC1klow4Zj2EUS8yUT1HJxMmEvje0GfO6t7+Tk1ur/Np/+3U+8eJVVkLL8c111tdG5MXA9NpNFtcuobev08SMHi86PmeMrh5j'
    'vLmKjjsygvgMYVmJvQqFVOzy1QxFq/JIuQtTuEsZaUNTpT5DCWaQTCgy1KLGkFHRzJoXZ4k01Vp4hANHVFYxNuv1mUE6KCYEWVbd'
    'YcUzPZX3IBU80p34e1OHwZGlE+aOWSiG6TuCX3bkRoZbGdnr8dkAGguFvJjCsuSElQzQDE2LrI4Jx0bEsyvkmWCXDsoX0veVHJCq'
    '/I+lUxjVaKl50R/puhN6Z7pccs89yl99c8PXn1ZG2RlQmg7+92Xjn/zyIf/1f+5w54NXYPca933OMb7hTz/BH3n7GR5bbSAl5tMl'
    'g4CJkEJgMBhM6BdlHDSh4EJmTA+My68Y01uJCKxuKOORli++oXS24qytxWpVTuztDBweGrnPSM6MYqBtoGupbpB8ZN+RpiFolDYE'
    'Jmsbcb0dx5MBzt55YefCJ97/8rlbV/vzB4t8+sb1Tx372PMvrn3gA78xwbvRl3zpH2vf8ukPheV0EKUlTZ3pjjM7zNy52jO707N7'
    'rWe6D3goeHMoun0/suSpsBwS/cKw7KTsZKujr5XeqB+Ea9fmzJYDB3MDj2VsjUZKwjAsC8kjBY/DA569RLHEgOZcxqEmlLQPN1BI'
    'gxOkRFxlF0ajNUajwHS2z3w6L0LoGrWn4gzmiCtDTuigtK2goZBOKRs5GSGWz9WNAjkNDMPAnIEkWqUzhYjK2UoXWUmfYiPJBPRu'
    'tJWECm04xLa4dXIC00KkNIQCKQhoUDxrwbRUSZm75E3xB4daJj0gElSlFWekyIqqbonKWcQPQHZQvxZcX3G3i5byy1i+YuI3RHRf'
    'YObqvSAZFZeuoalEST4SIFth00UKpipBkLiCho0anptgmEEeyKZYOkTpWMznNN0KX/znvoWV1RX+7v/1N/j3v/E72ADvedtDbB/r'
    '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'
    'lb8+ONqDE8rlE8qjr+Nut+TFEf/0n/pT/K2/8zP8+Bdf5yBCS2AtZnQVMXlOKsKqFFZjYdEqxakh05xe8zUEEWZeCSCq6tdjDiWn'
    'oKgvijhnfMSgoTV/pXeCJO/y2LoxzvqHZ+3je2sv3svs0HF+0fPOg4H3Hvc8ubcirdcMJTNER68Ngw9k19RtEKxTtFCgJpBKIieH'
    'nwkle/rJzO4FzZ4ojlSE3Djmh7d4xd+mF6FfP2L96GtoutoEi3/ilWP+9R/7IRaLzC/+5f8vv/zjP87MN7zUdnzTa0fc2etou469'
    'xQlFPfdOl7z55IKzi0ifYSy2Zcq6CxKQTTj5pOkac2Kde1IZ6xzObcPNJ62gXK/MUNvOTW4F2fUP73ADrhFVhBusKbkWICy7M0O9'
    '6cB4ugp91qEqPGMRIztVqN6IaNIdBqBeszlvt8MbbfV2Brkh5UyB8RM0VmpgT0loHqBcmf1t5/0XPwM3Q5OJYp1z+GZORrkQWO3d'
    'Id95ntXhnHW84jAlDoPHDSMpDXW5UP3GxbzB3utOpaxbuCtQJCPqbQmiajbX3bAq1Q1bMJFt4ysmvvY5WevlXd1MQ5xQ8kWJpjep'
    'M1GTyJTKq8uqBPE2OtHtRt/LJB0yB9CmvRXLyXaTH1y2FJ+SjUNoLb5sq8+pcq8JfTkXRudoaktpYmkhBEeKtsQJwW2cRdPMNNd8'
    '5jbsgDOqVU7r5lscSLbDOKVU9YYGzJXsoW2MVlMKTes2DUJ7cowODeXiFHeyZlwF7nz79/BH/rk/xC/8e/8hlzGx5ys8ovFIsefe'
    'hECfIg8vRz78XMedznF2GRmKw3mtEHKtxGdhVJXcD160tOqYOXUtDp9yEaeioZDwpcf3a5fXV21/sTw4vX969M7dq4PTy9BGWlck'
    'cT5GTh9c8eTxSFx7SuoqOso+zGEsxBIp6hnSSEw9nbfyWGk3hA4VoHiyCFlsoxaLWd2SwqiWDXwV11yevUlZ3ce7jTWRP/B7vpvf'
    '+gPfC+NIenCPdrni4we3+C0feo5XjhtmezOk2+PdR0veuPeQrz8643xMpGxMOGMB687czUph5wypGEthnUZSHsga6yfs4MbFvxHB'
    'PjVH2y4OdDfa111TLO/M4WSnKNtFW+200nr9uJMbmuj38wjLM30auhO8tDODlOmi2Q07312K1Nb9qbhiuS6V2alUZcetInizbE4p'
    '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'
    '9V/9mrEmlstjimWKzBAdAgGWOrqcYXXJ1afP6A6O2Dt+0EK0Enk+N8/d6FUu6PIZqbtQ8dHNLe8dLBhPL+rFxWa9VDk73JudjON0'
    'Zm5r3GrnOVk23ArTFP+UbXZtm/mB06ngntkQb358TCXhTF6bLiqOhskqZlPMCZv+R92CdmEWmzZuiLtbm5gV8JYults7KjnhmzWb'
    '06fceePbnF485Pnz5xweHXDntR+xPv+QOp4iCEXgV8+vuDckXjvoeP96zeW2OtlWOF9ZcbyMymcXyP1yStJNvq/w8nrjZb/sVyPR'
    'X2VW+S3zvN+SumwPP73xYtxO7nR5yUCyO3zlpbinG3G02G47e/ug26XaiTadoNy4JHah5x3Q39BmrCJ1xLv295XVrQWIRoSjO5L3'
    'oTvARPEamrgRZT0568kpFSaUjSRMYxuZJQWZT9tcuQEx4+cNo67vjIth3TJpPtrW5ll7bxVlEiN5iL+rOdIH7r1sCsVGhllg6Guz'
    'F6smVLZtKmjqI/HDM5od6gZRjyVfL0zFUenQlJHiWNLwO4tGNVOhijZys97MBJnFVjullhqguCRGUca54g865j/I7H/PGRKcvG+8'
    'eE9IH428ZmuO0orB17BeUX1N8jG6qxyVfcqyy+Fxv4mjLO7kNg8OjqrT5S3uqqXrObGddWHcxLKi7zqy9phYi/h0pimkbpvizJOA'
    'Zlwjn/jifMOwWGK14tX4zvffjTOiVrzUcNnkitUptruipDygeZ/f/fw9fv7L39OlY7rZIdVnpP6AyUJ/2c06JPeU65HV5Ug+WoYi'
    'wQtVKjr0FZE17meCnIj2Z2FRKjWrOb2qUesoSS/Wm/FssxkvRH304I8HSLG3NstTxnEMiCRC9sgqKMWoZYpglgakiwJDd4N0kUih'
    'smlsF7OQmoBWVUgxfggXQasMa3VSavmiUiNku1nwxAXF6DtlvDqhrq949Phtzi/OWF9vmB2/wfzoLS6/OA0rqQvnpfLR6YofPDrg'
    'W6vCz06vcKHdOl/HQ73d9t7w724Wsv41nJivQ7nI11vWXup8b/2t8tJQ7mVy81f4U7dwXbeF269+mPmNydjZ4ZZ8GyoTXPfdEmYX'
    '7L6jRW+tVSFyjRS1CL9CVpBGnBU+nYCtW8u8ldQk8nCE5H2sKCRFhiWWZlxcnHN+eglEpoRIFxpQlEJg22ujjtj251chk3ZjiB2u'
    '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'
    '0qRFLDW6JXQrdOc6/ZVXkOVBw+YfU08fYKcP8ekEmY/AN4hMEZvzPvR9FbIOUKw1PhK9KqSQO8zbIdlqONUxm19UAxiFxe6S3/jp'
    'h/wTP/ca/9y3vsJvPLjPu1bISTnaPOf05Gl956VrFz7wqBb/0Mfyfl+3nx5eOXi+9+13pvzaTZ8/eMj9H9/j+VjZTz1usOgTi6FD'
    'tzOb7UTXJ1IK2SSlyM66hCYoXUuyLSANC/Jf+bf/3/zP/1f/Muurn0MvTpE6Y+sRn0vkdZG42o9gz9dMmw2yM/Dam1dYffqUx49P'
    'GXYP2FsNfHq6DbNyLC+qi1+o8Mi8fDCIXMuZa/MseyTvs7FaGnpl5Szdyds1V5fnDG89o/+TC/zn3sBvHuJlB/3tCy7+2w2PPr3G'
    '03nFpsvMWZhnaXTkVj/Z4mtVEtOlwGtKFYlx2HI8KyjVKuWyNCmiBJTaId0KkyUlJXwwzHts2MGsw4dXYPFl0BX5+uvUZeKkzoxV'
    'KChztKFEqL9vhuZrkN5K6FuK3wY9oHHZYDtXUnFeVfjlHn5ZoofoGOd9hXUa8FL5L9bO5PA9V35UnK0JXYWlRALGjxLbxzA/nSn3'
    'Dbs3w8kMkyG1Q0lIn0iLSGUklFQCJcUIWgypE15K6DmtzJ1pxuY1JA9m3VzQZLjMQOQtczHQEj49VwTDfPofhIIDqa+pkDBEapBR'
    'xOka0adaHKiqP2sEFHFsDgiFSkJ9G2Wolhr5RChEy1dBSKnimsg1fn+/jFf2O3SrHRxjzFvYBHTXU4jl8a6XFqXziCRWwfsV9fo+'
    '9uoC/3KGLztyvcEYBDiXSOv8GOp/9Bj/6VNE9qDL1GdHSFfh1qvkGwchzJdWkpR6dBDSHE6LXow0j/j5Q7bb+2yP77E9usd88oQy'
    'PYPyHOomNuKLFC2J0g54s8B2NdpS8Sj2whMuA6QD0s7LyM4NdLmLSULCHUxZP2E+uYeffgrzEZRNvBhSHGAqC9Sis4+qrV6i9WNb'
    'fM6rzcBMsigbyzmjKexP1nqAnBo4Sje0W/Du8TH/0d//Xf7Xf+FP8s+8+QoffHCHKS85LRv79OG97S+99dbRwSrfKUnfm07SB0vy'
    'o8XOzoUuV3V75z4ffvfHfHT/hGFnNzB1c2W50yNz2KiyKotOY7pobgnKTF705IWG7pyVlIVSRvL/61//N/jWN7/Fl3/5TzFuj5Hy'
    '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'
    'eSf9AXJ8ulPdk3PNePJ8vZXOy868ko1Fo3U3YnKScSfYorKp4JKFrpWHwqq/OIfliXJyP9LegXS/R5/0hCdKs1DqSgguGM8snH0o'
    'B4O+G2jYuqSuI8l50uCVdcdofAC0TKqnbNDTpFPq7ojptMa5rpjzV1TOEfC41OFCz7JdGCQAIWqpLlzG5QEamQsBWelVC3ZISpXg'
    'S+5uJLvBwqdc2m04vz3h8HjOvFtYW1LaFkuQyyUSyhZHSezPMR1dac9wJSSnzAHVlSjLEmBPGmTRZ23XegtZ/jkNrD4tToxsM61s'
    'BBj1VlcNBacMLvxBQlN8pCKxLIGKxq+L5CJQFoRAKNUb6zkXxGF1WfKEKfgrLalwDicBsj2sKsleI1XE2/8HyXjXr4kz4Kydc0Il'
    'DVqqQcXhKqvgal2ylRfw+JTjD78F8QmuNjE42p/NRtcTzrO1kRtYe2W5s+EmjPyUmXas8oI0VISDHnDYBpPWh9r6/SnVYl6jxM4Y'
    'imuReJnpFhKUHVDi7E4aBM+ieMkEUSpv7aTmVAjfpUtAaLxfx5IGZwTrWtRIPGWWHLxjWoWcel0txR0E4ZYXfTeq3kzIvUrkOGft'
    'vUdHladpBFd53rnf8tVfuMs/cvUy25+q+eDunF/7tRPmqecHbkx59caU1EAv5WJpXOk+wdVieS616UdzNwedo1cu4F75PPWNT5Pm'
    'HYv/5q/z5D//m8hbC7a2IcjmjqGK6iXMFqSjpxCWiCohBNQFGO+x8ekbvMArfPCr+/zi/3CPP/nKC7z4o3ukGEnRMnAlZtJhS3x8'
    'ihyD35wgI9M6qQo6bsy4vhnQ4NCqVBq9p1q5PKl8e27LHZ5uyp1+ylYcsdsl3Vr02nS9+lHtmibgaoSpWtBP1yn9CcweZ7o7mcWH'
    'keVhJB556nnApUgVMhMNjCpBqpIClhNdZy1iFWw+kGKkSpYV3PUr6rwge08XxSQt2qE6B5Zs6ZxGl4zzjCYdUKUtHJE+tnhvcwn6'
    'jso3JDK+n9HlbOHPTsjO5k5JTJEvGaJGsmQLcy8SEBG71e1sshliSplzuxM+/fp1ZkdHfHj3KbFLhOCtAsiO7Ir8I6XiBS2e2yLp'
    'sHmZrA3yg9zBOG7DzG9Yfugzx1/ZaObSlqkl+emQs6vJ5nRZi74iGiyhPMQupzLwd+WwyevWy4R3JtRFrWXXJGVA722OmJWqvHYk'
    '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'
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


def hermite(a, b, va, vb, t, span_seconds):
    """Interpolate positions using snapshot velocities (velocities are per 60-Hz frame)."""
    t = clamp(t, 0.0, 1.0)
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    duration = max(0.0, span_seconds) * 60.0
    value = h00 * a + h10 * duration * va + h01 * b + h11 * duration * vb
    # Guard against brief network corrections causing the cubic curve to overshoot.
    margin = max(5.0, abs(b - a) * 0.12)
    return clamp(value, min(a, b) - margin, max(a, b) + margin)


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
        self.last_music_track = "menu"
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
                "bpm": 132.0,
                # Bright major-key stadium progression with a rising hook.
                "chords": [(55, 59, 62), (50, 54, 57), (52, 55, 59), (48, 55, 60)],
                "melody": [(74, 79, 81, 83), (81, 79, 76, 74),
                           (79, 83, 86, 83), (76, 79, 84, 86)],
                "energy": 0.96,
            },
            "match": {
                "bpm": 158.0,
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
                if beat_in_bar in (1, 3) and beat_phase < 0.085:
                    s_env = math.exp(-beat_phase * 62.0)
                    snap = (math.sin(tau * 1703.0 * t) + 0.68 * math.sin(tau * 2513.0 * t)
                            + 0.42 * math.sin(tau * 3691.0 * t))
                    clap = math.sin(tau * 225.0 * t) + 0.45 * math.sin(tau * 510.0 * t)
                    snare_gain = 1.0 if style == "match" else 0.68
                    snare = (snap * 0.035 + clap * 0.045) * s_env * snare_gain

                # Bright hi-hat on every eighth note adds movement without becoming harsh.
                hat = 0.0
                eighth_phase = (beat * 2.0) % 1.0
                if eighth_phase < 0.045:
                    h_env = math.exp(-eighth_phase * 105.0)
                    metal = (math.sin(tau * 5231.0 * t) + 0.65 * math.sin(tau * 6817.0 * t)
                             + 0.40 * math.sin(tau * 8123.0 * t))
                    hat = metal * h_env * (0.012 if style == "match" else 0.006)

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
                chant_beats = (0, 2)
                if beat_in_bar in chant_beats and beat_phase < 0.47:
                    c_env = min(1.0, beat_phase * 13.0) * math.exp(-beat_phase * 1.25)
                    chant_note = chord[1] + 12
                    f = hz(chant_note)
                    choir = (math.sin(tau * f * t) + 0.56 * math.sin(tau * f * 2.01 * t)
                             + 0.30 * math.sin(tau * f * 3.02 * t)
                             + 0.16 * math.sin(tau * hz(chant_note + 7) * t))
                    chant = choir * c_env * (0.045 if style == "match" else 0.038)

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
        if track in self.music_tracks:
            self.last_music_track = track
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
        if self.music_channel is not None:
            if not self.music_enabled:
                self.music_channel.stop()
                self.current_music = None
            else:
                # Restart immediately after an in-game/settings tap, rather than
                # waiting for the next screen transition.
                self.current_music = None
                self.set_music(self.last_music_track or "menu")

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
  """Browser WebSocket adapter using a safe JS queue so Pygbag never freezes."""

  def __init__(self):
    self.role = None
    self.inbox = []
    self.ready = False
    self.room_code = ""
    self.err = ""
    self.active = False

  def open(self, role):
    self.close()
    self.role = role
    self.inbox.clear()
    self.ready = False
    self.room_code = ""
    self.err = ""
    self.active = True

    js_setup = f"""
        (function() {{
            if (window._hs_ws) {{
                try {{ window._hs_ws.close(); }} catch(e) {{}}
            }}
            window._hs_q = [];
            window._hs_ready = false;
            window._hs_err = "";
            var ws = new WebSocket({json.dumps(RELAY_URL)});
            window._hs_ws = ws;
            ws.onopen = function() {{
                window._hs_ready = true;
                if ({json.dumps(role)} === "host") {{
                    ws.send(JSON.stringify({{"relay": "create"}}));
                }}
            }};
            ws.onmessage = function(evt) {{
                window._hs_q.push(String(evt.data));
            }};
            ws.onerror = function() {{
                window._hs_err = "Could not connect to relay server (waking up? Try again)";
            }};
            ws.onclose = function() {{
                window._hs_ready = false;
            }};
        }})();
        """
    platform.window.eval(js_setup)

  def close(self):
    if self.active:
      try:
        platform.window.eval(
            "if (window._hs_ws) { try { window._hs_ws.close(); } catch(e) {}"
            " window._hs_ws = null; }"
        )
      except Exception:
        pass
    self.active = False
    self.role = None
    self.ready = False

  def _send_raw(self, text):
    if not self.active:
      return
    try:
      platform.window.eval(
          "if (window._hs_ws && window._hs_ws.readyState === 1) {"
          f" window._hs_ws.send({json.dumps(text)}); }}"
      )
    except Exception:
      pass

  def send(self, msg, addr=None):
    if not self.active or not self.ready:
      return
    msg["g"] = MAGIC
    msg["v"] = PROTO
    self._send_raw(json.dumps(msg, separators=(",", ":")))

  def join_room(self, code):
    if self.active and self.ready:
      self._send_raw(
          json.dumps({"relay": "join", "code": code.upper().strip()})
      )

  def broadcast(self, msg):
    pass

  def poll(self):
    if not self.active:
      return []
    try:
      self.ready = bool(platform.window.eval("Boolean(window._hs_ready)"))
      err = str(platform.window.eval("String(window._hs_err || '')"))
      if err:
        self.err = err
        platform.window.eval("window._hs_err = '';")
      raw_list = str(
          platform.window.eval(
              "(function(){ var q = window._hs_q || []; window._hs_q = [];"
              " return JSON.stringify(q); })()"
          )
      )
      items = json.loads(raw_list)
      for raw in items:
        msg = json.loads(raw)
        if msg.get("relay") == "created":
          self.room_code = msg.get("code", "")
        elif msg.get("relay") == "error":
          self.err = msg.get("msg", "Room not found or full")
        elif msg.get("g") == MAGIC:
          self.inbox.append((msg, ("relay", 0)))
    except Exception:
      pass
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
            int(p.boost_t), int(p.mega_t), int(p.frozen_t),
            int(getattr(p, "special_armed", False)),
            int(getattr(p, "special_kind", "curve") == "chip"),
            r1(getattr(p, "special_cooldown", 0.0))]


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
        # Two alternating signature moves: a bending CURVE shot and a lifted CHIP.
        self.special_armed = False
        self.special_kind = "curve"
        self.special_cooldown = 0.0
        self.shot_special = None

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
        self.special_cooldown = max(0.0, self.special_cooldown - dt)
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
        self.curve = 0.0
        self.curve_t = 0.0
        self.lift = 0.0
        self.lift_v = 0.0

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
            self.curve = self.curve_t = self.lift = self.lift_v = 0.0
            self.trail.clear()
            return

        # Signature-shot physics. Curve gently bends the flight; chip adds a
        # short arc that visually clears a keeper without changing pitch geometry.
        speed_for_curve = math.hypot(self.vx, self.vy)
        if self.curve_t > 0.0 and speed_for_curve > 2.5:
            nx, ny = -self.vy / speed_for_curve, self.vx / speed_for_curve
            bend = self.curve * 0.075 * dt
            self.vx += nx * bend
            self.vy += ny * bend
            self.curve_t = max(0.0, self.curve_t - dt)
            self.curve *= 0.986 ** dt
        if self.lift > 0.0 or self.lift_v > 0.0:
            self.lift = max(0.0, self.lift + self.lift_v * dt)
            self.lift_v -= 0.20 * dt
            if self.lift <= 0.0:
                self.lift_v = 0.0

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

    def shoot(self, player, particles, charge=0.0, special=None):
        """Returns True if a kick actually happened; special may be curve or chip."""
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

        # Clear any previous shot effect before applying the selected move.
        self.curve = 0.0
        self.curve_t = 0.0
        self.lift = 0.0
        self.lift_v = 0.0
        if special == "curve":
            # The curve direction follows facing and player side for readable arcs.
            turn = -1.0 if player.is_p2 else 1.0
            self.curve = clamp((-player.facing_y * 0.75 + turn * 0.45), -1.0, 1.0) * 2.2
            self.curve_t = 42.0
        elif special == "chip":
            self.lift_v = 3.8

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
        if (player.tackle_timer > 0 and self.owner and self.owner is not player
                and self.owner.is_p2 != player.is_p2 and dist < tackle_range):
            self.give_to(player)
            self.possession_lock = 10.0
            return "steal"

        # Teammates can support and receive passes without stealing possession.
        if self.owner and self.owner.is_p2 == player.is_p2:
            return None

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
        draw_ball(surface, self.x, self.y - self.lift, self.radius, self.rotation,
                  ground_y=self.y)


class Goalkeeper:
    """A sliding goal-line bar. The host simulates saves; clients interpolate its state."""
    def __init__(self, side):
        self.side = int(side)  # 1 protects the left/blue goal; 2 protects right/red.
        self.x = FIELD_LEFT + 8 if self.side == 1 else FIELD_RIGHT - 8
        self.y = float(FIELD_CY)
        self.vy = 0.0
        self.target_y = float(FIELD_CY)
        self.reaction_timer = random.uniform(7.0, 13.0)
        self.dive_timer = 0.0
        self.dive_dir = 0.0
        self.save_flash = 0.0
        self.animation = random.random() * 8.0
        self.color = BLUE if self.side == 1 else RED
        self.light = BLUE_LIGHT if self.side == 1 else RED_LIGHT
        self.bar_half = 36.0

    def update(self, ball, dt):
        dt = max(0.0, float(dt))
        self.animation += (0.10 + abs(self.vy) * 0.018) * dt
        self.dive_timer = max(0.0, self.dive_timer - dt)
        self.save_flash = max(0.0, self.save_flash - dt)
        self.reaction_timer -= dt

        incoming = ball.vx < -0.8 if self.side == 1 else ball.vx > 0.8
        distance_x = abs(ball.x - self.x)

        # Reassess the shot every few frames. The line deliberately reacts late and
        # predicts only a little so that ordinary players can still score.
        if self.reaction_timer <= 0.0:
            self.reaction_timer = random.uniform(7.0, 13.0)
            if incoming and distance_x < 560:
                lead = min(1.15, distance_x / max(80.0, abs(ball.vx)) * 0.16)
                self.target_y = ball.y + ball.vy * lead + random.uniform(-8.0, 8.0)
            elif distance_x < 180:
                self.target_y = lerp(FIELD_CY, ball.y, 0.18)
            else:
                self.target_y = lerp(self.target_y, FIELD_CY, 0.24)
            self.target_y = clamp(self.target_y, GOAL_TOP + self.bar_half,
                                  GOAL_BOTTOM - self.bar_half)

        error = self.target_y - self.y
        # A clear speed limit keeps the keeper from snapping perfectly to every shot.
        desired_vy = clamp(error * 0.075, -2.65, 2.65)
        self.vy = lerp(self.vy, desired_vy, ease(0.17, dt))
        self.y += self.vy * dt
        self.y = clamp(self.y, GOAL_TOP + self.bar_half, GOAL_BOTTOM - self.bar_half)

        if (incoming and distance_x < 145 and abs(ball.y - self.y) < 45
                and self.dive_timer <= 0.0 and random.random() < 0.10 * dt):
            self.dive_dir = -1.0 if ball.y < self.y else 1.0
            self.dive_timer = 8.0

    def try_save(self, ball):
        incoming = ball.vx < -0.2 if self.side == 1 else ball.vx > 0.2
        if ball.owner is not None or ball.lift > 30.0 or not incoming:
            return False

        dx = ball.x - self.x
        dy = ball.y - self.y
        # The keeper is a vertical segment on the goal line, not a full-sized player.
        half_length = self.bar_half + (8.0 if self.dive_timer > 0.0 else 0.0)
        if abs(dx) > 18.0 + ball.radius * 0.45:
            return False
        if abs(dy) > half_length + ball.radius * 0.45:
            return False

        # Deflect the shot back into play; impact position determines its rebound angle.
        if self.side == 1:
            ball.x = self.x + 24
            ball.vx = max(6.4, abs(ball.vx) * 0.74)
        else:
            ball.x = self.x - 24
            ball.vx = -max(6.4, abs(ball.vx) * 0.74)
        ball.vy = clamp(ball.vy * 0.40 + dy * 0.11 + self.vy * 0.70, -10.5, 10.5)
        ball.possession_lock = max(ball.possession_lock, 10.0)
        ball.curve = ball.curve_t = ball.lift = ball.lift_v = 0.0
        self.dive_dir = -1.0 if dy < 0 else 1.0
        self.dive_timer = 16.0
        self.save_flash = 12.0
        return True

    def draw(self, surface):
        pulse = 0.5 + 0.5 * math.sin(self.animation * 2.0)
        dive = 1.0 - self.dive_timer / 16.0 if self.dive_timer > 0.0 else 0.0
        half_length = int(self.bar_half + dive * 8.0)
        cx = int(self.x + self.dive_dir * dive * 2.0)
        cy = int(self.y)
        top, bottom = cy - half_length, cy + half_length

        # Soft glow behind a compact neon bar.
        glow = pygame.Surface((54, half_length * 2 + 30), pygame.SRCALPHA)
        glow_alpha = int(34 + pulse * 24 + (75 if self.save_flash > 0 else 0))
        pygame.draw.rect(glow, (*self.light, glow_alpha),
                         (18, 10, 18, half_length * 2 + 10), border_radius=9)
        surface.blit(glow, (cx - 27, top - 15))

        pygame.draw.line(surface, (5, 11, 20), (cx, top), (cx, bottom), 17)
        pygame.draw.line(surface, self.color, (cx, top), (cx, bottom), 11)
        core = WHITE if self.save_flash > 0 else self.light
        pygame.draw.line(surface, core, (cx, top + 5), (cx, bottom - 5), 4)
        cap = WHITE if self.save_flash > 0 else self.light
        pygame.draw.circle(surface, cap, (cx, top), 6)
        pygame.draw.circle(surface, cap, (cx, bottom), 6)

        if self.save_flash > 0:
            pygame.draw.circle(surface, WHITE, (cx, cy), 9, 2)


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
        # Hybrid squads use two human online players and let AI fill the two open slots.
        # The current relay connection supports one host plus one remote guest.
        self.squad_mode = False
        self.host_team = 0       # 0 = blue, 1 = red
        self.guest_team = 1
        self.team_change_pending = False
        self.host_slot = 0
        self.guest_slot = 1
        self.local_slot = 0
        self.slot_names = ["HOST", "GUEST", "AI TEAMMATE", "AI TEAMMATE"]
        self.slot_is_human = [True, True, False, False]
        self.lobby_blue_rect = pygame.Rect(110, 245, 520, 170)
        self.lobby_red_rect = pygame.Rect(770, 245, 520, 170)
        self.lobby_start_rect = pygame.Rect(W // 2 - 170, 505, 340, 54)
        self.lobby_ready_rect = pygame.Rect(W // 2 - 170, 505, 340, 54)
        self.back_button_rect = pygame.Rect(18, 16, 48, 48)
        # Dedicated in-match back arrow; kept separate from menu navigation.
        self.game_back_rect = pygame.Rect(18, 16, 48, 48)
        self.menu_selection = 0
        menu_w = min(650, W - 150)
        menu_h = 64
        menu_x = (W - menu_w) // 2
        self.menu_rects = [pygame.Rect(menu_x, 205 + i * 70, menu_w, menu_h) for i in range(5)]
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
        self.menu_backdrop = self.build_menu_backdrop()
        self.menu_ball_sprite = self.build_menu_ball()

        self.bot_state = {"think": 0.0, "tx": W * 0.7, "ty": FIELD_CY, "lull": 0.0}

        self.running = True
        self.touch_held = set()
        self.touch_pointer_map = {}
        self.joystick_values = {"p1": (0.0, 0.0), "p2": (0.0, 0.0)}
        self.touch_controls_enabled = self.detect_touch_device()
        self.right_hand_control = False  # False: stick left / actions right; True: stick right / actions left
        self.game_settings_open = False
        self.name_editing = False
        self.name_edit_value = ""
        self.game_settings_button = pygame.Rect(W - 64, 14, 46, 46)
        self.game_settings_panel = pygame.Rect(W // 2 - 230, H // 2 - 150, 460, 300)
        self.game_settings_right_rect = pygame.Rect(W // 2 - 180, H // 2 - 62, 360, 58)
        self.game_settings_name_rect = pygame.Rect(W // 2 - 180, H // 2 + 12, 360, 58)
        self.game_settings_close_rect = pygame.Rect(W // 2 - 95, H // 2 + 88, 190, 42)
        self.settings = {"len": MATCH_SECONDS, "pu": True, "bot": 0}
        self.sound = Sound()
        self.profile = self.load_profile()
        audio_prefs = self.profile.get("audio", {})
        self.sound.on = bool(audio_prefs.get("effects", True))
        self.sound.music_enabled = bool(audio_prefs.get("music", True))
        self.upgrade_keys = ("shooting", "pace", "defending")
        self.upgrade_titles = ("SHOOTING POWER", "PACE", "DEFENDING")
        self.upgrade_descriptions = (
            "Faster shots and a higher shot-speed cap",
            "Move quicker and close down the ball faster",
            "Stronger tackles with a wider steal range",
        )
        upgrade_row_left = (W - (3 * 342 + 2 * 23)) // 2
        self.upgrade_rects = [pygame.Rect(upgrade_row_left + i * 365, 205, 342, 286)
                              for i in range(3)]
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
        self.net_in = {"dx": 0, "dy": 0, "dash": False, "sh": False,
                       "tk": 0, "sp": 0, "t": 0.0}
        self.net_axes = {"dx": 0.0, "dy": 0.0}
        self.p2_sh_prev = False
        self.p2_tk_prev = 0
        self.p2_sp_prev = 0
        self.c_special = 0
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
        self.replay_actor3 = None
        self.replay_actor4 = None
        self.replay_keeper_left = Goalkeeper(1)
        self.replay_keeper_right = Goalkeeper(2)
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

    def detect_touch_device(self):
        """Show the virtual controller only on phone/tablet browsers, never desktop browsers."""
        if not WEB_BUILD:
            return False
        try:
            return bool(platform.window.eval(
                "(function(){var ua=navigator.userAgent||'';"
                "var mobile=/Android|iPhone|iPod|Mobile|iPad/i.test(ua);"
                "var ipadOS=/Macintosh/i.test(ua)&&navigator.maxTouchPoints>1&&screen.width<1400;"
                "var touch=mobile||ipadOS;"
                "if(touch){document.documentElement.style.overflow='hidden';"
                "document.body.style.margin='0';document.body.style.overflow='hidden';"
                "document.body.style.background='#060c1b';document.body.style.touchAction='none';"
                "var c=document.querySelector('canvas');if(c){c.style.touchAction='none';"
                "c.style.userSelect='none';c.style.webkitUserSelect='none';}}"
                "return touch;})()"
            ))
        except Exception:
            return False

    def joystick_center(self, side):
        """Place single-player and online mobile controls together on the right.

        Local 2-player mode keeps one controller on each side of the screen.
        """
        if self.mode == "pvp":
            return (96, H - 142) if side == "p1" else (W - 96, H - 142)
        stick_right = bool(self.right_hand_control)
        return ((W - 100, H - 142) if stick_right else (100, H - 142))

    def update_joystick(self, side, pos):
        cx, cy = self.joystick_center(side)
        radius = 66.0
        dx = (float(pos[0]) - cx) / radius
        dy = (float(pos[1]) - cy) / radius
        length = math.hypot(dx, dy)
        if length > 1.0:
            dx, dy = dx / length, dy / length
            length = 1.0
        dead_zone = 0.12
        if length <= dead_zone:
            self.joystick_values[side] = (0.0, 0.0)
        else:
            strength = (length - dead_zone) / (1.0 - dead_zone)
            self.joystick_values[side] = (dx / max(length, 1e-6) * strength,
                                          dy / max(length, 1e-6) * strength)

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
            "audio": {"music": True, "effects": True},
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
            saved_audio = stored.get("audio", {})
            if isinstance(saved_audio, dict):
                profile["audio"]["music"] = bool(saved_audio.get("music", True))
                profile["audio"]["effects"] = bool(saved_audio.get("effects", True))
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

    def online_slot_layout(self):
        """Compute human player slots; AI fills every unoccupied active slot."""
        has_guest = self.mode == "client" or bool(self.guest_addr or self.guest_name)
        if not self.squad_mode:
            return (0, 1) if has_guest else (0, -1)
        host_team = int(clamp(self.host_team, 0, 1))
        host_slot = 0 if host_team == 0 else 1
        if not has_guest:
            return host_slot, -1
        guest_team = int(clamp(self.guest_team, 0, 1))
        if guest_team == host_team:
            guest_slot = 2 if guest_team == 0 else 3
        else:
            guest_slot = 1 if guest_team == 1 else 0
        return host_slot, guest_slot

    def refresh_online_slots(self):
        """Refresh human/AI labels and the local player's assigned slot."""
        self.host_slot, self.guest_slot = self.online_slot_layout()
        if self.mode == "client":
            self.local_slot = self.guest_slot
        else:
            self.local_slot = self.host_slot
        names = ["AI TEAMMATE", "AI TEAMMATE", "AI TEAMMATE", "AI TEAMMATE"]
        human = [False, False, False, False]
        if self.squad_mode:
            names[self.host_slot] = self.name + " (HOST)" if self.mode != "client" else (
                self.lobby_names[0] or "HOST")
            human[self.host_slot] = True
            if self.guest_slot >= 0 and self.mode == "client":
                names[self.guest_slot] = self.name + " (YOU)"
                human[self.guest_slot] = True
            elif self.guest_slot >= 0 and (self.guest_addr or self.guest_name):
                names[self.guest_slot] = self.guest_name or "GUEST"
                human[self.guest_slot] = True
        else:
            names[0] = self.name + " (HOST)" if self.mode != "client" else (
                self.lobby_names[0] or "HOST")
            human[0] = True
            if self.mode == "client":
                names[1] = self.name + " (YOU)"
                human[1] = True
            elif self.guest_addr or self.guest_name:
                names[1] = self.guest_name or "GUEST"
                human[1] = True
            else:
                names[1] = "OPPONENT"
        self.slot_names = names
        self.slot_is_human = human

    def match_players(self):
        """Return the active on-pitch players in stable snapshot/owner order."""
        if getattr(self, "squad_mode", False):
            return (self.p1, self.p2, self.p3, self.p4)
        return (self.p1, self.p2)

    def reset_positions(self):
        self.p1 = Player(FIELD_LEFT + 180, FIELD_CY, BLUE, BLUE_DARK, BLUE_LIGHT, False)
        self.p2 = Player(FIELD_RIGHT - 180, FIELD_CY, RED, RED_DARK, RED_LIGHT, True)
        self.apply_kit(self.p1, self.kit_indices[0])
        self.apply_kit(self.p2, self.kit_indices[1])
        self.apply_shape(self.p1, self.shape_indices[0])
        self.apply_shape(self.p2, self.shape_indices[1])
        self.apply_profile_to_player(self.p1)
        self.p3 = Player(FIELD_LEFT + 245, FIELD_CY + 112, BLUE, BLUE_DARK, BLUE_LIGHT, False)
        self.p4 = Player(FIELD_RIGHT - 245, FIELD_CY - 112, RED, RED_DARK, RED_LIGHT, True)
        self.p3.radius = self.p4.radius = 21
        self.p3.accent_color = BLUE_LIGHT
        self.p4.accent_color = RED_LIGHT
        self.p3.kit_name = "SQUAD AI"
        self.p4.kit_name = "SQUAD AI"
        self.ball = SoccerBall(W // 2, FIELD_CY)
        for player in (self.p1, self.p2, self.p3, self.p4):
            player.special_armed = False
            player.shot_special = None
        self.keeper_left = Goalkeeper(1)
        self.keeper_right = Goalkeeper(2)
        self.powerups = []
        self.bot_state.update({"think": 20.0, "lull": 0.0})

    def begin_countdown(self, frames):
        self.state = "countdown"
        self.countdown = float(frames)
        self.countdown_total = float(frames)

    def start_match(self, mode):
        self.mode = mode
        if mode in ("host", "client"):
            self.refresh_online_slots()
        if mode == "squad":
            self.squad_mode = True
        elif mode not in ("host", "client"):
            self.squad_mode = False
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
            if any(math.hypot(x - p.x, y - p.y) < 120 for p in self.match_players()):
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
            for p in self.match_players():
                if math.hypot(p.x - pu["x"], p.y - pu["y"]) < p.radius + 20:
                    self.collect_powerup(pu, 2 if p.is_p2 else 1, p)
                    break

    def collect_powerup(self, pu, idx, player=None):
        p = player or (self.p1 if idx == 1 else self.p2)
        foes = [q for q in self.match_players() if q.is_p2 != p.is_p2]
        foe = min(foes, key=lambda q: math.hypot(q.x - p.x, q.y - p.y)) if foes else (
            self.p2 if idx == 1 else self.p1)
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
        elif typ in ("post", "save"):
            self.sound.play("post" if typ == "post" else "steal", 0.9)
        elif typ == "pu":
            self.sound.play("freeze" if int(ex) % 10 == 2 else "pickup")

    def save_audio_preferences(self):
        if not hasattr(self, "profile"):
            return
        self.profile.setdefault("audio", {})
        self.profile["audio"]["music"] = bool(self.sound.music_enabled)
        self.profile["audio"]["effects"] = bool(self.sound.on)
        self.save_profile()

    def toggle_background_music(self):
        self.sound.toggle_music()
        self.save_audio_preferences()

    def toggle_sound(self):
        self.sound.on = not self.sound.on
        self.save_audio_preferences()
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
        self.squad_mode = True
        self.host_team = 0
        self.guest_team = 1
        self.guest_addr = None
        self.guest_name = None
        self.guest_ready = False
        self.lobby_names = [self.name, ""]
        self.refresh_online_slots()
        self.lobby_ready = [True, False]
        self.refresh_online_slots()
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
        self.refresh_online_slots()
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
        if self.guest_addr and not self.guest_ready:
            self.net_msg = "Waiting for the other player to ready up, or ask them to leave to play with AI."
            return
        self.net_msg = ""
        self.match_id += 1
        self.ev_log.clear()
        self.lobby_names = [self.name, self.guest_name or ""]
        self.refresh_online_slots()
        self.p2_sh_prev = False
        self.p2_tk_prev = self.net_in["tk"]
        self.p2_sp_prev = int(self.net_in.get("sp", 0))
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
                        net.send({"t": "welcome", "names": self.lobby_names,
                                  "sq": int(self.squad_mode), "ht": self.host_team,
                                  "gt": self.guest_team}, addr)
                    elif self.guest_addr is None and self.state == "lobby":
                        self.guest_addr = addr
                        self.guest_name = clean_name(msg.get("name"))
                        self.guest_ready = False
                        self.guest_last = now
                        self.lobby_names = [self.name, self.guest_name]
                        self.net_in = {"dx": 0, "dy": 0, "dash": False, "sh": False,
                                        "tk": 0, "sp": 0, "t": 0.0}
                        self.net_axes = {"dx": 0.0, "dy": 0.0}
                        self.lobby_send_t = -10.0
                        self.net_msg = ""
                        net.send({"t": "welcome", "names": self.lobby_names,
                                  "sq": int(self.squad_mode), "ht": self.host_team,
                                  "gt": self.guest_team}, addr)
                    else:
                        net.send({"t": "full"}, addr)
                elif addr == self.guest_addr:
                    self.guest_last = now
                    if t == "cl":
                        self.guest_ready = bool(msg.get("r"))
                        self.guest_team = int(clamp(int(msg.get("team", self.guest_team)), 0, 1))
                        if msg.get("name"):
                            self.guest_name = clean_name(msg.get("name"), self.guest_name or "GUEST")
                            self.lobby_names[1] = self.guest_name
                        self.refresh_online_slots()
                    elif t == "back":
                        # Keep the guest connected and return both players to the party lobby.
                        self.host_to_lobby("The other player returned to the lobby")
                    elif t == "in":
                        if msg.get("name"):
                            self.guest_name = clean_name(msg.get("name"), self.guest_name or "GUEST")
                            self.refresh_online_slots()
                        self.net_in = {
                            "dx": clamp(float(msg.get("dx", 0)), -1, 1),
                            "dy": clamp(float(msg.get("dy", 0)), -1, 1),
                            "dash": bool(msg.get("d")),
                            "sh": bool(msg.get("sh")),
                            "tk": int(msg.get("tk", 0)),
                            "sp": int(msg.get("sp", 0)),
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
            self.refresh_online_slots()
            net.send({"t": "lobby", "names": self.lobby_names,
                      "ready": [True, self.guest_ready], "ph": "lobby",
                      "sq": int(self.squad_mode), "mid": self.match_id,
                      "ht": self.host_team, "gt": self.guest_team}, self.guest_addr)

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
                    self.c_special = 0
                    self.lobby_names = [str(names[0] or ""), str(names[1] or self.name)]
                    self.guest_name = self.name
                    self.lobby_ready = [True, False]
                    self.squad_mode = bool(msg.get("sq", 0))
                    self.host_team = int(clamp(int(msg.get("ht", 0)), 0, 1))
                    self.guest_team = int(clamp(int(msg.get("gt", 1)), 0, 1))
                    self.team_change_pending = False
                    self.refresh_online_slots()
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
                        self.squad_mode = bool(msg.get("sq", self.squad_mode))
                        self.host_team = int(clamp(int(msg.get("ht", self.host_team)), 0, 1))
                        server_guest_team = int(clamp(int(msg.get("gt", self.guest_team)), 0, 1))
                        if not self.team_change_pending or server_guest_team == self.guest_team:
                            self.guest_team = server_guest_team
                            self.team_change_pending = False
                        self.refresh_online_slots()
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
        elif self.mode == "client":
          if now - self.host_last > 6.0:
            self.leave_party("Lost connection to the host")
            return
          if self.state == "lobby":
            if now - self.lobby_send_t > 0.25:
              self.lobby_send_t = now
              net.send({"t": "cl", "r": int(self.my_ready),
                        "team": int(self.guest_team), "name": self.name}, self.host_addr)
          elif self.state in GAME_STATES:
            self.client_send_input(now)

    def client_send_input(self, now):

        if now - self.in_send_t < 1.0 / 65.0:
            return
        self.in_send_t = now
        dx, dy, dash = self.combined_input(pygame.key.get_pressed())
        self.net.send({"t": "in", "dx": dx, "dy": dy, "d": int(bool(dash)),
                       "sh": int(self.c_shoot), "tk": self.c_tackle, "sp": self.c_special,
                       "name": self.name, "ts": now, "pg": int(self.ping)}, self.host_addr)

    def host_send_snapshot(self, now):
        if now - self.snap_send_t < 1.0 / 65.0:
            return
        self.snap_send_t = now
        ht = now - self.host_t0
        b = self.ball
        active_players = self.match_players()
        owner = next((i + 1 for i, player in enumerate(active_players) if b.owner is player), 0)
        snap = {"t": "snap", "ht": round(ht, 4), "mid": self.match_id,
                "st": STATE_IDX[self.state],
                "cd": r1(self.countdown), "ct": self.countdown_total,
                "cl": r1(self.clock_frames), "gt": r1(self.goal_timer),
                "s": [self.blue_score, self.red_score], "sq": int(self.squad_mode),
                "hs": int(self.host_slot), "gs": int(self.guest_slot),
                "hn": list(self.slot_names),
                "p": [pack_player(player) for player in active_players],
                "gk": [[r2(k.y), r2(k.vy), r1(k.dive_timer), r2(k.dive_dir),
                        r1(k.save_flash), r2(k.animation)]
                       for k in (self.keeper_left, self.keeper_right)],
                "b": [r2(b.x), r2(b.y), r2(b.vx), r2(b.vy), owner, r2(b.rotation),
                      r2(b.lift), r2(b.curve), r1(b.curve_t)],
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
        elif typ == "save":
            keeper = self.keeper_left if int(ex) == 1 else self.keeper_right
            keeper.dive_timer = 19.0
            keeper.dive_dir = -1.0 if y < keeper.y else 1.0
            keeper.save_flash = 12.0
            for _ in range(12):
                self.particles.append(Particle(x, y, random.uniform(-3, 3), random.uniform(-3, 3),
                                               keeper.light, random.randint(2, 4), 18))
        elif typ == "special":
            special_col = BLUE_LIGHT if int(ex) == 1 else GOLD
            for _ in range(16):
                self.particles.append(Particle(x, y, random.uniform(-4, 4), random.uniform(-4, 4),
                                               special_col, random.randint(2, 4), 22))
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
        span_seconds = 0.0 if a is b else max(1e-6, b["ht"] - a["ht"])
        f = 0.0 if a is b else clamp((rt - a["ht"]) / span_seconds, 0.0, 1.0)
        # A tiny velocity-based prediction covers a late WebSocket packet without freezing
        # the guest's view at the last received position. It is deliberately time-limited.
        extrapolate = min(0.065, max(0.0, rt - buf[-1]["ht"])) if rt > buf[-1]["ht"] else 0.0

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
        self.squad_mode = bool(b.get("sq", self.squad_mode))
        self.host_slot = int(clamp(int(b.get("hs", self.host_slot)), 0, 3))
        self.guest_slot = int(clamp(int(b.get("gs", self.guest_slot)), 0, 3))
        self.local_slot = self.guest_slot
        if isinstance(b.get("hn"), list) and len(b["hn"]) == 4:
            self.slot_names = [clean_name(n, "AI TEAMMATE") for n in b["hn"]]
            self.slot_is_human = ["AI" not in n.upper() for n in self.slot_names]
        sx = b.get("x")
        if sx and len(sx) >= 8:
            self.stats = {"shots": [sx[0], sx[1]], "steals": [sx[2], sx[3]],
                          "poss": [sx[4], sx[5]], "pu": [sx[6], sx[7]]}

        remote_players = (self.p1, self.p2, self.p3, self.p4) if self.squad_mode else (self.p1, self.p2)
        for player_index, p in enumerate(remote_players):
            if player_index >= len(b.get("p", [])) or player_index >= len(a.get("p", [])):
                continue
            pa, pb = a["p"][player_index], b["p"][player_index]
            jump = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) > 150     # kickoff reset: don't slide
            ff = 1.0 if jump else f
            if a is not b and not jump:
                p.x = hermite(pa[0], pb[0], pa[2], pb[2], ff, span_seconds)
                p.y = hermite(pa[1], pb[1], pa[3], pb[3], ff, span_seconds)
            else:
                p.x, p.y = float(pb[0]), float(pb[1])
            if extrapolate > 0.0 and a is b and not jump:
                p.x += float(pb[2]) * 60.0 * extrapolate
                p.y += float(pb[3]) * 60.0 * extrapolate
            p.x = clamp(p.x, FIELD_LEFT + p.radius, FIELD_RIGHT - p.radius)
            p.y = clamp(p.y, FIELD_TOP + p.radius, FIELD_BOTTOM - p.radius)
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
            if len(pb) > 17:
                p.special_armed = bool(pb[17])
                p.special_kind = "chip" if len(pb) > 18 and int(pb[18]) else "curve"
            if len(pb) > 19:
                p.special_cooldown = float(pb[19])
            speed = math.hypot(p.vx, p.vy)
            p.animation_time += (0.16 + speed * 0.025) * dt
            p.dribble_phase += (0.20 + speed * 0.03) * dt
            self.client_dust(p, dt)

        ba, bb = a["b"], b["b"]
        ball = self.ball
        jump = math.hypot(bb[0] - ba[0], bb[1] - ba[1]) > 150
        ff = 1.0 if jump else f
        if a is not b and not jump:
            ball.x = hermite(ba[0], bb[0], ba[2], bb[2], ff, span_seconds)
            ball.y = hermite(ba[1], bb[1], ba[3], bb[3], ff, span_seconds)
        else:
            ball.x, ball.y = float(bb[0]), float(bb[1])
        if extrapolate > 0.0 and a is b and not jump:
            ball.x += float(bb[2]) * 60.0 * extrapolate
            ball.y += float(bb[3]) * 60.0 * extrapolate
        ball.vx, ball.vy = float(bb[2]), float(bb[3])
        ball.rotation = float(bb[5])
        ball.lift = float(bb[6]) if len(bb) > 6 else 0.0
        ball.curve = float(bb[7]) if len(bb) > 7 else 0.0
        ball.curve_t = float(bb[8]) if len(bb) > 8 else 0.0
        owner = int(bb[4])
        all_players = (self.p1, self.p2, self.p3, self.p4)
        ball.owner = all_players[owner - 1] if 1 <= owner <= len(all_players) else None
        for idx, player in enumerate(all_players, 1):
            player.has_ball = owner == idx
        keeper_a = a.get("gk") if isinstance(a, dict) else None
        keeper_b = b.get("gk") if isinstance(b, dict) else None
        if (isinstance(keeper_a, list) and isinstance(keeper_b, list)
                and len(keeper_a) >= 2 and len(keeper_b) >= 2):
            for keeper, ka, kb in zip((self.keeper_left, self.keeper_right), keeper_a, keeper_b):
                if not isinstance(ka, (list, tuple)) or not isinstance(kb, (list, tuple)):
                    keeper.update(ball, dt)
                    continue
                keeper.y = lerp(float(ka[0]), float(kb[0]), f)
                keeper.vy = lerp(float(ka[1]), float(kb[1]), f)
                keeper.dive_timer = lerp(float(ka[2]), float(kb[2]), f)
                keeper.dive_dir = lerp(float(ka[3]), float(kb[3]), f)
                keeper.save_flash = lerp(float(ka[4]), float(kb[4]), f)
                keeper.animation = lerp(float(ka[5]), float(kb[5]), f)
        else:
            # Backward compatibility with snapshots from the previous build.
            self.keeper_left.update(ball, dt)
            self.keeper_right.update(ball, dt)
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

    def arm_special(self, player):
        """Arm the next shot; successive uses alternate curve and chip."""
        if player.special_cooldown > 0:
            self.sound.play("click", 0.55)
            return False
        if player.special_armed:
            player.special_kind = "chip" if player.special_kind == "curve" else "curve"
        player.special_armed = True
        self.sound.play("menuok", 0.7)
        return True

    def release_shot(self, player):
        if player.charging:
            player.charging = False
            player.shot_charge = player.charge
            player.charge = 0.0
            player.shot_special = player.special_kind if player.special_armed else None
            player.special_armed = False
            player.shot_buffer = 9.0

    def sync_mobile_join_field(self):
      """Show a real HTML text field only when editing player name on mobile."""
      if not WEB_BUILD:
        return
      try:
        if self.name_editing:
          js_name = r"""
                (function() {
                  var canvas = document.querySelector('canvas');
                  if (!canvas) return JSON.stringify({value: '', submit: false});
                  var input = document.getElementById('hs-mobile-player-name');
                  if (!input) {
                    input = document.createElement('input');
                    input.id = 'hs-mobile-player-name';
                    input.type = 'text';
                    input.autocomplete = 'nickname';
                    input.maxLength = 12;
                    input.placeholder = 'Type your player name';
                    input.style.cssText = 'position:fixed;z-index:10000;box-sizing:border-box;' +
                      'border:2px solid #e8bd42;border-radius:12px;background:#101e30;' +
                      'color:white;font:bold 18px sans-serif;text-align:center;padding:10px;' +
                      'outline:none;touch-action:auto;';
                    input.addEventListener('input', function(){ window._hs_name_value = input.value; });
                    input.addEventListener('keydown', function(e) {
                      e.stopPropagation();
                      if (e.key === 'Enter') { e.preventDefault(); window._hs_name_submit = true; input.blur(); }
                    });
                    document.body.appendChild(input);
                    window._hs_name_value = '';
                    window._hs_name_submit = false;
                    input.focus();
                  }
                  var r = canvas.getBoundingClientRect(), lw = canvas.width || 1200, lh = canvas.height || 700;
                  var sx = r.width/lw, sy = r.height/lh;
                  input.style.left = (r.left + (lw/2-190)*sx) + 'px';
                  input.style.top = (r.top + (lh/2+70)*sy) + 'px';
                  input.style.width = (380*sx) + 'px';
                  input.style.height = (54*sy) + 'px';
                  return JSON.stringify({value: input.value, submit: !!window._hs_name_submit});
                })()
                """
          data = json.loads(str(platform.window.eval(js_name)))
          self.name_edit_value = data.get("value", "")[:12]
          if data.get("submit"):
            platform.window.eval("window._hs_name_submit = false;")
            self.commit_online_name()
        else:
          platform.window.eval(
              "(function(){var"
              " n=document.getElementById('hs-mobile-player-name');if(n)n.remove();"
              "window._hs_name_value='';window._hs_name_submit=false;"
              "var e=document.getElementById('hs-mobile-join-code');"
              "if(e)e.remove();window._hs_join_value='';window._hs_join_submit=false;})()"
          )
      except Exception:
        pass

    def handle_events(self):
        self.sync_mobile_join_field()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            # B toggles background music from every screen without changing gameplay controls.
            # B toggles background music except when typing a room code or player name.
            typing = (
                self.state == "join"
                or self.name_editing
                or (self.state == "online_menu" and self.online_sel == 0)
            )
            if (
                event.type == pygame.KEYDOWN
                and event.key == pygame.K_b
                and not typing
            ):
              self.toggle_background_music()
              continue

            # F11 toggles native desktop fullscreen. On the web, the HTML overlay
            # button handles the browser's user-gesture requirement.
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                if not WEB_BUILD:
                    set_desktop_fullscreen(not DISPLAY_FULLSCREEN)
                continue

            st = self.state
            # SDL may deliver touch events without synthesizing mouse clicks on mobile.
            # Convert menu taps to clicks; gameplay keeps native finger events for multitouch.
            if event.type == pygame.FINGERDOWN and (st in MENU_STATES or st in BACK_NAV_STATES):
                event = pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN,
                    {"pos": (int(event.x * W), int(event.y * H)), "button": 1})
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and st in BACK_NAV_STATES and self.back_button_rect.collidepoint(event.pos)):
                self.navigate_back()
                continue
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

    def navigate_back(self):
        """Handle the persistent top-left back control on secondary screens."""
        state = self.state
        self.sound.play("click")
        if state == "online_menu":
            self.return_to_menu()
        elif state in ("join", "lobby"):
            # Closes the connection cleanly and returns to the online menu.
            self.leave_party()
        elif state in ("settings", "customize"):
            self.state = "menu"
        elif state == "upgrades":
            target = getattr(self, "upgrades_return_state", "menu")
            self.state = target if target in MENU_STATES else "menu"
        elif state == "replay":
            self.state = "finished"
        elif state in ("penalties", "penalty_finished", "finished"):
            self.return_to_menu()

    def game_navigate_back(self):
        """Return from a live match without accidentally disconnecting online guests."""
        self.sound.play("click")
        if self.mode == "host":
            self.host_to_lobby()
        elif self.mode == "client":
            if self.host_addr:
                self.net.send({"t": "back"}, self.host_addr)
            self.client_to_lobby()
        else:
            self.return_to_menu()

    def draw_game_settings_button(self):
        if self.state not in ("countdown", "play", "goal", "paused"):
            return
        r = self.game_settings_button
        pygame.draw.circle(screen, (5, 16, 27), r.center, 24)
        pygame.draw.circle(screen, (100, 150, 180), r.center, 22, 2)
        pygame.draw.circle(screen, (20, 39, 55), r.center, 18)
        # Simple gear glyph.
        pygame.draw.circle(screen, GOLD, r.center, 8, 3)
        pygame.draw.circle(screen, GOLD, r.center, 3)
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            p1 = (int(r.centerx + math.cos(a) * 10), int(r.centery + math.sin(a) * 10))
            p2 = (int(r.centerx + math.cos(a) * 15), int(r.centery + math.sin(a) * 15))
            pygame.draw.line(screen, GOLD, p1, p2, 3)

    def draw_game_settings_overlay(self):
        if not self.game_settings_open:
            return
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        screen.blit(shade, (0, 0))
        p = self.game_settings_panel
        pygame.draw.rect(screen, (12, 24, 38), p, border_radius=22)
        pygame.draw.rect(screen, (93, 170, 205), p, 2, border_radius=22)
        draw_text(screen, self.font, "MATCH SETTINGS", WHITE, (p.centerx, p.top + 34))
        r = self.game_settings_right_rect
        pygame.draw.rect(screen, (27, 48, 65), r, border_radius=12)
        pygame.draw.rect(screen, GOLD, r, 2, border_radius=12)
        hand = "RIGHT HAND  ·  STICK RIGHT" if self.right_hand_control else "LEFT HAND  ·  STICK LEFT"
        draw_text(screen, self.small_font, hand, GOLD, r.center, shadow=False)
        nr = self.game_settings_name_rect
        pygame.draw.rect(screen, (27, 48, 65), nr, border_radius=12)
        pygame.draw.rect(screen, (93, 170, 205), nr, 2, border_radius=12)
        name_label = ("NAME: " + (self.name_edit_value if self.name_editing else self.name)) if self.mode in ("host", "client") else "ONLINE NAME (ONLINE ONLY)"
        draw_text(screen, self.small_font, name_label[:34], WHITE, nr.center, shadow=False)
        cr = self.game_settings_close_rect
        pygame.draw.rect(screen, (32, 75, 92), cr, border_radius=10)
        draw_text(screen, self.small_font, "DONE", WHITE, cr.center, shadow=False)
        draw_text(screen, self.tiny_font, "Tap the name row to edit · Enter to save",
                  (175, 195, 210), (p.centerx, p.bottom - 8), shadow=False)

    def draw_game_back_button(self):
        """Compact top-left back arrow shown over live gameplay."""
        if self.state not in ("countdown", "play", "goal", "paused"):
            return
        rect = self.game_back_rect
        cx, cy = rect.center
        hover = rect.collidepoint(pygame.mouse.get_pos())
        # Slightly translucent dark-glass backing keeps the arrow readable on grass.
        pygame.draw.circle(screen, (5, 16, 27), (cx, cy), 25)
        pygame.draw.circle(screen, (67, 110, 137), (cx, cy), 23, 2)
        pygame.draw.circle(screen, (17, 37, 53) if not hover else (31, 62, 81),
                           (cx, cy), 20)
        pygame.draw.circle(screen, GOLD if hover else (125, 215, 239), (cx, cy), 20, 1)
        pygame.draw.line(screen, WHITE, (cx + 8, cy), (cx - 7, cy), 3)
        pygame.draw.line(screen, WHITE, (cx - 7, cy), (cx + 1, cy - 8), 3)
        pygame.draw.line(screen, WHITE, (cx - 7, cy), (cx + 1, cy + 8), 3)

    def draw_back_button(self):
        """Small round arrow button matching the game's dark glass UI."""
        if self.state not in BACK_NAV_STATES:
            return
        rect = self.back_button_rect
        cx, cy = rect.center
        hover = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.circle(screen, (4, 14, 27), (cx, cy), 25)
        pygame.draw.circle(screen, (50, 83, 105), (cx, cy), 23, 2)
        pygame.draw.circle(screen, (18, 34, 49) if not hover else (29, 57, 75),
                           (cx, cy), 20)
        edge = GOLD if hover else (115, 205, 229)
        pygame.draw.circle(screen, edge, (cx, cy), 20, 1)
        # Left arrow glyph drawn as clean vector strokes for crisp phone rendering.
        pygame.draw.line(screen, WHITE, (cx + 8, cy), (cx - 7, cy), 3)
        pygame.draw.line(screen, WHITE, (cx - 7, cy), (cx + 1, cy - 8), 3)
        pygame.draw.line(screen, WHITE, (cx - 7, cy), (cx + 1, cy + 8), 3)

    def menu_choose(self, i):
        if i == 0:
            self.start_match("pvp")
        elif i == 1:
            self.start_match("bot")
        elif i == 2:
            self.open_online_menu()
        elif i == 3:
            self.start_penalty_shootout(standalone=True)
        elif i == 4:
            self.start_match("squad")

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
            elif k in (pygame.K_5, pygame.K_KP5):
                self.menu_choose(4)
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
                self.menu_selection = min(4, self.menu_selection + 1)
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
        # Large, forgiving hit targets are important on phone screens.
        return pygame.Rect(42, 165 + i * 92, min(556, W - 84), 76)

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
            self.toggle_sound()
            return
        else:
            self.toggle_background_music()
            return
        self.sound.play("click")

    def events_settings(self, event):
        n = len(self.SET_ROWS)
        if event.type == pygame.MOUSEMOTION:
            for i in range(n):
                if self.set_row_rect(i).collidepoint(event.pos):
                    self.set_sel = i
        elif event.type == pygame.FINGERDOWN:
            # Some mobile SDL builds do not synthesize mouse-down from taps.
            pos = (int(event.x * W), int(event.y * H))
            for i in range(n):
                r = self.set_row_rect(i)
                if r.collidepoint(pos):
                    self.set_sel = i
                    self.settings_change(i, -1 if pos[0] < r.centerx else 1)
                    return
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(n):
                r = self.set_row_rect(i)
                if r.collidepoint(event.pos):
                    self.set_sel = i
                    self.settings_change(i, -1 if event.pos[0] < r.centerx else 1)
                    return
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
              if i == 0 and WEB_BUILD:
                try:
                  entered = platform.window.prompt(
                      "Enter your player name (max 12 chars):", self.name
                  )
                  if entered is not None:
                    self.name = clean_name(entered, self.name)
                except Exception:
                  pass
              elif i == 1:
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
        box = pygame.Rect(
            W // 2 - 310, 260 if WEB_BUILD else 440, 620, 84 if WEB_BUILD else 70
        )
        join_btn = pygame.Rect(W // 2 - 170, 375, 340, 56)
        if WEB_BUILD and box.collidepoint(event.pos):
          try:
            entered = platform.window.prompt(
                "Enter the 5-letter party code:", self.join_text
            )
            if entered is not None:
              self.join_text = str(entered).strip().upper()[:30]
              if len(self.join_text) >= 4:
                self.join_submit()
          except Exception:
            pass
          return
        if WEB_BUILD and join_btn.collidepoint(event.pos):
          self.join_submit()
          return
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
          self.join_sel = min(
              max(0, len(self.lan_list()) - 1), self.join_sel + 1
          )
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
          self.join_submit()
        elif k == pygame.K_BACKSPACE:
          self.join_text = self.join_text[:-1]
        elif k == pygame.K_v and (
            event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)
        ):
          self.join_text = (self.join_text + clipboard_text().strip())[:30]
        elif len(self.join_text) < 30:
          ch = event.unicode if len(event.unicode) == 1 else ""
          if not ch:
            name = pygame.key.name(k)
            if len(name) == 1 and name.isalnum():
              ch = name.upper() if (event.mod & pygame.KMOD_SHIFT) else name
          if ch and ch.isprintable():
            self.join_text += ch

    def events_lobby(self, event):
      if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        # 1. Check 1V1 / 2V2 Toggle first with a generous mobile tap zone (y: 418..474)
        squad_hit = pygame.Rect(W // 2 - 220, 418, 440, 56)
        if self.mode == "host" and squad_hit.collidepoint(event.pos):
          self.squad_mode = not self.squad_mode
          self.refresh_online_slots()
          self.net_msg = (
              "AI WILL FILL OPEN SLOTS"
              if self.squad_mode
              else "CLASSIC 1V1 ENABLED"
          )
          self.lobby_send_t = -10.0
          self.sound.play("menuok")
          return

        # 2. Check Start / Ready Up button (y: 495..569)
        start_hit = pygame.Rect(W // 2 - 200, 495, 400, 74)
        if self.mode == "host" and start_hit.collidepoint(event.pos):
          self.host_start_match()
          return
        if self.mode == "client" and start_hit.collidepoint(event.pos):
          self.my_ready = not self.my_ready
          self.lobby_send_t = -10.0
          self.sound.play("menuok")
          return

        # 3. Check Blue / Red team selection cards
        if getattr(
            self, "lobby_blue_rect", pygame.Rect(0, 0, 0, 0)
        ).collidepoint(event.pos):
          if self.squad_mode:
            if self.mode == "host":
              self.host_team = 0
            else:
              self.guest_team = 0
              self.my_ready = False
              self.team_change_pending = True
            self.refresh_online_slots()
            self.lobby_send_t = -10.0
            self.sound.play("menuok")
          return
        if getattr(
            self, "lobby_red_rect", pygame.Rect(0, 0, 0, 0)
        ).collidepoint(event.pos):
          if self.squad_mode:
            if self.mode == "host":
              self.host_team = 1
            else:
              self.guest_team = 1
              self.my_ready = False
              self.team_change_pending = True
            self.refresh_online_slots()
            self.lobby_send_t = -10.0
            self.sound.play("menuok")
          return
        return


    def events_game(self, event):

        # Live match settings stay in the match; they never reset or disconnect it.
        if self.game_settings_open:
            if WEB_BUILD and event.type == pygame.FINGERDOWN:
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                    {"pos": (int(event.x * W), int(event.y * H)), "button": 1})
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.game_settings_right_rect.collidepoint(event.pos):
                    self.right_hand_control = not self.right_hand_control
                    self.joystick_values = {"p1": (0.0, 0.0), "p2": (0.0, 0.0)}
                elif self.game_settings_name_rect.collidepoint(event.pos):
                    if self.mode in ("host", "client"):
                        self.name_editing = True
                        self.name_edit_value = self.name
                elif self.game_settings_close_rect.collidepoint(event.pos):
                    self.game_settings_open = False
                elif not self.game_settings_panel.collidepoint(event.pos):
                    self.game_settings_open = False
                return
            if event.type == pygame.KEYDOWN:
                if self.name_editing and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.commit_online_name()
                elif event.key == pygame.K_ESCAPE:
                    self.name_editing = False
                    self.game_settings_open = False
                elif self.name_editing and event.key == pygame.K_BACKSPACE:
                    self.name_edit_value = self.name_edit_value[:-1]
                elif self.name_editing and event.unicode and event.unicode.isprintable() and len(self.name_edit_value) < 12:
                    self.name_edit_value += event.unicode
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.game_settings_open = False
                return
            if event.type == pygame.TEXTINPUT and self.name_editing:
                self.name_edit_value = clean_name(self.name_edit_value + event.text)
                return
            return

        # The in-match back arrow is checked before joystick/action hitboxes so a
        # tap in the top-left corner always navigates back instead of moving.
        if self.state in ("countdown", "play", "goal", "paused"):
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and self.game_back_rect.collidepoint(event.pos)):
                self.game_navigate_back()
                return
            if event.type == pygame.FINGERDOWN:
                back_pos = (int(event.x * W), int(event.y * H))
                if self.game_back_rect.collidepoint(back_pos):
                    self.game_navigate_back()
                    return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state in ("play", "countdown", "goal") and self.game_settings_button.collidepoint(event.pos):
                self.game_settings_open = True
                self.name_editing = False
                return
            if self.state == "play" and self.handle_touch_pointer("mouse", event.pos, True):
                return
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.handle_touch_pointer("mouse", event.pos, False):
                return
        elif event.type == pygame.MOUSEMOTION and "mouse" in self.touch_pointer_map:
            if self.handle_touch_motion("mouse", event.pos):
                return
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * W), int(event.y * H))
            if self.state in ("play", "countdown", "goal") and self.game_settings_button.collidepoint(pos):
                self.game_settings_open = True
                self.name_editing = False
                return
            if self.state == "play" and self.handle_touch_pointer(("finger", event.finger_id), pos, True):
                return
        elif event.type == pygame.FINGERMOTION:
            pos = (int(event.x * W), int(event.y * H))
            if self.handle_touch_motion(("finger", event.finger_id), pos):
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
                local_player = (self.match_players()[self.host_slot]
                                if self.mode == "host" else self.p1)
                self.release_shot(local_player)
            elif event.key == pygame.K_p:
                if self.mode == "host":
                    players = self.match_players()
                    self.release_shot(players[int(clamp(self.host_slot, 0, len(players) - 1))])
                else:
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
            if k == pygame.K_ESCAPE and self.state in GAME_STATES:
                self.game_navigate_back()
            elif k == pygame.K_ESCAPE or (k == pygame.K_m and self.state == "finished"):
                self.leave_party()
            elif k in (pygame.K_e, pygame.K_p):
                self.c_shoot = True
            elif k in (pygame.K_r, pygame.K_l):
                self.c_tackle += 1
            elif k == pygame.K_q:
                self.c_special += 1
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

        local_player = (self.match_players()[self.host_slot]
                        if self.mode == "host" else self.p1)
        if k == pygame.K_e:
            local_player.charging = True
            local_player.charge = 0.0
        elif k == pygame.K_r:
            local_player.tackle_buffer = 8.0
        elif k == pygame.K_p:
            if self.mode == "host":
                pl = local_player
            else:
                pl = self.p2 if self.mode == "pvp" else self.p1
            pl.charging = True
            pl.charge = 0.0
        elif k == pygame.K_l:
            (self.p2 if self.mode == "pvp" else self.p1).tackle_buffer = 8.0
        elif k == pygame.K_q:
            self.arm_special(local_player)
        elif k == pygame.K_PERIOD and self.mode == "pvp":
            self.arm_special(self.p2)

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
            if self.ball.shoot(p, self.particles, p.shot_charge, p.shot_special):
                used_special = p.shot_special
                p.shot_buffer = 0.0
                p.shot_special = None
                self.stats["shots"][1 if p.is_p2 else 0] += 1
                self.shake = max(self.shake, 2.0 + 4.0 * p.shot_charge)
                self.emit("kick", self.ball.x, self.ball.y, p.shot_charge)
                if used_special:
                    p.special_cooldown = 260.0
                    p.special_kind = "chip" if used_special == "curve" else "curve"
                    self.emit("special", self.ball.x, self.ball.y,
                              1 if used_special == "curve" else 2)
        if p.tackle_buffer > 0:
            p.tackle_buffer -= dt
            if self.attempt_tackle(p):
                p.tackle_buffer = 0.0

    def apply_remote_actions(self, now):
        """Host: turn the guest's held-key state into charge / release / tackle."""
        ni = self.net_in
        fresh = (now - ni["t"]) < 0.5
        sh = bool(ni["sh"]) and fresh
        players = self.match_players()
        remote = players[self.guest_slot] if 0 <= self.guest_slot < len(players) else self.p2
        if self.state == "play":
            if sh and not self.p2_sh_prev:
                remote.charging = True
                remote.charge = 0.0
            elif not sh and self.p2_sh_prev:
                self.release_shot(remote)
            if ni["tk"] != self.p2_tk_prev:
                remote.tackle_buffer = 8.0
            if int(ni.get("sp", 0)) != self.p2_sp_prev:
                self.arm_special(remote)
        self.p2_sh_prev = sh
        self.p2_tk_prev = ni["tk"]
        self.p2_sp_prev = int(ni.get("sp", 0))

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

    def squad_ai_inputs(self, player, dt):
        """Casual squad AI: slow reactions, loose positioning and no automatic sprinting."""
        direction = -1.0 if player.is_p2 else 1.0
        ball = self.ball
        allies = [q for q in self.match_players()
                  if q is not player and q.is_p2 == player.is_p2]
        ally = min(allies, key=lambda q: math.hypot(q.x - player.x, q.y - player.y)) if allies else player
        owner = ball.owner

        if not hasattr(player, "ai_rethink"):
            player.ai_rethink = random.uniform(5.0, 14.0)
            player.ai_target_x = player.x
            player.ai_target_y = player.y

        player.ai_rethink -= dt
        if player.ai_rethink <= 0.0:
            player.ai_rethink = random.uniform(18.0, 31.0)  # roughly 0.3–0.5 seconds
            if owner is player:
                target_x = player.x + direction * 145
                target_y = lerp(player.y, FIELD_CY, 0.12)
            elif owner is not None and owner.is_p2 == player.is_p2:
                side_offset = -125 if player.y > ally.y else 125
                target_x = owner.x + direction * 115
                target_y = owner.y + side_offset
            elif owner is not None:
                # AI only presses when the opponent is fairly close; otherwise it drifts back.
                if math.hypot(player.x - owner.x, player.y - owner.y) < 205:
                    target_x, target_y = owner.x, owner.y
                else:
                    target_x = lerp(player.x, ball.x - direction * 115, 0.25)
                    target_y = lerp(FIELD_CY, ball.y, 0.30)
            else:
                own_dist = math.hypot(ball.x - player.x, ball.y - player.y)
                ally_dist = math.hypot(ball.x - ally.x, ball.y - ally.y)
                if own_dist <= ally_dist + 18:
                    target_x, target_y = ball.x + ball.vx * 0.8, ball.y + ball.vy * 0.8
                else:
                    target_x = lerp(ally.x, ball.x + direction * 145, 0.42)
                    target_y = lerp(ally.y, ball.y + (105 if player.y < ally.y else -105), 0.42)

            # Imperfect reads: AI targets are intentionally a little off.
            player.ai_target_x = clamp(target_x + random.uniform(-48, 48),
                                       FIELD_LEFT + 48, FIELD_RIGHT - 48)
            player.ai_target_y = clamp(target_y + random.uniform(-58, 58),
                                       FIELD_TOP + 42, FIELD_BOTTOM - 42)

        dx = player.ai_target_x - player.x
        dy = player.ai_target_y - player.y
        distance = math.hypot(dx, dy)
        if distance < 17:
            return 0.0, 0.0, False
        strength = min(0.66, 0.42 + distance / 420.0)
        # Teammates do not sprint continuously; humans keep the pace advantage.
        return dx / distance * strength, dy / distance * strength, False

    def squad_ai_actions(self, player, dt):
        """Less clinical AI: tackles and shots need a pause and a bit of luck."""
        if player.frozen_t > 0:
            return
        if not hasattr(player, "ai_action_wait"):
            player.ai_action_wait = random.uniform(14.0, 30.0)
        player.ai_action_wait = max(0.0, player.ai_action_wait - dt)
        if player.ai_action_wait > 0.0:
            return

        ball = self.ball
        if ball.owner is not None and ball.owner.is_p2 != player.is_p2:
            dist = math.hypot(ball.owner.x - player.x, ball.owner.y - player.y)
            if player.tackle_cooldown <= 0 and dist < 59 and random.random() < 0.20:
                player.tackle_buffer = max(player.tackle_buffer, 2.5)
                player.ai_action_wait = random.uniform(24.0, 42.0)
        elif ball.owner is player:
            goal_x = FIELD_LEFT - 20 if player.is_p2 else FIELD_RIGHT + 20
            distance = abs(goal_x - player.x)
            # AI waits until it is reasonably close and occasionally wastes a shooting chance.
            if distance < 390 and player.shot_buffer <= 0 and random.random() < 0.30:
                aim_error = random.uniform(-115, 115)
                aim_y = clamp(FIELD_CY + aim_error, GOAL_TOP + 20, GOAL_BOTTOM - 20)
                fx, fy = normalize(-1.0 if player.is_p2 else 1.0, (aim_y - player.y) / 310.0)
                player.facing_x, player.facing_y = fx, fy
                player.shot_charge = random.uniform(0.04, 0.22)
                player.shot_buffer = 2.5
                player.ai_action_wait = random.uniform(30.0, 52.0)

    def separate_players(self):
        players = self.match_players()
        for i, first in enumerate(players):
            for second in players[i + 1:]:
                dx = second.x - first.x
                dy = second.y - first.y
                dist = math.hypot(dx, dy)
                min_dist = first.radius + second.radius
                if dist < min_dist:
                    if dist < 0.001:
                        dx, dy, dist = 1.0, 0.0, 1.0
                    nx, ny = dx / dist, dy / dist
                    push = (min_dist - dist) / 2
                    first.x -= nx * push
                    first.y -= ny * push
                    second.x += nx * push
                    second.y += ny * push
                    first.clamp_to_field()
                    second.clamp_to_field()


    def commit_online_name(self):
        new_name = clean_name(self.name_edit_value, self.name)
        self.name = new_name
        self.name_editing = False
        if self.mode == "host":
            self.lobby_names[0] = new_name
            self.refresh_online_slots()
        elif self.mode == "client" and self.host_addr:
            self.net.send({"t": "cl", "r": int(self.my_ready),
                           "team": int(self.guest_team), "name": new_name}, self.host_addr)
        self.sound.play("menuok")

    def touch_down(self, name):
        if name in self.touch_held:
            return
        self.touch_held.add(name)
        side, action = name.split("_", 1)
        if self.mode == "host":
            player = self.match_players()[int(clamp(self.host_slot, 0, len(self.match_players()) - 1))]
        else:
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
        elif action == "skill":
            if self.mode == "client":
                self.c_special += 1
            else:
                self.arm_special(player)
        elif action == "dash":
            # Dash is read continuously from touch_held by combined_input/read_inputs.
            pass

    def touch_up(self, name):
        if name not in self.touch_held:
            return
        self.touch_held.discard(name)
        side, action = name.split("_", 1)
        if action == "shoot":
            if self.mode == "client":
                self.c_shoot = False
            elif self.mode == "host":
                players = self.match_players()
                self.release_shot(players[int(clamp(self.host_slot, 0, len(players) - 1))])
            else:
                self.release_shot(self.p2 if side == "p2" else self.p1)

    def touch_rects(self):
        """Circular action hit areas; the move stick is handled as an analog pointer zone."""
        if not self.touch_controls_enabled:
            return {}
        def circle(cx, cy, radius):
            return pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)

        if self.mode == "pvp":
            rects = {
                "p1_dash": circle(225, H - 220, 37),
                "p1_tackle": circle(225, H - 125, 37),
                "p1_shoot": circle(335, H - 172, 49),
                "p1_skill": circle(335, H - 65, 34),
                "p2_dash": circle(W - 225, H - 220, 37),
                "p2_tackle": circle(W - 225, H - 125, 37),
                "p2_shoot": circle(W - 335, H - 172, 49),
                "p2_skill": circle(W - 335, H - 65, 34),
            }
        else:
            # One-human modes (1vBot and online 1v1): joystick stays on the
            # right edge; action buttons sit on the left. Local 2-player
            # keeps its existing split-controller layout.
            # One-human layout mirrors cleanly when the dominant hand changes.
            if self.right_hand_control:
                dash_x, shoot_x = 390, 260
            else:
                dash_x, shoot_x = W - 390, W - 260
            rects = {
                "p1_dash": circle(dash_x, H - 220, 37),
                "p1_tackle": circle(dash_x, H - 125, 37),
                "p1_shoot": circle(shoot_x, H - 170, 51),
                "p1_skill": circle(shoot_x, H - 65, 34),
            }
        return rects

    def _joystick_side_at(self, pos):
        if not self.touch_controls_enabled:
            return None
        sides = ("p1", "p2") if self.mode == "pvp" else ("p1",)
        for side in sides:
            cx, cy = self.joystick_center(side)
            if math.hypot(pos[0] - cx, pos[1] - cy) <= 78:
                return side
        return None

    def handle_touch_pointer(self, pointer_id, pos, down):
        if not self.touch_controls_enabled:
            return False
        if down:
            side = self._joystick_side_at(pos)
            if side:
                self.touch_pointer_map[pointer_id] = side + "_joystick"
                self.update_joystick(side, pos)
                return True
            for name, rect in self.touch_rects().items():
                if rect.collidepoint(pos):
                    self.touch_pointer_map[pointer_id] = name
                    self.touch_down(name)
                    return True
        else:
            name = self.touch_pointer_map.pop(pointer_id, None)
            if name:
                if name.endswith("_joystick"):
                    side = name.split("_", 1)[0]
                    self.joystick_values[side] = (0.0, 0.0)
                else:
                    self.touch_up(name)
                return True
        return False

    def handle_touch_motion(self, pointer_id, pos):
        name = self.touch_pointer_map.get(pointer_id)
        if not name or not name.endswith("_joystick"):
            return False
        side = name.split("_", 1)[0]
        self.update_joystick(side, pos)
        return True

    def combined_input(self, keys):
        jx, jy = self.joystick_values["p1"]
        dx = (int(keys[pygame.K_d]) - int(keys[pygame.K_a])
              + int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT]) + jx)
        dy = (int(keys[pygame.K_s]) - int(keys[pygame.K_w])
              + int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP]) + jy)
        length = math.hypot(dx, dy)
        if length > 1.0:
            dx, dy = dx / length, dy / length
        dash = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or keys[pygame.K_SLASH]
                    or "p1_dash" in self.touch_held)
        return dx, dy, dash

    def read_inputs(self, keys):
        if self.mode == "pvp":
            j1x, j1y = self.joystick_values["p1"]
            j2x, j2y = self.joystick_values["p2"]
            dx1 = int(keys[pygame.K_d]) - int(keys[pygame.K_a]) + j1x
            dy1 = int(keys[pygame.K_s]) - int(keys[pygame.K_w]) + j1y
            dx2 = int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT]) + j2x
            dy2 = int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP]) + j2y
            l1, l2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
            if l1 > 1.0:
                dx1, dy1 = dx1 / l1, dy1 / l1
            if l2 > 1.0:
                dx2, dy2 = dx2 / l2, dy2 / l2
            in1 = (dx1, dy1, bool(keys[pygame.K_LSHIFT] or "p1_dash" in self.touch_held))
            in2 = (dx2, dy2, bool(keys[pygame.K_RSHIFT] or keys[pygame.K_SLASH]
                                   or "p2_dash" in self.touch_held))
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
            for player in self.match_players():
                player.tick_timers(dt)
            self.keeper_left.update(self.ball, dt)
            self.keeper_right.update(self.ball, dt)
            if random.random() < 0.5 * dt:
                self.spawn_confetti()
            return

        if self.state == "countdown":
            for player in self.match_players():
                player.update(0, 0, False, dt, self.particles)
            self.keeper_left.update(self.ball, dt)
            self.keeper_right.update(self.ball, dt)
            self.ball.update(dt, self.particles)
            self.update_particles(dt)
            self.countdown -= dt
            if self.countdown <= 0:
                self.state = "play"
                self.go_timer = 45.0
            return

        if self.state == "goal":
            slow = dt * 0.35
            for player in self.match_players():
                player.update(0, 0, False, slow, self.particles)
            self.keeper_left.update(self.ball, slow)
            self.keeper_right.update(self.ball, slow)
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

        if self.mode == "host":
            # Host-authoritative hybrid 2v2: host and guest control their selected
            # slots; every unoccupied slot is driven by the squad AI.
            active = self.match_players()
            host_index = int(clamp(self.host_slot, 0, len(active) - 1))
            guest_index = self.guest_slot
            active[host_index].update(*self.combined_input(keys), dt, self.particles)

            if guest_index >= 0:
                ni = self.net_in
                fresh = time.perf_counter() - ni["t"] <= 0.5
                target_x = float(ni["dx"]) if fresh else 0.0
                target_y = float(ni["dy"]) if fresh else 0.0
                blend = ease(0.52, dt)
                self.net_axes["dx"] = lerp(self.net_axes["dx"], target_x, blend)
                self.net_axes["dy"] = lerp(self.net_axes["dy"], target_y, blend)
                active[guest_index].update(self.net_axes["dx"], self.net_axes["dy"],
                                           bool(ni["dash"] and fresh), dt, self.particles)

            # In a solo hosted match the guest slot is also AI-controlled.
            for index, teammate in enumerate(active):
                if index == host_index or index == guest_index:
                    continue
                teammate.update(*self.squad_ai_inputs(teammate, dt), dt, self.particles)
                self.squad_ai_actions(teammate, dt)
        else:
            self.p1.update(*in1, dt, self.particles)
            if self.mode == "pvp":
                self.p2.update(*in2, dt, self.particles)
            else:
                self.p2.update(*self.bot_inputs(dt), dt, self.particles)
                self.bot_actions(dt)

            if self.squad_mode:
                for teammate in (self.p3, self.p4):
                    teammate.update(*self.squad_ai_inputs(teammate, dt), dt, self.particles)
                    self.squad_ai_actions(teammate, dt)

        for player in self.match_players():
            self.process_actions(player, dt)
        self.separate_players()

        self.keeper_left.update(self.ball, dt)
        self.keeper_right.update(self.ball, dt)
        self.ball.update(dt, self.particles)
        for keeper in (self.keeper_left, self.keeper_right):
            if keeper.try_save(self.ball):
                self.shake = max(self.shake, 7.0)
                self.emit("save", keeper.x, keeper.y, keeper.side)
                for _ in range(18):
                    self.particles.append(Particle(keeper.x, keeper.y,
                        random.uniform(-4, 4), random.uniform(-4, 4), keeper.light,
                        random.randint(2, 4), 20))
        for p in self.match_players():
            if self.ball.check_collision(p) == "steal":
                self.stats["steals"][1 if p.is_p2 else 0] += 1
                self.shake = max(self.shake, 6)
                self.particles.append(Particle(self.ball.x, self.ball.y, 0, 0, GOLD, 12, 18, ring=True))
                self.emit("steal", self.ball.x, self.ball.y)

        if self.ball.post_hit:
            self.shake = max(self.shake, 5)
            self.emit("post", self.ball.x, self.ball.y)

        holder = self.ball.owner
        if holder is not None:
            self.stats["poss"][1 if holder.is_p2 else 0] += dt
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
            "p3": self._replay_player_state(self.p3) if self.squad_mode else None,
            "p4": self._replay_player_state(self.p4) if self.squad_mode else None,
            "kl": [float(self.keeper_left.y), float(self.keeper_left.vy),
                   float(self.keeper_left.dive_timer), float(self.keeper_left.dive_dir),
                   float(self.keeper_left.save_flash), float(self.keeper_left.animation)],
            "kr": [float(self.keeper_right.y), float(self.keeper_right.vy),
                   float(self.keeper_right.dive_timer), float(self.keeper_right.dive_dir),
                   float(self.keeper_right.save_flash), float(self.keeper_right.animation)],
            "bx": float(self.ball.x), "by": float(self.ball.y),
            "bl": float(self.ball.lift), "br": float(self.ball.rotation),
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
        replay_pairs = [(self.p1, self.replay_actor1), (self.p2, self.replay_actor2)]
        self.replay_actor3 = self.replay_actor4 = None
        if self.squad_mode:
            self.replay_actor3 = Player(self.p3.x, self.p3.y, self.p3.color,
                                        self.p3.dark_color, self.p3.light_color, False)
            self.replay_actor4 = Player(self.p4.x, self.p4.y, self.p4.color,
                                        self.p4.dark_color, self.p4.light_color, True)
            replay_pairs.extend(((self.p3, self.replay_actor3),
                                 (self.p4, self.replay_actor4)))
        for src, dst in replay_pairs:
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
        for p in self.match_players():
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
        if self.mode not in ("bot", "pvp", "squad") or player_number != 1:
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
        if self.mode not in ("bot", "pvp", "squad"):
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
        for scorer in self.match_players():
            if (2 if scorer.is_p2 else 1) == player_number:
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
        for p in self.match_players():
            p.charging = False
            p.charge = 0.0
            p.shot_buffer = p.tackle_buffer = 0.0
            p.shot_special = None
            p.special_armed = False

        self.goal_fx(self.ball.x, self.ball.y, player_number)
        self.emit("goal", self.ball.x, self.ball.y, player_number)

    def update_menu(self, dt):
        self.menu_t += dt
        for p in (self.menu_p1, self.menu_p2):
            p.vx = 3.0
            p.tick_timers(dt)
        # Ambient drifting motes.
        if random.random() < 0.25 * dt:
            mote_col = random.choice(((92, 195, 255), (169, 125, 255), (255, 125, 205)))
            self.particles.append(Particle(
                random.uniform(0, W), H + 10, random.uniform(-0.3, 0.3), random.uniform(-1.4, -0.6),
                mote_col, random.randint(2, 4), random.randint(120, 200)))
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

    def build_menu_backdrop(self):
        """Load the cinematic neon stadium image and crop it to this screen."""
        try:
            raw = base64.b64decode(MENU_BG_ART_B64)
            source = pygame.image.load(io.BytesIO(raw)).convert()
            scale = max(W / source.get_width(), H / source.get_height())
            sw = max(W, int(source.get_width() * scale))
            sh = max(H, int(source.get_height() * scale))
            scaled = pygame.transform.smoothscale(source, (sw, sh))
            ox = (sw - W) // 2
            oy = (sh - H) // 2
            bg = pygame.Surface((W, H))
            bg.blit(scaled, (0, 0), pygame.Rect(ox, oy, W, H))
            # A gentle dark wash keeps the existing labels and buttons readable.
            shade = pygame.Surface((W, H), pygame.SRCALPHA)
            shade.fill((1, 7, 20, 48))
            bg.blit(shade, (0, 0))
            return bg
        except Exception:
            # The original procedural stadium remains as a fallback if image loading fails.
            bg = pygame.Surface((W, H))
            top = (6, 12, 27)
            bottom = (13, 32, 49)
            for y in range(H):
                f = y / max(1, H - 1)
                col = tuple(int(lerp(top[i], bottom[i], f)) for i in range(3))
                pygame.draw.line(bg, col, (0, y), (W, y))
            for i in range(8):
                col = (17 + i, 29 + i, 45 + i)
                pygame.draw.ellipse(bg, col, (-190 - i * 8, 145 - i * 7,
                                             W + 380 + i * 16, 520 + i * 18), 1)
            return bg

    def build_menu_ball(self):
        """Load the extracted cartoon football used for the looping menu fly-in."""
        try:
            raw = base64.b64decode(MENU_BALL_ART_B64)
            source = pygame.image.load(io.BytesIO(raw)).convert_alpha()
            size = max(250, min(340, int(H * 0.49)))
            return pygame.transform.smoothscale(source, (size, size))
        except Exception:
            return None

    def draw_menu_ball(self):
        """Animated fireball entry: flies in, bobs gently and continuously spins."""
        t = self.ui_t
        progress = clamp(t / 72.0, 0.0, 1.0)
        eased = 1.0 - (1.0 - progress) ** 3
        target_x = W * 0.765
        target_y = H * 0.405 + math.sin(t * 0.075) * 5.0
        x = lerp(W + 185, target_x, eased)
        y = lerp(-125, target_y, eased)
        radius = max(110, int(H * 0.245))

        # Layered orange/yellow flame ribbons trail behind the incoming ball.
        trail = pygame.Surface((W, H), pygame.SRCALPHA)
        tail = [
            (int(x + radius * 0.58), int(y - radius * 0.45)),
            (int(x + radius * 2.15), int(y - radius * 0.98 + math.sin(t * 0.09) * 10)),
            (int(x + radius * 1.78), int(y - radius * 0.08)),
            (int(x + radius * 2.05), int(y + radius * 0.50)),
            (int(x + radius * 0.55), int(y + radius * 0.40)),
        ]
        pygame.draw.polygon(trail, (255, 76, 12, 72), tail)
        pygame.draw.polygon(trail, (255, 145, 20, 92), [
            (int(x + radius * 0.60), int(y - radius * 0.25)),
            (int(x + radius * 1.92), int(y - radius * 0.64)),
            (int(x + radius * 1.46), int(y + radius * 0.02)),
            (int(x + radius * 0.56), int(y + radius * 0.22)),
        ])
        pygame.draw.polygon(trail, (255, 218, 80, 118), [
            (int(x + radius * 0.56), int(y - radius * 0.10)),
            (int(x + radius * 1.48), int(y - radius * 0.39)),
            (int(x + radius * 1.18), int(y + radius * 0.03)),
            (int(x + radius * 0.55), int(y + radius * 0.12)),
        ])
        # Electric-blue orbit arcs complement the orange fire trail.
        orbit_rect = pygame.Rect(int(x - radius * 1.05), int(y - radius * 0.70),
                                 int(radius * 2.65), int(radius * 1.42))
        orbit_col = (40, 190, 255, 165)
        pygame.draw.arc(trail, orbit_col, orbit_rect, 0.15, 2.55, 4)
        pygame.draw.arc(trail, (35, 105, 255, 110), orbit_rect.inflate(20, 16),
                        3.25, 5.35, 3)
        screen.blit(trail, (0, 0))

        # Small sparks stream from the back of the moving ball.
        for i in range(12):
            phase = t * 0.12 + i * 1.83
            sx = int(x + radius * (0.75 + (i % 4) * 0.30) + math.sin(phase) * 15)
            sy = int(y + math.sin(phase * 0.73) * radius * (0.22 + (i % 3) * 0.12))
            spark_r = 2 + (i % 3)
            spark_col = (255, 225, 120) if i % 2 else (255, 112, 35)
            pygame.draw.circle(screen, spark_col, (sx, sy), spark_r)
            pygame.draw.line(screen, (255, 145, 48), (sx - 7, sy), (sx + 8, sy - 2), 2)

        # Warm glow behind the ball.
        glow_size = radius * 3
        glow = pygame.Surface((glow_size, glow_size), pygame.SRCALPHA)
        pulse = int(38 + 14 * math.sin(t * 0.11))
        pygame.draw.circle(glow, (255, 105, 25, pulse),
                           (glow_size // 2, glow_size // 2), int(radius * 0.94))
        screen.blit(glow, (int(x - glow_size / 2), int(y - glow_size / 2)), special_flags=pygame.BLEND_RGBA_ADD)

        if self.menu_ball_sprite is not None:
            # Rotozoom rotates the actual ball artwork continuously without altering menu controls.
            spinning = pygame.transform.rotozoom(self.menu_ball_sprite, -(t * 6.0), 1.0)
            screen.blit(spinning, spinning.get_rect(center=(int(x), int(y))))
        else:
            # Fallback football drawing if the embedded sprite cannot be decoded.
            pygame.draw.circle(screen, (244, 248, 255), (int(x), int(y)), radius)
            pygame.draw.circle(screen, (9, 20, 37), (int(x), int(y)), radius, 7)
            for i in range(5):
                a = t * 0.10 + i * math.tau / 5
                px = int(x + math.cos(a) * radius * 0.43)
                py = int(y + math.sin(a) * radius * 0.43)
                pygame.draw.circle(screen, (13, 28, 50), (px, py), int(radius * 0.23))

    def draw_menu_bg(self):
        """Shared animated stadium artwork for every non-match menu page."""
        if not hasattr(self, "menu_backdrop"):
            self.menu_backdrop = self.build_menu_backdrop()
        screen.blit(self.menu_backdrop, (0, 0))

        # Subtle dark edge shading keeps UI contrast high while preserving the stadium art.
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.rect(shade, (1, 5, 15, 44), (0, 0, W, H), border_radius=0)
        screen.blit(shade, (0, 0))

        self.draw_menu_ball()

        # Existing ambient particles continue to drift above the shared background.
        self.fx_layer.fill((0, 0, 0, 0))
        for p in self.particles:
            p.draw(self.fx_layer)
        screen.blit(self.fx_layer, (0, 0))

    def draw_button(self, base_rect, selected, name, desc):
        t = self.menu_t
        rect = base_rect.copy()
        try:
            idx = self.menu_rects.index(base_rect)
        except ValueError:
            idx = 0
        accents = ((65, 215, 255), (255, 174, 74), (175, 132, 255),
                   (255, 105, 130), (100, 238, 174))
        accent = accents[idx % len(accents)]
        if selected:
            grow = int(2 + math.sin(t * 0.14) * 1.5)
            rect.inflate_ip(grow * 2, grow)
            glow = pygame.Surface((rect.w + 24, rect.h + 18), pygame.SRCALPHA)
            glow_col = (*accent, int(22 + 12 * (0.5 + 0.5 * math.sin(t * 0.18))))
            pygame.draw.rect(glow, glow_col, glow.get_rect(), border_radius=20)
            screen.blit(glow, (rect.left - 12, rect.top - 9))

        # Deep layered card with a sharp broadcast-style accent edge.
        pygame.draw.rect(screen, (2, 7, 15), rect.move(0, 6), border_radius=17)
        fill = (19, 39, 58) if selected else (10, 23, 38)
        pygame.draw.rect(screen, fill, rect, border_radius=17)
        inner = rect.inflate(-4, -4)
        pygame.draw.rect(screen, (28, 54, 75) if selected else (17, 34, 51),
                         inner, 1, border_radius=14)
        pygame.draw.rect(screen, accent if selected else (48, 78, 99), rect,
                         2 if selected else 1, border_radius=17)
        pygame.draw.line(screen, (*accent,), (rect.left + 22, rect.top + 2),
                         (rect.right - 22, rect.top + 2), 2 if selected else 1)

        # Number plate and moving selection marker.
        tag = pygame.Rect(rect.left + 15, rect.top + 10, 50, rect.h - 20)
        pygame.draw.rect(screen, (5, 16, 28), tag, border_radius=10)
        pygame.draw.rect(screen, accent if selected else (55, 88, 111), tag, 1, border_radius=10)
        number = f"{(idx + 1):02d}"
        draw_text(screen, self.small_font, number,
                  accent if selected else (145, 169, 187), tag.center, shadow=False)
        if selected:
            bar_h = max(16, int((rect.h - 16) * (0.72 + 0.18 * math.sin(t * 0.17))))
            pygame.draw.rect(screen, accent,
                             (rect.left + 5, rect.centery - bar_h // 2, 4, bar_h),
                             border_radius=3)

        name_y = rect.top + int(rect.h * 0.34)
        desc_y = rect.top + int(rect.h * 0.75)
        text_color = WHITE if selected else (224, 234, 242)
        draw_text(screen, self.menu_font, name, text_color,
                  (rect.centerx + 5, name_y), shadow=False)
        draw_text(screen, self.small_font, desc, (167, 190, 207),
                  (rect.centerx + 5, desc_y), shadow=False)
        # A crisp chevron makes the card feel like a selectable game tile.
        cx, cy = rect.right - 25, rect.centery
        chevron_col = accent if selected else (102, 130, 151)
        pygame.draw.line(screen, chevron_col, (cx - 5, cy - 7), (cx + 2, cy), 2)
        pygame.draw.line(screen, chevron_col, (cx + 2, cy), (cx - 5, cy + 7), 2)

    def draw_menu(self):
        t = self.menu_t
        self.draw_menu_bg()

        # Animated match showcase: two kit-clad players keep the title screen alive.
        ground = H - 70
        phase = t * 0.028
        lx, rx = 185, W - 185
        bx = W / 2 + math.sin(phase) * (W / 2 - 245)
        height = abs(math.cos(phase)) * 155
        for p, px, face in ((self.menu_p1, lx, 1.0), (self.menu_p2, rx, -1.0)):
            p.x = px
            p.y = ground - 15 + math.sin(t * 0.07 + (0 if face > 0 else 1.5)) * 3
            p.facing_x, p.facing_y = face, 0.0
            p.kick_timer = 6.0 if abs(math.cos(phase)) < 0.1 and (bx - W / 2) * face < 0 else 0.0
        self.menu_p1.draw(screen)
        self.menu_p2.draw(screen)

        # Large esports-style masthead.
        title_plate = pygame.Rect(W // 2 - 360, 24, 720, 124)
        plate = pygame.Surface((title_plate.w, title_plate.h), pygame.SRCALPHA)
        pygame.draw.rect(plate, (3, 10, 22, 218), plate.get_rect(), border_radius=25)
        pygame.draw.rect(plate, (70, 195, 229, 155), plate.get_rect(), 2, border_radius=25)
        pygame.draw.line(plate, (255, 183, 74, 170), (28, 5), (title_plate.w - 28, 5), 3)
        screen.blit(plate, title_plate.topleft)
        draw_text(screen, self.tiny_font, "THE ARCADE FOOTBALL ARENA",
                  (156, 207, 226), (W // 2, 43), shadow=False)
        words = [("HYPER", (99, 220, 255)), ("SOCCER", (255, 158, 104))]
        total_w = sum(self.title_font.size(w)[0] for w, _ in words) + 30
        cx = W // 2 - total_w // 2
        for word, col in words:
            for ch in word:
                gw = self.title_font.size(ch)[0]
                k = (cx - W // 2) * 0.012
                yo = math.sin(t * 0.05 + k) * 3
                img = self.title_font.render(ch, True, col)
                glow = self.title_font.render(ch, True, col)
                glow.set_alpha(58)
                screen.blit(glow, (cx + 2, 60 + yo + 2))
                sh = self.title_font.render(ch, True, (0, 0, 0))
                sh.set_alpha(190)
                screen.blit(sh, (cx + 3, 60 + yo + 4))
                screen.blit(img, (cx, 60 + yo))
                cx += gw
            cx += 30
        pygame.draw.line(screen, (80, 204, 239), (W // 2 - 250, 151),
                         (W // 2 + 250, 151), 2)
        draw_text(screen, self.small_font, "PICK A MODE. OWN THE MATCH.",
                  (217, 231, 241), (W // 2, 168), shadow=False)

        # Compact, high-contrast navigation chips along the top corners.
        nav_items = ((self.customize_rect, "KIT LAB", (255, 202, 91)),
                     (self.upgrade_rect, f"UPGRADES  {self.profile['coins']} C", (116, 238, 173)),
                     (self.settings_rect, "SETTINGS", (92, 215, 255)))
        for rect, label, accent in nav_items:
            hover = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (3, 9, 18), rect.move(0, 4), border_radius=12)
            pygame.draw.rect(screen, (19, 34, 51) if not hover else (28, 54, 72),
                             rect, border_radius=12)
            pygame.draw.rect(screen, accent if hover else (67, 100, 123), rect,
                             2 if hover else 1, border_radius=12)
            pygame.draw.rect(screen, accent, (rect.left + 8, rect.top + 9, 4, rect.h - 18),
                             border_radius=2)
            draw_text(screen, self.small_font, label, accent if hover else WHITE,
                      rect.center, shadow=False)

        # Small live status strip above the mode cards.
        strip = pygame.Rect(W // 2 - 160, 180, 320, 20)
        pygame.draw.rect(screen, (4, 14, 25), strip, border_radius=8)
        pygame.draw.circle(screen, (95, 235, 165), (strip.left + 13, strip.centery), 4)
        draw_text(screen, self.tiny_font, "ARCADE MODES  /  SEASON 01",
                  (161, 190, 208), (strip.centerx + 8, strip.centery), shadow=False)

        options = [
            ("1 V 1", "Play against another player on this device"),
            ("1 V BOT", "Take on the computer and test your skills"),
            ("ONLINE PARTY", "Create a room or join a friend's party"),
            ("PENALTY SHOOTOUTS", "Pick your shot. Beat the goalkeeper"),
            ("2V2 SQUAD", "You and an AI teammate vs a rival AI duo"),
        ]
        for i, (name, description) in enumerate(options):
            self.draw_button(self.menu_rects[i], self.menu_selection == i, name, description)

        music_label = "MUSIC: ON" if self.sound.music_enabled else "MUSIC: OFF"
        effects_label = "SFX: ON" if self.sound.on else "SFX: OFF"
        footer = f"TAP A MODE TO PLAY     {music_label}  [B]     {effects_label}  [N]     F11 FULLSCREEN"
        draw_text(screen, self.tiny_font, footer, (179, 201, 216), (W // 2, H - 19), shadow=False)
        if WEB_BUILD and self.net_msg:
            draw_text(screen, self.small_font, self.net_msg, GOLD, (W // 2, H - 45))

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
        # Twelve compact colour swatches per player, centred at every canvas width.
        row_width = (len(KITS) - 1) * 82 + 72
        left = (W - row_width) // 2
        return [[pygame.Rect(left + i * 82, 245 + side * 80, 72, 68)
                 for i in range(len(KITS))] for side in range(2)]

    def shape_card_rects(self):
        row_width = (len(self.shape_options) - 1) * 116 + 108
        left = (W - row_width) // 2
        return [[pygame.Rect(left + i * 116, 400 + side * 42, 108, 34)
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
        draw_text(screen, self.big_font, "SETTINGS", WHITE, (W // 2, 67))
        draw_text(screen, self.tiny_font, "TAP ANY SETTING TO CHANGE IT",
                  (153, 191, 211), (W // 2, 111), shadow=False)

        for i, (name, hint) in enumerate(self.SET_ROWS):
            r = self.set_row_rect(i)
            sel = i == self.set_sel
            pygame.draw.rect(screen, (3, 8, 16), r.move(0, 4), border_radius=14)
            pygame.draw.rect(screen, (21, 43, 62) if sel else (11, 25, 40), r,
                             border_radius=14)
            pygame.draw.rect(screen, (78, 211, 247) if sel else (54, 86, 108),
                             r, 2 if sel else 1, border_radius=14)
            pygame.draw.rect(screen, (255, 190, 81) if i in (3, 4) else (74, 197, 232),
                             (r.left + 8, r.top + 10, 4, r.h - 20), border_radius=2)
            draw_text(screen, self.small_font, name, WHITE if sel else (205, 220, 231),
                      (r.left + 24, r.top + 26), anchor="midleft", shadow=False)
            draw_text(screen, self.tiny_font, hint, (150, 173, 192),
                      (r.left + 24, r.top + 54), anchor="midleft", shadow=False)
            val = self.settings_text(i)

            if i in (1, 3, 4):
                # Large ON/OFF switch, with a clear state for touch users.
                sw = pygame.Rect(r.right - 112, r.centery - 17, 92, 34)
                enabled = (self.settings["pu"] if i == 1 else
                           self.sound.on if i == 3 else self.sound.music_enabled)
                audio_unavailable = i in (3, 4) and not self.sound.ok
                track = ((54, 66, 78) if audio_unavailable else
                         (35, 151, 105) if enabled else (83, 93, 107))
                pygame.draw.rect(screen, track, sw, border_radius=17)
                pygame.draw.rect(screen, (210, 230, 239), sw, 1, border_radius=17)
                if audio_unavailable:
                    draw_text(screen, self.tiny_font, "NO AUDIO", WHITE,
                              sw.center, shadow=False)
                else:
                    knob_x = sw.right - 17 if enabled else sw.left + 17
                    pygame.draw.circle(screen, (245, 250, 252), (knob_x, sw.centery), 12)
                    draw_text(screen, self.tiny_font, "ON" if enabled else "OFF",
                              WHITE, (sw.centerx, sw.centery), shadow=False)
            else:
                cx = r.right - 122
                font = self.font if len(val) <= 6 else self.small_font
                draw_text(screen, font, val, GOLD if sel else WHITE,
                          (cx, r.centery), shadow=False)
                if sel:
                    bump = int(math.sin(self.menu_t * 0.2) * 2)
                    draw_text(screen, self.font, "<", GOLD, (cx - 95 - bump, r.centery), shadow=False)
                    draw_text(screen, self.font, ">", GOLD, (cx + 95 + bump, r.centery), shadow=False)

        panel = pygame.Rect(620, 150, max(360, W - 670), 470)
        pygame.draw.rect(screen, (7, 17, 29), panel, border_radius=18)
        pygame.draw.rect(screen, (61, 99, 125), panel, 2, border_radius=18)
        draw_text(screen, self.small_font, "HOW TO PLAY", GOLD, (panel.centerx, panel.top + 28),
                  shadow=False)
        lines = (("MOVE", "WASD OR ARROW KEYS"),
                 ("SHOOT", "E OR P  -  HOLD FOR MORE POWER"),
                 ("TACKLE", "R OR L  -  STEAL THE BALL"),
                 ("DASH", "SHIFT  -  USES STAMINA"))
        for i, (a, b) in enumerate(lines):
            y = panel.top + 68 + i * 30
            draw_text(screen, self.tiny_font, a, BLUE_LIGHT, (panel.left + 30, y),
                      anchor="midleft", shadow=False)
            draw_text(screen, self.tiny_font, b, WHITE, (panel.left + 130, y),
                      anchor="midleft", shadow=False)
        draw_text(screen, self.tiny_font, "1 V 1:  BLUE = WASD  E  R  LSHIFT",
                  (170, 185, 200), (panel.left + 30, panel.top + 198), anchor="midleft", shadow=False)
        draw_text(screen, self.tiny_font, "RED = ARROWS  P  L  RSHIFT",
                  (170, 185, 200), (panel.left + 30, panel.top + 220), anchor="midleft", shadow=False)
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
            draw_text(screen, self.tiny_font, descs[t], (205, 215, 225),
                      (panel.left + 90, ry + 11), anchor="midleft", shadow=False)
        draw_text(screen, self.tiny_font, "TIED AT FULL TIME  =  GOLDEN GOAL  (NEXT GOAL WINS)",
                  WHITE, (panel.centerx, panel.bottom - 22), shadow=False)
        draw_text(screen, self.tiny_font,
                  "TAP A ROW OR USE LEFT / RIGHT TO CHANGE  •  B MUSIC  •  N SOUND EFFECTS",
                  (179, 201, 216), (W // 2, H - 24), shadow=False)

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

      if not WEB_BUILD:
        panel = pygame.Rect(W // 2 - 310, 130, 620, 270)
        pygame.draw.rect(screen, UI, panel, border_radius=18)
        pygame.draw.rect(screen, UI_LIGHT, panel, 2, border_radius=18)
        draw_text(
            screen,
            self.tiny_font,
            "PARTIES ON YOUR NETWORK",
            (170, 185, 180),
            (panel.centerx, panel.top + 22),
            shadow=False,
        )

        lst = self.lan_list()
        if not lst:
          dots = "." * (1 + int(t * 0.05) % 3)
          draw_text(
              screen,
              self.small_font,
              "SEARCHING" + dots,
              (205, 215, 210),
              (panel.centerx, panel.top + 120),
              shadow=False,
          )
        for i, (addr, info) in enumerate(lst):
          rr = self.join_row_rect(i)
          sel = (i == self.join_sel) and not self.join_text
          pygame.draw.rect(
              screen, UI_LIGHT if sel else (28, 34, 41), rr, border_radius=12
          )
          pygame.draw.rect(
              screen, GOLD if sel else (70, 80, 86), rr, 2, border_radius=12
          )
          draw_text(
              screen,
              self.small_font,
              info["name"].upper(),
              WHITE,
              (rr.left + 18, rr.centery),
              anchor="midleft",
              shadow=False,
          )
          status = (
              f"{info['n']}/2 PLAYERS" if info["ph"] == "lobby" else "IN A MATCH"
          )
          draw_text(
              screen,
              self.tiny_font,
              status,
              GOLD if info["ph"] == "lobby" else RED_LIGHT,
              (rr.right - 18, rr.centery),
              anchor="midright",
              shadow=False,
          )

      box = pygame.Rect(
          W // 2 - 310, 260 if WEB_BUILD else 440, 620, 84 if WEB_BUILD else 70
      )
      pygame.draw.rect(screen, UI_LIGHT, box, border_radius=16)
      pygame.draw.rect(
          screen,
          GOLD if self.join_text else (90, 100, 105),
          box,
          3,
          border_radius=16,
      )
      hint = (
          "TAP HERE TO ENTER 5-LETTER ROOM CODE"
          if WEB_BUILD
          else "OR TYPE A PARTY CODE / IP ADDRESS  (CTRL+V TO PASTE)"
      )
      draw_text(
          screen,
          self.tiny_font,
          hint,
          (170, 185, 180),
          (box.centerx, box.top + 18),
          shadow=False,
      )
      caret = "|" if int(t * 0.08) % 2 == 0 else ""
      shown = (
          (self.join_text + caret)
          if (self.join_text or not WEB_BUILD)
          else "TAP TO TYPE CODE"
      )
      draw_text(
          screen,
          self.menu_font,
          shown,
          WHITE if self.join_text else (150, 165, 175),
          (box.centerx, box.top + 52),
          shadow=False,
      )

      if WEB_BUILD:
        join_btn = pygame.Rect(W // 2 - 170, 375, 340, 56)
        pygame.draw.rect(screen, (20, 65, 85), join_btn, border_radius=15)
        pygame.draw.rect(screen, GOLD, join_btn, 2, border_radius=15)
        draw_text(
            screen,
            self.font,
            "JOIN PARTY",
            GOLD,
            join_btn.center,
            shadow=False,
        )

      if self.net_msg:
        col = GOLD if self.net_msg.startswith("Connecting") else RED_LIGHT
        draw_text(screen, self.small_font, self.net_msg, col, (W // 2, 545))
      draw_text(
          screen,
          self.small_font,
          "ENTER  JOIN      UP / DOWN  PICK A PARTY      ESC  BACK",
          WHITE,
          (W // 2, H - 36),
      )


    def draw_lobby(self):
        t = self.menu_t
        self.draw_menu_bg()
        host = self.mode == "host"
        draw_text(screen, self.big_font, "2V2 PARTY LOBBY", WHITE, (W // 2, 48))

        if host:
            draw_text(screen, self.tiny_font, "SHARE THIS PARTY CODE", (170, 185, 180),
                      (W // 2, 94), shadow=False)
            draw_text(screen, self.title_font, self.party_code, GOLD, (W // 2, 132))
        else:
            draw_text(screen, self.small_font,
                      f"CONNECTED TO {self.lobby_names[0].upper() or 'HOST'}",
                      (220, 235, 220), (W // 2, 112), shadow=False)
            if self.ping:
                draw_text(screen, self.tiny_font, f"PING {int(self.ping)} MS",
                          (170, 185, 180), (W // 2, 140), shadow=False)

        # Build the preview lineup: every unclaimed squad slot is an AI teammate.
        host_slot, guest_slot = self.online_slot_layout()
        preview = ["AI TEAMMATE", "AI TEAMMATE", "AI TEAMMATE", "AI TEAMMATE"]
        if self.squad_mode:
            preview[host_slot] = (self.name + "  ·  YOU") if host else (self.lobby_names[0] or "HOST")
            if guest_slot >= 0:
                preview[guest_slot] = (self.guest_name or self.name) if host else (self.name + "  ·  YOU")
        else:
            preview = ["NOT USED", "NOT USED", "NOT USED", "NOT USED"]
            preview[0] = (self.name + "  ·  YOU") if host else (self.lobby_names[0] or "HOST")
            preview[1] = (self.guest_name or "GUEST") if host else (self.name + "  ·  YOU")

        card_w = min(545, (W - 150) // 2)
        card_gap = 44
        card_left = (W - (2 * card_w + card_gap)) // 2
        self.lobby_blue_rect = pygame.Rect(card_left, 190, card_w, 220)
        self.lobby_red_rect = pygame.Rect(card_left + card_w + card_gap, 190, card_w, 220)
        for team, rect, col, light, title in (
                (0, self.lobby_blue_rect, BLUE_DARK, BLUE_LIGHT, "BLUE TEAM"),
                (1, self.lobby_red_rect, RED_DARK, RED_LIGHT, "RED TEAM")):
            selected = ((self.host_team if host else self.guest_team) == team
                        if self.squad_mode else team == (0 if host else 1))
            pygame.draw.rect(screen, (16, 26, 39), rect, border_radius=20)
            pygame.draw.rect(screen, light if selected else col, rect, 4 if selected else 2,
                             border_radius=20)
            draw_text(screen, self.font, title, light, (rect.centerx, rect.top + 36))
            slots = (0, 2) if team == 0 else (1, 3)
            for row, slot in enumerate(slots):
                y = rect.top + 92 + row * 58
                is_unused = preview[slot] == "NOT USED"
                is_ai = preview[slot].startswith("AI")
                badge_col = (110, 120, 130) if is_unused else ((145, 160, 175) if is_ai else light)
                pygame.draw.circle(screen, badge_col, (rect.left + 50, y), 13)
                draw_text(screen, self.small_font, f"{row + 1}.", WHITE,
                          (rect.left + 50, y), shadow=False)
                draw_text(screen, self.small_font, preview[slot],
                          (185, 198, 208) if is_ai else light,
                          (rect.left + 82, y), anchor="midleft", shadow=False)
                slot_type = "OFF" if is_unused else ("AI" if is_ai else "HUMAN")
                draw_text(screen, self.tiny_font, slot_type,
                          (110, 120, 130) if is_unused else ((145, 160, 175) if is_ai else light),
                          (rect.right - 22, y), anchor="midright", shadow=False)
            if selected:
                draw_text(screen, self.tiny_font,
                          "YOUR TEAM  ·  TAP TO CHANGE" if not host else "YOUR TEAM  ·  TAP TO CHANGE",
                          GOLD, (rect.centerx, rect.bottom - 17), shadow=False)
            else:
                draw_text(screen, self.tiny_font, "TAP TO CHOOSE THIS TEAM",
                          (170, 185, 195), (rect.centerx, rect.bottom - 17), shadow=False)

        draw_text(screen, self.font, "VS", WHITE, (W // 2, 295))
        self.lobby_squad_rect = pygame.Rect(W // 2 - 210, 422, 420, 46)
        if host:
            mode_label = "2V2 HYBRID  ·  AI FILLS OPEN SLOTS" if self.squad_mode else "CLASSIC 1V1"
            mode_col = GOLD if self.squad_mode else (180, 200, 215)
            pygame.draw.rect(screen, (14, 28, 43), self.lobby_squad_rect, border_radius=12)
            pygame.draw.rect(screen, mode_col, self.lobby_squad_rect, 2, border_radius=12)
            draw_text(screen, self.tiny_font, mode_label + "  ·  TAP / F TO TOGGLE",
                      mode_col, self.lobby_squad_rect.center, shadow=False)
        else:
            draw_text(screen, self.small_font, "AI AUTOMATICALLY FILLS ANY EMPTY SQUAD SLOTS",
                      (180, 200, 215), (W // 2, 445), shadow=False)

        if host:
            if self.guest_addr:
                ready_text = "GUEST READY — START ONLINE MATCH" if self.guest_ready else "WAITING FOR GUEST TO READY UP..."
                start_label = "START ONLINE MATCH"
                start_enabled = self.guest_ready
            else:
                ready_text = "NO GUEST YET — AI WILL FILL ALL THREE OPEN SLOTS"
                start_label = "PLAY WITH AI"
                start_enabled = True
            draw_text(screen, self.tiny_font, ready_text,
                      (110, 230, 130) if start_enabled else (205, 215, 210),
                      (W // 2, 478), shadow=False)
            self.lobby_start_rect = pygame.Rect(W // 2 - 170, 505, 340, 54)
            pygame.draw.rect(screen, (20, 65, 85) if start_enabled else (42, 48, 54),
                             self.lobby_start_rect, border_radius=15)
            pygame.draw.rect(screen, GOLD if start_enabled else (100, 110, 118),
                             self.lobby_start_rect, 2, border_radius=15)
            draw_text(screen, self.font, start_label, GOLD if start_enabled else (160, 170, 175),
                      self.lobby_start_rect.center, shadow=False)
        else:
            self.lobby_ready_rect = pygame.Rect(W // 2 - 170, 505, 340, 54)
            ready_label = "UNREADY" if self.my_ready else "READY UP"
            pygame.draw.rect(screen, (20, 65, 85) if not self.my_ready else (25, 85, 55),
                             self.lobby_ready_rect, border_radius=15)
            pygame.draw.rect(screen, GOLD, self.lobby_ready_rect, 2, border_radius=15)
            draw_text(screen, self.font, ready_label, GOLD, self.lobby_ready_rect.center, shadow=False)

        if self.net_msg:
            draw_text(screen, self.small_font, self.net_msg, RED_LIGHT, (W // 2, 574))
        if host:
            help_text = ("CLICK BLUE / RED TO CHOOSE YOUR TEAM  ·  F TO TOGGLE 1V1 / 2V2  ·  ESC TO LEAVE"
                         if self.squad_mode else "F TO ENABLE 2V2 TEAM SELECTION  ·  ESC TO LEAVE")
        else:
            help_text = ("CLICK BLUE / RED TO CHOOSE YOUR TEAM  ·  SPACE TO READY  ·  ESC TO LEAVE"
                         if self.squad_mode else "WAIT FOR HOST TO ENABLE 2V2  ·  SPACE TO READY  ·  ESC TO LEAVE")
        draw_text(screen, self.tiny_font, help_text, WHITE, (W // 2, H - 24), shadow=False)

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
            controls_text = ("MOVE: WASD / ARROWS  -  SHOOT: E / P  -  TACKLE: R / L  -  DASH: SHIFT  -  SKILL: Q")
        elif self.mode == "pvp":
            controls_text = ("BLUE: WASD MOVE - E SHOOT (HOLD = POWER) - R TACKLE - LSHIFT DASH     "
                             "RED: ARROWS - P SHOOT (HOLD) - L TACKLE - RSHIFT DASH")
        else:
            controls_text = ("MOVE: WASD / ARROWS  -  SHOOT: E / P  -  TACKLE: R / L  -  DASH: SHIFT  -  SKILL: Q"
                             "     RED: BOT")

        control_panel = pygame.Rect(W // 2 - 520, H - 58, 1040, 40)
        pygame.draw.rect(screen, UI, control_panel, border_radius=12)
        draw_text(screen, self.tiny_font, controls_text, WHITE, control_panel.center, shadow=False)

        if self.squad_mode:
            draw_text(screen, self.tiny_font, "2V2 HYBRID  ·  AI FILLS OPEN SLOTS", GOLD,
                      (W // 2, 13), shadow=False)
        if online:
            ping = self.ping if self.mode == "client" else self.guest_ping
            if ping:
                pc = (110, 230, 130) if ping < 80 else (GOLD if ping < 150 else RED_LIGHT)
                draw_text(screen, self.tiny_font, f"PING {int(ping)} MS", pc, (76, 29),
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
        self.draw_menu_bg()
        t = self.ui_t

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
        self.draw_menu_bg()
        t = self.ui_t
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
        if not self.goal_replays:
            self.draw_menu_bg()
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
        replay_actors = [self.replay_actor1, self.replay_actor2]
        if frame.get("p3") and frame.get("p4"):
            if self.replay_actor3 is None:
                self.replay_actor3 = Player(frame["p3"]["x"], frame["p3"]["y"],
                                            self.p3.color, self.p3.dark_color,
                                            self.p3.light_color, False)
                self.replay_actor3.accent_color = self.p3.accent_color
                self.replay_actor3.kit_name = self.p3.kit_name
                self.replay_actor3.shape = self.p3.shape
            if self.replay_actor4 is None:
                self.replay_actor4 = Player(frame["p4"]["x"], frame["p4"]["y"],
                                            self.p4.color, self.p4.dark_color,
                                            self.p4.light_color, True)
                self.replay_actor4.accent_color = self.p4.accent_color
                self.replay_actor4.kit_name = self.p4.kit_name
                self.replay_actor4.shape = self.p4.shape
            apply_state(self.replay_actor3, frame["p3"])
            apply_state(self.replay_actor4, frame["p4"])
            replay_actors.extend((self.replay_actor3, self.replay_actor4))

        for keeper, key in ((self.replay_keeper_left, "kl"),
                            (self.replay_keeper_right, "kr")):
            ks = frame.get(key)
            if ks and len(ks) >= 6:
                keeper.y, keeper.vy, keeper.dive_timer = float(ks[0]), float(ks[1]), float(ks[2])
                keeper.dive_dir, keeper.save_flash, keeper.animation = map(float, ks[3:6])

        self.fx_layer.fill((0, 0, 0, 0))
        trail = frame.get("trail", [])
        for i, (tx, ty) in enumerate(trail):
            alpha = int(25 + 115 * (i + 1) / max(1, len(trail)))
            rr = max(2, int(13 * (i + 1) / max(1, len(trail))))
            pygame.draw.circle(self.fx_layer, (238, 247, 255, alpha), (int(tx), int(ty)), rr)
        cv.blit(self.fx_layer, (0, 0))

        self.replay_keeper_left.draw(cv)
        self.replay_keeper_right.draw(cv)
        for actor in sorted(replay_actors, key=lambda q: q.y):
            actor.draw(cv)
        draw_ball(cv, frame["bx"], frame["by"] - float(frame.get("bl", 0.0)),
                  13, frame["br"], ground_y=frame["by"])

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


    def draw_virtual_stick(self, side):
        cx, cy = self.joystick_center(side)
        vx, vy = self.joystick_values[side]
        if self.mode == "host":
            local = self.match_players()[int(clamp(self.host_slot, 0, len(self.match_players()) - 1))]
            col = RED_LIGHT if local.is_p2 else BLUE_LIGHT
        elif self.mode == "client":
            local = self.match_players()[int(clamp(self.local_slot, 0, len(self.match_players()) - 1))]
            col = RED_LIGHT if local.is_p2 else BLUE_LIGHT
        else:
            col = BLUE_LIGHT if side == "p1" else RED_LIGHT
        radius = 62
        knob_x = int(cx + vx * 29)
        knob_y = int(cy + vy * 29)

        pygame.draw.circle(screen, (4, 11, 22), (cx, cy), radius + 9)
        pygame.draw.circle(screen, (27, 49, 66), (cx, cy), radius + 5, 3)
        pygame.draw.circle(screen, (20, 31, 47), (cx, cy), radius)
        pygame.draw.circle(screen, (135, 169, 193), (cx, cy), radius, 2)
        # Twelve notches give the stick the segmented hardware look.
        for i in range(12):
            ang = i * math.tau / 12
            inner, outer = radius - 6, radius + 2
            a = (int(cx + math.cos(ang) * inner), int(cy + math.sin(ang) * inner))
            b = (int(cx + math.cos(ang) * outer), int(cy + math.sin(ang) * outer))
            pygame.draw.line(screen, (205, 225, 238), a, b, 3)
        pygame.draw.circle(screen, (5, 10, 20), (cx, cy), 36)
        pygame.draw.circle(screen, (54, 89, 114), (cx, cy), 34, 3)
        pygame.draw.circle(screen, (116, 139, 158), (cx, cy), 27)
        pygame.draw.circle(screen, (38, 49, 64), (cx, cy), 22)
        pygame.draw.circle(screen, (220, 232, 241), (cx - 7, cy - 8), 7)

        # Thumb knob moves within the well with the player's analog direction.
        pygame.draw.circle(screen, (5, 12, 24), (knob_x, knob_y), 21)
        pygame.draw.circle(screen, col, (knob_x, knob_y), 21, 2)
        pygame.draw.circle(screen, (145, 177, 197), (knob_x, knob_y), 15)
        pygame.draw.circle(screen, (45, 58, 75), (knob_x, knob_y), 12)
        pygame.draw.circle(screen, (225, 238, 247), (knob_x - 5, knob_y - 6), 4)
        draw_text(screen, self.tiny_font, "MOVE", (206, 225, 238),
                  (cx, cy + 84), shadow=True)

    def draw_action_button(self, name, rect, side, label):
        active = name in self.touch_held
        if self.mode == "host":
            owner = self.match_players()[int(clamp(self.host_slot, 0, len(self.match_players()) - 1))]
        elif self.mode == "client":
            owner = self.match_players()[int(clamp(self.local_slot, 0, len(self.match_players()) - 1))]
        else:
            owner = self.p2 if side == "p2" else self.p1
        if name.endswith("_skill"):
            active = active or owner.special_armed
        col = RED_LIGHT if owner.is_p2 else BLUE_LIGHT
        radius = min(rect.w, rect.h) // 2
        cx, cy = rect.center
        pygame.draw.circle(screen, (17, 34, 52), (cx, cy), radius + 7, 2)
        pygame.draw.circle(screen, (15, 27, 43), (cx, cy), radius)
        pygame.draw.circle(screen, col if active else (93, 125, 149),
                           (cx, cy), radius, 3)
        pygame.draw.circle(screen, (210, 229, 242), (cx, cy), max(5, radius - 8), 1)
        if active:
            pygame.draw.circle(screen, col, (cx, cy), radius - 4, 2)
        draw_text(screen, self.tiny_font, label, WHITE if active else (222, 234, 242),
                  (cx, cy), shadow=False)

    def draw_touch_controls(self):
        if (not self.touch_controls_enabled
                or self.state not in ("play", "countdown", "goal")):
            return
        self.draw_virtual_stick("p1")
        if self.mode == "pvp":
            self.draw_virtual_stick("p2")
        labels = {"dash": "DASH", "tackle": "TACKLE", "shoot": "SHOOT", "skill": "SKILL"}
        for name, rect in self.touch_rects().items():
            side, action = name.split("_", 1)
            if self.mode == "host":
                player = self.match_players()[int(clamp(self.host_slot, 0, len(self.match_players()) - 1))]
            elif self.mode == "client":
                player = self.match_players()[int(clamp(self.local_slot, 0, len(self.match_players()) - 1))]
            else:
                player = self.p2 if side == "p2" else self.p1
            label = labels[action]
            if action == "skill":
                label = "CHIP" if player.special_kind == "chip" else "CURVE"
            self.draw_action_button(name, rect, side, label)

    def draw(self):
        if self.state == "menu":
            self.draw_menu()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "online_menu":
            self.draw_online_menu()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "join":
            self.draw_join()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "lobby":
            self.draw_lobby()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "settings":
            self.draw_settings()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "customize":
            self.draw_customize()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "upgrades":
            self.draw_upgrade_shop()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state in ("penalties", "penalty_finished"):
            self.draw_penalties()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "finished":
            self.draw_match_highlights()
            self.draw_back_button()
            self.draw_fade()
            pygame.display.flip()
            return
        if self.state == "replay":
            self.draw_replay_viewer()
            self.draw_back_button()
            pygame.display.flip()
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

        # Goalkeepers sit in the goal mouths and animate reactions/dive saves.
        self.keeper_left.draw(cv)
        self.keeper_right.draw(cv)
        for p in sorted(self.match_players(), key=lambda q: q.y):
            p.draw(cv)
            if self.squad_mode:
                slot = self.match_players().index(p)
                if slot < len(self.slot_is_human) and not self.slot_is_human[slot]:
                    draw_text(cv, self.tiny_font, "AI TEAMMATE", (225, 235, 242),
                              (int(p.x), int(p.y - p.radius - 26)), shadow=True)

        # Shot preview: a subtle aiming guide while charging, with a special
        # gold pulse when the shot reaches full power.
        for shooter in self.match_players():
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
            me_list = self.match_players()
            my_slot = self.host_slot if self.mode == "host" else self.local_slot
            me = me_list[int(clamp(my_slot, 0, len(me_list) - 1))]
            for slot, p in enumerate(me_list):
                if slot < len(self.slot_names):
                    name_col = BLUE_LIGHT if not p.is_p2 else RED_LIGHT
                    draw_text(cv, self.tiny_font, self.slot_names[slot], name_col,
                              (int(p.x), int(p.y - p.radius - 32)))
            bob = math.sin(self.ui_t * 0.15) * 3
            ax, ay = int(me.x), int(me.y - me.radius - 50 + bob)
            pygame.draw.polygon(cv, GOLD, [(ax - 7, ay - 8), (ax + 7, ay - 8), (ax, ay + 2)])

        screen.fill((10, 14, 12))
        screen.blit(cv, (offx, offy))

        self.draw_hud()
        self.draw_touch_controls()
        self.draw_game_back_button()
        self.draw_game_settings_button()
        self.draw_game_settings_overlay()
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

 