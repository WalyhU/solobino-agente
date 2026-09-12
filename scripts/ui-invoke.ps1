<#
  Pulsa un control de una aplicación por su NOMBRE accesible, usando UI Automation.
  No usa coordenadas ni capturas de pantalla: el control debe existir en el árbol
  de accesibilidad de la ventana.

  Uso: ui-invoke.ps1 -Window AppleMusic -Control Reproducir[,Play]
  Salida: "OK: <control>" | "NOTFOUND: <lista de controles disponibles>" | "NOWINDOW"
#>
param(
    [Parameter(Mandatory)][string]$Window,
    [Parameter(Mandatory)][string]$Control,  # uno o varios, separados por comas
    [ValidateSet('largest', 'first')][string]$Prefer = 'largest',
    [int]$TimeoutSeconds = 15
)
$ErrorActionPreference = 'Stop'
# -File no construye arrays: los nombres llegan como una sola cadena.
$wantedNames = $Control.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)

function Get-TargetWindow {
    param([string]$Match)
    $candidates = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle }
    $exact = $candidates | Where-Object { $_.ProcessName -eq $Match } | Select-Object -First 1
    if ($exact) { return $exact }
    $candidates | Where-Object {
        $_.ProcessName -like "*$Match*" -or $_.MainWindowTitle -like "*$Match*"
    } | Select-Object -First 1
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastNames = @()
do {
    $process = Get-TargetWindow -Match $Window
    if ($process) {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
        $lastNames = @()
        $byName = @{}
        for ($i = 0; $i -lt $buttons.Count; $i++) {
            $element = $buttons.Item($i)
            $name = $element.Current.Name
            if (-not $name -or $name.Length -gt 60) { continue }
            $lastNames += $name
            $box = $element.Current.BoundingRectangle
            $area = $box.Width * $box.Height
            # El control grande es el principal de la vista; el pequeño suele ser
            # el de la barra de transporte o una versión colapsada.
            if (-not $byName.ContainsKey($name) -or
                ($Prefer -eq 'largest' -and $area -gt $byName[$name].Area)) {
                $byName[$name] = [pscustomobject]@{ Element = $element; Area = $area }
            }
        }
        foreach ($wanted in $wantedNames) {
            $hit = $byName.Keys | Where-Object { $_ -eq $wanted } | Select-Object -First 1
            if (-not $hit) {
                $hit = $byName.Keys | Where-Object { $_ -like "*$wanted*" } | Select-Object -First 1
            }
            if ($hit) {
                $byName[$hit].Element.GetCurrentPattern(
                    [System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                Write-Output "OK: $hit"
                exit 0
            }
        }
    }
    Start-Sleep -Milliseconds 400
} while ((Get-Date) -lt $deadline)

if (-not $process) { Write-Output 'NOWINDOW'; exit 3 }
Write-Output ('NOTFOUND: ' + (($lastNames | Select-Object -Unique -First 30) -join ' | '))
exit 2
