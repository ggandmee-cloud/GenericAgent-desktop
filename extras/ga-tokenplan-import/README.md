# ga-tokenplan-import

GenericAgent **可选包**：本机 34134 回调，把 TokenPlan 站下发的 `TOKENPLAN` snippet 写入 `mykey.py`。

开源上游 **没有** 这份插件。桌面设置「GA Token」和 Streamlit 空 key 引导已经按
`getattr(agentmain, "start_subscription_portal", None)` 探测——文件不在就隐藏入口，不改核心。

克隆本仓库后默认 **不启用**。`plugins/subscription_portal.py` 仍在 `.gitignore` 里。

## 别人拿到仓库之后怎么装

在**仓库根目录**执行（会把插件复制进当前克隆的 `plugins/`）：

```bash
python3 extras/ga-tokenplan-import/install.py install --copy
```

开发机想跟着 extras 源文件改、不必每次复制：

```bash
python3 extras/ga-tokenplan-import/install.py install --link
```

看状态 / 卸掉：

```bash
python3 extras/ga-tokenplan-import/install.py status
python3 extras/ga-tokenplan-import/install.py uninstall
```

指定另一棵 GA 树：

```bash
python3 extras/ga-tokenplan-import/install.py install --copy --ga-root /path/to/GenericAgent
```

装上后重启桌面端 / 桥。`discover_and_load()` 会 import 该插件，并挂上 `agentmain.start_subscription_portal`。设置里才会出现「GA Token」。

也可 `pip install -e extras/ga-tokenplan-import` 之后用命令 `ga-tokenplan-import`。

## 行为

- 监听 `127.0.0.1:34134`，CORS 对本机开放
- `POST/GET` 只接受服务端 `snippet` / `block`，整段替换 `<TOKENPLAN>…</TOKENPLAN>`
- **双写**：当前 `GA_ROOT/mykey.py` + 已存在的 `~/GA/GenericAgent/mykey.py`（可用 `GA_MYKEY_PATH` 再加目标）
- 测试或单目标写入设 `GA_TOKENPLAN_IMPORT_DUAL=0`
- 邀请码 `INVITE_CODE` 会进门户 URL

卸掉插件后上游行为不变：设置里不再出现 GA Token 入口。
