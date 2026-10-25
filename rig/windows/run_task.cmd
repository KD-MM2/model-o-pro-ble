@echo off
rem usage: run_task.cmd <script.py> [args]  -> runs in the INTERACTIVE session, output in %USERPROFILE%\out_<script>.txt
rem BLE pairing/GATT calls from an ssh session fail with ACCESS_DENIED; a scheduled task with /IT runs in the logged-in desktop session.
set SCRIPT=%1
shift
%USERPROFILE%\blevenv\Scripts\python.exe %USERPROFILE%\%SCRIPT% %1 %2 %3 > %USERPROFILE%\out_%SCRIPT%.txt 2>&1
