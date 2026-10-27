# GitHub 公开上传前核对清单

本文件用于防止把没有再分发权的内容上传到公开仓库；它不是法律意见。

## 已确定的许可证策略

当前首次公开版本已确定采用 **GPL-3.0-only**。当前程序实际依赖 `PyQt6`（GPL-3.0-only），且随源码附带的 `seed-vc/` 使用 GPL-3.0；仓库根目录必须保留完整的 [LICENSE](LICENSE) 文本。

未来若迁移到 PySide6 LGPL、取得 PyQt 商业授权并移除/隔离 Seed-VC，可为后续版本重新评估许可证；已公开的 GPL-3.0-only 版本仍保留其既有授权。

## 上传前禁止包含的内容

- 任何模型权重、缓存或检查点，包括 `*.bin`、`*.onnx`、`*.pt`、`*.pth`、`*.safetensors`、`*.ckpt`、`*.gguf` 与 `*.tflite`。
- 用户素材、演示音视频、生成结果及来源不明的图片、字体或 ASS 模板。
- 虚拟环境、构建产物、FFmpeg/VLC 等二进制文件；除非已逐项确认其许可证、来源、版本、哈希和再分发条件。
- 配置、日志、`.env`、API 密钥、证书、用户数据和模型下载缓存。

`.gitignore` 已覆盖上述常见类型，但忽略规则不能保护已被强制加入或已经提交到 Git 历史的文件。

## 上传前逐项确认

1. 保留仓库根目录 GPL-3.0-only `LICENSE` 文本。
2. 保留 `seed-vc/LICENSE`、`VideoTaskHub/LICENSE`、`THIRD_PARTY_NOTICES.md` 和所有随包字体的 OFL 文件。
3. 对每一张保留的界面图片、图标和背景，记录作者、来源、许可与是否允许公开再分发；无法证明权利的文件不上传。
4. 如果发布可执行包，核验 FFmpeg 为 LGPL-only 构建，并随包提供其许可证、构建配置和源码获取方式。
5. 模型权重只提供官方下载链接和许可证说明，不将权重推送到仓库，除非模型卡明确允许再分发。
6. 上传前检查暂存区，确认没有二进制模型、媒体、缓存、凭据或构建输出。

## 现有文件的特别说明

- `seed-vc/campplus_cn_common.bin`、`seed-vc/baselines/dnsmos/*.onnx` 和 `seed-vc/assets/real-time-demo.webm` 均不应作为本项目自行确认可再分发的内容上传。
- `assets/` 与 `VideoTaskHub/assets/` 中的字体已保留 OFL 许可证；背景图、图标和其他视觉资源仍须由项目权利人确认来源与公开再分发权。
