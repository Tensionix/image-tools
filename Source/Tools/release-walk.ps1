# The built program walked through without a mouse: its own buttons are pressed by UI Automation.
#
#   Source\Tools\release-walk.ps1 -Stand C:\Temp\image_stand
#
# A release build has no steps of a check inside, so the stand is a copy of the program: App\, the
# console command, the engine, the Python of the project and config\ without the files of the
# owner (the history of paths, the threads, the look of the window). Its input, output, logs and
# report are its own - nothing of the owner's is read or written. The window is started with
# AUDION_WALK=1: it and its questions stand off every screen and take no focus. It is found by the
# id of its process, never by its name or title; the pointer is not moved.
#
# What is pressed: a section, THREADS up and down, a quick operation, a form with a choice of its
# own, an operation that refuses (a watermark without its text), the pin of the Source, TO SOURCE
# with its question, CLEAR with its menu and its question (the probe files of the stand go to the
# Recycle Bin), STOP while a long conversion goes, and the window closed while one goes. Exit
# code 0 - every check held; 1 - one did not, and the line says which.
#
# Needs a PowerShell with the WindowsDesktop assemblies (an installed PowerShell 7).
# -Keep leaves the stand in place for a look; otherwise it is removed at the end.
param(
    [Parameter(Mandatory)][string]$Stand,
    # The built window to walk: App\ of the program, or another build of it.
    [string]$App = '',
    [switch]$Keep
)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$project = Split-Path -Parent $source
$window = 'AudionImageTools.exe'
if (-not $App) { $App = Join-Path $project 'App' }

if (Test-Path -LiteralPath $Stand) { "the stand must not exist yet: $Stand"; exit 2 }
if (-not (Test-Path -LiteralPath (Join-Path $App $window))) { "no built window in $App`: install\Build-App.cmd"; exit 2 }
[void](New-Item -ItemType Directory -Force -Path $Stand)
$Stand = (Resolve-Path -LiteralPath $Stand).Path
$copies = @(
    @($App, 'App', @()),
    @((Join-Path $project 'system_core'), 'system_core', @('__pycache__', 'powershell')),
    @((Join-Path $project 'runtime'), 'runtime', @('__pycache__')),
    @((Join-Path $project 'config'), 'config', @())
)
foreach ($copy in $copies) {
    $skip = @('/XD') + $copy[2] + @('/XF', 'window_settings.json*', 'path_history.json*', 'parallel_settings.json*')
    $null = robocopy $copy[0] (Join-Path $Stand $copy[1]) /E @skip /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { "the copy of $($copy[1]) failed"; exit 2 }
}
Copy-Item -LiteralPath (Join-Path $project 'image_cli.cmd') -Destination $Stand
$in = Join-Path $Stand 'input'; $out = Join-Path $Stand 'output'
foreach ($name in 'input', 'output', 'logs', 'report') { [void](New-Item -ItemType Directory -Force -Path (Join-Path $Stand $name)) }
$exe = Join-Path $Stand "App\$window"
$python = Join-Path $Stand 'runtime\python.exe'

# Pictures of the stand, made by its own Python: noise, so that no encoder makes short work of them.
function MakePictures([int]$count, [int]$width, [int]$height, [string]$prefix) {
    $script = "import sys`nfrom PIL import Image`nfor i in range(int(sys.argv[2])):`n    Image.merge('RGB', [Image.effect_noise((int(sys.argv[3]), int(sys.argv[4])), 64) for _ in range(3)]).save(sys.argv[1] + '/' + sys.argv[5] + '%03d.jpg' % i, quality=92)"
    & $python -I -c $script $in $count $width $height $prefix
    if ($LASTEXITCODE -ne 0) { throw 'the pictures of the stand were not made' }
}
function FilesIn([string]$folder) { @(Get-ChildItem -LiteralPath $folder -Recurse -File -Force -ErrorAction SilentlyContinue) }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$auto = [System.Windows.Automation.AutomationElement]
$failed = 0
function Say([bool]$ok, [string]$what) {
    '{0} {1}' -f $(if ($ok) { '[OK]  ' } else { '[FAIL]' }), $what
    if (-not $ok) { $script:failed++ }
}
function Find($root, [string]$id, [int]$seconds = 20) {
    $condition = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        # The tree may be rebuilt under the search - a section was just pressed - and the search
        # then breaks instead of finding nothing: asked again like any other "not yet".
        $found = $null
        try { $found = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition) } catch { }
        if ($found) { return $found }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function Press($element) {
    if ($null -eq $element) { throw 'nothing to press' }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke(); return }
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { $pattern.Toggle(); return }
    throw 'the element can be neither invoked nor toggled'
}
function IsOn($element) {
    $pattern = $null
    if (-not $element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { return $false }
    return $pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
}
function TextOf($root, [string]$id) {
    $found = Find $root $id 5
    if (-not $found) { return '' }
    $value = $null
    if ($found.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) { return $value.Current.Value }
    return $found.Current.Name
}
function Shown($root, [string]$id) {
    # One look, no waiting: a control that is hidden is not in the tree at all.
    try { return $null -ne $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)) }
    catch { return $false }
}
function Outcome($root) {
    # The line of the facts over the journal is hidden in this window: how a run ended is read from the
    # status line, in either language, and a run that goes - from STOP, which is in sight only then.
    $line = TextOf $root 'StatusText'
    if ($line -match '^(Готово|Done): ') { return 'done' }
    if ($line -match '^(Остановлено|Stopped): ') { return 'stopped' }
    if ($line -match ': (отказ до начала|refused before it began)') { return 'refused' }
    if ($line -match ': (ошибка|failed) - ') { return 'failed' }
    if (Shown $root 'StopButton') { return 'running' }
    return ''
}
function WaitOutcome($root, [string]$wanted, [int]$seconds, [string]$before = '') {
    # $before: the status line before the press - an outcome of the run before is not this run's.
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $now = Outcome $root
        if ($now -eq $wanted -and ($wanted -eq 'running' -or (TextOf $root 'StatusText') -ne $before)) { return $now }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return "$(Outcome $root) <$(TextOf $root 'StatusText')>"
}
function FindInProcess([int]$id, [string]$name, [int]$seconds = 15) {
    # A question is a window of its own: looked for among the windows of the process, not inside the main one.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $id)
    $named = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $name)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        try {
            foreach ($top in $auto::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {
                $found = $top.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $named)
                if ($found) { return $found }
            }
        }
        catch { }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function AnswerYes([int]$id, [int]$seconds = 30) {
    # "Yes" of a question that cannot be taken back comes alive a moment after it opens.
    $yes = FindInProcess $id 'AskYes' $seconds
    if (-not $yes) { return $false }
    $until = (Get-Date).AddSeconds(5)
    while (-not $yes.Current.IsEnabled -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }
    Press $yes
    Start-Sleep -Milliseconds 500
    return $true
}
function WaitFile([string]$path, [string]$pattern, [bool]$present, [int]$seconds = 15) {
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $text = if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue } else { '' }
        if (($text -match $pattern) -eq $present) { return $true }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $false
}
function Settled($root, [string]$id, [int]$seconds = 15) {
    # A number read twice, a second apart, the same: the window has done with its settings.
    $until = (Get-Date).AddSeconds($seconds)
    $last = TextOf $root $id
    do {
        Start-Sleep -Milliseconds 1000
        $now = TextOf $root $id
        if ($now -eq $last -and $now.Length -gt 0) { return $now }
        $last = $now
    } while ((Get-Date) -lt $until)
    return $last
}
function StartWindow {
    $env:AUDION_WALK = '1'
    try { $process = Start-Process -FilePath $exe -PassThru }
    finally { Remove-Item Env:\AUDION_WALK -ErrorAction SilentlyContinue }
    # A window with no button on the taskbar is no "main window" to .NET: it is looked for among the
    # windows of the desktop by the id of its process.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $process.Id)
    $until = (Get-Date).AddSeconds(40)
    do {
        $found = $null
        try { $found = $auto::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $mine) } catch { }
        if ($found) { $script:root = $found; return $process }
        Start-Sleep -Milliseconds 300
    } while (-not $process.HasExited -and (Get-Date) -lt $until)
    throw $(if ($process.HasExited) { "the window ended at its start, exit code $($process.ExitCode)" } else { 'the window did not open' })
}
function CloseWindow($root) {
    $close = $null
    [void]$root.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$close)
    $close.Close()
}

try {
    MakePictures 6 640 480 'small_'
    $process = StartWindow
    $bounds = $root.Current.BoundingRectangle
    Say ($bounds.Right -le 0 -or $bounds.Bottom -le 0) ("the window of the walk stands off the screen: {0},{1}" -f $bounds.Left, $bounds.Top)

    $tab = Find $root 'section_convert' 40
    Say ($null -ne $tab) 'the layout is read: the section "convert" is in the window'

    # THREADS: the arrows change the number, and the file the engine reads at every run follows it.
    $threads = Join-Path $Stand 'config\parallel_settings.json'
    $before = Settled $root 'threads'
    Press (Find $root 'threads_up' 5)
    Start-Sleep -Milliseconds 700
    $after = TextOf $root 'threads'
    $kept = if (Test-Path -LiteralPath $threads) { Get-Content -LiteralPath $threads -Raw | ConvertFrom-Json } else { $null }
    Say ([int]$after -eq [int]$before + 1 -and $kept -and $kept.worker_count -eq [int]$after) "THREADS up: $before -> $after, config\parallel_settings.json says $($kept.worker_count)"
    Press (Find $root 'threads_down' 5)
    Start-Sleep -Milliseconds 700
    Say ((TextOf $root 'threads') -eq $before) "THREADS down: back to $before"

    # A quick operation: one press, no form.
    Press $tab
    $quick = Find $root 'run_quick_jpg_75'
    Say ($null -ne $quick -and $quick.Current.IsEnabled) 'the quick button "JPG 75%" is there and can be pressed'
    $before = TextOf $root 'StatusText'
    Press $quick
    $state = WaitOutcome $root 'done' 60 $before
    $made = FilesIn $out
    Say ($state -eq 'done' -and $made.Count -eq 6) "pressed, the operation ended: $state, files in output: $($made.Count) of 6"
    $log = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*quick_jpg_75*' })
    Say ($log.Count -ge 1) "the operation ran through the console command: its journal lies in the logs of the stand ($($log.Count))"

    # A form: a choice of its own, then RUN of the form.
    Press (Find $root 'section_size')
    $quarter = Find $root 'field_scale_mode_percent-25'
    if ($quarter) { Press $quarter; Start-Sleep -Milliseconds 600 }
    # The choice shapes the form ("own percent" comes and goes with it): the form is built anew, so the switch is looked for again.
    $quarter = Find $root 'field_scale_mode_percent-25' 5
    Say ($null -ne $quarter -and (IsOn $quarter)) 'the form of "downscale_percent": 25 % pressed and on'
    # The preview of the page: worked out by the console command on a copy of a picture - nothing written into the Target.
    $was = (FilesIn $out).Count
    $said = ''
    $until = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $until) { $said = TextOf $root 'preview_state'; if ($said -match '^(Посчитано|Worked out)') { break }; Start-Sleep -Milliseconds 500 }
    Say ($said -match '^(Посчитано|Worked out)' -and (FilesIn $out).Count -eq $was) "the preview of the form: <$said>, files in output: $was -> $((FilesIn $out).Count)"
    $was = (FilesIn $out).Count
    $before = TextOf $root 'StatusText'
    Press (Find $root 'run_downscale_percent')
    $state = WaitOutcome $root 'done' 60 $before
    Say ($state -eq 'done' -and (FilesIn $out).Count -gt $was) "RUN of the form: $state, files in output: $was -> $((FilesIn $out).Count)"

    # An operation that refuses: the watermark without its text is not run.
    Press (Find $root 'section_sheets')
    $page = Find $root 'page_sheets_watermark' 10
    if ($page) { Press $page; Start-Sleep -Milliseconds 500 }
    $was = (FilesIn $out).Count
    $before = TextOf $root 'StatusText'
    Press (Find $root 'run_watermark')
    $state = WaitOutcome $root 'refused' 30 $before
    Say ($state -eq 'refused' -and (FilesIn $out).Count -eq $was) "a watermark without its text: $state, nothing written"

    # The pin of the Source: kept in the history of the stand, and taken off again.
    $history = Join-Path $Stand 'config\path_history.json'
    Press (Find $root 'route_pin_source' 15)
    Say (WaitFile $history '"pinned":\s*true' $true) 'the pin of the Source: config\path_history.json holds a pinned path'
    Press (Find $root 'route_pin_source' 15)
    Say (WaitFile $history '"pinned":\s*true' $false) 'pressed again: no path is pinned'

    # TO SOURCE: the Source is cleared, the result moves into it, the Target is left empty.
    $results = (FilesIn $out).Count
    Press (Find $root 'route_to_source' 15)
    Say (AnswerYes $process.Id) 'TO SOURCE asks first'
    $until = (Get-Date).AddSeconds(20)
    while ((FilesIn $out).Count -gt 0 -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }
    Start-Sleep -Milliseconds 500
    Say ((FilesIn $out).Count -eq 0 -and (FilesIn $in).Count -eq $results) "TO SOURCE: output is empty, input holds the $results results ($((FilesIn $in).Count))"

    # CLEAR: its menu, the question, the contents gone and the folders left - to the Recycle Bin.
    Set-Content -LiteralPath (Join-Path $out 'release-walk-probe.txt') -Value 'a probe of release-walk.ps1' -Encoding utf8
    Press (Find $root 'route_clear' 15)
    $both = Find $root 'clear_both' 15
    Say ($null -ne $both) 'the button CLEAR opens its menu: "both" is in it'
    if ($both) {
        Press $both
        Say (AnswerYes $process.Id) 'CLEAR asks first'
        # A folder outside the program is asked about once more; the stand's are its own.
        [void](AnswerYes $process.Id 2)
        $until = (Get-Date).AddSeconds(20)
        do { Start-Sleep -Milliseconds 300; $left = (FilesIn $in).Count + (FilesIn $out).Count } while ($left -gt 0 -and (Get-Date) -lt $until)
        Say ($left -eq 0 -and (Test-Path -LiteralPath $in) -and (Test-Path -LiteralPath $out)) "CLEAR: the contents of input and output are gone, the folders stay ($left left)"
    }

    # STOP while a long conversion goes.
    MakePictures 40 4000 3000 'large_'
    Press (Find $root 'section_convert')
    $png = Find $root 'run_quick_png'
    Start-Sleep -Milliseconds 600
    Say ($png.Current.IsEnabled) 'after the clearing the button of an operation can be pressed again'
    Press $png
    $state = WaitOutcome $root 'running' 15
    Say ($state -eq 'running') "40 large pictures to PNG: the operation goes ($state)"
    Start-Sleep -Seconds 4
    $stop = Find $root 'StopButton' 5
    Say ($null -ne $stop -and $stop.Current.IsEnabled) 'STOP is in sight and can be pressed while the operation goes'
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    Press $stop
    $state = WaitOutcome $root 'stopped' 70
    $took = [Math]::Round($clock.Elapsed.TotalSeconds, 1)
    $made = (FilesIn $out).Count
    Say ($state -eq 'stopped' -and $took -lt 30) "STOP pressed: $state in $took s"
    Say ($made -lt 40) "the operation stopped before its end: $made of 40 written"
    Start-Sleep -Milliseconds 600
    Say ($png.Current.IsEnabled) 'after the stop the button of the operation can be pressed again'

    # The window closed while the conversion goes: it asks, stops the operation and then closes.
    Press $png
    $null = WaitOutcome $root 'running' 15
    Start-Sleep -Seconds 3
    CloseWindow $root
    $asked = AnswerYes $process.Id 15
    Say $asked 'closing during an operation asks first'
    Say ($process.WaitForExit(90000)) 'answered: the operation stopped and the window closed'

    Start-Sleep -Seconds 2
    $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase) })
    Say ($left.Count -eq 0) ("no process of the stand is left: {0}" -f $left.Count)
    $crash = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'gui-crash-*' -or ($_.Name -eq 'gui-event-errors.log' -and $_.Length -gt 0) })
    Say ($crash.Count -eq 0) ("the window wrote no report of its own errors: {0}" -f (($crash | ForEach-Object Name) -join ', '))
}
catch {
    Say $false ("the walk broke: " + $_.Exception.Message)
}
finally {
    Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { try { $_.Kill($true) } catch { } }
    if ($Keep) { "the stand is kept: $Stand" }
    else {
        Start-Sleep -Milliseconds 800
        # The stand is a plain copy - no link of it leads into the program - so it goes whole.
        [System.IO.Directory]::Delete($Stand, $true)
        'the stand is removed'
    }
}
"failed checks: $failed"
exit $(if ($failed) { 1 } else { 0 })
