$b = [System.IO.File]::ReadAllBytes('F:\keypad-api\PentaStarStudios.png')
$sb = New-Object System.Text.StringBuilder
 
$null = $sb.AppendLine('#pragma once')
$null = $sb.AppendLine()
$null = $sb.AppendLine("const unsigned int PentaStarStudiosPngSize = $($b.Length);")
$null = $sb.AppendLine('const unsigned char PentaStarStudiosPng[] = {')
 
for ($i = 0; $i -lt $b.Length; $i++) {
    $hex = ('0x{0:X2}' -f $b[$i])
    if ($i -lt $b.Length - 1) { $hex += ',' }
    $null = $sb.Append($hex)
 
    if ((($i + 1) % 12) -eq 0) {
        $null = $sb.AppendLine()
    } else {
        $null = $sb.Append(' ')
    }
}
 
$null = $sb.AppendLine()
$null = $sb.AppendLine('};')
 
$dest = 'F:\keypad-api\firmware\esp32_displaypad\src\penta_star_studios_png.h'
[System.IO.File]::WriteAllText($dest, $sb.ToString())
Write-Host "Wrote $dest"