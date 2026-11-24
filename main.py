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

        /* Fullscreen is now controlled by the in-game button between Back and Settings.
           Keep the old DOM element hidden so it cannot cover gameplay on phones. */
        if (button) button.style.display = 'none';
        window._hs_toggle_fullscreen = enterOrExitFullscreen;
        window._hs_match_ui_active = false;

        /* The browser requires fullscreen to be requested directly in a user gesture.
           This canvas listener handles the visible in-game hit area before Pygame polls it. */
        function isInGameFullscreenZone(evt) {
          if (!canvas) return false;
          var rect = canvas.getBoundingClientRect();
          if (!rect.width || !rect.height) return false;
          var nx = (evt.clientX - rect.left) / rect.width;
          var ny = (evt.clientY - rect.top) / rect.height;
          return Math.abs(nx - 0.5) <= 0.045 && ny >= 0.012 && ny <= 0.105;
        }
        if (canvas && !canvas._hsFullscreenPointerBound) {
          canvas._hsFullscreenPointerBound = true;
          canvas.addEventListener('pointerdown', function(evt) {
            if (window._hs_match_ui_active && isInGameFullscreenZone(evt)) {
              enterOrExitFullscreen();
            }
          }, {passive: true});
        }

        if (rotateOverlay) {
          var rotateButton = rotateOverlay.querySelector('button');
          if (rotateButton) rotateButton.onclick = enterOrExitFullscreen;
        }

        function updateViewport() {
          sizeCanvas();
          var portrait = window.innerHeight > window.innerWidth;
          if (rotateOverlay) rotateOverlay.style.display = portrait ? 'flex' : 'none';
          if (button) button.style.display = 'none';
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
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQIBAQICAgICAgICAwUDAwMDAwYEBAMFBwYHBwcGBwcICQsJCAgKCAcHCg0KCgsM'
    'DAwMBwkODw0MDgsMDAz/2wBDAQICAgMDAwYDAwYMCAcIDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwM'
    'DAwMDAwMDAz/wgARCAMqBZ8DASIAAhEBAxEB/8QAHAAAAgIDAQEAAAAAAAAAAAAAAQIAAwQFBgcI/8QAGwEAAgMBAQEAAAAAAAAA'
    'AAAAAAECBAUDBgf/2gAMAwEAAhADEAAAAfgUMoZ235e4fSviZ5JGaDViQhLACSCkkAYQBhCSQJIAMWDaJSLJGtxHHejmsVw63H5O'
    'sOoxdLuOvNW2+B3r3nKNW1i2tWmyrAixVMrEhIqFkFQgQBUioUCoUCoUCoUApANlYd0uN+q6LnunKMJWsl0acrGVgdkcHdHCx0eU'
    'WdHB3Rwd0cLHQiq57qLbNTmbKtnKPLzLxKdyZ+B1fbhsozPopLR7hiJc4uPretfP1aDj0SPOPZBYASNGJHAhkZWusVa1tFW1WLRJ'
    'VC0BWLIFUsA644GsMBJbbLni2X47UpdeXSuEKaqysZWUiskazOr4jeNboERYWQeBXswFFuJjBsxh5QFQpIgBsqytijIRGJRsAo6u'
    'ndKGjXe4otZGAg0YFLQAWYFLMFQIBA6gNzpYPtH5TpCWQXg1aEDDAENAr5rsQW8HNYodhTxlZHrcTnC1t8XCLTKYhI8jJC14qNhs'
    '9p254uWw52KCbLVPGcLx6PFlbu0WAwWdOZEHTklWQWYFW2WRqV22PJ65ba6/dAViBYrcWKBEUjGQC6nku34nRzjAczSjozlYyOxn'
    'RgtauwLWV5RZ0cHdHCx0cGdLAchhX6DdX26GBxnoGosVuV9C5LtuVjFc3VblD0YPbhma0pzlULpy70m1WJHjVVeShPHGSEUZ1eXZ'
    'qa+l5Vs1i0RdYtDKxYArFoCsWKpLLczty12RZiON1AEegV15zrDgEDAEVwCBliKDAW6mSXV5PN9CJgyxkAVAAgKMXYANdkW4g8kY'
    'VrlkLEGyQJCSCiwAYsCnXbekWvdLhJLFGGjDhjBjgAiygBBAEdIHS7XhSPscTmYPd42ugX45IljwEZyCxyFZsIVl2CtngIcvc9+O'
    't3dsbME42TAXFGI71a6M/X9OQizP0GKRjxIJlCieIAcLGy9Ucc0YZs1bqgJRwMLprVLk06dBczNvquPVEK8evb8b1eg1snWkHI1o'
    '6s5OyMx3VxNYrisepmWulzjHsv6c6HzL+nLXWbGzpz1rbEEsI7Bh4myso08bEyNnzk+V2uUY3oFjSvYrFsCqWgKhcrKpaArrvVuu'
    'PuOvBdLk0z5VS2V7VQugY65IDGF6jqF+f24a7JyMCfO3EdePepbF59K1sUFDLGSq6gi2ICBlBQQhQQCyRDdBzuVLj1KVWKcEimAV'
    'YAVAKygmNko3htk1DsGIUZIQoMWAQFBgsAYuXUJJTcBeONSxDUyyEa5YQrLkKy5CsZChUXsCg3ElUbiFRtIVGxgqawhUbWZSbsh8'
    '8TZZ+RZ5giV+0kEOhAUGuxthpZ+OhGfftxbsjRzNLErytO9axJ2yqNWBIDhIDhAOyVgLZVAtlUCyVwVppkTMzNPLHHb4+Bu7lCzH'
    'fmLtLPu0Nebo9MeVifVnlWkdUeZdPpH5u0OiPOuQ3w0tkJ7Vde0e2YtGc1S24x7VXG2Wl51LtNbyicumfgA1bfq73avd85h4PTYF'
    'XQ1BY52nWLAJBYArFoCqWAEj2Sjc+z56/mVJembq1yyMrjhRUZOfZ5avPOunwytfYte1ULU59KlsVutLVTqFiorV0JhWVkVhBVq6'
    'gquoIrgEBESSAW22/L7/AK8MqAQsMsUIAAiFAilBxYoysAUC8AjV0oyRTagiKDLFCUXgHv12cDszBqY8EpcghchWzkKzZAouLzhU'
    'ztDoksIVG1gpa0hWbCFT5myuVcHYNIzUQVLJAVjBVBlAcputTttnHwFIxdmbXVbrWyuLmTh5t5go5dHiRpwsBokE4UA0UA8SA8SA'
    '8SA8S9qvY7zQ62bueS0sqzkkpXoysh2VkM6Oyx62kWPWw3c9HZrc/Z1Nd2ji53OaeJ2uq58cerVMtG+gYEQrKSgM6Hsml6LnNrz0'
    'zsIZ+tm6Lf5l/N5SWjK2KxZG6xbApFtakN/MPWxtYlwx9OkZCSnSc3Z2a+l2a6zrxzNbYlXuiuvDvWtiAqso1VlGiupNFsUKUuVT'
    'pW4MqGVkvjql3NMoapdrXE19t+MPIOtQNkmvkXn5WmvnHYvVq2ugt5o8uvSDQ3D2w194ZCCKQVgpqrKiQKDqgQKbgCNKwsWpgcKQ'
    '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'
    'psNzy8wvo3xmEeblkx/VI5MwsSQhLEQ8bpGNDIhBYZIKxq7Jc2EgmIM4sJGiyHrCyKZR2fonlRsY/rGp4BJ5j+W+7d3xl8dJ9e6S'
    't3+XZ6T59nepx+54Yvp94/NGN9Ner+VfOn098y/TlqHxpq+k1/n/AKdz2v7b3Lnn8x6Br/Wtn5D8kY+ZTi/StPj9jlOXnuP6dsOk'
    'PFavfXlHwE++Q7eCP7sjl4fb7OesfFx7Msp+OP6+r6eSn1mqZ5Y3p7h5cfTUOnm9noSLrwJ7jGjPkG6Wnh30Lbeuv31sya4dKoyR'
    'k8SQ6uytzk201k6cd5j6u/vWpG4ZPCejZd6+kychIzbn9PpuLycQnM1VDrGfW8pvMG/n62WSjo1yyMrZoIRiCRyF8gJQQAAVCSAM'
    'zt/PdpqZeIO54Xl1L1nPvXPQzeS+O8pXtSQyZVZCOz6nhX1c/wBDq4LMvVMmnrsyZww7jkcy5i+t+Sv3r673jHxPongPFfaPO/Uf'
    'O7/jWiYeL9mDG4dA8dyUksDRkhGKSFoEaFkaMyNGFCCBMLlPePCrNDC9E879P2+hheNxJg+3uapkrTW7TMp6c2K2SipZ+nOuZDOO'
    'M2W75YgzmccFtldLnqJu2nz0Tb6yXLnz0byhzTdK8+PMt07Sjy56uzrHkF7e2fFOn0N1vzzc11GXz4fOXefR+z50eI6rtMjY+b/D'
    '3qh+e8D7V9B/PXLHN9GvsvjmRx0vq75O+1fmPS8LwZNmT9JqlpkqmtMiprCOuWlKlrS41GyCUsU1aEAlpCo2SarsJiXPjCcM+/VR'
    're3c4e/HqG5aOPWWchIPrW5GOPWDkyPqzykhLqZyzKXTNz26719zsOC0NnP6TjPQvP8AM1q2eZ2qsaSii2wLtxoOsu5/HM8paCSy'
    'AhYgkchWXgMCCUUgAJAWSAwKuO96HgOp2sfnJ1nI5Wja1LV7V70PJXGpwuepwusxrHLINRg8g1lvJ7bgX06Po583u0szofbvJPWP'
    'deIfwX6M8MfHzw+jN4D3vm7+jGR5yfRGjDzaemKoeb5Hf0k+Rytxiomx5zXi77N8twVH2hvCkR71X4QDn74vgqJ/QE+fQQ9+Twn2'
    '21kdj6v5F8+6Xn/dKfCxgey94XwqJ+7nwote6nw11L26eJNE9pXxlk/YV8hK6eunyIxPXW8icj6wnlrD9PnmTN+lL500n6AOBYl3'
    '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'
    'dYrHxzrCoKod29XXk/C2jo5MTk37gnyOe4ud0grrvuFT4nFVsFNX/J3D4qvw+WkdZ27uPcVm6QHQCZI9nYNkKsv0mAcnU9K/i36o'
    '4Y53qnA/RTUk0Xbb0A4g3CppxVtse2Pqo28Vb+mkCdEUNCsTtJDHMOFk1NKB9Pcjco8SmAyydYe9WpJ93UP0UtDMzW1xxCIW7csQ'
    'F8so70VBTZhnfuUm7r6N4IVNjZmgVUXMfcFGof3rajvarsPcrR8VkHHoUFWYHZXdk71XUmz+0j1YeUX7lT4xVxDLmzDg7UfVGrw6'
    'f7xFkPFn8FDBIp/uU7XHgeqf4VVh1VTG08Zb/wC8dyvyYdiMtFMJ4d4WNYfFWwedaL/cOHvWEv51gs9N3tVPSvllbEN5XlTM2nZH'
    'hsO5m/0Vlh+KbNnN6gZo/wBPgq/Ctm3b05zRn6fFDktyBX6N0CsyDkyokbuKLo5PWsB+idh9M7suLVJhEo1js74J8L2aPFlDKY3Z'
    'gqedtU3O3tDemm8L05qFFJL2QqWKB8JpS6536IijBsQ76LLRcXeA/lNZRn8Z8P7rZUvdJ9EIqb/N+hXN6f8Azh4FMoYndmYfVebe'
    'ErPFDC3HdIz/AJf2Xmabuc3/AJBeY6o7rH/cP5XmCv7o/qP5XmDEf8o+I/lHA8QG+Ep2E1o3xO8E6kqG743eBWwl9g+BWzfwPgiD'
    'wRfdRVEkfq3WTqmKQfbN14hCkzi8Lr/qog58DonDUKnohbaTGwU9aP8AxpxJNzyTOzxByB9Dh9UG/YTdg/RV1E6nd+U7ir8l1dEc'
    'FS45XU4tHJpwOo+qOLUNR9+p7HizT6bkMGo6gXoqgfB/VP8ACrcDrqXWaM247x4rA8ZfQTXOrDvHFYXQRQVZfTm8Uw/9C8n6Hmc0'
    '9dU7o72+aqqh88zpZN59JQ4hJTHq7u8KehjqW7ei+be8I6aFZldAqyyOWzdwWyfwWyfwWxfwQp5PZK2EvsnwQhl9k+C2cnsnwQjk'
    '9k+C2UnsnwQgl9kobe1iL/FPoY39qO3wUOFOjfnp3W+KdATE7uJT5qaL8x+iqK2WXQnTgqeR0bw9qxGAPAqo9x3/ABWVAdKytyZ3'
    'cVtH+0fFc4m9s+JXOp/bd4lNxKrbuld4o4pW/wCaV5yrP8wrztV97/0XnOo4/QLzjN7vBc/lPc3wULpn9YtbbivOkcZtvWJB+e5N'
    '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'
    'euNo2RhSmbgMy7S5h9QFG2xVUCby/OtZPlReW0q0zvV8oXJfoxJNN6jMrGP5q8YLs1MOvL2qOG4YCK64QpRSJWZ0HfV74by3Ki02'
    '8OOphTUY1dBxMYn3xffGAjARq93kuWsfxGPSvf1DH1iY/qmPrU0P90xdPTP81Y+vPfCPrjnuEfWz/ImPTg/wCOe0f4I/9Mf9uNJu'
    'VP8ADF8rLmNKQlz4xfk1n+aL8np/nj6gr+ePqbv80fV3x4x6OYEfvxFhtbq+6zWAi4E6oLKE5oDXtipvPDSrwhLnRLSb0nnDbAmp'
    'Xnaxtih5biXnWj6qvygJm2JecTrqmioN8xk91Xgn5RblXpebb1WTQxZeacaPrJp8cPIhbarDjZqhWwwW3KInmtuNdsTWTX0WFt/G'
    'HsnoFkuL0e6GsntXOOiggJ2dIwMUsmm6EyGUAqakHdGpvW18xByjkBSZqVXpuNJXWz7MXrQk7Cqh90eka/nEelZ/qCPSNfziOcj+'
    'byYK90c1z+mqOY9/SV8o9G//AEV/KPRTH9Bfyj0Ez/QX8o+rTf8Ax3PlH1Wc/wCO58o+qTn/ABnPlH1Od/4znyj6nPf8Zz5R9Snv'
    '+M58oukZ/wD4y/lH7Pn/APjL+Ufs7KH/AB1R+zZ/+gY/ZOUf6MfsjKX9MfOP2PlL+mPnH7Hyl/In5x+x8o/yJ+cfsif/AJU/OP2T'
    'Pe5H/wAo/ZM7/wCH/wAo/ZM770f/ACj9kzf8zf8A8o/ZkwP4kfOP2e7/ADo+cfUT/UT84+pp/qpiz5q0RsLopFZVIlz/AJc3Z+GE'
    'WHUZMnGdYmHNI+I+UD9b/o9KsvduVeF34QtiWmZhySVzWXqKze4w5Lz7qmZMaTigaR5n+jUk0Am4zTied+avGC5NzDjx78BuGAjb'
    '5ddDjD+RMocYptFNLrJh+SWk6BtNmzS2PsujaFH8ItzToKvu0mM3KJzKNtL4DtslY1mA63zwI2cgPV6LTFpfOEedSwtDrdBtsuLZ'
    'VtQaRZmc1Ot7HRfHGsu5OdPWRh8otyM2xOIO02T8oRMFl1lxs6V1UrG+GsqS5AXg5TXDuU1Us0u7oedCrbTZo2eHeUjxjnI98Yjw'
    'vi5t07mzF0tNH/ZMaMjOH/ZMXZOmfgI+oODe4iPqiE730ReiUTvejSeyane6Y4zKWTG9yyYq7+kMm3T1RGl+lEv/AAtpjjP0kJ9l'
    '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'
    'Za6vdGlwEYJQsBGKGGsRNZehdhR/s9REXoK+Cghe2s+Ard06tW7KkTdam4yfCaCjFVpumua4pqWuEYvcQWlt+wtZVaYNJpO7rKx3'
    '41+dabPGt40PjX/LWmnxqfGtNnnXND5WsWvCtjz6jzKCLc/wuSVWtV/CU5+rqEbwqdSCUaQbrLULFN8yjFdlM9vOJJnaGGMmxSi3'
    'XHTw2pPwcXjYsJS4JTM11ojVBeHS73V/NuZhh1c3a+dyi/4G+sIqv7TFqsq54D+kiAGafFyuXyg3Fct0tYd0pVz1nrPWNNpWVlZW'
    'VlZWN1hL8H3L8H3L8H3F3tL8kvyRZxC3M+c+c+c+c+c+c+c+c+c+ctxD5AplRbS8os2AkbjRtlSsr3K9yvcr3K9yvcr3K9yvcr3K'
    '9yvcr3K9xz0nr4fKes9PBXlVObzUwxoM5Ysbjbb/APBMrKwaTCE5oyXvEHItaqfJ4XKXl4qhXAHKNIyFlazUwi8QPVbvOswMCaPE'
    'NLvaY3udMwfTtQWdOnU5mCzzz7HR9OJVAqr9yj5j9oiqo/hLsJHTHlshENUlZmZZRVoOxllLuHjCvgFNY41uGNRMBdCpS9oOmEVS'
    'YbWE3ExGILHtuxwPpiWxmAQaWqBzhd7hRgp7AsyJmmIE9JSD2ZTqBUZzlqOtnuFL+yKrRb6hyxDcamsSt5Qjt8602eNbxofGv+Wt'
    'NPjU+NabPOuaHxpmybIqItEWLFb4NHn9KXiqv9SYC9P1TmRU3WKj+gflA0xXQ0lpAxwNZYMNpC+EvWpc9HUW3zZ9SFRhr0SiHL1n'
    '6CAe+lyNyJTX8tsxFjRw5iNb4EVyJkeyExYMkdC1flHUEYepKtxizs/uHcpZwCAfotNfzSL4wH4WbikTZKYgyJcM8z5T5T5T5T5T'
    '5T5QVaS/CX4S/COTgnwnwmLaDnWV7le5XuV7le5XuV7le5XuV7lJi4q6MtYcD6lsAljS5tyz2ntPae09p7T28L9S/Uv1L9S/Uv1L'
    '9R6E9Cek9GejKViOxh8peLwa8IjSr/8AxXsigI0y1FTcfRtZNkQmala1LemPSfOX7iCy8wV7FaSv0ZgCJiDJgPDvG6v1cI35ERJx'
    'ElWhWFLyOzH7Fkmm1Rg++5n9vO8gur0VF7BS6Ox273gbBshLamZyJ88uZ4hkTQFixEoF2vjiEJo/gjhWFfUVax+Zah3L49xifa4I'
    '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'
)
MENU_BALL_ART_B64 = (
    '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'
    'TkSuQmCC'
)

# ============================================================
# FIELD / 2.5D MATCH RENDERING
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
    """Draw a smooth, shaded football with rotating panels and a soft ground shadow."""
    r = max(4, int(r))
    gx = int(x)
    gy = int(y if ground_y is None else ground_y)
    cx, cy = int(x), int(y)
    height = max(0.0, float(gy - cy))
    shadow_w = max(18, int(r * 2.55 * clamp(1.0 - height / 420.0, .52, 1.0)))
    shadow_h = max(5, int(r * .72 * clamp(1.0 - height / 420.0, .52, 1.0)))
    shadow_hi = pygame.Surface((shadow_w * 3, shadow_h * 3), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow_hi, (0, 0, 0, 95), (3, 3, shadow_w * 3 - 6, shadow_h * 3 - 6))
    shadow = pygame.transform.smoothscale(shadow_hi, (shadow_w, shadow_h))
    surf.blit(shadow, (gx - shadow_w // 2, gy + max(3, int(r * .38)) - shadow_h // 2))

    # Render the ball at 3x resolution, then downsample for clean edges on
    # both desktop and the phone canvas.
    ss = 3
    diameter = r * 2 + 8
    hi = pygame.Surface((diameter * ss, diameter * ss), pygame.SRCALPHA)
    cc = diameter * ss // 2
    rr = r * ss
    pygame.draw.circle(hi, (5, 10, 18, 220), (cc + ss, cc + ss), rr + ss)
    pygame.draw.circle(hi, (105, 119, 137), (cc, cc), rr + ss)
    pygame.draw.circle(hi, (202, 213, 225), (cc, cc), rr)
    pygame.draw.circle(hi, (246, 249, 253), (cc - int(rr * .10), cc - int(rr * .13)), int(rr * .91))

    # Soft lower-right shading gives the ball a rounded, glossy volume.
    shade = pygame.Surface(hi.get_size(), pygame.SRCALPHA)
    pygame.draw.ellipse(shade, (18, 31, 48, 92),
                        (cc - int(rr * .18), cc - int(rr * .05), int(rr * 1.12), int(rr * 1.14)))
    hi.blit(shade, (0, 0))

    # Rotating dark pentagon panels and subtle seam highlights.
    for i in range(5):
        a = rot + i * math.tau / 5.0
        px = cc + math.cos(a) * rr * .47
        py = cc + math.sin(a) * rr * .47
        pts = []
        for j in range(5):
            aa = a + j * math.tau / 5.0
            pts.append((int(px + math.cos(aa) * rr * .22),
                        int(py + math.sin(aa) * rr * .22)))
        pygame.draw.polygon(hi, (10, 18, 29), pts)
        pygame.draw.polygon(hi, (52, 68, 86), pts, max(1, ss))
        # Tiny highlight on one edge of each rotating panel.
        pygame.draw.aaline(hi, (125, 143, 161), pts[0], pts[1])

    pygame.draw.arc(hi, (255, 255, 255),
                    (cc - int(rr * .77), cc - int(rr * .82), int(rr * 1.46), int(rr * 1.48)),
                    math.radians(195), math.radians(305), max(1, int(rr * .075)))
    pygame.draw.circle(hi, (65, 79, 96), (cc, cc), rr, max(1, ss))
    pygame.draw.circle(hi, (255, 255, 255),
                       (cc - int(rr * .38), cc - int(rr * .43)), max(1, int(rr * .105)))

    sprite = pygame.transform.smoothscale(hi, (diameter, diameter))
    surf.blit(sprite, (cx - diameter // 2, cy - diameter // 2))


def field_depth_scale(y):
    """Scale objects by their distance from the near edge of the pitch."""
    depth = clamp((float(y) - FIELD_TOP) / max(1.0, FIELD_RECT.height), 0.0, 1.0)
    return 0.74 + 0.26 * depth


def project_field_point(x, y):
    """Project the flat physics coordinates onto a shallow 3D perspective pitch."""
    depth_scale = field_depth_scale(y)
    px = FIELD_RECT.centerx + (float(x) - FIELD_RECT.centerx) * depth_scale
    return int(round(px)), int(round(float(y)))


def draw_projected_line(surface, color, a, b, width=1):
    pa, pb = project_field_point(*a), project_field_point(*b)
    if int(width) <= 1:
        pygame.draw.aaline(surface, color, pa, pb)
    else:
        pygame.draw.line(surface, color, pa, pb, max(1, int(width)))


def draw_projected_rect(surface, color, rect, width=0):
    pts = [project_field_point(rect.left, rect.top),
           project_field_point(rect.right, rect.top),
           project_field_point(rect.right, rect.bottom),
           project_field_point(rect.left, rect.bottom)]
    if width:
        if int(width) <= 1:
            pygame.draw.aalines(surface, color, True, pts)
        else:
            pygame.draw.polygon(surface, color, pts, max(1, int(width)))
    else:
        pygame.draw.polygon(surface, color, pts)


def draw_3d_player(surface, player, projected=True):
    """Render the game's original shape mascot as a smooth, beveled 3D character.

    The six selectable silhouettes (ROUND/SQUARE/DIAMOND/HEXAGON/STAR/SHIELD)
    are preserved. A small supersampled sprite supplies clean edges, a dark
    extrusion, glossy face shading, eyes, shoes and the existing status effects.
    Set projected=False for menu/customization character previews.
    """
    if projected:
        x, ground_y = project_field_point(player.x, player.y)
        depth = field_depth_scale(player.y)
        # Physics coordinates describe the centre of the mascot; the rendered
        # sprite uses its feet as the ground anchor.
        ground_y += int(24 * depth)
    else:
        x, ground_y = int(player.x), int(player.y + 24)
        depth = 1.0

    speed = math.hypot(player.vx, player.vy)
    moving = speed > .7
    t = float(getattr(player, 'animation_time', 0.0))
    bounce = (math.sin(t * 1.8) * min(2.6, speed * .42) if moving
              else math.sin(t * .7) * .7)
    stretch = 1.0 + min(.10, speed * .014) + float(getattr(player, 'squash', 0.0)) * .08
    stride = math.sin(t * 2.3) * min(4.0, speed * .7) if moving else 0.0
    fx, fy = normalize(player.facing_x, player.facing_y,
                       (-1.0 if player.is_p2 else 1.0, 0.0))
    perp_x, perp_y = -fy, fx

    # The sprite is authored at 3x and downsampled to the correct field depth.
    SS, SW, SH = 3, 108, 116
    layer = pygame.Surface((SW * SS, SH * SS), pygame.SRCALPHA)

    def sc(v):
        return int(round(v * SS))

    def rect(x0, y0, w, h):
        return pygame.Rect(sc(x0), sc(y0), max(1, sc(w)), max(1, sc(h)))

    def point(px, py):
        return (sc(px), sc(py))

    cx, cy = 54.0, 78.0 + bounce
    rx, ry = 23.0 * stretch, 22.0 / max(.85, stretch)
    shape_name = getattr(player, 'shape', 'ROUND')

    def shape(surface_target, color, center_x, center_y, radius_x, radius_y,
              extra=0.0, offset=(0.0, 0.0), border=0):
        ox, oy = offset
        ex, ey = radius_x + extra, radius_y + extra
        bx, by = center_x + ox, center_y + oy
        left, right, top, bottom = bx - ex, bx + ex, by - ey, by + ey
        if shape_name == 'SQUARE':
            pygame.draw.rect(surface_target, color,
                             rect(left, top, ex * 2, ey * 2), sc(border),
                             border_radius=sc(8))
        elif shape_name == 'DIAMOND':
            pts = [point(bx, top), point(right, by), point(bx, bottom), point(left, by)]
            pygame.draw.polygon(surface_target, color, pts, sc(border))
        elif shape_name == 'HEXAGON':
            pts = [point(left + ex * .48, top), point(right - ex * .48, top),
                   point(right, by), point(right - ex * .48, bottom),
                   point(left + ex * .48, bottom), point(left, by)]
            pygame.draw.polygon(surface_target, color, pts, sc(border))
        elif shape_name == 'STAR':
            pts = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rad = 1.0 if i % 2 == 0 else .48
                pts.append(point(bx + math.cos(ang) * ex * rad,
                                 by + math.sin(ang) * ey * rad))
            pygame.draw.polygon(surface_target, color, pts, sc(border))
        elif shape_name == 'SHIELD':
            pts = [point(left + ex * .24, top), point(right - ex * .24, top),
                   point(right, top + ey * .48), point(bx, bottom),
                   point(left, top + ey * .48)]
            pygame.draw.polygon(surface_target, color, pts, sc(border))
        else:
            pygame.draw.ellipse(surface_target, color, rect(left, top, ex * 2, ey * 2), sc(border))

    # Ground shadow is part of the sprite and stays below the body as it bounces.
    pygame.draw.ellipse(layer, (0, 0, 0, 102), rect(23, 94, 62, 15))
    pygame.draw.ellipse(layer, (0, 0, 0, 48), rect(31, 97, 46, 8))

    # Low rounded shoes retain the original mascot character style.
    kick = getattr(player, 'kick_timer', 0.0) > 0
    for side in (-1, 1):
        foot_x = cx + side * (10 + stride * .48)
        foot_y = cy + 29 + stride * side * .18
        if kick and side == 1:
            foot_x += fx * 9
            foot_y += fy * 8
        shoe = rect(foot_x - 8, foot_y - 1, 17, 9)
        pygame.draw.ellipse(layer, (5, 9, 16), shoe.inflate(sc(2), sc(2)))
        pygame.draw.ellipse(layer, GOLD if kick and side == 1 else (31, 42, 57), shoe)
        pygame.draw.ellipse(layer, (180, 194, 207), rect(foot_x - 5, foot_y, 10, 3))

    # Extruded underside and outer rim create visible volume without changing the shape.
    shape(layer, (4, 9, 17), cx, cy, rx, ry, extra=3.8, offset=(4.0, 7.0))
    shape(layer, player.dark_color, cx, cy, rx, ry, extra=2.2, offset=(1.7, 3.0))
    shape(layer, (13, 24, 38), cx, cy, rx, ry, extra=1.0, offset=(0.0, 1.2))
    shape(layer, player.color, cx, cy - 1.0, rx, ry)

    # Clip a smooth highlight and a darker side-face to the chosen silhouette.
    mask = pygame.Surface((SW * SS, SH * SS), pygame.SRCALPHA)
    shape(mask, (255, 255, 255, 255), cx, cy - 1.0, rx, ry)
    gloss = pygame.Surface((SW * SS, SH * SS), pygame.SRCALPHA)
    pygame.draw.ellipse(gloss, (255, 255, 255, 88), rect(cx - 18, cy - 18, 24, 18))
    gloss.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    layer.blit(gloss, (0, 0))
    shade = pygame.Surface((SW * SS, SH * SS), pygame.SRCALPHA)
    pygame.draw.ellipse(shade, (3, 8, 18, 78), rect(cx + 1, cy - 2, 23, 37))
    shade.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    layer.blit(shade, (0, 0))

    # Bright bevel around the upper edge.
    if shape_name in ('ROUND', 'SQUARE'):
        pygame.draw.arc(layer, player.light_color,
                        rect(cx - rx + 2, cy - ry + 2, rx * 1.55, ry * 1.52),
                        math.radians(195), math.radians(300), sc(2.0))
    else:
        pygame.draw.circle(layer, player.light_color,
                           point(cx - rx * .30, cy - ry * .36), sc(4))

    # Team kit stripe runs across the face of the original shape mascot.
    stripe_a = point(cx - perp_x * rx * .60, cy - perp_y * ry * .60)
    stripe_b = point(cx + perp_x * rx * .60, cy + perp_y * ry * .60)
    pygame.draw.line(layer, player.accent_color, stripe_a, stripe_b, sc(4))
    pygame.draw.line(layer, player.light_color,
                     (stripe_a[0], stripe_a[1] - sc(1)),
                     (stripe_b[0], stripe_b[1] - sc(1)), sc(1))

    # Two expressive eyes follow the facing direction, as in the original game.
    face_x = cx + fx * 7.0
    face_y = cy + fy * 7.0 - 3.0
    for side in (-1, 1):
        ex = face_x + perp_x * 6.2 * side
        ey = face_y + perp_y * 6.2 * side
        eye_rect = rect(ex - 4.0, ey - 4.5, 8.0, 9.0)
        pygame.draw.ellipse(layer, (248, 251, 255), eye_rect)
        pygame.draw.ellipse(layer, (33, 43, 59), rect(ex + fx * 1.0 - 2.0,
                                                       ey + fy * 1.0 - 2.1, 4.2, 4.2))
        pygame.draw.circle(layer, (255, 255, 255), point(ex - 1.0, ey - 2.0), sc(1.0))

    # Celebration arms are small matching colour fins, not human limbs.
    if getattr(player, 'celebration_timer', 0.0) > 0:
        wave = math.sin(t * .42) * 4.0
        for side in (-1, 1):
            start_pt = point(cx + side * 17, cy - 3)
            end_pt = point(cx + side * (31 + wave), cy - 23 - abs(math.sin(t * .28)) * 5)
            pygame.draw.line(layer, (5, 10, 18), start_pt, end_pt, sc(9))
            pygame.draw.line(layer, player.color, start_pt, end_pt, sc(6))
            pygame.draw.circle(layer, player.light_color, end_pt, sc(4))

    # Existing status effects are retained and given a shallow 3D ring treatment.
    if getattr(player, 'flash_timer', 0.0) > 0:
        pygame.draw.ellipse(layer, GOLD, rect(cx - 31, cy - 31, 62, 62), sc(2))
    if getattr(player, 'tackle_timer', 0.0) > 0:
        pygame.draw.ellipse(layer, GOLD, rect(cx - 34, cy + 23, 68, 13), sc(2))
    if speed > 4.8 or getattr(player, 'boost_t', 0.0) > 0:
        pulse = 1.0 + math.sin(t * .7) * .08
        ring_col = player.accent_color if player.boost_t > 0 else player.light_color
        pygame.draw.ellipse(layer, ring_col,
                            rect(cx - 31 * pulse, cy + 22 - 7 * pulse,
                                 62 * pulse, 15 * pulse), sc(2))
        for i in range(4):
            ang = t * .22 + i * math.tau / 4
            pygame.draw.circle(layer, ring_col,
                               point(cx + math.cos(ang) * 30, cy + 23 + math.sin(ang) * 6), sc(2))
    if getattr(player, 'boost_t', 0.0) > 0:
        pygame.draw.ellipse(layer, PU_COLORS[0], rect(cx - 31, cy - 31, 62, 62), sc(2))
    if getattr(player, 'mega_t', 0.0) > 0:
        pygame.draw.ellipse(layer, PU_COLORS[1], rect(cx - 35, cy - 35, 70, 70), sc(2))
    if getattr(player, 'frozen_t', 0.0) > 0:
        pygame.draw.ellipse(layer, (155, 226, 255), rect(cx - 34, cy - 34, 68, 68), sc(3))

    # Charging meter sits above the mascot and stays readable at every pitch depth.
    if getattr(player, 'charging', False) and getattr(player, 'charge', 0.0) > .03:
        amount = clamp(player.charge, 0.0, 1.0)
        bar_color = GOLD if amount >= .95 else player.light_color
        pygame.draw.arc(layer, bar_color, rect(cx - 31, cy - 31, 62, 62),
                        -math.pi / 2, -math.pi / 2 + math.tau * amount, sc(3))

    # Tiny stamina strip above the avatar.
    bar_w = 42
    bar_x, bar_y = cx - bar_w / 2, 35.0
    pygame.draw.rect(layer, (20, 29, 42), rect(bar_x, bar_y, bar_w, 5), border_radius=sc(2))
    fill = int(bar_w * clamp(player.stamina / max(1.0, player.max_stamina), 0.0, 1.0))
    if fill:
        pygame.draw.rect(layer, GOLD if not player.exhausted else RED,
                         rect(bar_x, bar_y, fill, 5), border_radius=sc(2))

    display_w = max(28, int(SW * depth))
    display_h = max(30, int(SH * depth))
    sprite = pygame.transform.smoothscale(layer, (display_w, display_h))
    baseline = int(108 * depth)
    surface.blit(sprite, (int(x - display_w / 2), int(ground_y - baseline)))


def draw_3d_keeper(surface, keeper):
    """Render the moving goal-line keeper as a raised, padded 3D bar."""
    pulse = .5 + .5 * math.sin(keeper.animation * 2.0)
    dive = 1.0 - keeper.dive_timer / 16.0 if keeper.dive_timer > 0.0 else 0.0
    half_length = keeper.bar_half + dive * 8.0
    wx = keeper.x + keeper.dive_dir * dive * 2.0
    cx, cy = project_field_point(wx, keeper.y)
    scale = field_depth_scale(keeper.y)
    half = int(half_length * scale)
    thick = max(7, int(15 * scale))
    glow = pygame.Surface((thick * 5, half * 2 + 24), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*keeper.light, int(35 + pulse * 25)),
                     (thick * 2, 9, thick, half * 2 + 6), border_radius=thick // 2)
    surface.blit(glow, (cx - thick * 2, cy - half - 12))
    pygame.draw.line(surface, (5, 10, 18), (cx + 3, cy - half + 2),
                     (cx + 3, cy + half + 2), thick + 6)
    pygame.draw.line(surface, keeper.dark if hasattr(keeper, "dark") else (18, 30, 45),
                     (cx, cy - half), (cx, cy + half), thick + 2)
    pygame.draw.line(surface, keeper.color, (cx, cy - half), (cx, cy + half), thick)
    pygame.draw.line(surface, WHITE if keeper.save_flash > 0 else keeper.light,
                     (cx - 2, cy - half + 5), (cx - 2, cy + half - 5), max(2, thick // 3))
    pygame.draw.circle(surface, WHITE if keeper.save_flash > 0 else keeper.light,
                       (cx, cy - half), max(3, thick // 2))
    pygame.draw.circle(surface, WHITE if keeper.save_flash > 0 else keeper.light,
                       (cx, cy + half), max(3, thick // 2))


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

    def draw(self, layer, projector=None):
        if self.life <= 0:
            return
        ratio = self.life / self.max_life
        alpha = int(255 * ratio)
        if projector is None:
            px, py, scale = int(self.x), int(self.y), 1.0
        else:
            px, py = projector(self.x, self.y)
            scale = field_depth_scale(self.y)
        if self.ring:
            pygame.draw.circle(layer, (*self.color, int(alpha * 0.75)),
                               (int(px), int(py)),
                               max(2, int((self.size + (1 - ratio) * 34) * scale)), 2)
            return
        size = max(1, int(self.size * (0.65 + 0.35 * ratio) * scale))
        pygame.draw.circle(layer, (*self.color, alpha), (int(px), int(py)), size)


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
        # Q cycles between a bending CURVE shot and a lifted AIR shot.
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
        # Menu/customization previews use the same rounded 3D mascot design.
        draw_3d_player(surface, self, projected=False)


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
            # A more visible arcing air shot; keeper collision already ignores
            # sufficiently elevated balls, while ground position still governs goals.
            self.lift_v = 6.2

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
        # Fullscreen control sits in the clear top-center gap between Back and Settings.
        self.game_fullscreen_button = pygame.Rect(W // 2 - 23, 14, 46, 46)
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
        self.settings_tap_cooldown = 0.0
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
        """Q arms the next shot; press Q again before shooting to switch CURVE/AIR."""
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

    def draw_game_fullscreen_button(self):
        """Fullscreen toggle placed in the top gap between Back and Match Settings."""
        if self.state not in ("countdown", "play", "goal", "paused"):
            return
        r = self.game_fullscreen_button
        hover = r.collidepoint(pygame.mouse.get_pos())
        edge = GOLD if hover else (125, 215, 239)
        pygame.draw.circle(screen, (5, 16, 27), r.center, 24)
        pygame.draw.circle(screen, (67, 110, 137), r.center, 22, 2)
        pygame.draw.circle(screen, (20, 39, 55) if not hover else (31, 62, 81),
                           r.center, 18)
        # Four crisp corner strokes form a familiar fullscreen/expand symbol.
        cx, cy = r.center
        reach, inner = 10, 3
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            pygame.draw.line(screen, edge,
                             (cx + sx * inner, cy + sy * reach),
                             (cx + sx * reach, cy + sy * reach), 3)
            pygame.draw.line(screen, edge,
                             (cx + sx * reach, cy + sy * inner),
                             (cx + sx * reach, cy + sy * reach), 3)

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
            pos = (int(event.x * W), int(event.y * H))
            for i in range(n):
                r = self.set_row_rect(i)
                if r.collidepoint(pos):
                    self.set_sel = i
                    if self.settings_tap_cooldown <= 0:
                        self.settings_tap_cooldown = 15.0
                        self.settings_change(i, -1 if pos[0] < r.centerx else 1)
                    return
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(n):
                r = self.set_row_rect(i)
                if r.collidepoint(event.pos):
                    self.set_sel = i
                    if self.settings_tap_cooldown <= 0:
                        self.settings_tap_cooldown = 15.0
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

        # The center-top fullscreen button is independent of the settings panel and
        # is checked before movement/action controls so it never triggers gameplay.
        if self.state in ("countdown", "play", "goal", "paused"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.game_fullscreen_button.collidepoint(event.pos):
                    if not WEB_BUILD:
                        set_desktop_fullscreen(not DISPLAY_FULLSCREEN)
                    # In web builds, the canvas pointerdown listener above invokes
                    # requestFullscreen directly inside the browser gesture.
                    return
            elif event.type == pygame.FINGERDOWN:
                fs_pos = (int(event.x * W), int(event.y * H))
                if self.game_fullscreen_button.collidepoint(fs_pos):
                    return

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
        self.settings_tap_cooldown = max(0.0, self.settings_tap_cooldown - dt)
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
        # Front-on 3D goal cage: front frame, inset back plane, roof and side nets.
        goal = pygame.Rect(W//2-220, 135, 440, 190)
        back = pygame.Rect(goal.left + 38, goal.top - 31, goal.w - 76, goal.h - 43)
        cage = pygame.Surface((W, H), pygame.SRCALPHA)
        ftl, ftr = goal.topleft, goal.topright
        fbl, fbr = goal.bottomleft, goal.bottomright
        btl, btr = back.topleft, back.topright
        bbl, bbr = back.bottomleft, back.bottomright
        pygame.draw.polygon(cage, (36, 105, 132, 54), [ftl, ftr, btr, btl])
        pygame.draw.polygon(cage, (24, 79, 104, 50), [ftl, btl, bbl, fbl])
        pygame.draw.polygon(cage, (24, 79, 104, 50), [ftr, btr, bbr, fbr])
        pygame.draw.polygon(cage, (9, 27, 40, 70), [btl, btr, bbr, bbl])
        # Full back net mesh.
        for i in range(1, 12):
            x = back.left + back.w * i / 12
            pygame.draw.line(cage, (165, 205, 222, 145), (int(x), back.top), (int(x), back.bottom), 1)
        for i in range(1, 8):
            y = back.top + back.h * i / 8
            pygame.draw.line(cage, (165, 205, 222, 145), (back.left, int(y)), (back.right, int(y)), 1)
        # Side and roof mesh strands: longitudinal lines and cross-lines.
        def mix_point(a, b, amount):
            return (int(a[0] + (b[0] - a[0]) * amount),
                    int(a[1] + (b[1] - a[1]) * amount))
        for i in range(1, 8):
            t = i / 8.0
            # Roof panel across its width at this depth.
            pygame.draw.aaline(cage, (155, 199, 220, 115),
                               mix_point(ftl, btl, t), mix_point(ftr, btr, t))
            # Both side panels across their height at this depth.
            pygame.draw.aaline(cage, (155, 199, 220, 115),
                               mix_point(ftl, btl, t), mix_point(fbl, bbl, t))
            pygame.draw.aaline(cage, (155, 199, 220, 115),
                               mix_point(ftr, btr, t), mix_point(fbr, bbr, t))
            # Cross strands running toward the back wall at several heights.
            pygame.draw.aaline(cage, (155, 199, 220, 115),
                               mix_point(ftl, fbl, t), mix_point(btl, bbl, t))
            pygame.draw.aaline(cage, (155, 199, 220, 115),
                               mix_point(ftr, fbr, t), mix_point(btr, bbr, t))
        screen.blit(cage, (0, 0))
        # Thick metallic front and rear frames with bright highlights.
        for a, b, width in ((ftl, ftr, 8), (ftl, fbl, 8), (ftr, fbr, 8),
                            (fbl, fbr, 5), (btl, btr, 4), (btl, bbl, 4),
                            (btr, bbr, 4), (bbl, bbr, 3),
                            (ftl, btl, 4), (ftr, btr, 4),
                            (fbl, bbl, 3), (fbr, bbr, 3)):
            pygame.draw.line(screen, (22, 35, 49), (a[0]+3, a[1]+4), (b[0]+3, b[1]+4), width+3)
            pygame.draw.line(screen, (184, 210, 225), a, b, width)
            pygame.draw.aaline(screen, (250, 253, 255), (a[0]-1, a[1]-1), (b[0]-1, b[1]-1))
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
        kdark = tuple(max(0, int(v * .48)) for v in kcol)
        klight = tuple(min(255, int(v * 1.22 + 22)) for v in kcol)
        keeper_source = self.p2 if self.penalty_shooter == 1 else self.p1
        keeper_model = Player(keeper_x, keeper_y + 6, kcol, kdark, klight,
                              is_p2=(self.penalty_shooter == 1))
        keeper_model.shape = getattr(keeper_source, 'shape', 'ROUND')
        keeper_model.accent_color = getattr(keeper_source, 'accent_color', klight)
        keeper_model.animation_time = self.ui_t * .8
        keeper_model.vx = math.sin(self.ui_t * .16) * (2.0 + dive * 4.0)
        keeper_model.tackle_timer = 3.0 if dive > .2 else 0.0
        draw_3d_player(screen, keeper_model, projected=False)
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
        """Build a raised, perspective pitch with stadium lighting and 3D edging."""
        surf = pygame.Surface((W, H))
        surf.fill((5, 13, 23))

        # Deep stadium bowl and subtle horizontal light bands.
        for y in range(H):
            k = y / max(1, H - 1)
            col = (int(5 + 5 * k), int(13 + 9 * k), int(24 + 16 * k))
            pygame.draw.line(surf, col, (0, y), (W, y))

        crowd = random.Random(22)
        crowd_pal = [(40, 140, 220), (80, 195, 255), (235, 85, 70),
                     (245, 200, 70), (230, 240, 250), (90, 110, 145)]
        # Spectator stands are visible above and below the pitch.
        stand_bands = [(0, FIELD_TOP - 2), (FIELD_BOTTOM + 3, H)]
        for top, bottom in stand_bands:
            for _ in range(max(400, int(W * max(1, bottom - top) / 115))):
                x = crowd.randrange(0, W)
                y = crowd.randrange(max(0, top), max(top + 1, bottom))
                base = crowd.choice(crowd_pal)
                shade = crowd.uniform(.25, .75)
                c = tuple(int(v * shade) for v in base)
                pygame.draw.circle(surf, c, (x, y), crowd.choice((1, 1, 2)))

        # Stadium floodlight beams.
        for side in (0, 1):
            anchor_x = 45 if side == 0 else W - 45
            for i in range(8):
                lx = anchor_x + (i * 17 if side == 0 else -i * 17)
                ly = 34 + (i % 2) * 8
                pygame.draw.circle(surf, (120, 195, 255), (lx, ly), 11, 1)
                pygame.draw.circle(surf, (230, 248, 255), (lx, ly), 4)

        tl = project_field_point(FIELD_LEFT, FIELD_TOP)
        tr = project_field_point(FIELD_RIGHT, FIELD_TOP)
        br = project_field_point(FIELD_RIGHT, FIELD_BOTTOM)
        bl = project_field_point(FIELD_LEFT, FIELD_BOTTOM)

        # Thick side-wall and drop shadow make the playing surface look raised.
        shadow_poly = [(tl[0] - 8, tl[1] + 15), (tr[0] + 8, tr[1] + 15),
                       (br[0] + 10, br[1] + 22), (bl[0] - 10, bl[1] + 22)]
        pygame.draw.polygon(surf, (1, 5, 10), shadow_poly)
        side_poly = [tl, tr, (tr[0] + 2, tr[1] + 12), (br[0] + 2, br[1] + 18),
                     (bl[0] - 2, bl[1] + 18), (tl[0] - 2, tl[1] + 12)]
        pygame.draw.polygon(surf, (13, 48, 40), side_poly)
        pitch_poly = [tl, tr, br, bl]
        pygame.draw.polygon(surf, (10, 72, 43), pitch_poly)

        # Alternating turf bands taper with the pitch to reinforce perspective.
        stripe_count = 10
        for i in range(stripe_count):
            ya = FIELD_TOP + FIELD_RECT.height * i / stripe_count
            yb = FIELD_TOP + FIELD_RECT.height * (i + 1) / stripe_count
            col = (38, 139, 63) if i % 2 == 0 else (25, 111, 51)
            poly = [project_field_point(FIELD_LEFT, ya),
                    project_field_point(FIELD_RIGHT, ya),
                    project_field_point(FIELD_RIGHT, yb),
                    project_field_point(FIELD_LEFT, yb)]
            pygame.draw.polygon(surf, col, poly)

        # Fine grass streaks add a little surface texture without heavy per-frame cost.
        rng = random.Random(19)
        for _ in range(1250):
            wx = rng.randint(FIELD_LEFT, FIELD_RIGHT)
            wy = rng.randint(FIELD_TOP, FIELD_BOTTOM)
            px, py = project_field_point(wx, wy)
            sc = field_depth_scale(wy)
            tint = rng.choice(((75, 165, 82), (24, 90, 48), (108, 180, 88)))
            pygame.draw.line(surf, tint, (px, py), (px + max(1, int(3 * sc)), py), 1)

        # Main boundary with a bright near-edge highlight.
        pygame.draw.polygon(surf, (8, 38, 30), pitch_poly, 10)
        pygame.draw.polygon(surf, (220, 245, 224), pitch_poly, 3)
        pygame.draw.line(surf, (255, 255, 255), bl, br, 5)
        pygame.draw.line(surf, (105, 245, 160), (bl[0], bl[1] + 3), (br[0], br[1] + 3), 2)

        # Center line and perspective circle.
        draw_projected_line(surf, WHITE, (FIELD_RECT.centerx, FIELD_TOP),
                            (FIELD_RECT.centerx, FIELD_BOTTOM), 3)
        circle_pts = []
        for i in range(81):
            a = math.tau * i / 80
            wx = FIELD_RECT.centerx + math.cos(a) * 92
            wy = FIELD_CY + math.sin(a) * 92
            circle_pts.append(project_field_point(wx, wy))
        pygame.draw.lines(surf, WHITE, True, circle_pts, 3)
        cc = project_field_point(FIELD_RECT.centerx, FIELD_CY)
        pygame.draw.circle(surf, WHITE, cc, 4)

        penalty_w, penalty_h = 150, 310
        for side in (0, 1):
            left = FIELD_LEFT if side == 0 else FIELD_RIGHT - penalty_w
            rect = pygame.Rect(left, FIELD_CY - penalty_h // 2, penalty_w, penalty_h)
            draw_projected_rect(surf, WHITE, rect, 3)
        box_w, box_h = 62, 170
        for side in (0, 1):
            left = FIELD_LEFT if side == 0 else FIELD_RIGHT - box_w
            rect = pygame.Rect(left, FIELD_CY - box_h // 2, box_w, box_h)
            draw_projected_rect(surf, WHITE, rect, 3)

        for wx in (FIELD_LEFT + 105, FIELD_RIGHT - 105):
            q = project_field_point(wx, FIELD_CY)
            pygame.draw.circle(surf, WHITE, q, 4)

        # Full 3D goal cages: front frame, roof, floor, two side walls and a
        # meshed rear panel. The translucent net is drawn separately so the
        # pitch and players remain visible through it.
        net_layer = pygame.Surface((W, H), pygame.SRCALPHA)
        net_line = (178, 208, 224, 150)
        net_dim = (105, 142, 163, 115)
        net_fill = (45, 92, 116, 28)
        net_height = 58.0
        net_depth = 56.0

        def goal_point(wx, wy, z):
            qx, qy = project_field_point(wx, wy)
            return (qx, int(qy - z * field_depth_scale(wy)))

        def net_line_draw(a, b, color=net_line, width=1, target=net_layer):
            if int(width) <= 1:
                pygame.draw.aaline(target, color, a, b)
            else:
                pygame.draw.line(target, color, a, b, max(1, int(width)))

        def tube(a, b, width=7):
            # Dark underside + silver front face + white specular edge.
            pygame.draw.line(surf, (19, 31, 44), (a[0] + 3, a[1] + 4),
                             (b[0] + 3, b[1] + 4), width + 3)
            pygame.draw.line(surf, (185, 207, 221), a, b, width)
            pygame.draw.aaline(surf, (247, 252, 255), (a[0] - 1, a[1] - 1),
                               (b[0] - 1, b[1] - 1))

        for side in (0, 1):
            front_x = FIELD_LEFT if side == 0 else FIELD_RIGHT
            sign = -1 if side == 0 else 1
            back_x = front_x + sign * net_depth
            ya, yb = GOAL_TOP, GOAL_BOTTOM

            # Front frame (standing uprights and crossbar).
            fta = goal_point(front_x, ya, net_height)
            ftb = goal_point(front_x, yb, net_height)
            fba = goal_point(front_x, ya, 0)
            fbb = goal_point(front_x, yb, 0)
            # Rear frame corners.
            bta = goal_point(back_x, ya, net_height * .82)
            btb = goal_point(back_x, yb, net_height * .82)
            bba = goal_point(back_x, ya, 0)
            bbb = goal_point(back_x, yb, 0)

            # Lightly tinted cage panels, all closed to make a full net rather
            # than a single flat rectangle.
            for poly in (
                [fta, ftb, btb, bta],       # roof
                [fta, bta, bba, fba],       # upper-side wall
                [ftb, btb, bbb, fbb],       # lower-side wall
                [bta, btb, bbb, bba],       # back net
                [fba, fbb, bbb, bba],       # ground/floor mesh
            ):
                pygame.draw.polygon(net_layer, net_fill, poly)

            # Back-wall grid.
            for i in range(1, 10):
                t = i / 10.0
                wy = ya + (yb - ya) * t
                net_line_draw(goal_point(back_x, wy, 0),
                              goal_point(back_x, wy, net_height * .82), net_line, 1)
            for i in range(1, 6):
                z = net_height * .82 * i / 6.0
                net_line_draw(goal_point(back_x, ya, z),
                              goal_point(back_x, yb, z), net_line, 1)

            # Roof grid, with transverse and longitudinal net strands.
            for i in range(1, 8):
                t = i / 8.0
                wx = front_x + (back_x - front_x) * t
                net_line_draw(goal_point(wx, ya, net_height * (1.0 - .18 * t)),
                              goal_point(wx, yb, net_height * (1.0 - .18 * t)), net_dim, 1)
            for i in range(1, 8):
                t = i / 8.0
                wy = ya + (yb - ya) * t
                net_line_draw(goal_point(front_x, wy, net_height),
                              goal_point(back_x, wy, net_height * .82), net_dim, 1)

            # Side wall mesh strands along both sides of the cage.
            for wy in (ya, yb):
                for i in range(1, 6):
                    z = net_height * i / 6.0
                    z_back = z * .82
                    net_line_draw(goal_point(front_x, wy, z),
                                  goal_point(back_x, wy, z_back), net_line, 1)
                for i in range(1, 7):
                    t = i / 7.0
                    wx = front_x + (back_x - front_x) * t
                    z = net_height * (1.0 - .18 * t)
                    net_line_draw(goal_point(wx, wy, 0), goal_point(wx, wy, z), net_dim, 1)

            # Floor net strands give the cage a complete 3D enclosure.
            for i in range(1, 7):
                t = i / 7.0
                wx = front_x + (back_x - front_x) * t
                net_line_draw(goal_point(wx, ya, 0), goal_point(wx, yb, 0), net_dim, 1)
            for i in range(1, 8):
                t = i / 8.0
                wy = ya + (yb - ya) * t
                net_line_draw(goal_point(front_x, wy, 0), goal_point(back_x, wy, 0), net_dim, 1)

            surf.blit(net_layer, (0, 0))
            # Re-create a clean overlay for the next goal so both nets keep
            # their own translucency and mesh density.
            net_layer.fill((0, 0, 0, 0))

            # Strong 3D tubing around the opening and rear cage edges.
            tube(fta, ftb, 8)
            tube(fta, fba, 8)
            tube(ftb, fbb, 8)
            tube(bta, btb, 4)
            tube(fta, bta, 4)
            tube(ftb, btb, 4)
            tube(fba, bba, 3)
            tube(fbb, bbb, 3)
            # Rounded front-post feet catch the stadium light.
            for q in (fba, fbb):
                pygame.draw.circle(surf, (36, 51, 66), (q[0] + 2, q[1] + 3), 6)
                pygame.draw.circle(surf, GOAL_FRAME, q, 5)
                pygame.draw.circle(surf, WHITE, (q[0] - 1, q[1] - 1), 2)

        # Pitch-side LED ribbon.
        pygame.draw.line(surf, (18, 95, 125), (bl[0], bl[1] + 12), (br[0], br[1] + 12), 3)
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
            controls_text = ("MOVE: WASD / ARROWS  -  SHOOT: E / P  -  TACKLE: R / L  -  DASH: SHIFT  -  Q: CURVE / AIR")
        elif self.mode == "pvp":
            controls_text = ("BLUE: WASD - E SHOOT - R TACKLE - LSHIFT DASH - Q CURVE/AIR     "
                             "RED: ARROWS - P SHOOT - L TACKLE - RSHIFT DASH - PERIOD CURVE/AIR")
        else:
            controls_text = ("MOVE: WASD / ARROWS  -  SHOOT: E / P  -  TACKLE: R / L  -  DASH: SHIFT  -  Q: CURVE / AIR"
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
            rr = max(2, int(13 * field_depth_scale(ty) * (i + 1) / max(1, len(trail))))
            pygame.draw.circle(self.fx_layer, (238, 247, 255, alpha), project_field_point(tx, ty), rr)
        cv.blit(self.fx_layer, (0, 0))

        draw_3d_keeper(cv, self.replay_keeper_left)
        draw_3d_keeper(cv, self.replay_keeper_right)
        for actor in sorted(replay_actors, key=lambda q: q.y):
            draw_3d_player(cv, actor)
        bx, by = project_field_point(frame["bx"], frame["by"] - float(frame.get("bl", 0.0)))
        gx, gy = project_field_point(frame["bx"], frame["by"])
        draw_ball(cv, bx, by, max(5, int(13 * field_depth_scale(frame["by"]))),
                  frame["br"], ground_y=gy)

        # A gentle zoom follows the scoring action, like a TV replay camera.
        progress = idx / max(1, len(frames) - 1)
        zoom = 1.0 + 0.095 * (0.5 - 0.5 * math.cos(math.pi * progress))
        sw, sh = int(W * zoom), int(H * zoom)
        scaled = pygame.transform.smoothscale(cv, (sw, sh)) if zoom > 1.001 else cv
        if zoom > 1.001:
            replay_focus_x, replay_focus_y = project_field_point(frame["bx"], frame["by"])
            cx = replay_focus_x * zoom
            cy = replay_focus_y * zoom
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
                label = "AIR" if player.special_kind == "chip" else "CURVE"
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
            px, py = project_field_point(tx, ty)
            rr = max(2, int(self.ball.radius * field_depth_scale(ty) * (0.4 + 0.5 * k)))
            pygame.draw.circle(self.fx_layer, (255, 255, 255, int(70 * k)), (px, py), rr)
        for p in self.particles:
            p.draw(self.fx_layer, project_field_point)
        cv.blit(self.fx_layer, (0, 0))

        for pu in self.powerups:
            px, py = project_field_point(pu["x"], pu["y"])
            draw_powerup(cv, pu["t"], px, py, self.ui_t,
                         r=max(10, int(17 * field_depth_scale(pu["y"]))))

        # Goalkeepers and footballers are rendered as shaded 3D-style game models.
        draw_3d_keeper(cv, self.keeper_left)
        draw_3d_keeper(cv, self.keeper_right)
        for p in sorted(self.match_players(), key=lambda q: q.y):
            draw_3d_player(cv, p)
            if self.squad_mode:
                slot = self.match_players().index(p)
                if slot < len(self.slot_is_human) and not self.slot_is_human[slot]:
                    tag_x, tag_y = project_field_point(p.x, p.y - p.radius - 26)
                    draw_text(cv, self.tiny_font, "AI TEAMMATE", (225, 235, 242),
                              (tag_x, tag_y), shadow=True)

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
                start_x, start_y = project_field_point(start_x, start_y)
                end_x, end_y = project_field_point(end_x, end_y)
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
                    tag_pos = project_field_point(shooter.x, shooter.y - 58)
                    draw_text(cv, self.tiny_font, "MAX POWER", GOLD, tag_pos, shadow=True)

        # Fast shots get a pulsing energy halo for extra arcade impact.
        ball_speed = math.hypot(self.ball.vx, self.ball.vy)
        if ball_speed > 7:
            halo = pygame.Surface((100, 100), pygame.SRCALPHA)
            pulse = int(45 + 25 * math.sin(self.ui_t * 0.45))
            ball_px, ball_py = project_field_point(self.ball.x, self.ball.y)
            halo_r = max(10, int(min(43, 14 + ball_speed * 2) * field_depth_scale(self.ball.y)))
            pygame.draw.circle(cv, (255, 205, 85), (ball_px, ball_py), halo_r, 2)
            if ball_speed > 12:
                for i in range(3):
                    ang = math.atan2(self.ball.vy, self.ball.vx) + math.pi + (i - 1) * 0.22
                    wx = self.ball.x + math.cos(ang) * 25
                    wy = self.ball.y + math.sin(ang) * 25
                    sx, sy = project_field_point(wx, wy)
                    pygame.draw.circle(cv, (255, 240, 155), (sx, sy), max(1, int(3 * field_depth_scale(wy))))
        ball_x, ball_y = project_field_point(self.ball.x, self.ball.y - self.ball.lift)
        ground_x, ground_y = project_field_point(self.ball.x, self.ball.y)
        draw_ball(cv, ball_x, ball_y, max(5, int(self.ball.radius * field_depth_scale(self.ball.y))),
                  self.ball.rotation, ground_y=ground_y)

        # Online: name tags and a bobbing "you" arrow.
        if self.mode in ("host", "client"):
            me_list = self.match_players()
            my_slot = self.host_slot if self.mode == "host" else self.local_slot
            me = me_list[int(clamp(my_slot, 0, len(me_list) - 1))]
            for slot, p in enumerate(me_list):
                if slot < len(self.slot_names):
                    name_col = BLUE_LIGHT if not p.is_p2 else RED_LIGHT
                    tag_pos = project_field_point(p.x, p.y - p.radius - 32)
                    draw_text(cv, self.tiny_font, self.slot_names[slot], name_col, tag_pos)
            bob = math.sin(self.ui_t * 0.15) * 3
            ax, ay = project_field_point(me.x, me.y - me.radius - 50 + bob)
            pygame.draw.polygon(cv, GOLD, [(ax - 7, ay - 8), (ax + 7, ay - 8), (ax, ay + 2)])

        screen.fill((10, 14, 12))
        screen.blit(cv, (offx, offy))

        self.draw_hud()
        self.draw_touch_controls()
        self.draw_game_back_button()
        self.draw_game_settings_button()
        self.draw_game_settings_overlay()
        self.draw_game_fullscreen_button()
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
        web_fullscreen_ui_active = None
        while self.running:
            ms = clock.tick(FPS)
            dt = min(ms / (1000.0 / 60.0), 2.5)
            self.handle_events()
            if not self.running:
                break
            self.update(dt)
            if WEB_BUILD:
                active = self.state in ("countdown", "play", "goal", "paused")
                if active != web_fullscreen_ui_active:
                    try:
                        platform.window.eval("window._hs_match_ui_active = " + ("true" if active else "false") + ";")
                    except Exception:
                        pass
                    web_fullscreen_ui_active = active
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

 