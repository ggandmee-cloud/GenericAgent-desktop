# 本仓库是什么

这是本地桌面版工作树，基于 [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent)，不是官方仓。

`mykey.py` 不会进 git。克隆下来要自己配模型，或按下面装可选包从 TokenPlan 导入。

## 跑桌面端

开发启动见上游文档与 `frontends/desktop/`。macOS 装机包说明：`docs/macos_desktop_installation_zh.md`。

## 可选包：TokenPlan 导入 key

默认 **不启用**。仓库里带的是源码，在 `extras/ga-tokenplan-import/`；不会自动写进 `plugins/`。

别人 clone 之后若需要「设置 → GA Token / 本机 34134 导入」：

```bash
git clone <本仓库>
cd GenericAgent-desktop          # 目录名以你 clone 的为准
python3 extras/ga-tokenplan-import/install.py install --copy
```

然后重启桌面端。卸掉：

```bash
python3 extras/ga-tokenplan-import/install.py uninstall
```

不装可选包时，桌面端与开源上游一样：没有 GA Token 入口，用设置里的「导入模型配置」或手写 `mykey.py`。

更细的说明：`extras/ga-tokenplan-import/README.md`。
