"""Optional P2P phone pairing plug-in for hub.py — one PC, many phones.

传输层房间是双人房(见 p2p_ws_client.P2PSocket), 一间只能装一台手机, 所以多手机 = PC 侧多房间:
  * 每台已配对手机 = rooms.json 一个槽 `ga-hub-phone.<slot>` + 一条常驻 reconnect 任务 + 一个 HTTPExporter;
  * 至多一枚「待扫」邀请(配对码): 扫成即落为新槽并接管其 socket, 已配对手机全程不受影响;
  * `/pair?fresh=1` 只换码(旧语义「清空重配」会把在线手机踢下线, 且手机侧存着死房间会无限重连);
  * 移除手机走显式 `POST /pair/forget?slot=`。
老键 `ga-hub-phone`(单机时代)原地视为槽 `legacy`, 不迁移不重写, 升级零感。
"""
import asyncio
import contextlib
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Response
from fastapi.responses import JSONResponse
from p2p_ws_client import HTTPExporter, connect_saved, create_code, save_room

QR_PREFIX = "ga-pclink:v1:"
INVITE_RETRY = 5          # 出码失败后的最短重试间隔(秒): /pair/status 每秒轮询, 不能每拍都去撞信令服务器


def install(app, *, web_port, token, here):
    signal = os.environ.get("GA_P2P_SIGNAL", "ws://47.101.182.29:49157/ws")
    name = os.environ.get("GA_P2P_NAME", "ga-hub-phone")
    rooms = Path(os.environ.get("GA_P2P_ROOMS", "~/.p2p_ws/rooms.json")).expanduser()
    pending_key = name + "-pending"
    phones = {}    # slot -> {task, status, error, saved_at, connected_at}
    invite = {"task": None, "obj": None, "status": "idle", "error": None, "next_try": 0.0}
    owner = [None]   # 全部 asyncio 任务归属的循环: hub.py 起两个 uvicorn(总线口/Web 口)共用本 app, startup 各跑一次,
    app.state.p2p_pair_open = True   # 首个到者即主; 另一循环上的请求处理器把状态变更封送过来, 不跨循环 cancel/create_task
    here = Path(here)

    def _own(fn, *a):
        """fire-and-forget 到主循环(同循环直呼)。"""
        loop = asyncio.get_running_loop()
        owner[0] = owner[0] or loop
        if owner[0] is loop:
            return fn(*a)
        owner[0].call_soon_threadsafe(fn, *a)

    async def _own_await(coro_fn, *a):
        loop = asyncio.get_running_loop()
        owner[0] = owner[0] or loop
        if owner[0] is loop:
            return await coro_fn(*a)
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro_fn(*a), owner[0]))

    # ---- rooms.json: 读/删自管(p2p_ws_client 只暴露 save/load 单键), 写沿用 save_room 的原子落盘 ----
    def _read_rooms():
        try:
            data = json.loads(rooms.read_text(encoding="utf-8")) if rooms.is_file() else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _drop_key(key):
        data = _read_rooms()
        if data.pop(key, None) is None:
            return
        rooms.parent.mkdir(parents=True, exist_ok=True)
        tmp = rooms.with_name(rooms.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if os.name != "nt":
            tmp.chmod(0o600)
        os.replace(tmp, rooms)

    def _saved_slots():
        """slot -> rooms.json 键。老键 ga-hub-phone 即槽 legacy; -pending 是待扫邀请不算手机。"""
        out = {}
        for k, v in _read_rooms().items():
            if not isinstance(v, dict) or k == pending_key:
                continue
            if k == name:
                out["legacy"] = k
            elif k.startswith(name + "."):
                out[k[len(name) + 1:]] = k
        return out

    # ---- 每台手机一条常驻任务 ----
    async def _export(ws):
        exporter = await HTTPExporter(
            ws, f"http://127.0.0.1:{web_port}", allow=("/api/",), query={"t": token},
        ).start()
        try:
            await exporter.wait_closed()
        finally:
            await exporter.close()

    async def _serve_slot(slot, key, ws=None):
        """重连已存房间 → 导出 hub API → 断了再来; 只被 forget 取消。ws 给定 = 刚扫成的首连直接用。"""
        st = phones[slot]
        while True:
            connected = False
            try:
                if ws is None:
                    st["status"], st["error"] = "reconnecting", None
                    ws = await connect_saved(key, path=rooms, direct_timeout=15)
                connected = True
                st["status"], st["error"], st["connected_at"] = "connected", None, int(time.time())
                try:
                    await _export(ws)
                finally:
                    await ws.close()   # 不关会泄漏信令连接: 旧连接与新连接自配对占满房间
                    ws = None
                    st["status"], st["connected_at"] = "reconnecting", None
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                st["status"], st["error"] = "reconnecting", None   # 手机不在线: 等 peer 进房超时是常态, 不算错误
            except Exception as exc:
                st["status"], st["error"] = "error", str(exc)
            await asyncio.sleep(0.2 if connected else 5)

    def _start_saved_slots():
        """启动: rooms.json 里每个手机槽起一条常驻任务(之后新槽由扫码即时创建, 任务只被 forget 终止)。"""
        data = _read_rooms()
        for slot, key in _saved_slots().items():
            phones[slot] = {"task": None, "status": "idle", "error": None,
                            "saved_at": (data.get(key) or {}).get("saved_at"), "connected_at": None}
            phones[slot]["task"] = asyncio.create_task(_serve_slot(slot, key))

    async def _forget(slot):
        st = phones.pop(slot, None)
        key = _saved_slots().get(slot)
        if st and st["task"] and not st["task"].done():
            st["task"].cancel()
            try:
                await st["task"]
            except (asyncio.CancelledError, Exception):
                pass
        if key:
            _drop_key(key)
        return bool(st or key)

    # ---- 待扫邀请(至多一枚) ----
    async def _run_invite():
        """出码 → 等扫; 扫成落新槽并把 socket 交给常驻任务; 码过期静默回 idle(下次 /pair 再出)。"""
        try:
            inv = invite["obj"] = await create_code(signal, name=pending_key, rooms_file=rooms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:   # 信令服务器不可达等: 带退避, 免得 1s 轮询变成对服务器的连打
            invite.update(obj=None, status="error", error=str(exc), next_try=time.time() + INVITE_RETRY)
            return
        invite["status"], invite["error"] = "waiting", None
        try:
            ws = await inv.connect(direct_timeout=15)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:   # 120s 没人扫: 码过期是常态, 静默回 idle
            invite.update(obj=None, status="idle", error=None)
            return
        except Exception as exc:
            invite.update(obj=None, status="error", error=str(exc), next_try=time.time() + INVITE_RETRY)
            return
        slot = secrets.token_hex(3)
        key = f"{name}.{slot}"
        save_room(signal, inv.room, name=key, path=rooms)
        _drop_key(pending_key)
        invite.update(obj=None, status="idle", error=None)
        now = int(time.time())
        phones[slot] = {"task": None, "status": "connected", "error": None, "saved_at": now, "connected_at": now}
        phones[slot]["task"] = asyncio.create_task(_serve_slot(slot, key, ws))

    def _ensure_invite(fresh=False):
        task = invite["task"]
        live = task is not None and not task.done()
        if live and not fresh:
            return
        if not fresh and time.time() < invite["next_try"]:
            return
        if live:
            task.cancel()   # 换码: 只取消待扫邀请(P2PSocket.connect 自带失败关信令), 手机任务各自独立
        invite.update(obj=None, status="idle", error=None)
        invite["task"] = asyncio.create_task(_run_invite())

    def _status_payload():
        inv = invite["obj"]
        code = getattr(inv, "code", None) if invite["status"] == "waiting" else None
        rows = [{"slot": s, "status": st["status"], "error": st["error"],
                 "saved_at": st["saved_at"], "connected_at": st["connected_at"]}
                for s, st in sorted(list(phones.items()), key=lambda kv: kv[1]["saved_at"] or 0)]   # list(): 可能在另一循环线程读, C 级快照免「迭代中被改」
        return {
            "status": invite["status"],          # 配对码状态: waiting / idle / error (手机连接态在 phones[])
            "code": code,
            "qr_payload": (QR_PREFIX + str(code)) if code else None,
            "expires_at": getattr(inv, "expires_at", None) if code else None,
            "error": invite["error"],
            "phones": rows,
            "connected": sum(1 for r in rows if r["status"] == "connected"),
        }

    @app.get("/pair")
    async def pair(fresh: int = 0):
        _own(_ensure_invite, bool(fresh))
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
        _own(_ensure_invite, False)   # 有人在看就保证码常新(过期自动续); 没人轮询就不出码
        return JSONResponse(_status_payload())

    @app.post("/pair/forget")   # 与 /pair* 同信任级(127.0.0.1 免 token): 旧 /pair?fresh=1 本就能踢手机, 未扩权
    async def pair_forget(slot: str = ""):
        ok = await _own_await(_forget, slot) if slot else False
        return JSONResponse({"ok": ok, "slot": slot, **_status_payload()})

    # 启动即重连所有已配对手机(邀请码等有人打开配对页再出)。挂 lifespan 而非 add_event_handler:
    # 后者在 FastAPI ≥0.13x 已不存在, 老版本这句 AttributeError 被 hub.py 的 except 吞掉 ⇒ 现网 hub 重启后手机从不自动重连。
    prev_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(a):
        async with prev_lifespan(a):
            if owner[0] is None:   # 两个 uvicorn 实例各进一次 lifespan, 首个成主
                _own(_start_saved_slots)
            yield

    app.router.lifespan_context = lifespan


_PAIR_HTML = '''<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>手机互联 · Phone pairing</title>
<style>
  :root { color-scheme: light dark; --fg:#111; --muted:#666; --bg:#fafafa; --card:#fff; --line:#e6e6e6; --ok:#0a7; --wait:#c60; }
  @media (prefers-color-scheme: dark) {
    :root { --fg:#eee; --muted:#aaa; --bg:#121212; --card:#1c1c1c; --line:#2a2a2a; }
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
  #state.wait { color: var(--wait); }
  #phones { margin: 20px 0 0; padding: 0; list-style: none; text-align: left; border-top: 1px solid var(--line); }
  #phones li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line); font-size: .92rem; }
  #phones .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
  #phones .dot.ok { background: var(--ok); }
  #phones .lbl { flex: 1; min-width: 0; }
  #phones .lbl small { display: block; color: var(--muted); font-size: .8rem; }
  #phones button { border: 1px solid var(--line); background: none; color: var(--fg); border-radius: 8px; padding: 4px 10px; font: inherit; font-size: .85rem; cursor: pointer; }
  #phones .none { color: var(--muted); justify-content: center; }
</style></head><body>
<div class="card">
  <h1>手机互联</h1>
  <p class="sub">用 GAndroid 扫码连接本机 · 可同时连接多台手机</p>
  <canvas id="qr" width="220" height="220"></canvas>
  <pre id="code">……</pre>
  <p id="state">starting…</p>
  <ul id="phones"></ul>
</div>
<script src="/pair/qr.js"></script>
<script>
const fmt = ts => ts ? new Date(ts*1000).toLocaleString() : '';
const ST = { connected:'已连接', reconnecting:'重连中', error:'异常', idle:'…' };
async function forget(slot){ await fetch('/pair/forget?slot='+encodeURIComponent(slot), {method:'POST'}); poll(true); }
let timer = null;
async function poll(once){
  clearTimeout(timer);
  try{
    const s = await (await fetch('/pair/status')).json();
    document.getElementById('code').textContent = s.code || '—';
    const st = document.getElementById('state');
    st.textContent = (s.status === 'waiting' ? '等待手机扫码' : s.status === 'error' ? '出码失败' : '配对码生成中')
                     + (s.error ? ' · ' + s.error : '');
    st.className = s.status === 'waiting' ? 'wait' : '';
    if (s.qr_payload && window.QR) { try { QR.renderCanvas(s.qr_payload, document.getElementById('qr'), 220); } catch (e) {} }
    const ul = document.getElementById('phones'); ul.innerHTML = '';
    if (!s.phones || !s.phones.length) { const li = document.createElement('li'); li.className='none'; li.textContent='尚无手机配对'; ul.appendChild(li); }
    (s.phones || []).forEach((p, i) => {
      const li = document.createElement('li');
      const dot = document.createElement('span'); dot.className = 'dot' + (p.status === 'connected' ? ' ok' : '');
      const lbl = document.createElement('span'); lbl.className = 'lbl';
      lbl.textContent = '手机 ' + (i+1) + ' · ' + (ST[p.status] || p.status) + (p.error ? ' · ' + p.error : '');
      const sm = document.createElement('small'); sm.textContent = '配对于 ' + fmt(p.saved_at); lbl.appendChild(sm);
      const btn = document.createElement('button'); btn.textContent = '移除'; btn.onclick = () => forget(p.slot);
      li.append(dot, lbl, btn); ul.appendChild(li);
    });
  } catch (e) {
    document.getElementById('state').textContent = String(e);
  }
  if (!once) timer = setTimeout(poll, 1000);
}
poll();
</script>
</body></html>
'''
