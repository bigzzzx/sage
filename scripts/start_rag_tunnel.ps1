param(
    [string]$HostAlias = "remote-rag-host"
)

$ErrorActionPreference = "Stop"
Write-Host "SAGE RAG tunnel: localhost:18081 -> remote embedding; localhost:18082 -> remote reranker"
Write-Host "Keep this terminal open while using remote RAG. Press Ctrl+C to stop."
& ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
    -o ServerAliveCountMax=3 -N `
    -L 127.0.0.1:18081:127.0.0.1:8081 `
    -L 127.0.0.1:18082:127.0.0.1:8082 $HostAlias
if ($LASTEXITCODE -ne 0) {
    throw "SSH tunnel exited with code $LASTEXITCODE. Check SSH alias and port availability."
}
