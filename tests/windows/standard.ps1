$job = Start-Job { cmd /c "ping -n 14 127.0.0.1 | C:\wiretrace\desktop\agent\target\release\whosees-agent.exe --geo C:\wiretrace\shared\geo\world.wtgeo --categories C:\wiretrace\shared\categories\domains.json > C:\wiretrace\agent-std.out" }
Start-Sleep 3
$p = @()
foreach ($u in 'https://fsn1-speed.hetzner.com/100MB.bin','https://proof.ovh.net/files/100Mb.dat','https://speedtest.tokyo2.linode.com/100MB-tokyo2.bin') { $p += Start-Process curl.exe -ArgumentList '-s','-o','NUL','--limit-rate','30k','-m','7',$u -PassThru -NoNewWindow }
Wait-Job $job -Timeout 25 | Out-Null
Get-Content C:\wiretrace\agent-std.out
