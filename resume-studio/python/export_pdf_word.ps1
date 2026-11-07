param(
    [string]$InputDocx,
    [string]$OutputPdf,
    [switch]$Both
)

$ErrorActionPreference = "Stop"

function Export-DocxToPdf {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DocxPath,
        [string]$PdfPath
    )

    $resolvedDocx = Resolve-Path -LiteralPath $DocxPath
    $fileName = $resolvedDocx.Path

    if (-not $PdfPath) {
        $PdfPath = [System.IO.Path]::ChangeExtension($fileName, ".pdf")
    }
    elseif (-not [System.IO.Path]::IsPathRooted($PdfPath)) {
        $PdfPath = Join-Path -Path (Get-Location) -ChildPath $PdfPath
    }

    $word = $null
    $document = $null

    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0

        # Word COM expects optional parameters as by-ref VARIANT objects in Windows PowerShell.
        $confirmConversions = $false
        $readOnly = $true
        $addToRecentFiles = $false
        $document = $word.Documents.Open([ref]$fileName, [ref]$confirmConversions, [ref]$readOnly, [ref]$addToRecentFiles)

        # 17 = wdExportFormatPDF
        $document.ExportAsFixedFormat($PdfPath, 17)
        Write-Host "PDF exported: $PdfPath"
    }
    finally {
        if ($document -ne $null) {
            $document.Close($false)
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($document) | Out-Null
        }
        if ($word -ne $null) {
            $word.Quit()
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

function Get-StandardResumeDocxFiles {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location }
    Get-ChildItem -LiteralPath $scriptDir -Filter "resume_*.docx" |
        Where-Object { $_.Name -in @("resume_en.docx", "resume_zh.docx") } |
        Sort-Object Name
}

if ($Both) {
    $files = @(Get-StandardResumeDocxFiles)
    if ($files.Count -eq 0) {
        throw "No standard DOCX resume files found."
    }
    foreach ($file in $files) {
        Export-DocxToPdf -DocxPath $file.FullName
    }
    exit 0
}

if (-not $InputDocx) {
    throw "Provide -InputDocx path, or use -Both."
}

Export-DocxToPdf -DocxPath $InputDocx -PdfPath $OutputPdf
