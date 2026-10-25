#!/bin/bash
# winctl.sh <command> -- drive a Windows BLE test host over ssh.  Configure with environment variables:
#   WIN_HOST  ssh host alias of the Windows PC          (default g15)
#   WIN_USER  Windows user name                         (default $USER)
#   MOUSE_MAC the mouse BLE address, 12 hex, no colons  (e.g. D6BFB2D943F2; see ble_scan.py)
# Commands: clean | unpair [wait] | pair [wait] | cursor [secs] | cursorout | battery [wait] | btnwatch [secs] | btnout
# Needs on Windows (once): python venv %USERPROFILE%\blevenv with `pip install bleak`, and these scripts + run_task.cmd copied to %USERPROFILE%.
cd "$(dirname "$0")"
H=${WIN_HOST:-g15}; U=${WIN_USER:-$USER}; HOME_W="C:\\Users\\$U"
MOUSE_MAC_COLON=$(echo "$MOUSE_MAC" | sed "s/../&:/g; s/:$//")
runtask(){ # script, args  -> create + run a one-shot scheduled task in the interactive session
  ssh "$H" "del $HOME_W\\out_$1.txt 2>nul & schtasks /Create /TN blerun /TR \"$HOME_W\\run_task.cmd $1 $2\" /SC ONCE /ST 23:59 /RU $U /IT /F >nul && schtasks /Run /TN blerun >nul" 2>&1 | grep -v "^\*\*\|cannot find the path"
}
out(){ ssh "$H" "type $HOME_W\\out_$1.txt" 2>&1 | grep -v "^\*\*"; }
case "$1" in
 clean)     ssh "$H" "powershell -NoProfile -Command \"Get-PnpDevice | ? { \$_.InstanceId -like '*$MOUSE_MAC*' } | % { pnputil /remove-device \$_.InstanceId | Out-Null }\"" 2>&1 | grep -v "^\*\*";;
 unpair)    runtask ble_unpair.py "$MOUSE_MAC_COLON"; sleep ${2:-20}; out ble_unpair.py;;
 pair)      runtask ble_pair.py ""; sleep ${2:-35}; out ble_pair.py | head -3;;
 cursor)    runtask cursor.py "${2:-12}"; sleep 2; echo started;;
 cursorout) out cursor.py;;
 battery)   runtask ble_battery.py "$MOUSE_MAC_COLON"; sleep ${2:-12}; out ble_battery.py;;
 btnwatch)  runtask btnwatch.py "${2:-60}"; sleep 2; echo started;;
 btnout)    out btnwatch.py;;
 *) sed -n 2,9p "$0";;
esac
