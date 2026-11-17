param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$views = Get-Content -LiteralPath $InputPath -Raw | ConvertFrom-Json
$cellWidth = 400
$cellHeight = 320
$columns = 4
$rows = [Math]::Ceiling($views.Count / $columns)
$bitmap = [System.Drawing.Bitmap]::new($cellWidth * $columns, $cellHeight * $rows, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$graphics.Clear([System.Drawing.Color]::FromArgb(255, 13, 21, 34))
$font = [System.Drawing.Font]::new('Segoe UI', 11, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$brushText = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 141, 180, 204))
$penCard = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 32, 51, 70), 1)
$zoom = 2.0

function Convert-LinearChannel([double]$Value) {
    $c = [Math]::Max(0.0, [Math]::Min(1.0, $Value))
    if ($c -le 0.0031308) { return [int][Math]::Round(12.92 * $c * 255.0) }
    return [int][Math]::Round((1.055 * [Math]::Pow($c, 1.0 / 2.4) - 0.055) * 255.0)
}

function Make-Brush($Color) {
    $a = [int][Math]::Round([Math]::Max(0.0, [Math]::Min(1.0, [double]$Color[3])) * 255.0)
    $r = Convert-LinearChannel ([double]$Color[0])
    $g = Convert-LinearChannel ([double]$Color[1])
    $b = Convert-LinearChannel ([double]$Color[2])
    return [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($a, $r, $g, $b))
}

for ($i = 0; $i -lt $views.Count; $i++) {
    $view = $views[$i]
    $column = $i % $columns
    $row = [Math]::Floor($i / $columns)
    $left = $column * $cellWidth
    $top = $row * $cellHeight
    $panel = [System.Drawing.Rectangle]::new($left + 8, $top + 8, $cellWidth - 16, $cellHeight - 16)
    $panelBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 17, 29, 44))
    $graphics.FillRectangle($panelBrush, $panel)
    $panelBrush.Dispose()
    $graphics.DrawRectangle($penCard, $panel)
    $graphics.DrawString([string]$view.label, $font, $brushText, [single]($left + 20), [single]($top + 16))
    $centerX = $left + $cellWidth * 0.5
    $centerY = $top + $cellHeight * 0.56
    $baseX = [double]$view.center[0]
    $baseY = [double]$view.center[1]

    foreach ($instance in $view.instances) {
        if ($instance.kind -ne 4) { continue }
        $brush = Make-Brush $instance.color
        $points = [System.Drawing.PointF[]]@(
            [System.Drawing.PointF]::new([single]($centerX + ([double]$instance.p0[0] - $baseX) * $zoom), [single]($centerY - ([double]$instance.p0[1] - $baseY) * $zoom)),
            [System.Drawing.PointF]::new([single]($centerX + ([double]$instance.p1[0] - $baseX) * $zoom), [single]($centerY - ([double]$instance.p1[1] - $baseY) * $zoom)),
            [System.Drawing.PointF]::new([single]($centerX + ([double]$instance.params[0] - $baseX) * $zoom), [single]($centerY - ([double]$instance.params[1] - $baseY) * $zoom))
        )
        $graphics.FillPolygon($brush, $points)
        $brush.Dispose()
    }
}

$bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$font.Dispose()
$brushText.Dispose()
$penCard.Dispose()
