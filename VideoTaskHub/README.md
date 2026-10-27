# VideoTaskHub

**AI 视频任务工作台**：用于识别、匹配、整理图片与文案，输出待生成任务，并为后续视频回收、核验与返工管理提供统一的数据基础。

桌面端运行入口是 `videotaskhub_app.py`。运行源码按职责分为：

- `videotaskhub_app.py`：Qt 界面、导航和交互。
- `videotaskhub_data.py`：项目、指令、扫描、历史、日志和跨平台配置。
- `videotaskhub_core.py`：表格引擎、AI 匹配、路径模板、英文分段等核心能力。

## 当前能力

- 递归扫描数字台词 TXT、图片与同名视频；已完成视频会自动跳过。
- 图文智能匹配、批量整理、分段英文、图片副本与 CSV/Excel/TXT 导出。
- 内置项目工作台、指令库、临时表格查看与编辑、操作历史、系统日志和皮肤设置。
- 默认本地 CLIP 极速匹配；也可保存远程视觉 API 配置。

## 数据目录

VideoTaskHub 从全新用户配置开始，不读取、复制或修改旧版 `dialogue-material-manager` 数据。

| 平台 | 默认用户配置目录 |
| --- | --- |
| Windows | `%APPDATA%\video-task-hub` |
| macOS | `~/Library/Application Support/video-task-hub` |
| Linux | `$XDG_CONFIG_HOME/video-task-hub`，默认 `~/.config/video-task-hub` |

配置目录中保存 `settings.json`、项目、指令库、历史、临时表格快照、皮肤资源与日志。软件设置含 `application_id: video-task-hub` 与配置格式版本，便于未来云同步及浏览器插件接入。

## 本地开发环境

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-qt.txt
python -m pip install PyInstaller
```

如需使用本地 AI 图文匹配或远程视觉 API，再安装可选依赖：

```bat
python -m pip install -r requirements-ai.txt
```

本地模型权重不随项目发布；若准备把 AI 依赖或模型打入发行包，请先阅读 [NOTICE.md](NOTICE.md) 的模型与发布核对要求。

运行桌面端：

```bat
.\.venv\Scripts\python.exe .\videotaskhub_app.py
```

也可双击 `启动VideoTaskHub.bat`。

## 构建 Windows 绿色版

若发行版需要支持“本地 CLIP 极速匹配”，构建环境必须先安装完整 AI 依赖：

```bat
python -m pip install -r requirements-ai.txt
```

请使用项目内的构建配置。它会将本地 AI 所需的 PyTorch、Transformers、Pillow、NumPy、Safetensors 等延迟加载组件一并收集，避免 EXE 在其它电脑上无法启动 AI 匹配：

```bat
python -m PyInstaller --clean --noconfirm VideoTaskHub.spec
```

产物位于 `dist\VideoTaskHub\VideoTaskHub.exe`。

单文件版：

```bat
python -m PyInstaller --clean --noconfirm --onefile --windowed --noupx --name "VideoTaskHub" --icon="assets\app_icon.ico" --version-file "version_info.txt" --add-data "assets;assets" --collect-all torch --collect-all torchvision --collect-all numpy --collect-all PIL --collect-all transformers --collect-all tokenizers --collect-all safetensors --collect-all huggingface_hub --collect-all requests --collect-all certifi "videotaskhub_app.py"
```

发布时请同时提供 [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)、[Release/THIRD_PARTY_NOTICES.md](Release/THIRD_PARTY_NOTICES.md) 与 [Release/DEPENDENCY_MANIFEST.md](Release/DEPENDENCY_MANIFEST.md)，并以最终打包环境的真实依赖补齐许可证文件。

在视频整合添加一个 一键智能拼接加水印 业务流程，
视频素材列表，这里用户可能会提供1个或者多个素材目录。
先读取视频素材列表，按顺序执行每个素材目录的任务，每执行一个目录的任务时，都先执行清空输出目录，执行清空表格，执行“刷新素材表"，执行"按文件夹智能组合"，执行开始批量拼接，每拼接完一个，就执行给这个视频加水印，加水印直接使用"批量视频水印(多层)"中 设置层水印 里面当前用户设置好 的内容参数。 

当用户填写视频素材列表，并点击 一键智能拼接加水印 后，开始执行。执行的过程中锁定输入和当前视频整合相关的功能操作，避免在执行过程用户误操作。但是提供暂停/继续执行和停止执行的功能，点击暂停时，允许用户修改各种设置，若是用户检测到用户修改了设置，那么继续执行时使用新的设置对未完成的任务和视频进行输出。若点击停止执行，先询问用户是否确定停止，得到用户确定再停止，若用户取消停止则任务继续。 这里我担心一个问题，就是是否需要等到上一个队列执行完才能暂停或者停止，还是可以直接先暂停？然后点击继续后又执行，会不会损坏数据，会不会干扰渲染？

再此页面中执行这个一键任务流程时，只锁定当前页面。同时制作一个精美的进度界面，悬浮在当前界面，能够通过这个界面看到背后输出目录、素材表、组合表里面的信息，每执行一个素材列表时，能看到这些信息已填入，同时若是暂停了，也能去修改设置参数，这个界面能展示单个素材目录中每组视频拼接的执行进度，每个视频列表执行的总进度，所有素材目录加在一起的总进度。把暂停、取消按钮显示在这里。 而且可以支持后台运行，不占用整个软件，也不锁定整个软件，不影响用户切换到导航栏里面的其他功能去操作别任务。


对于 一键智能拼接加水印 输出目录
假设视频素材填写的路径是
D:\素材\小明
D:\素材\小红

那么拼接的视频输出就是在文件夹后面加上-智能拼接
例如：
D:\素材\小明-智能拼接
D:\素材\小红-智能拼接

加水印的输出目录是在文件夹后面加上-智能加水印
例如：
D:\素材\小明-智能加水印
D:\素材\小红-智能加水印
