# Threat alerts on Windows: test lists (no real malicious hosts are contacted), a program in Downloads.
Copy-Item C:\Windows\System32\curl.exe "$env:USERPROFILE\Downloads\wt-test-tool.exe" -Force
"evil-c2.example`nwikipedia.org" | Set-Content C:\wiretrace\test-threats-domains.txt
New-Item -ItemType Directory -Force C:\wiretrace\test-threats | Out-Null
Move-Item -Force C:\wiretrace\test-threats-domains.txt C:\wiretrace\test-threats\domains.txt
"1.1.1.1`tTEST botnet control server`ttest" | Set-Content C:\wiretrace\test-threats\ips.txt
$job = Start-Job { cmd /c "ping -n 14 127.0.0.1 | C:\wiretrace\desktop\agent\target\release\whosees-agent.exe --deep --geo C:\wiretrace\shared\geo\world.wtgeo --categories C:\wiretrace\shared\categories\domains.json --threats C:\wiretrace\test-threats > C:\wiretrace\agent-alerts.out" }
Start-Sleep 4
curl.exe -s -o NUL --max-time 4 https://www.wikipedia.org
& "$env:USERPROFILE\Downloads\wt-test-tool.exe" -s -o NUL --limit-rate 20k -m 4 https://fsn1-speed.hetzner.com/100MB.bin
$u = New-Object System.Net.Sockets.UdpClient; $u.Connect('1.1.1.1', 443); 1..5 | % { [void]$u.Send((New-Object byte[] 200), 200); Start-Sleep -Milliseconds 100 }; $u.Close()
Wait-Job $job -Timeout 25 | Out-Null
Remove-Item -Force "$env:USERPROFILE\Downloads\wt-test-tool.exe"
Get-Content C:\wiretrace\agent-alerts.out
