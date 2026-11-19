import asyncio
import json
import os
import random
import string
import websockets

ROOMS = {}


def make_code():
  while True:
    code = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=5))
    if code not in ROOMS:
      return code


async def handler(ws):
  room_code = None
  role = None
  try:
    async for raw in ws:
      msg = json.loads(raw)
      action = msg.get("relay")

      if action == "create":
        room_code = make_code()
        ROOMS[room_code] = {"host": ws, "guest": None}
        role = "host"
        await ws.send(json.dumps({"relay": "created", "code": room_code}))

      elif action == "join":
        code = str(msg.get("code", "")).upper().strip()
        room = ROOMS.get(code)
        if not room:
          await ws.send(json.dumps({"relay": "error", "msg": "Room not found"}))
        elif room["guest"] is not None:
          await ws.send(json.dumps({"relay": "error", "msg": "Room is full"}))
        else:
          room_code = code
          room["guest"] = ws
          role = "guest"
          await ws.send(json.dumps({"relay": "joined", "code": code}))

      elif room_code and room_code in ROOMS:
        room = ROOMS[room_code]
        target = room["guest"] if role == "host" else room["host"]
        if target:
          await target.send(raw)

  except websockets.ConnectionClosed:
    pass
  finally:
    if room_code and room_code in ROOMS:
      room = ROOMS[room_code]
      other = room["guest"] if role == "host" else room["host"]
      if other:
        try:
          await other.send(
              json.dumps({"g": "HSOC", "t": "closed" if role == "host" else "leave"})
          )
        except Exception:
          pass
      if role == "host":
        del ROOMS[room_code]
      else:
        room["guest"] = None


async def main():
  port = int(os.environ.get("PORT", 8765))
  async with websockets.serve(handler, "0.0.0.0", port):
    await asyncio.Future()


if __name__ == "__main__":
  asyncio.run(main())
