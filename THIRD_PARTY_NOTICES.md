# 第三方组件、许可证与发布声明

## 项目发布许可证

本仓库当前可运行的软件组合采用 **GNU GPL v3.0 only**。这是由当前实际使用的 PyQt6（GPL-3.0-only）和随附 Seed-VC（GPL-3.0）共同决定的发布策略。第三方组件仍保留各自许可证；模型权重、用户素材、缓存和生成结果不随仓库发布。

本项目的默认字幕链路只使用下列可审计的开源组件；发布前必须保留本文件、各组件
许可证文本以及所用二进制的构建信息。

| 组件 | 用途 | 许可证 | 发布规则 |
| --- | --- | --- | --- |
| faster-whisper | 本地语音转写、基础词时间戳 | MIT | 可作为默认本地引擎；保留 MIT 声明。 |
| WhisperX | 可选词级强制对齐 | BSD-2-Clause | 不默认安装，不捆绑模型；由用户明确启用。 |
| pysubs2 | SRT/ASS/SSA/VTT 的读写与转换 | MIT | 可选依赖；保留 MIT 声明。 |
| libass | ASS/SSA 字幕渲染 | ISC | 通过合规 FFmpeg 构建使用；保留 ISC 声明。 |
| FFmpeg | 视频与 ASS 字幕渲染 | LGPL-2.1-or-later 或 GPL-2.0-or-later | 发行包只允许 LGPL-only 构建，除非整个项目改为 GPL 并履行 GPL 义务。 |
| PyQt6 | 当前桌面界面绑定 | GPL-3.0-only（或商业许可） | 当前开源发行使用 GPL-3.0-only；不得错误声称其为 LGPL。 |
| Seed-VC | 可选本地人声转换 | GPL-3.0 | 源码位于 `seed-vc/`，保留其原始 LICENSE；模型权重不随仓库发布。 |

## 严格禁止随发行包自动携带的内容

- 启用了 `--enable-gpl` 的 FFmpeg，或带有 `libx264`、`libx265` 等 GPL 组件的 FFmpeg。
- 未逐项核实许可的 WhisperX 对齐模型、说话人分离模型、Hugging Face 模型权重。
- 受限商用字体、Windows/Office 字体副本、来源不明 ASS 模板或 Lua 特效脚本。
- 会在用户不知情的情况下下载模型或将用户音视频上传到第三方服务的代码路径。

## 模型与字体政策

“源码开源”不代表“模型权重可再分发”。WhisperX 仅作为可选本地适配器：首次启用时
必须显示模型来源、模型许可证、下载大小和用户确认；默认不下载、不随安装包分发。
内置字体仅可使用 SIL Open Font License（OFL）或同等可再分发许可的字体，并同时携带
其许可证。用户自行选择的本机字体不随本项目分发。

## 发布检查

1. 执行 `ffmpeg -version`，确认没有 `--enable-gpl`、`--enable-libx264`、`--enable-libx265`。
2. 随发行包提供 FFmpeg 的 LGPL 声明、源码获取地址和完整构建配置。
3. 对每个附带模型、字体和二进制建立来源、版本、哈希和许可证清单。
4. CI 禁止把模型缓存、字体缓存、`*.pt`、`*.bin`、`*.safetensors`、`*.onnx` 误提交进源码仓库。

参考：

- https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE
- https://github.com/m-bain/whisperX/blob/main/LICENSE
- https://github.com/tkarabela/pysubs2
- https://github.com/libass/libass/blob/master/COPYING
- https://ffmpeg.org/legal.html
