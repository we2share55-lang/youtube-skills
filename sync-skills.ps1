<#
.SYNOPSIS
  ~/.claude/skills 의 스킬들을 이 저장소로 동기화한 뒤 커밋·푸시한다.

.DESCRIPTION
  이 저장소의 skills\ 아래에 이미 있는 스킬 폴더들을 기준으로,
  ~/.claude/skills\<스킬> 의 최신 내용을 그대로 복사(mirror)한다.
  변경이 있으면 커밋하고 origin 으로 push 한다. 변경이 없으면 아무것도 하지 않는다.
  API 키 등 민감정보는 .gitignore 로 제외되며 이 스크립트는 키를 다루지 않는다.

.PARAMETER Message
  커밋 메시지. 생략하면 타임스탬프가 들어간 기본 메시지를 쓴다.

.PARAMETER NoPush
  커밋만 하고 push 는 하지 않는다.

.EXAMPLE
  .\sync-skills.ps1
  .\sync-skills.ps1 -Message "value-investing-coach 검수 항목 추가"
  .\sync-skills.ps1 -NoPush
#>
param(
    [string]$Message,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"

# 저장소 루트 = 이 스크립트가 있는 폴더
$RepoRoot   = $PSScriptRoot
$RepoSkills = Join-Path $RepoRoot "skills"
$SrcSkills  = Join-Path $env:USERPROFILE ".claude\skills"

if (-not (Test-Path $RepoSkills)) {
    throw "저장소에 skills 폴더가 없습니다: $RepoSkills"
}
if (-not (Test-Path $SrcSkills)) {
    throw "원본 스킬 폴더가 없습니다: $SrcSkills"
}

# 저장소가 추적 중인 스킬 폴더 목록을 기준으로 동기화
$skills = Get-ChildItem -Path $RepoSkills -Directory | Select-Object -ExpandProperty Name
if (-not $skills) {
    throw "저장소 skills\ 아래에 스킬 폴더가 없습니다."
}

Write-Host "동기화할 스킬: $($skills -join ', ')" -ForegroundColor Cyan

foreach ($name in $skills) {
    $src = Join-Path $SrcSkills  $name
    $dst = Join-Path $RepoSkills $name
    if (-not (Test-Path $src)) {
        Write-Warning "원본에 없음, 건너뜀: ~/.claude/skills/$name"
        continue
    }
    Write-Host "  <- $name" -ForegroundColor DarkGray
    # /MIR: 완전 미러(삭제 포함), __pycache__ 와 .pyc 제외, 로그 최소화
    # .venv / node_modules 와 개인 자료(참조 음성, 원본 캐릭터 사진)는 저장소(공개)에 올리지 않는다
    robocopy $src $dst /MIR /XD "__pycache__" ".venv" "node_modules" /XF "*.pyc" "ref_voice.*" "character_01.jpg" /NFL /NDL /NJH /NJS /NP | Out-Null
    # robocopy 종료코드 8 이상만 실패
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy 실패 ($name), 종료코드 $LASTEXITCODE"
    }
}

# git 변경 확인
Push-Location $RepoRoot
try {
    $changes = git status --porcelain
    if (-not $changes) {
        Write-Host "변경 사항 없음 — 커밋/푸시할 것이 없습니다." -ForegroundColor Green
        return
    }

    Write-Host "`n변경된 파일:" -ForegroundColor Yellow
    git status --short

    if (-not $Message) {
        $Message = "Sync skills from ~/.claude/skills ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    }

    # git 은 CRLF 경고 등을 stderr 로 내보내는데, PowerShell 5.1 에서 $ErrorActionPreference=Stop 이면
    # 그것이 오류로 취급돼 중단된다 -> 이 구간만 Continue 로 두고 종료코드로 판단한다.
    $ErrorActionPreference = "Continue"
    git add -A 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git add 실패" }
    git commit -m $Message 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git commit 실패" }
    Write-Host "커밋 완료: $Message" -ForegroundColor Green

    if ($NoPush) {
        Write-Host "(-NoPush 지정됨, push 생략)" -ForegroundColor DarkGray
    } else {
        git push 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "git push 실패" }
        Write-Host "push 완료." -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
