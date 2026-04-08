# OmniVoice: PyTorch CUDA (cu128) + editable install. Run from repo root.
# Matches upstream README / pyproject (torch 2.8.0+cu128).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
$env:PIP_DEFAULT_TIMEOUT = "600"
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 `
  --extra-index-url https://download.pytorch.org/whl/cu128 `
  --default-timeout 600
pip install -e . --default-timeout 300
Write-Host "Done. Activate: .\.venv\Scripts\Activate.ps1"
