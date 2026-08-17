# ga-tokenplan-import

GenericAgent 桌面版 TokenPlan 导入：本机 34134 回调，把 TokenPlan 站下发的 `TOKENPLAN` snippet 写入 `mykey.py`。

默认门户：**https://plan.khrey.com/**

开源上游没有这份插件。本目录是发布源；桌面安装包不随包携带。运行时 **先探测** `plugins/subscription_portal.py`（源码树还会探测本 extras），缺失则读取：

```text
https://plan.khrey.com/desktop/plugin-manifest.json
```

核对 size / SHA-256 后解压写入 `plugins/subscription_portal.py`（与 GAnet 插件清单同款）。`latest.json` 的 `plugin` 字段是同一份清单的副本。

发版时 `sync_plan_khrey_desktop.sh` 会调用 `pack_release.py` 把 zip 和清单镜像到 plan.khrey.com。

## 源码树

clone 后直接启动桌面端即可：探测会命中本目录，不必先下载。

换门户 / 邀请码 / 清单：

```bash
export GA_TOKENPLAN_URL=https://plan.khrey.com/
export GA_TOKENPLAN_INVITE=ljq
export GA_TOKENPLAN_PLUGIN_MANIFEST=https://plan.khrey.com/desktop/plugin-manifest.json
```

关掉（下次点击 GA Token 会再探测并安装）：

```bash
python3 extras/ga-tokenplan-import/install.py uninstall
# 或删 plugins/subscription_portal.py 后重启
```

开发时若只改 extras、想强制写成 plugins 文件：

```bash
python3 extras/ga-tokenplan-import/install.py install --copy
```

也可 `pip install -e extras/ga-tokenplan-import` 之后用命令 `ga-tokenplan-import`。

打包插件 zip（CI / 镜像脚本会调）：

```bash
python3 extras/ga-tokenplan-import/pack_release.py --out-dir dist/plugin \
  --public-base https://plan.khrey.com/desktop/files
```

## 行为

- 打开浏览器到 `GA_TOKENPLAN_URL`（默认 plan.khrey.com）
- 监听 `127.0.0.1:34134`，CORS 对本机开放
- `POST/GET` 只接受服务端 `snippet` / `block`，整段替换 `<TOKENPLAN>…</TOKENPLAN>`
- **双写**：当前 `GA_ROOT/mykey.py` + 已存在的 `~/GA/GenericAgent/mykey.py`（可用 `GA_MYKEY_PATH` 再加目标）
- 测试或单目标写入设 `GA_TOKENPLAN_IMPORT_DUAL=0`
