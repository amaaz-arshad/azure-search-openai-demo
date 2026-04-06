# set the parent of the script as the current location.
Set-Location $PSScriptRoot

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -NoNewWindow -PassThru
    if ($process.ExitCode -ne 0) {
        Write-Host $FailureMessage
        exit $process.ExitCode
    }
}

function Get-VenvPythonPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDirectory
    )

    $venvPythonPath = Join-Path $ProjectDirectory ".venv/scripts/python.exe"
    if (Test-Path -Path "/usr") {
        $venvPythonPath = Join-Path $ProjectDirectory ".venv/bin/python"
    }

    return $venvPythonPath
}

Write-Host ""
Write-Host "Loading azd .env file from current environment"
Write-Host ""

foreach ($line in (& azd env get-values)) {
    if ($line -match "([^=]+)=(.*)") {
        $key = $matches[1]
        $value = $matches[2] -replace '^"|"$'
        Set-Item -Path "env:\$key" -Value $value
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to load environment variables from azd environment"
    exit $LASTEXITCODE
}

$directory = Get-Location
$venvPythonPath = Get-VenvPythonPath -ProjectDirectory $directory
$pythonVersion = ""
if ($env:PYTHON_VERSION) {
    $pythonVersion = $env:PYTHON_VERSION.Trim()
}
if (-not $pythonVersion) {
    # Match the Azure runtime by default, while still allowing overrides per machine.
    $pythonVersion = "3.11"
}

if (Test-Path -Path $venvPythonPath) {
    Write-Host 'Reusing existing python virtual environment ".venv"'
} else {
    Write-Host ("Creating python virtual environment `".venv`" using Python {0}" -f $pythonVersion)

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        Invoke-CheckedProcess `
            -FilePath $pyLauncher.Source `
            -ArgumentList @("-$pythonVersion", "-m", "venv", ".venv") `
            -FailureMessage "Failed to create Python virtual environment with py -$pythonVersion. Install that version or set PYTHON_VERSION to one you have."
    } else {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCmd) {
            $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
        }

        if (-not $pythonCmd) {
            Write-Host "Could not find 'py', 'python', or 'python3'. Install Python $pythonVersion or create .venv manually before running this script."
            exit 1
        }

        Write-Host "Python launcher 'py' was not found. Falling back to $($pythonCmd.Source) to create .venv."
        Write-Host "If you need a specific interpreter version, create .venv manually first or install the Windows py launcher and set PYTHON_VERSION."
        Invoke-CheckedProcess `
            -FilePath $pythonCmd.Source `
            -ArgumentList @("-m", "venv", ".venv") `
            -FailureMessage "Failed to create Python virtual environment."
    }
}

$venvPythonPath = Get-VenvPythonPath -ProjectDirectory $directory
if (-not (Test-Path -Path $venvPythonPath)) {
    Write-Host "Python virtual environment was not created successfully"
    exit 1
}

Write-Host ""
Write-Host "Restoring backend python packages"
Write-Host ""

Invoke-CheckedProcess `
    -FilePath $venvPythonPath `
    -ArgumentList @("-m", "pip", "install", "-r", "backend/requirements.txt") `
    -FailureMessage "Failed to restore backend python packages"

Write-Host ""
Write-Host "Restoring frontend npm packages"
Write-Host ""
Set-Location ./frontend
npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to restore frontend npm packages"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Building frontend"
Write-Host ""
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to build frontend"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Starting backend"
Write-Host ""
Set-Location ../backend

$port = 50505
$hostname = "localhost"
Invoke-CheckedProcess `
    -FilePath $venvPythonPath `
    -ArgumentList @("-m", "quart", "--app", "main:app", "run", "--port", "$port", "--host", $hostname, "--reload") `
    -FailureMessage "Failed to start backend"
