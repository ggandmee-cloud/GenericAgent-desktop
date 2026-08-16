"""Optional P2P phone pairing plug-in for hub.py."""
import asyncio
import os
from pathlib import Path

from fastapi import Response
from fastapi.responses import JSONResponse
from p2p_ws_client import HTTPExporter, connect_saved, create_code, load_room, save_room

QR_PREFIX = "ga-pclink:v1:"


def install(app, *, web_port, token, here):
    signal = os.environ.get("GA_P2P_SIGNAL", "ws://47.101.182.29:49157/ws")
    name = os.environ.get("GA_P2P_NAME", "ga-hub-phone")
    rooms = Path(os.environ.get("GA_P2P_ROOMS", "~/.p2p_ws/rooms.json")).expanduser()
    state = {"task": None, "invite": None, "status": "idle", "error": None,
             "started": False}
    app.state.p2p_pair_open = True
    here = Path(here)

    async def export(ws):
        exporter = await HTTPExporter(
            ws, f"http://127.0.0.1:{web_port}",
            allow=("/api/",), query={"t": token},
        ).start()
        try:
            state["status"], state["error"] = "connected", None
            await exporter.wait_closed()
        finally:
            await exporter.close()

    async def reconnect():
        while True:
            connected = False
            try:
                state["status"], state["error"] = "reconnecting", None
                ws = await connect_saved(name, path=rooms, direct_timeout=15)
                connected = True
                try:
                    await export(ws)
                finally:
                    await ws.close()  # 不关会泄漏信令连接: 旧连接与新连接自配对占满房间
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["status"], state["error"] = "error", str(exc)
            await asyncio.sleep(0.2 if connected else 5)

    async def new_pair():
        try:
            invite = state["invite"] = await create_code(
                signal, name=name + "-pending", rooms_file=rooms,
            )
            state["status"], state["error"] = "waiting", None
            ws = await invite.connect(direct_timeout=15)
            save_room(signal, invite.room, name=name, path=rooms)
            try:
                await export(ws)
            finally:
                await ws.close()
                await reconnect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["status"], state["error"] = "error", str(exc)

    def _ensure_pair_task():
        task = state["task"]
        if task is None or task.done():
            try:
                load_room(name, path=rooms)
            except KeyError:
                state["task"] = asyncio.create_task(new_pair())
            else:
                state["task"] = asyncio.create_task(reconnect())

    @app.get("/pair")
    async def pair():
        _ensure_pair_task()
        return Response(content=_PAIR_HTML, media_type="text/html; charset=utf-8")

    @app.get("/pair/qr.js")
    async def pair_qr_js():
        p = here / "desktop" / "static" / "vendor" / "qr-matrix.js"
        if not p.is_file():
            return Response(status_code=404)
        return Response(content=p.read_text(encoding="utf-8"),
                        media_type="application/javascript; charset=utf-8")

    @app.get("/pair/status")
    async def pair_status():
        _ensure_pair_task()
        invite = state["invite"]
        code = getattr(invite, "code", None)
        return JSONResponse({
            "status": state["status"],
            "code": code,
            "qr_payload": (QR_PREFIX + str(code)) if code else None,
            "expires_at": getattr(invite, "expires_at", None),
            "error": state["error"],
        })

    async def startup():
        if state["started"]:
            return
        state["started"] = True
        try:
            load_room(name, path=rooms)
        except KeyError:
            return
        state["task"] = asyncio.create_task(reconnect())

    app.add_event_handler("startup", startup)
    return state


_PAIR_HTML = '''<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>手机互联 · Phone pairing</title>
<style>
  :root { color-scheme: light dark; --fg:#111; --muted:#666; --bg:#fafafa; --card:#fff; --ok:#0a7; --wait:#c60; }
  @media (prefers-color-scheme: dark) {
    :root { --fg:#eee; --muted:#aaa; --bg:#121212; --card:#1c1c1c; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 system-ui,sans-serif; background: var(--bg); color: var(--fg);
         min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: var(--card); border-radius: 16px; padding: 28px 32px; max-width: 420px; width: 100%;
          box-shadow: 0 8px 28px rgba(0,0,0,.08); text-align: center; }
  h1 { font-size: 1.25rem; margin: 0 0 6px; font-weight: 650; }
  .sub { color: var(--muted); margin: 0 0 20px; font-size: .92rem; }
  #qr { width: 220px; height: 220px; margin: 0 auto 16px; border-radius: 12px; background: #fff; }
  #code { font: 700 1.75rem/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .18em;
          margin: 0 0 8px; user-select: all; }
  #state { color: var(--muted); font-size: .9rem; min-height: 1.4em; }
  #state.ok { color: var(--ok); } #state.wait { color: var(--wait); }
</style></head><body>
<div class="card">
  <h1>手机互联</h1>
  <p class="sub">用 GAndroid 扫码连接本机 · Scan with GAndroid</p>
  <canvas id="qr" width="220" height="220"></canvas>
  <pre id="code">……</pre>
  <p id="state">starting…</p>
</div>
<script src="/pair/qr.js"></script>
<script>
async function poll(){
  try{
    const s = await (await fetch('/pair/status')).json();
    const codeEl = document.getElementById('code');
    const st = document.getElementById('state');
    const canvas = document.getElementById('qr');
    codeEl.textContent = s.code || '—';
    let msg = s.status || '';
    if (s.error) msg += ' · ' + s.error;
    st.textContent = msg;
    st.className = s.status === 'connected' ? 'ok' : (s.status === 'waiting' ? 'wait' : '');
    if (s.qr_payload && window.QR) {
      try { QR.renderCanvas(s.qr_payload, canvas, 220); } catch (e) { console.warn(e); }
    }
    if (s.status !== 'connected') setTimeout(poll, 1000);
  } catch (e) {
    document.getElementById('state').textContent = String(e);
    setTimeout(poll, 1500);
  }
}
poll();
</script>
</body></html>
'''
