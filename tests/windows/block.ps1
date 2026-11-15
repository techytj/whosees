function T($label, $sb) { try { & $sb | Out-Null; "RESULT $label WORKS" } catch { "RESULT $label BLOCKED" } }
"RESULT before-run WhoSees rules: " + (@(Get-NetFirewallRule -DisplayName 'WhoSees *' -ea 0).Count)
ipconfig /flushdns | Out-Null  # nothing known in advance: the first request below is a true first contact
$job = Start-Job { cmd /c "(echo {""cmd"":""rules"",""rules"":[{""kind"":""host"",""value"":""wikipedia.org""},{""kind"":""app"",""value"":""C:\\Windows\\System32\\curl.exe""},{""kind"":""category"",""value"":""tracking""}]} & ping -n 22 127.0.0.1) | C:\wiretrace\desktop\agent\target\release\whosees-agent.exe --deep --blocking --geo C:\wiretrace\shared\geo\world.wtgeo --categories C:\wiretrace\shared\categories\domains.json > C:\wiretrace\agent-block.out 2>&1" }
Start-Sleep 6
"RESULT during-run WhoSees rules: " + (@(Get-NetFirewallRule -DisplayName 'WhoSees *' -ea 0).Count)
T 'powershell->wikipedia (host blocked)' { Invoke-WebRequest https://www.wikipedia.org -UseBasicParsing -TimeoutSec 6 }
T 'curl->github (app blocked)' { $o = curl.exe -s -o NUL -w '%{http_code}' --max-time 6 https://github.com; if ($o -eq '000') { throw 'x' } }
T 'powershell->sentry.io first request (all trackers and ads blocked)' { Invoke-WebRequest https://sentry.io -UseBasicParsing -TimeoutSec 6 }
Start-Sleep 2
T 'powershell->sentry.io analytics (all trackers and ads blocked)' { Invoke-WebRequest https://sentry.io -UseBasicParsing -TimeoutSec 6 }
T 'powershell->github (allowed)' { Invoke-WebRequest https://github.com -UseBasicParsing -TimeoutSec 8 }
Wait-Job $job -Timeout 30 | Out-Null
Start-Sleep 2
"RESULT after-stop WhoSees rules: " + (@(Get-NetFirewallRule -DisplayName 'WhoSees *' -ea 0).Count)
Select-String -Path C:\wiretrace\agent-block.out -Pattern '"t":"rules"' | % { "RESULT agent: " + $_.Line }
