$log='C:\smsf-hub\push_retry.log'
for($i=1;$i -le 40;$i++){
  Push-Location 'C:\smsf-hub'
  $o = git push origin master 2>&1 | Out-String
  Pop-Location
  if($LASTEXITCODE -eq 0){ Add-Content $log "尝试 $i : 成功 $(Get-Date -Format 'HH:mm:ss')"; break }
  Add-Content $log "尝试 $i : 失败 $(Get-Date -Format 'HH:mm:ss')"
  Start-Sleep -Seconds 60
}
