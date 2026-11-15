$job = Start-Job { cmd /c "ping -n 14 127.0.0.1 | C:\wiretrace\desktop\agent\target\release\whosees-agent.exe --deep --geo C:\wiretrace\shared\geo\world.wtgeo --categories C:\wiretrace\shared\categories\domains.json > C:\wiretrace\agent-deep.out 2> C:\wiretrace\agent-deep.err" }
Start-Sleep 4
# short-lived TCP (closes within ~100 ms)
foreach ($u in 'https://example.com','https://www.wikipedia.org') { curl.exe -s -o NUL --max-time 3 $u }
# UDP like QUIC: a few datagrams to Cloudflare port 443
$u = New-Object System.Net.Sockets.UdpClient; $u.Connect('1.1.1.1', 443); 1..20 | % { [void]$u.Send((New-Object byte[] 1200), 1200); Start-Sleep -Milliseconds 100 }; $u.Close()
Wait-Job $job -Timeout 25 | Out-Null
Get-Content C:\wiretrace\agent-deep.out
Get-Content C:\wiretrace\agent-deep.err | Select -First 5 | % { "ERR $_" }
