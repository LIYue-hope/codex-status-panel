param(
    [int]$RefreshSeconds = 2
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$createdNew = $false
$singleInstanceMutex = [System.Threading.Mutex]::new($true, 'Local\CodexStatusOverlay', [ref]$createdNew)
if (-not $createdNew) {
    $singleInstanceMutex.Dispose()
    return
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$providerPath = Join-Path $scriptRoot 'read_status.py'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonPath = if (Test-Path -LiteralPath $bundledPython) {
    $bundledPython
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    (Get-Command py.exe).Source
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    (Get-Command python.exe).Source
} else {
    throw '未找到 Python。请保留 Codex 自带运行时，或安装 Python 3。'
}

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Width="344" Height="336" WindowStyle="None" AllowsTransparency="True"
        Background="Transparent" Topmost="True" ShowInTaskbar="False"
        ResizeMode="NoResize" FontFamily="Segoe UI Variable Text, Segoe UI, Microsoft YaHei UI"
        TextOptions.TextFormattingMode="Display" TextOptions.TextRenderingMode="Auto">
  <Window.Resources>
    <Style x:Key="PanelTabButtonStyle" TargetType="Button">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="Transparent" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"
                                VerticalAlignment="{TemplateBinding VerticalContentAlignment}"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="HistoryDatePickerStyle" TargetType="DatePicker">
      <Setter Property="Height" Value="28"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Foreground" Value="#FF111318"/>
      <Setter Property="Background" Value="#FF25292F"/>
      <Setter Property="BorderBrush" Value="#FF3A4048"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style x:Key="HistoryMetricCardStyle" TargetType="Border">
      <Setter Property="Background" Value="#B31F2329"/>
      <Setter Property="BorderBrush" Value="#243F4854"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding" Value="10,4"/>
    </Style>
    <Style x:Key="HistoryApplyButtonStyle" TargetType="Button">
      <Setter Property="Foreground" Value="#FFFFFFFF"/>
      <Setter Property="Background" Value="#FF10A37F"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="ButtonSurface" Background="{TemplateBinding Background}" CornerRadius="6">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="ButtonSurface" Property="Background" Value="#FF18B88F"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="ButtonSurface" Property="Background" Value="#FF0D8E70"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="ButtonSurface" Property="Opacity" Value="0.45"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
  <Grid>
    <Border x:Name="PanelBorder" CornerRadius="16" Background="#F2181B20" BorderBrush="#3AFFFFFF" BorderThickness="1" Padding="16">
      <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="34"/>
        <RowDefinition Height="*"/>
      </Grid.RowDefinitions>

      <Grid x:Name="Header" Grid.Row="0" Background="Transparent">
        <StackPanel Orientation="Horizontal">
          <Grid Margin="0,0,8,0">
            <Button x:Name="StatusTabButton" Content="Codex 状态" Foreground="#FFF5F7FA"
                    Style="{StaticResource PanelTabButtonStyle}" Padding="0,0,8,3"/>
            <Border x:Name="StatusTabIndicator" Height="2" CornerRadius="1" Background="#FF10A37F"
                    HorizontalAlignment="Stretch" VerticalAlignment="Bottom" Margin="0,0,8,0"/>
          </Grid>
          <Grid>
            <Button x:Name="HistoryTabButton" Content="历史用量" Foreground="#FF828B98"
                    Style="{StaticResource PanelTabButtonStyle}" Padding="8,0,8,3"/>
            <Border x:Name="HistoryTabIndicator" Height="2" CornerRadius="1" Background="#FF10A37F"
                    HorizontalAlignment="Stretch" VerticalAlignment="Bottom" Margin="8,0" Visibility="Collapsed"/>
          </Grid>
        </StackPanel>
        <Button x:Name="CloseButton" Content="×" Width="28" Height="28" HorizontalAlignment="Right"
                Foreground="#FFB7BEC8" Background="Transparent" BorderThickness="0" FontSize="18" Cursor="Hand"/>
      </Grid>

      <Grid x:Name="StatusView" Grid.Row="1">
        <Grid.RowDefinitions>
          <RowDefinition Height="62"/>
          <RowDefinition Height="62"/>
          <RowDefinition Height="62"/>
          <RowDefinition Height="62"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <StackPanel Grid.Row="0" Margin="0,3,0,0">
          <TextBlock x:Name="ThreadTitle" Text="正在读取当前任务…" Foreground="#FFF5F7FA" FontSize="13"
                     FontWeight="SemiBold" TextTrimming="CharacterEllipsis" ToolTip=""/>
          <TextBlock x:Name="ThreadMeta" Text="" Foreground="#FF8F99A8" FontSize="11" Margin="0,6,0,0" TextTrimming="CharacterEllipsis"/>
        </StackPanel>
        <StackPanel Grid.Row="1">
          <DockPanel>
            <TextBlock Text="当前上下文" Foreground="#FFC7CDD6" FontSize="11"/>
            <TextBlock x:Name="ContextText" Text="等待数据" Foreground="#FFF5F7FA" FontSize="11" HorizontalAlignment="Right"/>
          </DockPanel>
          <ProgressBar x:Name="ContextBar" Minimum="0" Maximum="100" Value="0" Height="8" Margin="0,8,0,0"
                       Background="#FF2A2F38" Foreground="#FF10A37F" BorderThickness="0"/>
          <TextBlock x:Name="ContextDetail" Text="来自最新 token_count" Foreground="#FF6F7885" FontSize="10" Margin="0,5,0,0"/>
        </StackPanel>
        <StackPanel Grid.Row="2">
          <DockPanel>
            <TextBlock Text="5 小时限额" Foreground="#FFC7CDD6" FontSize="11"/>
            <TextBlock x:Name="FiveHourText" Text="等待数据" Foreground="#FFF5F7FA" FontSize="11" HorizontalAlignment="Right"/>
          </DockPanel>
          <ProgressBar x:Name="FiveHourBar" Minimum="0" Maximum="100" Value="0" Height="8" Margin="0,8,0,0"
                       Background="#FF2A2F38" Foreground="#FF10A37F" BorderThickness="0"/>
          <TextBlock x:Name="FiveHourReset" Text="" Foreground="#FF6F7885" FontSize="10" Margin="0,5,0,0"/>
        </StackPanel>
        <StackPanel Grid.Row="3">
          <DockPanel>
            <TextBlock Text="一周限额" Foreground="#FFC7CDD6" FontSize="11"/>
            <TextBlock x:Name="WeekText" Text="等待数据" Foreground="#FFF5F7FA" FontSize="11" HorizontalAlignment="Right"/>
          </DockPanel>
          <ProgressBar x:Name="WeekBar" Minimum="0" Maximum="100" Value="0" Height="8" Margin="0,8,0,0"
                       Background="#FF2A2F38" Foreground="#FF10A37F" BorderThickness="0"/>
          <TextBlock x:Name="WeekReset" Text="" Foreground="#FF6F7885" FontSize="10" Margin="0,5,0,0"/>
        </StackPanel>
        <TextBlock x:Name="StatusText" Grid.Row="4" Text="本地状态 · 每 2 秒刷新"
                   Foreground="#FF646D79" FontSize="9" HorizontalAlignment="Right" VerticalAlignment="Bottom"/>
      </Grid>

      <Grid x:Name="HistoryView" Grid.Row="1" Visibility="Collapsed" Margin="0,4,0,0">
        <Grid.RowDefinitions>
          <RowDefinition Height="24"/>
          <RowDefinition Height="64"/>
          <RowDefinition Height="70"/>
          <RowDefinition Height="88"/>
          <RowDefinition Height="*"/>
        </Grid.RowDefinitions>
        <TextBlock x:Name="HistoryInstalledText" Grid.Row="0" Text="正在初始化本地记录…"
                   Foreground="#FF8F99A8" FontSize="10.5" VerticalAlignment="Top"/>
        <Border Grid.Row="1" Background="#991F2329" BorderBrush="#243F4854" BorderThickness="1"
                CornerRadius="10" Padding="10,5" Margin="0,0,0,6">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="12"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="48"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
              <TextBlock Text="开始" Foreground="#FF8F99A8" FontSize="9.5" Margin="2,0,0,3"/>
              <DatePicker x:Name="HistoryStartDate" Style="{StaticResource HistoryDatePickerStyle}"
                          ToolTip="点击日期或日历图标选择开始日期"/>
            </StackPanel>
            <TextBlock Grid.Column="1" Text="–" Foreground="#FF69727E" FontSize="12"
                       VerticalAlignment="Bottom" HorizontalAlignment="Center" Margin="0,0,0,7"/>
            <StackPanel Grid.Column="2">
              <TextBlock Text="结束" Foreground="#FF8F99A8" FontSize="9.5" Margin="2,0,0,3"/>
              <DatePicker x:Name="HistoryEndDate" Style="{StaticResource HistoryDatePickerStyle}"
                          ToolTip="点击日期或日历图标选择结束日期"/>
            </StackPanel>
            <Button x:Name="HistoryApplyButton" Grid.Column="3" Content="查询" Height="28" Margin="8,15,0,0"
                    Style="{StaticResource HistoryApplyButtonStyle}"/>
          </Grid>
        </Border>
        <Border Grid.Row="2" Background="#182FAE8F" BorderBrush="#343FC3A0" BorderThickness="1"
                CornerRadius="10" Padding="12,6" Margin="0,0,0,6">
          <Grid>
            <StackPanel VerticalAlignment="Center">
              <TextBlock Text="总 Token 用量" Foreground="#FFA8B0BB" FontSize="10"/>
              <TextBlock x:Name="HistoryTotalText" Text="0" Foreground="#FFF5F7FA" FontSize="23"
                         FontWeight="SemiBold"/>
            </StackPanel>
            <Border Width="8" Height="8" CornerRadius="4" Background="#FF10A37F"
                    HorizontalAlignment="Right" VerticalAlignment="Top" Margin="0,3,3,0"/>
          </Grid>
        </Border>
        <Grid Grid.Row="3">
          <Grid.RowDefinitions><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
          <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/></Grid.ColumnDefinitions>
          <Border Grid.Row="0" Grid.Column="0" Style="{StaticResource HistoryMetricCardStyle}" Margin="0,0,4,3">
            <StackPanel VerticalAlignment="Center"><TextBlock Text="输入" Foreground="#FF828B98" FontSize="9"/><TextBlock x:Name="HistoryInputText" Text="0" Foreground="#FFE8EAED" FontSize="12.5" FontWeight="SemiBold"/></StackPanel>
          </Border>
          <Border Grid.Row="0" Grid.Column="1" Style="{StaticResource HistoryMetricCardStyle}" Margin="4,0,0,3">
            <StackPanel VerticalAlignment="Center"><TextBlock Text="缓存输入" Foreground="#FF828B98" FontSize="9"/><TextBlock x:Name="HistoryCachedText" Text="0" Foreground="#FFE8EAED" FontSize="12.5" FontWeight="SemiBold"/></StackPanel>
          </Border>
          <Border Grid.Row="1" Grid.Column="0" Style="{StaticResource HistoryMetricCardStyle}" Margin="0,3,4,0">
            <StackPanel VerticalAlignment="Center"><TextBlock Text="输出" Foreground="#FF828B98" FontSize="9"/><TextBlock x:Name="HistoryOutputText" Text="0" Foreground="#FFE8EAED" FontSize="12.5" FontWeight="SemiBold"/></StackPanel>
          </Border>
          <Border Grid.Row="1" Grid.Column="1" Style="{StaticResource HistoryMetricCardStyle}" Margin="4,3,0,0">
            <StackPanel VerticalAlignment="Center"><TextBlock Text="推理输出" Foreground="#FF828B98" FontSize="9"/><TextBlock x:Name="HistoryReasoningText" Text="0" Foreground="#FFE8EAED" FontSize="12.5" FontWeight="SemiBold"/></StackPanel>
          </Border>
        </Grid>
        <TextBlock x:Name="HistoryMetaText" Grid.Row="4" Text="仅统计安装后的模型调用"
                   Foreground="#FF69727E" FontSize="9" HorizontalAlignment="Right" VerticalAlignment="Bottom" Margin="0,5,0,0"/>
      </Grid>
      </Grid>
    </Border>
    <Grid x:Name="EdgeIndicator" Width="32" Height="116" Background="Transparent"
          HorizontalAlignment="Right" VerticalAlignment="Center" Visibility="Collapsed">
      <Border x:Name="EdgeIndicatorFill" Width="6" Height="8" CornerRadius="3"
              HorizontalAlignment="Center" VerticalAlignment="Bottom" Background="#FF10A37F"/>
    </Grid>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$names = @(
    'PanelBorder','Header','StatusTabButton','HistoryTabButton','StatusTabIndicator','HistoryTabIndicator','CloseButton','StatusView','HistoryView',
    'ThreadTitle','ThreadMeta','ContextText','ContextBar','ContextDetail','FiveHourText','FiveHourBar',
    'FiveHourReset','WeekText','WeekBar','WeekReset','StatusText','HistoryInstalledText','HistoryStartDate',
    'HistoryEndDate','HistoryApplyButton','HistoryTotalText','HistoryInputText','HistoryCachedText',
    'HistoryOutputText','HistoryReasoningText','HistoryMetaText','EdgeIndicator','EdgeIndicatorFill'
)
foreach ($name in $names) {
    Set-Variable -Name $name -Value $window.FindName($name) -Scope Script
}

$script:HistoryRangeInitialized = $false
$script:HistoryStartEpoch = $null
$script:HistoryEndEpoch = $null

function Set-BarColor($bar, [double]$percent) {
    $color = if ($percent -ge 85) { '#FFFF5D5D' } elseif ($percent -ge 65) { '#FFFFB84D' } else { '#FF10A37F' }
    $bar.Foreground = [Windows.Media.BrushConverter]::new().ConvertFromString($color)
}

function Format-ResetTime($epoch) {
    if ($null -eq $epoch) { return '重置时间不可用' }
    try {
        $time = [DateTimeOffset]::FromUnixTimeSeconds([int64]$epoch).ToLocalTime()
        return '重置：' + $time.ToString('MM-dd HH:mm')
    } catch {
        return '重置时间不可用'
    }
}

function Read-CodexStatus {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $pythonPath
    $arguments = '"' + $providerPath + '"'
    if ($null -ne $script:HistoryStartEpoch -and $null -ne $script:HistoryEndEpoch) {
        $arguments += ' --history-start ' + ([int64]$script:HistoryStartEpoch)
        $arguments += ' --history-end ' + ([int64]$script:HistoryEndEpoch)
    }
    $startInfo.Arguments = $arguments
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    if ($startInfo.PSObject.Properties.Name -contains 'StandardOutputEncoding') {
        $startInfo.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $startInfo.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $json = $process.StandardOutput.ReadToEnd()
    $errorText = $process.StandardError.ReadToEnd()
    $process.WaitForExit(5000) | Out-Null
    if ($process.ExitCode -ne 0 -and [string]::IsNullOrWhiteSpace($json)) {
        throw $errorText
    }
    return $json | ConvertFrom-Json
}

function Format-TokenCount([int64]$value) {
    return $value.ToString('N0')
}

function Convert-LocalDateToEpoch([DateTime]$date) {
    $localDate = [DateTime]::SpecifyKind($date.Date, [DateTimeKind]::Local)
    return [DateTimeOffset]::new($localDate).ToUnixTimeSeconds()
}

function Open-HistoryDatePickerFromText($datePicker) {
    $textBox = $datePicker.Template.FindName('PART_TextBox', $datePicker)
    if ($null -ne $textBox -and $textBox.IsMouseOver) {
        $datePicker.IsDropDownOpen = $true
    }
}

function Hide-HistoryDatePickerButton($datePicker) {
    [void]$datePicker.ApplyTemplate()
    $button = $datePicker.Template.FindName('PART_Button', $datePicker)
    if ($null -eq $button) { return }

    $button.Visibility = 'Collapsed'
    $parent = [Windows.Media.VisualTreeHelper]::GetParent($button)
    if ($parent -is [Windows.Controls.Grid]) {
        $column = [Windows.Controls.Grid]::GetColumn($button)
        if ($column -ge 0 -and $column -lt $parent.ColumnDefinitions.Count) {
            $parent.ColumnDefinitions[$column].Width = [Windows.GridLength]::new(0)
        }
    }
}

function Apply-HistoryDateRange {
    if ($null -eq $HistoryStartDate.SelectedDate -or $null -eq $HistoryEndDate.SelectedDate) {
        $HistoryMetaText.Text = '请选择开始与结束日期'
        return $false
    }
    if ($HistoryStartDate.SelectedDate.Date -gt $HistoryEndDate.SelectedDate.Date) {
        $HistoryMetaText.Text = '开始日期不能晚于结束日期'
        return $false
    }
    $script:HistoryStartEpoch = Convert-LocalDateToEpoch $HistoryStartDate.SelectedDate
    $script:HistoryEndEpoch = Convert-LocalDateToEpoch ($HistoryEndDate.SelectedDate.AddDays(1))
    return $true
}

function Update-HistoryView($history, $historyError) {
    if ($null -eq $history) {
        $HistoryTotalText.Text = '—'
        $HistoryMetaText.Text = if ([string]::IsNullOrWhiteSpace([string]$historyError)) { '历史记录暂不可用' } else { '记录失败：' + [string]$historyError }
        return
    }
    $installedAt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$history.installed_at).ToLocalTime()
    $HistoryInstalledText.Text = '自 ' + $installedAt.ToString('yyyy-MM-dd HH:mm') + ' 安装后开始记录'
    if (-not $script:HistoryRangeInitialized) {
        $today = (Get-Date).Date
        $HistoryStartDate.SelectedDate = $today
        $HistoryEndDate.SelectedDate = $today
        $script:HistoryRangeInitialized = $true
        [void](Apply-HistoryDateRange)
    }
    $HistoryTotalText.Text = Format-TokenCount ([int64]$history.total_tokens)
    $HistoryInputText.Text = Format-TokenCount ([int64]$history.input_tokens)
    $HistoryCachedText.Text = Format-TokenCount ([int64]$history.cached_input_tokens)
    $HistoryOutputText.Text = Format-TokenCount ([int64]$history.output_tokens)
    $HistoryReasoningText.Text = Format-TokenCount ([int64]$history.reasoning_output_tokens)
    $lastUpdated = if ($null -ne $history.last_event_at) {
        [DateTimeOffset]::FromUnixTimeSeconds([int64]$history.last_event_at).ToLocalTime().ToString('MM-dd HH:mm')
    } else {
        '暂无记录'
    }
    $HistoryMetaText.Text = ('{0:N0} 次模型调用 · 最近 {1}' -f [int64]$history.event_count, $lastUpdated)
}

function Update-Limit($limit, $text, $bar, $reset) {
    if ($null -eq $limit) {
        $text.Text = '暂无数据'
        $bar.Value = 0
        $reset.Text = ''
        return
    }
    $used = [Math]::Max(0, [Math]::Min(100, [double]$limit.used_percent))
    $text.Text = ('已用 {0:0.#}% · 剩余 {1:0.#}%' -f $used, (100 - $used))
    $bar.Value = $used
    Set-BarColor $bar $used
    $reset.Text = Format-ResetTime $limit.resets_at
}

function Update-Panel {
    try {
        $data = Read-CodexStatus
        if (-not $data.ok) { throw $data.error }

        $ThreadTitle.Text = [string]$data.thread.title
        $ThreadTitle.ToolTip = [string]$data.thread.title
        $ThreadMeta.Text = ([string]$data.thread.model) + '  ·  ' + ([string]$data.thread.id).Substring(0, 8)

        if ($null -ne $data.context) {
            $percent = [double]$data.context.percent
            $displayPercent = [Math]::Max(0, [Math]::Min(100, $percent))
            $ContextText.Text = ('{0:N0} / {1:N0}  ({2:0.0}%)' -f [int64]$data.context.tokens, [int64]$data.context.window, $percent)
            $ContextBar.Value = $displayPercent
            Set-BarColor $ContextBar $displayPercent
            $EdgeIndicatorFill.Height = [Math]::Max(8, [Math]::Round(116 * $displayPercent / 100))
            $ContextDetail.Text = ('输入 {0:N0} · 输出 {1:N0} tokens' -f [int64]$data.context.input_tokens, [int64]$data.context.output_tokens)
        } else {
            $ContextText.Text = '等待首次模型响应'
            $ContextBar.Value = 0
            $EdgeIndicatorFill.Height = 8
            $ContextDetail.Text = '尚无 token_count 事件'
        }

        $fiveHour = $data.limits | Where-Object { $_.window_minutes -eq 300 } | Select-Object -First 1
        $week = $data.limits | Where-Object { $_.window_minutes -eq 10080 } | Select-Object -First 1
        Update-Limit $fiveHour $FiveHourText $FiveHourBar $FiveHourReset
        Update-Limit $week $WeekText $WeekBar $WeekReset
        Update-HistoryView $data.history $data.history_error
        $selectionLabel = if ($data.thread.selection_source -in @('desktop_activity_log','window_accessibility')) { '随点击更新' } else { '最近任务回退' }
        $StatusText.Text = $selectionLabel + ' · ' + (Get-Date).ToString('HH:mm:ss')
    } catch {
        $StatusText.Text = '读取失败：' + $_.Exception.Message
    }
}

function Set-PanelView([string]$viewName) {
    $workArea = [System.Windows.SystemParameters]::WorkArea
    $oldBottom = if ([double]::IsNaN([double]$window.Top)) { $workArea.Bottom - 18 } else { $window.Top + $window.Height }
    if ($viewName -eq 'History') {
        $StatusView.Visibility = 'Collapsed'
        $HistoryView.Visibility = 'Visible'
        $StatusTabButton.Foreground = [Windows.Media.BrushConverter]::new().ConvertFromString('#FF828B98')
        $HistoryTabButton.Foreground = [Windows.Media.BrushConverter]::new().ConvertFromString('#FFF5F7FA')
        $StatusTabIndicator.Visibility = 'Collapsed'
        $HistoryTabIndicator.Visibility = 'Visible'
        $window.Height = 336
    } else {
        $StatusView.Visibility = 'Visible'
        $HistoryView.Visibility = 'Collapsed'
        $StatusTabButton.Foreground = [Windows.Media.BrushConverter]::new().ConvertFromString('#FFF5F7FA')
        $HistoryTabButton.Foreground = [Windows.Media.BrushConverter]::new().ConvertFromString('#FF828B98')
        $StatusTabIndicator.Visibility = 'Visible'
        $HistoryTabIndicator.Visibility = 'Collapsed'
        $window.Height = 336
    }
    $window.Top = [Math]::Max($workArea.Top, [Math]::Min($oldBottom - $window.Height, $workArea.Bottom - $window.Height))
}

$script:DockSide = $null
$script:IsDockHidden = $false
$script:IsDockAnimating = $false
$script:SlideTargetLeft = 0.0
$script:SlideHideAtEnd = $false
$script:PeekWidth = 32
$script:DockThreshold = 32
$script:SlideDurationMs = 220

function Get-DockedLeft([bool]$hidden) {
    $workArea = [System.Windows.SystemParameters]::WorkArea
    if ($script:DockSide -eq 'Left') {
        if ($hidden) { return $workArea.Left - $window.Width + $script:PeekWidth }
        return $workArea.Left
    }
    if ($hidden) { return $workArea.Right - $script:PeekWidth }
    return $workArea.Right - $window.Width
}

function Stop-SlideAnimation {
    $currentLeft = [double]$window.Left
    # Mark the old clock inactive before removing it. A cancelled animation
    # must never be allowed to commit its stale end state.
    $script:IsDockAnimating = $false
    $window.BeginAnimation([Windows.Window]::LeftProperty, $null)
    $window.Left = $currentLeft
}

function Complete-SlideAnimation {
    if (-not $script:IsDockAnimating) { return }

    $window.BeginAnimation([Windows.Window]::LeftProperty, $null)
    $window.Left = $script:SlideTargetLeft
    $script:IsDockAnimating = $false
    $script:IsDockHidden = $script:SlideHideAtEnd

    if ($script:SlideHideAtEnd) {
        # Once fully off-screen, remove every part of the original panel from
        # rendering and hit testing. The indicator is the only visible child.
        $PanelBorder.Visibility = 'Collapsed'
        $EdgeIndicator.Visibility = 'Visible'
    } else {
        $PanelBorder.Visibility = 'Visible'
        $EdgeIndicator.Visibility = 'Collapsed'
    }
}

function Start-SlideAnimation([double]$targetLeft, [bool]$hideAtEnd) {
    Stop-SlideAnimation
    $startLeft = [double]$window.Left

    # The full panel remains visible while moving. Only after it is completely
    # off-screen do we swap it for the isolated green edge indicator.
    $PanelBorder.Visibility = 'Visible'
    $EdgeIndicator.Visibility = 'Collapsed'
    $script:IsDockHidden = $false
    $script:IsDockAnimating = $true
    $script:SlideTargetLeft = $targetLeft
    $script:SlideHideAtEnd = $hideAtEnd

    $easing = New-Object Windows.Media.Animation.CubicEase
    $easing.EasingMode = [Windows.Media.Animation.EasingMode]::EaseInOut
    $animation = New-Object Windows.Media.Animation.DoubleAnimation
    $animation.From = $startLeft
    $animation.To = $targetLeft
    $animation.Duration = [Windows.Duration]::new([TimeSpan]::FromMilliseconds($script:SlideDurationMs))
    $animation.EasingFunction = $easing
    $animation.FillBehavior = [Windows.Media.Animation.FillBehavior]::Stop
    # Do not use GetNewClosure here: it gives $script: variables a separate
    # dynamic-module scope, so the completion state never reaches this script.
    $animation.Add_Completed({ Complete-SlideAnimation })
    $window.BeginAnimation([Windows.Window]::LeftProperty, $animation)
}

function Show-DockedWindow {
    if ($null -eq $script:DockSide) { return }
    Start-SlideAnimation (Get-DockedLeft $false) $false
}

function Hide-DockedWindow {
    if ($null -eq $script:DockSide) { return }
    Start-SlideAnimation (Get-DockedLeft $true) $true
}

function Update-DockState {
    $workArea = [System.Windows.SystemParameters]::WorkArea
    if ($window.Left -le ($workArea.Left + $script:DockThreshold)) {
        $script:DockSide = 'Left'
        $EdgeIndicator.HorizontalAlignment = 'Right'
        $EdgeIndicator.Visibility = 'Collapsed'
        $PanelBorder.Visibility = 'Visible'
        $window.Left = $workArea.Left
    } elseif (($window.Left + $window.Width) -ge ($workArea.Right - $script:DockThreshold)) {
        $script:DockSide = 'Right'
        $EdgeIndicator.HorizontalAlignment = 'Left'
        $EdgeIndicator.Visibility = 'Collapsed'
        $PanelBorder.Visibility = 'Visible'
        $window.Left = $workArea.Right - $window.Width
    } else {
        $script:DockSide = $null
        $script:IsDockHidden = $false
        $PanelBorder.Visibility = 'Visible'
        $EdgeIndicator.Visibility = 'Collapsed'
    }
}

$hideTimer = New-Object Windows.Threading.DispatcherTimer
$hideTimer.Interval = [TimeSpan]::FromMilliseconds(650)
$hideTimer.Add_Tick({
    $hideTimer.Stop()
    if ($null -ne $script:DockSide -and -not $script:IsDockHidden -and -not $script:IsDockAnimating -and -not $window.IsMouseOver) {
        Hide-DockedWindow
    }
})

$Header.Add_MouseLeftButtonDown({
    $hideTimer.Stop()
    Stop-SlideAnimation
    $window.DragMove()
    Update-DockState
    if ($null -ne $script:DockSide -and -not $window.IsMouseOver) { $hideTimer.Start() }
})
$StatusTabButton.Add_Click({ Set-PanelView 'Status' })
$HistoryTabButton.Add_Click({ Set-PanelView 'History' })
$HistoryStartDate.Add_Loaded({ Hide-HistoryDatePickerButton $HistoryStartDate })
$HistoryEndDate.Add_Loaded({ Hide-HistoryDatePickerButton $HistoryEndDate })
$HistoryStartDate.Add_PreviewMouseLeftButtonUp({ Open-HistoryDatePickerFromText $HistoryStartDate })
$HistoryEndDate.Add_PreviewMouseLeftButtonUp({ Open-HistoryDatePickerFromText $HistoryEndDate })
$HistoryApplyButton.Add_Click({
    if (Apply-HistoryDateRange) { Update-Panel }
})
$CloseButton.Add_Click({ $window.Close() })
$window.Add_MouseEnter({
    $hideTimer.Stop()
    if ($script:IsDockHidden -or ($script:IsDockAnimating -and $null -ne $script:DockSide)) { Show-DockedWindow }
})
$window.Add_MouseLeave({
    if ($null -ne $script:DockSide) {
        $hideTimer.Stop()
        $hideTimer.Start()
    }
})
$window.Add_Loaded({
    $workArea = [System.Windows.SystemParameters]::WorkArea
    $window.Left = $workArea.Right - $window.Width - 18
    $window.Top = $workArea.Bottom - $window.Height - 18
    Update-Panel
    Update-DockState
    if ($null -ne $script:DockSide -and -not $window.IsMouseOver) { $hideTimer.Start() }
})

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromSeconds([Math]::Max(1, $RefreshSeconds))
$timer.Add_Tick({ Update-Panel })
$timer.Start()
$window.Add_Closed({ $timer.Stop(); $hideTimer.Stop(); Stop-SlideAnimation })

try {
    [void]$window.ShowDialog()
} finally {
    try { $singleInstanceMutex.ReleaseMutex() } catch { }
    $singleInstanceMutex.Dispose()
}
