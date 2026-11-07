# Xiaoke probe: given a window handle, print the page URLs shown in the Claude window and the
# position of the chat input box, via UI Automation. Output: "<urls> || <x>,<y>,<w>,<h>"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$CT = [System.Windows.Automation.ControlType]
$docCond = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $CT::Document)
$editCond = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $CT::Edit)
$btnCond = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $CT::Button)
$vp =[System.Windows.Automation.ValuePattern]::Pattern
$scope = [System.Windows.Automation.TreeScope]::Descendants
while (($line = [Console]::In.ReadLine()) -ne $null) {
    $out = @()
    $box = ''
    try {
        $w = $A::FromHandle([IntPtr][long]$line)
        foreach ($d in $w.FindAll($scope, $docCond)) {
            $v = ''
            try { $v = $d.GetCurrentPattern($vp).Current.Value } catch {}
            if (-not $v -or $d.Current.IsOffscreen) { continue }
            $r = $d.Current.BoundingRectangle
            if ($r.Width -lt 50 -or $r.Height -lt 50) { continue }
            $out += ('{0:0}x{1:0} {2}' -f $r.Width, $r.Height, $v.Split('?')[0])
        }
        $best = $null
        foreach ($e in $w.FindAll($scope, $editCond)) {
            if ($e.Current.IsOffscreen -or -not $e.Current.IsKeyboardFocusable) { continue }
            $r = $e.Current.BoundingRectangle
            if ($r.Width -lt 150) { continue }
            if ($best -eq $null -or $r.Y -gt $best.Y) { $best = $r }
        }
        if ($best -ne $null) {
            $box = '{0:0},{1:0},{2:0},{3:0}' -f $best.X, $best.Y, $best.Width, $best.Height
            # microphone button on the same row as the input box
            foreach ($b in $w.FindAll($scope, $btnCond)) {
                $n = $b.Current.Name
                if ($b.Current.IsOffscreen -or $n -notmatch '录音|语音|麦克风|听写|(?i)microphone|dictat|voice|record') { continue }
                $r = $b.Current.BoundingRectangle
                if ($r.Y -gt $best.Y + $best.Height + 40 -or $r.Bottom -lt $best.Y - 40) { continue }
                $box += ',{0:0},{1:0}' -f $r.X, $r.Width
                break
            }
        }
    } catch { $out = @('err') }
    [Console]::Out.WriteLine(($out -join ' | ') + ' || ' + $box)
    [Console]::Out.Flush()
}
