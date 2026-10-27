# v1.4.0 安全审核报告

审核日期：2026-10-28（复审更新）  
审核范围：仅 `AI视频任务工作站-dev源码v1.4.0-GitHub上传源码-GPL-3.0-only`；不包含工作目录、历史版本、模型、缓存、用户配置或构建产物。

## 项目概况

- 语言与框架：Python 3.11、PyQt6 桌面应用、PyInstaller；内含隔离的 Seed-VC 语音转换子项目。
- 审核文件：62 个 Python 文件、8 份 Python 依赖清单、1 个 GitHub Actions 发布工作流、安装/构建脚本与配置文件。
- 锁文件：未提供 `poetry.lock`、`requirements.lock` 或其他可重建锁文件。因此仅能确认清单中固定的直接依赖；间接依赖的最终版本须在发布构建环境中重新导出并审计。
- 本地工具：未安装 `pip-audit`、`safety`、`bandit` 或 `semgrep`；已用 OSV API 对清单中的 54 条固定依赖声明做版本查询（去重后为 49 个包），并以 OSV/GitHub Advisory 的公开记录交叉确认重点问题。2026-10-28 的复审结果仅命中 `torch 2.11.0` 的一项已知公告。

## 直接依赖清单

主运行环境：`requests 2.34.2`、`urllib3 2.8.0`、`PyQt6 6.11.0`、`PyAutoGUI 0.9.54`、`pyperclip 1.11.0`、`Pillow 13.0.0`、`opencv-python 5.0.0.93`、`Markdown 3.10.3`、`pandas 3.0.5`、`openpyxl 3.1.5`、`numpy 2.4.6`、`python-vlc 3.0.21203`、`Send2Trash 1.8.3`、`faster-whisper 1.2.1`、`ctranslate2 4.8.1`、`librosa 0.11.0`、`soundfile 0.14.0`、`transformers 5.20.1`、`accelerate 1.15.0`、`safetensors 0.8.0`、`sentence-transformers 5.7.0`、`qwen-vl-utils 0.0.14`、`nvidia-ml-py 13.610.43`、`fsspec 2026.9.0`、`torch/torchvision/torchaudio 2.11.0/0.26.0/2.11.0`、`PyInstaller 6.22.2`。

可选项：`llama-cpp-python 0.3.36`、`cn-clip 1.6.0`、`pillow-heif 1.8.1`、`rawpy 0.27.1`、`pysubs2 1.8.1`。

Seed-VC 独立推理环境：`accelerate 1.15.0`、`scipy 1.13.1`、`librosa 0.10.2`、`huggingface-hub 2.2.0`、`munch 4.0.0`、`einops 0.8.0`、`descript-audio-codec 1.0.0`、`pydub 0.25.1`、`resemblyzer 0.1.4`、`jiwer 3.0.3`、`transformers 5.20.1`、`FreeSimpleGUI 5.1.1`、`soundfile 0.12.1`、`sounddevice 0.5.0`、`modelscope 1.27.0`、`funasr 1.1.5`、`numpy 1.26.4`、`Pillow 13.0.0`、`hydra-core 1.3.8`、`pyyaml 6.0.3`、`python-dotenv 1.2.4`、`urllib3 2.8.0`、`werkzeug 3.1.9`。Gradio WebUI 不属于该推理环境。

这些是两个独立环境，不能混合安装；它们故意存在 Pillow、NumPy、Librosa 和 SoundFile 版本差异。

## 问题汇总

| 编号 | 类别 | 严重级别 | 位置 | 状态 |
| --- | --- | --- | --- | --- |
| SEC-01 | 代码：文件边界绕过 | Medium | `file_operation_engine.py:38` 与 `VideoTaskHub/file_operation_engine.py:38` | 已修复 |
| SEC-02 | 依赖：Hydra 策略绕过 | High | `seed-vc/requirements.txt:28` | 已修复 |
| SEC-03 | 依赖：Pillow 图像解码 | Critical | `seed-vc/requirements.txt`；安装器过滤规则 | 已修复 |
| SEC-04 | 依赖：PyTorch JIT | Low | `requirements-torch-cpu.txt:6`；Seed-VC JIT 调用 | 待开发者决定 |
| SEC-05 | 供应链：未固定的 BigVGAN Hub 权重 | Medium | `seed-vc/inference.py:116-117` | 待开发者决定 |
| SEC-06 | 供应链：FFmpeg 可变下载包 | Medium | `bootstrap_install.py:30-32, 45-76, 109-116` | 已修复 |
| SEC-07 | 依赖可重现性 | Low | 全部 requirements 文件 | 建议关注 |
| SEC-08 | CI：构建工具版本漂移 | Low | `.github/workflows/release.yml:34` | 已修复 |

## 已修复

### SEC-01：目录联接/符号链接逃逸

此前文件操作引擎使用 `abspath()` 做允许目录检查。若允许目录内存在指向外部位置的符号链接或 Windows 目录联接，字符串前缀检查可能允许实际操作落到允许目录之外。

已在两个引擎副本中改为 `realpath(abspath(...))` 后再比较边界和同一路径。正常的重命名、复制、移动和回收站操作不受影响；解析到允许目录外的联接目标会被拒绝。

### SEC-02：Hydra 1.3.6 / 1.3.7

初始修复将 `hydra-core` 从 `1.3.6` 升至 `1.3.7`。2026-10-27 新公开的公告又确认 `1.3.7` 仍受影响，因此已继续升至同一稳定分支的 `1.3.8`。该版本修复 `instantiate()` 可被不可信配置导向不安全 PyYAML 加载器的问题：[GHSA-wf6j-7hvr-gr93](https://github.com/advisories/GHSA-wf6j-7hvr-gr93)。这是补丁级升级，不改变 Seed-VC 的配置格式。

### SEC-08：发布构建工具版本漂移

发布工作流原先直接执行未固定版本的 `pip install pyinstaller`，即使项目已有 `requirements-build.txt`，也可能在未来构建中无提示使用不同版本。现已改为安装该固定清单中的 `PyInstaller 6.22.2`。

## 需要开发者决定

### SEC-03：Seed-VC 的 Pillow 12.3.0

OSV 显示 Pillow `<=12.3.0` 存在至少一项已修复的严重 JPEG 解码堆溢出，修复版本为 `13.0.0`：[GHSA-8g5g-8vmr-9782](https://osv.dev/vulnerability/GHSA-8g5g-8vmr-9782)。程序会处理用户选择的图片/视频帧，因此不应把不可信图像视为完全无风险。

已修复：VideoTaskHub 只调用 `inference.py`，不使用 Seed-VC 的 Gradio WebUI。已从主推理清单移除 Gradio、将 Pillow 固定为 `13.0.0`，并让两个安装器副本即使遇到上游需求文件再次列入 Gradio 时也会排除它。安装后会验证 Pillow 至少为 13.0。

原始 Seed-VC 的 `app.py`、`app_vc.py` 等浏览器入口仍保留在上游源码中，但不属于本发行版支持的运行模式；若将来要恢复 WebUI，应创建独立环境，不能与受支持的推理环境混装。

### SEC-04：PyTorch 2.11.0

OSV 查询将 `torch 2.11.0` 命中 `GHSA-rrmf-rvhw-rf47`。该问题与 `torch.jit.script` 有关，而 Seed-VC 源码确实使用了该 API，例如 `seed-vc/modules/commons.py:131` 和 `seed-vc/modules/openvoice/attentions.py:27`。官方公告将其列为 Low，受影响范围为 `<=2.12.1`，修复版本为 `2.13.0`：[GHSA-rrmf-rvhw-rf47](https://github.com/advisories/GHSA-rrmf-rvhw-rf47)。本项目仅对随源码提供的内部模块使用 JIT，未发现把用户提供代码交给 JIT 的路径，因此实际暴露面低于通用库场景。

建议升级到与 TorchAudio、TorchVision、CUDA 轮子完全匹配的官方修复组合后，执行 Seed-VC 模型加载和实际转换回归测试；不能单独替换 `torch`，也不应在未经验证的情况下猜测固定版本。

### SEC-05：BigVGAN 模型供应链

Seed-VC 自身的关键权重下载已采用固定 Hugging Face revision 和 SHA-256 校验；本地 `torch.load` 调用使用 `weights_only=True`。但 BigVGAN 仍由配置提供模型标识并调用 Hub 下载，未固定 revision 或文件哈希。模型文件不执行远程 Python 代码，但模型内容仍可能被上游可变分支替换。

修复需要先确认实际使用的 BigVGAN 模型 ID、对应 commit 和兼容的权重哈希；随后才能固定 revision 与 SHA-256，不能凭空写入值。

### SEC-06：FFmpeg 可变下载包

已固定到发行方当前稳定版 FFmpeg `9.0.2` Windows x64 GPL Essentials 包：`ffmpeg-9.0.2-essentials_build.zip`。安装器使用不可变的版本化 URL，并在流式下载时验证发行方公布的 SHA-256 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`；哈希不匹配时会删除临时包并拒绝安装。该构建包含本软件需要的 `ffmpeg.exe` 与 `ffprobe.exe`。

## 密钥与凭据

- 未发现 API Key、Token、私钥、证书、带密码的 URL 或数据库连接串硬编码在本次范围内。
- `.gitignore` 已排除 `.env`、`config.json`、运行状态文件、证书/私钥扩展名、模型、媒体和构建产物；`.env.example` 只含变量名。
- 用户保存的 API 凭据由 Windows DPAPI 保护。若历史 Git 提交曾含真实凭据，必须在对应平台撤销并重新生成；删除源码中的文本不足以使旧凭据失效。

## 代码与 CI 结论

- 未发现 `shell=True`、关闭 TLS 证书验证、`yaml.load()`、`pickle`/`dill` 反序列化或应用自定义加密。
- ZIP 安装包与配置备份均对路径穿越和解压容量设限；安装器下载限制 HTTPS 主机、文件尺寸和符号链接。
- 模型加载默认关闭 `trust_remote_code`；Seed-VC 固定的权重加载使用 `weights_only=True`。
- 发布工作流仅由 tag push 触发，没有 `pull_request_target`；第三方 Actions 以 commit SHA 固定。
- 发布工作流现从 `requirements-build.txt` 安装固定的 PyInstaller 版本，不再使用未固定的构建工具。

## 验证

- 62 个 Python 文件已用不生成字节码的 AST 解析检查通过。
- 文件操作引擎的正常重命名、非法名称拒绝回归检查通过；Windows DPAPI 往返加解密与 ZIP 路径拒绝检查通过。
- FFmpeg 固定版本下载的哈希匹配与不匹配拒绝分支均已通过模拟下载回归；发行方当前公布的 SHA-256 与源码常量一致。
- 重新查询 49 个固定直接依赖的 OSV 记录：Hydra 升至 `1.3.8` 后，只有上文列明的 PyTorch JIT 公告仍匹配。
- 交付目录复核为 0 个缓存目录、模型下载、字节码或二进制构建产物；仅保留 4 个受版本控制的界面 PNG 资源（应用图标与两张背景图）。

## 后续建议

1. 在受控构建环境生成带哈希的锁文件或 SBOM，并在发布 CI 中运行 `pip-audit`/OSV 扫描。
2. 对新建的 Seed-VC 推理环境做一次真实媒体转换回归；现有已安装的旧环境不会因源码修改自动升级。
3. 固定所有首次下载模型的 revision 与 SHA-256；BigVGAN 是当前剩余缺口。
