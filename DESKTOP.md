# 本仓库是什么

这是本地桌面版工作树，基于 [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent)，不是官方仓。

`mykey.py` 不会进 git。克隆后 **TokenPlan 导入已启用**，门户是 [https://plan.khrey.com/](https://plan.khrey.com/)。

## 跑桌面端

开发启动见上游文档与 `frontends/desktop/`。macOS 装机包说明：`docs/macos_desktop_installation_zh.md`。

启动后设置 / 模型菜单里应有 **GA Token**：点开会打开 plan.khrey.com，本机 `127.0.0.1:34134` 收 snippet 写入 `mykey.py`。

## TokenPlan 导入 key

源码在 `extras/ga-tokenplan-import/`，`plugins/subscription_portal.py` 是薄加载，clone 即可用，不必再跑 install。

换门户或邀请码（可选）：

```bash
export GA_TOKENPLAN_URL=https://plan.khrey.com/
export GA_TOKENPLAN_INVITE=ljq
```

若要关掉这套导入，删掉 `plugins/subscription_portal.py` 后重启。也可用：

```bash
python3 extras/ga-tokenplan-import/install.py uninstall
```

更细的说明：`extras/ga-tokenplan-import/README.md`。
