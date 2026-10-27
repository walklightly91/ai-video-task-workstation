# VideoTaskHub 第三方组件与许可说明

`VideoTaskHub` 目录中标有 [MIT License](LICENSE) 的原创模块仍保留其 MIT 许可；但仓库作为可运行软件组合的公开发行采用根目录 `LICENSE` 所载的 GPL-3.0-only。该组合许可证不替代任何第三方软件、模型、服务或操作系统组件的许可证。

本清单基于当前正式入口 `videotaskhub_app.py`、核心模块 `videotaskhub_core.py`、数据模块 `videotaskhub_data.py`、构建配置及 `work/qtdeps` 的已安装包整理。它是发布核对清单，不构成法律意见。

## 依赖范围

| 范围 | 内容 | 是否随普通 Qt 运行环境提供 |
| --- | --- | --- |
| 正式桌面端 | Python、PyQt6、Qt 动态库 | 是 |
| 本地 AI 图文匹配 | requests、PyTorch、Transformers、Sentence Transformers、Pillow、NumPy、CN-CLIP 等 | 否，按用户选择安装或下载 |
| 远程视觉 API | `requests` 与用户自行配置的 API 服务 | 否 |
| 构建环境 | PyInstaller 及其构建依赖 | 仅开发/构建时 |
| 历史参考文件 | `main.py`、`videotaskhub_legacy_extract.py` | 不属于正式入口；其额外能力须单独审计后才可发布 |

## 正式桌面端及构建组件

| 组件 | 当前记录版本 | 许可证/说明 | 上游许可信息 |
| --- | --- | --- | --- |
| Python | 由发行环境决定 | PSF License | https://docs.python.org/3/license.html |
| PyQt6 | 6.11.0 | GPL-3.0-only 或商业许可；当前开源发行采用 GPL-3.0-only | https://en.riverbankcomputing.com/software/pyqt |
| Qt 及 PyQt6 wheel 内含的第三方组件 | 随 PyQt6 6.11.0 | 以实际 wheel 的许可证、NOTICE 和 Qt 第三方声明为准 | https://doc.qt.io/qt-6/licensing.html |
| PyInstaller | 6.11.1 | GPL-2.0-or-later，附对被打包应用的特别例外；构建工具本身不改变上游或项目组合的许可证义务 | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |
| pyinstaller-hooks-contrib | 2024.10 | 构建依赖；保留其发行包中的 LICENSE 文件 | https://github.com/pyinstaller/pyinstaller-hooks-contrib |
| altgraph | 0.17.5 | MIT | https://github.com/ronaldoussoren/altgraph |
| pefile | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause；仅 Windows 构建链使用 | https://github.com/enthought/pywin32-ctypes |

`requirements-base.txt` 列出正式 Qt 运行依赖。PyInstaller 及其依赖仅用于构建，不应被误写为应用功能依赖。

## 可选 AI 与网络组件

以下组件由本地 AI 匹配或远程 API 模式按需导入；它们不在当前 Qt 运行环境中固定捆绑。建议仅在需要对应功能时，根据 [requirements-ai.txt](requirements-ai.txt) 安装，并在把它们打进发行包时保留**该次实际安装版本**随附的许可证和 NOTICE。

| 组件 | 用途 | 上游许可证/注意事项 |
| --- | --- | --- |
| requests | 远程视觉 API 请求 | Apache-2.0：https://github.com/psf/requests |
| PyTorch / torch | 本地模型推理 | PyTorch 主体为 BSD-3-Clause；二进制 wheel 还可能含 CUDA、MKL 等其他组件，必须随实际 wheel 保留完整许可文件：https://github.com/pytorch/pytorch/blob/main/LICENSE |
| Transformers | CLIP 模型与处理器 | Apache-2.0：https://github.com/huggingface/transformers/blob/main/setup.py |
| sentence-transformers | 本地图文匹配优先后端 | Apache-2.0；以实际安装包随附许可为准：https://github.com/UKPLab/sentence-transformers |
| Pillow | 图片读取与处理 | MIT-CMU：https://github.com/python-pillow/Pillow/blob/main/LICENSE |
| NumPy | 向量与图像数组计算 | 主许可证 BSD-3-Clause；wheel 可能含额外依赖许可，须随实际 wheel 核对：https://github.com/numpy/numpy/blob/main/LICENSE.txt |
| safetensors | 安全权重格式支持 | Apache-2.0；部分 wheel 未附许可证文件时，发行者仍须主动提供许可证副本：https://github.com/safetensors/safetensors |
| CN-CLIP / `cn_clip` | 本地中文 CLIP 兜底后端 | 上游仓库标注 MIT；仅按需安装，且仍须核对其传递依赖与模型权重许可证：https://github.com/OFA-Sys/Chinese-CLIP |

## 模型、外部服务与素材

1. 模型代码的许可证不等于模型权重、训练数据或模型卡的许可证。VideoTaskHub 不在源代码仓库或普通 Qt 发行包中预置模型权重。
2. 默认模型名称仅是下载标识；如将模型权重缓存后随软件、网盘或安装包再分发，必须先阅读该模型页/模型卡的许可证与使用限制。例如默认中文 CLIP 模型页面：<https://huggingface.co/OFA-Sys/chinese-clip-vit-large-patch14>。
3. 用户配置的远程 API、云端模型、密钥和上传素材受相应服务条款、隐私政策及素材权利约束；项目不授予这些内容的任何再分发权。
4. 用户导入的图片、文案、视频及导出结果的著作权、肖像权、商标权和其他权利由用户自行确认。

## 历史参考代码的边界

仓库根目录的 `main.py` 是旧版/参考实现，不由 `启动VideoTaskHub.bat`、`videotaskhub_app.py` 或 `VideoTaskHub.spec` 调用。扫描发现它还可能自动安装或调用 `urllib3`、`python-vlc` 与 VLC Runtime、OpenCV、Markdown、pandas、openpyxl、librosa、faster-whisper、llama-cpp-python、accelerate 及其模型/运行时等组件。

这些组件**不在本次正式 VideoTaskHub 发行依赖清单中**，也没有被本文件逐项作为可发布组件确认。若未来重新启用或发布该文件，必须先锁定实际版本、补全每个包及其传递依赖的许可证，并另行核对 VLC、模型权重、语音模型和系统编解码组件的许可。发布普通 VideoTaskHub 时，建议不要将该参考文件或其缓存、模型、运行时打入可执行发行包。

`assets/` 中的图标仅应放入对其拥有使用和再分发权的文件；新增第三方图标、字体、示例图片或音视频前，也必须记录来源、作者和许可。

## 发布前必须执行的核对

1. 发布当前 GPL 版本时：随包提供根目录 `LICENSE`、`THIRD_PARTY_NOTICES.md`，并保留 PyQt6/Qt 发行内容中自带的许可文件。
2. 若用 PyInstaller 打包：从**最终用于打包的虚拟环境**导出依赖清单，复制每个被收集包的许可证、NOTICE 与版权文件；不要仅依赖本表中的版本。
3. 若打包本地 AI：额外核对 torch、CUDA/显卡运行时、NumPy、Pillow、Transformers、Sentence Transformers、CN-CLIP 及模型权重的真实版本和全部传递依赖。
4. 不要把 `work/qtdeps`、用户配置目录、模型缓存或构建缓存原样上传为源代码发行包；它们可能包含不在当前清单中的二进制组件或用户数据。
5. 新增依赖、模型、图标、字体、示例素材或在线服务前，应同步更新本文件和 [Release/THIRD_PARTY_NOTICES.md](Release/THIRD_PARTY_NOTICES.md)。

如涉及商业发布、预装模型、嵌入 CUDA 或向第三方提供云服务，请在正式发布前取得专业法律意见。
