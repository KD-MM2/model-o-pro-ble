param([string]$Mac = $env:MOUSE_MAC)   # 12 hex digits without colons, e.g. AABBCCDDEEFF
$devs = Get-PnpDevice | Where-Object { $_.InstanceId -like "*$Mac*" }
Write-Output ("found devices: " + @($devs).Count)
foreach ($d in $devs) {
  Write-Output ("DEV " + $d.InstanceId + " | " + $d.FriendlyName + " | " + $d.Status)
  $props = Get-PnpDeviceProperty -InstanceId $d.InstanceId -ErrorAction SilentlyContinue
  foreach ($p in $props) { if ($p.KeyName -like '*104EA319*') { Write-Output ("   " + $p.KeyName + " = " + $p.Data) } }
}
