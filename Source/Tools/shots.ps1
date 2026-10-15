# The Debug window walked off the screen, its pages pictured into a folder.
#
#   Source\Tools\shots.ps1 -To D:\shots -Only downscale_percent,watermark [-Steps "page=size/downscale_percent;shot=one"] [-Set "scale_mode=custom"]
#
# The window is found by the id of its process and is never shown: it stands off the screen and
# draws its pictures from itself. Nothing is run unless a step says so. Build first:
#   dotnet build -c Debug   (in Source\)
param(
    [Parameter(Mandatory)][string]$To,
    [string]$Only = '',
    [string]$Steps = '',
    [string]$Set = '',
    [string]$Height = '',
    [int]$WaitSeconds = 180
)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $source 'bin\Debug\net10.0\AudionImageTools.exe'
if (-not (Test-Path -LiteralPath $exe)) { "no Debug build: dotnet build -c Debug in $source"; exit 2 }
if (Test-Path -LiteralPath $To) { [IO.Directory]::Delete($To, $true) }
$env:AUDION_SHOT_ONLY = $Only
$env:AUDION_SHOT_STEPS = $Steps
$env:AUDION_SHOT_SET = $Set
$env:AUDION_SHOT_HEIGHT = $Height
$env:AUDION_SHOT_PAGES = if ($Only -or -not $Steps) { '1' } else { '0' }
$env:AUDION_SHOT_WAIT = '500'
$window = Start-Process -FilePath $exe -ArgumentList @('-Shot', ('"{0}"' -f $To)) -PassThru
if (-not $window.WaitForExit($WaitSeconds * 1000)) { $window.Kill($true); "the window did not end in $WaitSeconds s and was ended"; exit 1 }
"exit $($window.ExitCode)"
Get-ChildItem -LiteralPath $To -ErrorAction SilentlyContinue | ForEach-Object { "  $($_.Name)" }
$said = Join-Path $To 'steps.txt'
if (Test-Path -LiteralPath $said) { Get-Content -LiteralPath $said }
