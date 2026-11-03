# Contributing

Contributions are welcome through issues and pull requests.

## Development setup

1. Use Windows 10/11 with Python 3.11 or newer.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Run `python main.py`.
4. Run `python -m unittest discover -s tests -v` before opening a pull request.

Do not include proprietary scan data, generated SolidWorks files, task logs,
credentials, or build directories. Tests should use synthetic geometry only.

Changes to SolidWorks automation must preserve serial COM access, explicit
unit handling, output-path containment, and manual-review gates for unverified
capabilities.

