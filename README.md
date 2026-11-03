# Ti5 Scan Rebuild

[简体中文](README.zh-CN.md)

**钛虎扫描件参数化重建助手** is an open-source Windows desktop tool that
orchestrates STL analysis, engineering alignment, editable SolidWorks forward
reconstruction, STEP export, and evidence-based review.

> Status: early public release. The workflow is intended for engineering
> assistance, not unattended manufacturing approval.

## What it does

- Reads binary and ASCII STL files locally and inspects mesh bounds, triangle
  count, degeneracy, and suspected open edges.
- Uses the locally installed Codex runtime with **GPT-6 Astra** and high
  reasoning for demanding forward-reconstruction tasks.
- Drives a locally licensed SolidWorks installation through COM automation.
- Aligns functional datums before reconstruction instead of centering only by
  the bounding box.
- Creates editable native SolidWorks features and exports SLDPRT and STEP.
- Provides Simple, Medium, and Fine engineering-reconstruction profiles.
- Continues the same Codex session and improves the same SLDPRT when a review
  gate is not met.
- Checks single-solid output, sketch definition, native rebuild/reopen,
  dimension round-trip, STEP re-import, extreme dimensions, and visual/section
  evidence.
- Keeps RMS/P95 mesh deviation as diagnostic evidence rather than pretending
  noisy scan data is a manufacturing tolerance.
- Includes an explicit local mesh-import fallback, clearly separated from
  editable forward reconstruction.

## Requirements

- Windows 10/11, 64-bit
- Python 3.11+ when running from source
- SolidWorks installed and licensed locally (tested with SolidWorks 2021)
- Official Codex desktop app or Codex CLI, signed in with an eligible account
- GPT-6 Astra availability for the signed-in account

The Codex window does not need to remain open. The Codex runtime must be
installed and authenticated.

## Quick start from source

```powershell
git clone https://github.com/chuck-wu55/ti5-scan-rebuild.git
cd Ti5-Scan-Rebuild
python -m pip install -r requirements.txt
python .\main.py
```

Or double-click `run_ti5.cmd` after installing the dependencies.

In the application:

1. Start SolidWorks and wait for it to finish loading.
2. Select an STL, an output directory, and the correct STL unit.
3. Open **Model settings**, sign in to Codex, and run the environment check.
4. Select a reconstruction level and start forward reconstruction.
5. Review the generated SLDPRT, STEP, reports, and preview evidence before use.

Chinese usage guides are provided in
[`QUICKSTART_CN.txt`](QUICKSTART_CN.txt) and
[`USER_GUIDE_CN.txt`](USER_GUIDE_CN.txt).

## Reconstruction profiles

| Profile | Intended result | Minimum refinement |
| --- | --- | ---: |
| Simple | Main envelope, functional datum, principal interface | 1 round |
| Medium | Core exterior/surfaces, main holes and interfaces | 2 rounds |
| Fine | Core curved surfaces, functional interfaces and major features | 3 rounds |

These are engineering reconstruction profiles, not universal dimensional
tolerances. Scan noise, occlusion, inaccessible surfaces, and missing design
dimensions limit what can be recovered from an STL.

## Data and privacy

The application analyzes the original STL locally. During Codex forward
reconstruction, prompts and model-derived information may be processed by
OpenAI, and the local Codex agent is permitted to inspect the selected STL and
operate SolidWorks. Only use data that you are authorized to process with the
selected service. See [`SECURITY.md`](SECURITY.md).

API keys entered for compatible providers are stored with Windows DPAPI for
the current user. No credentials are included in this repository.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The unit suite uses synthetic geometry and does not require proprietary scan
files. Real SolidWorks/Codex end-to-end testing requires the corresponding
local applications and account access.

## Build a Windows release

Install PyInstaller and run:

```powershell
python -m pip install pyinstaller
.\build_windows.ps1
```

The unpacked application is created under `dist\Ti5 Scan Rebuild`. Build
outputs are intentionally excluded from Git; publish them as GitHub Release
assets instead.

## Limitations

- Freeform and damaged scans may require manual CAD refinement.
- The tool cannot recover unknown original dimensions or design intent with
  certainty.
- Output must be reviewed by a qualified engineer before manufacturing,
  inspection, safety-critical, or regulated use.
- SolidWorks and the Codex service are not bundled and may have separate
  licenses, subscriptions, and usage limits.

## License

Ti5 Scan Rebuild is released under the [MIT License](LICENSE).
The vendored SolidWorks automation skill is also MIT licensed; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

SolidWorks, OpenAI, ChatGPT, and Codex are names of their respective owners.
This project is independent and is not endorsed by them.
