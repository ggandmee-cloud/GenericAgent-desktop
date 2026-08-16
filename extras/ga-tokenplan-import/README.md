# ga-tokenplan-import

GenericAgent 桌面版 **开箱即用**：本机 34134 回调，把 TokenPlan 站下发的 `TOKENPLAN` snippet 写入 `mykey.py`。

默认门户：**https://plan.khrey.com/**

开源上游没有这份插件。本仓用 `plugins/subscription_portal.py` 薄加载本目录，clone 后设置里就会出现「GA Token」。

## 别人拿到仓库之后

不用再跑 install。直接启动桌面端。

换门户 / 邀请码：

```bash
export GA_TOKENPLAN_URL=https://plan.khrey.com/
export GA_TOKENPLAN_INVITE=ljq
```

关掉：

```bash
python3 extras/ga-tokenplan-import/install.py uninstall
# 或删 plugins/subscription_portal.py 后重启
```

开发时若只改 extras、插件文件丢了，可重新挂上：

```bash
python3 extras/ga-tokenplan-import/install.py install --copy
```

也可 `pip install -e extras/ga-tokenplan-import` 之后用命令 `ga-tokenplan-import`。

## 行为

- 打开浏览器到 `GA_TOKENPLAN_URL`（默认 plan.khrey.com）
- 监听 `127.0.0.1:34134`，CORS 对本机开放
- `POST/GET` 只接受服务端 `snippet` / `block`，整段替换 `<TOKENPLAN>…</TOKENPLAN>`
- **双写**：当前 `GA_ROOT/mykey.py` + 已存在的 `~/GA/GenericAgent/mykey.py`（可用 `GA_MYKEY_PATH` 再加目标）
- 测试或单目标写入设 `GA_TOKENPLAN_IMPORT_DUAL=0`
