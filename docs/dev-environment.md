# Development Environment

## Goal

This document explains what should be installed in the project virtual environment and how to set it up for local development and testing.

## Required Inside `.venv`

Install the project dependencies from [requirements.txt](/d:/Dprojects/krafton_week3/requirements.txt#L1).

Current dependency list:

```text
pytest==9.0.2
```

## Recommended Base Tools

These should exist on the machine before creating the virtual environment:

- Python 3.12
- `pip`

## Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Verify

Check the Python interpreter:

```powershell
.\.venv\Scripts\python.exe --version
```

Check `pytest`:

```powershell
.\.venv\Scripts\python.exe -m pytest --version
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Notes

- The repository currently uses [pytest.ini](/d:/Dprojects/krafton_week3/pytest.ini) to collect tests from `tests/`.
- `pytest` cache is disabled in this project config to avoid local Windows permission issues.
- The current application code uses the Python standard library only. `pytest` is included for running the test suite.
- If dependencies change, update [requirements.txt](/d:/Dprojects/krafton_week3/requirements.txt#L1).
