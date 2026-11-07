$ErrorActionPreference = "Stop"

python -m PyInstaller `
  --onefile `
  --windowed `
  --name ResumeBuilder `
  --distpath . `
  --workpath build `
  --specpath build `
  resume_builder_ui.py

Write-Host "Built ResumeBuilder.exe"
