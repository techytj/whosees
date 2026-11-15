# Report (PDF) on Windows: run the dev app (copied by tools/vm-dist.sh), start a live view, save a report.
# Prints CHECK lines; the PDF is left at C:\wiretrace\win-report.pdf for the caller to inspect.
$env:WT_SHOT='C:\wiretrace\shot';
$env:WT_SHOT_STEPS='live:3000,rep:16000:%28async%20%28%29%20%3D%3E%20%7B%20var%20r%20%3D%20await%20window.__wt.saveReport%28%7B%20theme%3A%20%27light%27%2C%20paper%3A%20%27a4%27%20%7D%29%3B%20console.log%28%27CHECK%20win-report%20%27%20%2B%20%28r.ok%20%3F%20%27PASS%27%20%3A%20%27FAIL%27%29%20%2B%20%27%20%27%20%2B%20JSON.stringify%28r%29%29%3B%20%7D%29%28%29';
$env:WT_REPORT_OUT='C:\wiretrace\win-report.pdf';
Remove-Item -Force C:\wiretrace\win-report.pdf -ea 0;
Remove-Item -Recurse -Force C:\wiretrace\ud-rep -ea 0;
New-Item -ItemType Directory C:\wiretrace\ud-rep | Out-Null;
Set-Content C:\wiretrace\ud-rep\settings.json '{"updatePromptSeen":true,"home":{"city":"Toronto","country":"CA","lat":43.65,"lon":-79.38}}';
cd C:\wiretrace\desktop\app;
$p = Start-Process -FilePath node_modules\electron\dist\electron.exe -ArgumentList '.','--user-data-dir=C:\wiretrace\ud-rep' -PassThru -RedirectStandardOutput C:\wiretrace\rep-out.txt -RedirectStandardError C:\wiretrace\rep-err.txt;
$p.WaitForExit(60000) | Out-Null;
if (!$p.HasExited) { Stop-Process -Id $p.Id -Force };
Get-Content C:\wiretrace\rep-out.txt | Select-String 'CHECK|shot';
Get-Item C:\wiretrace\win-report.pdf -ea 0 | Select-Object Length