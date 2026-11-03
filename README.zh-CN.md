# Ti5 Scan Rebuild（钛虎扫描件参数化重建助手）

[English](README.md)

Ti5 Scan Rebuild 是面向 Windows 和 SolidWorks 的开源桌面工具，用于组织
“STL 分析 → 功能基准对齐 → 正向参数化重建 → STEP 导出 → 证据复核”工作流。

> 当前为早期开源版本。它是工程辅助工具，不能替代制造审批和人工工程复核。

## 主要能力

- 本地读取二进制或 ASCII STL，分析包围盒、三角面、退化面和疑似破边。
- 通过本机已登录的 Codex 运行时，固定使用 GPT-6 Astra 高推理执行复杂重建。
- 通过 COM 驱动本机已授权的 SolidWorks。
- 先识别并摆正功能基准，再进行正向建模。
- 使用草图、拉伸、切除、旋转、放样等原生特征生成可编辑 SLDPRT，并导出 STEP。
- 提供简单、中等、精细三档工程重建标准。
- 门禁未通过时，续接同一 Codex 会话并修改同一个 SLDPRT，而不是从头粗建。
- 检查单实体、草图定义、重建/重开、尺寸往返、STEP 回导、六方向极值及视图证据。
- RMS/P95 偏差作为诊断证据，不把扫描噪声虚构成制造公差。

## 使用条件

- Windows 10/11 64 位
- 源码运行需要 Python 3.11 或更高版本
- 本机安装并授权 SolidWorks（目前实测 SolidWorks 2021）
- 安装官方 Codex 桌面端或 Codex CLI，并登录有权限的账号
- 登录账号可使用 GPT-6 Astra

Codex 窗口无需一直打开，但本机必须安装并完成登录。

## 从源码运行

```powershell
git clone https://github.com/chuck-wu55/ti5-scan-rebuild.git
cd Ti5-Scan-Rebuild
python -m pip install -r requirements.txt
python .\main.py
```

依赖安装完成后，也可以双击 `run_ti5.cmd`。

## 基本流程

1. 启动 SolidWorks，并等待主界面加载完成。
2. 选择 STL、输出文件夹和正确的 STL 单位。
3. 在“模型设置”中登录 Codex，然后执行环境自检。
4. 选择简单、中等或精细档，启动正向重建。
5. 人工检查生成的 SLDPRT、STEP、报告和预览证据。

详细说明见 [`QUICKSTART_CN.txt`](QUICKSTART_CN.txt) 和
[`USER_GUIDE_CN.txt`](USER_GUIDE_CN.txt)。

## 数据与隐私

原始 STL 的基础分析在本机完成。执行 Codex 正向重建时，提示词和模型派生信息
可能由 OpenAI 处理，本地 Codex 代理也会读取所选 STL 并操作 SolidWorks。
请只处理已获得授权、且允许交由所选服务处理的数据。详见
[`SECURITY.md`](SECURITY.md)。

## 测试和打包

```powershell
python -m unittest discover -s tests -v
python -m pip install pyinstaller
.\build_windows.ps1
```

打包结果位于 `dist\Ti5 Scan Rebuild`。构建目录不提交 Git，应作为 GitHub
Release 附件发布。

## 许可证

主程序采用 [MIT License](LICENSE)。随包使用的 SolidWorks Automation Skill
同样采用 MIT License，原作者与许可证信息保留在
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 和对应资源目录中。

SolidWorks、OpenAI、ChatGPT 和 Codex 是各自权利人的名称或商标；本项目与其
不存在官方隶属或背书关系。
