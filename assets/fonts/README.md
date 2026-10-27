# 随软件附带的开源字体

本目录只包含 SIL Open Font License 1.1（OFL-1.1）字体，用于字幕预览与 FFmpeg/libass 输出；不安装到 Windows 系统字体目录。

- Be Vietnam Pro：越南语优先的正体与粗体。
- Inter：现代无衬线显示字体，含 Vietnamese 字符集。
- Noto Sans：多语言正文与字幕回退字体，含 Vietnamese 字符集。
- Nunito Sans：圆润字幕风格字体，含 Vietnamese 字符集。

每个字体对应的原始 OFL-1.1 许可证均以 `OFL-*.txt` 保留在本目录。字体在软件内作为应用字体注册，并在输出时通过 FFmpeg 的 `fontsdir` 指向本目录，保证预览与成片使用同一套字体资源。
