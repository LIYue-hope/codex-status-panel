# Run with pwsh -NoProfile -STA -File tests/test_date_picker.ps1.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
$source = Join-Path $PSScriptRoot '../CodexStatusOverlay.ps1'
$parseErrors = $null
$tokens = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Test-HistoryDatePickerClick', 'Find-VisualDescendantByType', 'Enable-HistoryCalendarAutoHide')) {
    $function = $ast.Find({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    $definition = [scriptblock]::Create($function.Extent.Text)
    . $definition
}
$clickRegistration = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and
    $node.Expression.Extent.Text -eq '$window' -and
    $node.Member.Value -eq 'Add_PreviewMouseLeftButtonDown'
}, $true)
$outsideClick = $clickRegistration.Arguments[0].ScriptBlock.GetScriptBlock()
$script:HistoryCalendarEntered = @{}
$script:HistoryAutoHideCalendars = @{}
$window = [Windows.Window]::new()
$window.ShowActivated = $false
$window.Opacity = 0
$window.Width = 300
$window.Height = 150
$panel = [Windows.Controls.StackPanel]::new()
$window.Content = $panel
$HistoryStartDate = [Windows.Controls.DatePicker]::new()
$HistoryStartDate.Name = 'HistoryStartDate'
$HistoryEndDate = [Windows.Controls.DatePicker]::new()
$HistoryEndDate.Name = 'HistoryEndDate'
[void]$panel.Children.Add($HistoryStartDate)
[void]$panel.Children.Add($HistoryEndDate)
$outsideButton = [Windows.Controls.Button]::new()
[void]$panel.Children.Add($outsideButton)

try {
    $window.Show()
    $window.UpdateLayout()
    foreach ($picker in @($HistoryStartDate, $HistoryEndDate)) {
        $picker.DisplayDate = [datetime]'2026-10-03'
        $popup = $picker.Template.FindName('PART_Popup', $picker)
        $popup.Child.Opacity = 0
        $picker.IsDropDownOpen = $true
        Enable-HistoryCalendarAutoHide $picker
        $popup.Child.UpdateLayout()
        $calendar = Find-VisualDescendantByType $popup.Child ([Windows.Controls.Calendar])
        $calendarItem = Find-VisualDescendantByType $calendar ([Windows.Controls.Primitives.CalendarItem])
        foreach ($step in @(@('PART_PreviousButton', 9), @('PART_NextButton', 10), @('PART_NextButton', 11))) {
            $arrow = $calendarItem.Template.FindName($step[0], $calendarItem)
            if ($null -eq $arrow) { throw "Month arrow not found: $($step[0])" }
            # Exercise the window's real preview handler with the arrow as the
            # input source, before allowing the default calendar button action.
            & $outsideClick $window ([pscustomobject]@{ OriginalSource = $arrow })
            if (-not $picker.IsDropDownOpen) { throw "Calendar closed on $($step[0])" }
            $peer = [Windows.Automation.Peers.ButtonAutomationPeer]::new($arrow)
            $invoke = $peer.GetPattern([Windows.Automation.Peers.PatternInterface]::Invoke)
            $invoke.Invoke()
            [void]$window.Dispatcher.Invoke([Action]{}, [Windows.Threading.DispatcherPriority]::ApplicationIdle)
            if ($calendar.DisplayDate.Month -ne $step[1]) { throw "Month did not change to $($step[1])" }
            if (-not $picker.IsDropDownOpen) { throw 'Calendar closed after month navigation' }
        }
        $textBox = $picker.Template.FindName('PART_TextBox', $picker)
        & $outsideClick $window ([pscustomobject]@{ OriginalSource = $textBox })
        if (-not $picker.IsDropDownOpen) { throw 'Date text was treated as an outside click' }
        & $outsideClick $window ([pscustomobject]@{ OriginalSource = $outsideButton })
        if ($picker.IsDropDownOpen) { throw 'Outside click did not close the calendar' }
    }
    Write-Output 'PASS: both date pickers navigate months, stay open inside, and close outside.'
} finally {
    $HistoryStartDate.IsDropDownOpen = $false
    $HistoryEndDate.IsDropDownOpen = $false
    $window.Close()
}
