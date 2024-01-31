$START_DIR = "$(get-location)"
$product_version = $Env:MTX_PRODUCT_VERSION
if (!"$product_version") {
    $product_version = "9.9.9.9"
}

$build_number = $Env:MTX_BUILD_NUMBER
if (!"$build_number") {
    $build_number = "999"
}

$app = Get-WmiObject -Class Win32_Product | Where-Object {
    $_.Name -match "Python*"
}
$app.Uninstall()
#Get-Package "*python*" | Uninstall-Package -Force -Confirm
if ( $LastExitCode ) { exit 1 }
#Restart-Computer -Force

#Set-Location -Path $START_DIR
#if( Test-Path $START_DIR\python39 ) { Remove-Item $START_DIR\python39 -Recurse -Force }
#Set-Location -Path $START_DIR
#New-Item -ItemType directory -Path .\python39
Set-Location -Path "${START_DIR}\packaging\python3"
#Start-Process -FilePath ./python-3.9.5-amd64.exe -ArgumentList "/quiet TargetDir=${START_DIR}\python39 InstallAllUsers=1 PrependPath=1 Include_test=0" -NoNewWindow -Wait
& .\python-3.8.6-amd64.exe /quiet TargetDir=${START_DIR}\python39 InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=0 /log "%WINDIR%\Temp\Python39-Install.log"
if ( $LastExitCode ) { exit 1 }
Start-Sleep -Seconds 120
Set-Location -Path "${START_DIR}"
if (-Not (Test-Path "${START_DIR}\python39")) {
    Write-Host "Python Not Installed"
    exit 1
}

#New-Item -ItemType directory -Path .\lessmsi
#& 7z x -y -olessmsi .\packaging\lessmsi\lessmsi-v1.3.zip
#if ( $LastExitCode ) { exit 1 }

#if( Test-Path $START_DIR\python-2.7.10.amd64 ) { Remove-Item $START_DIR\python-2.7.11.amd64 -Recurse -Force }
#& $START_DIR\lessmsi\lessmsi x .\packaging\python\python-2.7.11.amd64.msi
#if ( $LastExitCode ) { exit 1 }
#$Env:PYTHONPATH="$START_DIR\src"
#$PYTHON_AMD64 = "${START_DIR}\python-2.7.11.amd64\SourceDir\python.exe"

# Create an exe from the python script
$Env:PYTHONPATH="${START_DIR}\python39\Lib\site-packages"
$PYTHON_AMD64 = "${START_DIR}\python39\python.exe"
$PIP_AMD64 = "${START_DIR}\python39\Scripts\pip.exe"

Set-Location -Path $START_DIR

Function InstallPythonModuleZip($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.zip
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}"
    & $python setup.py install
    Set-Location -Path "${START_DIR}"
}

Function InstallPythonModule($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.tar.gz
    & 7z x -y "-o${name}" "${START_DIR}\${name}\dist\${name}-${version}.tar"
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}"
    & $python setup.py install
    Set-Location -Path "${START_DIR}"
}

InstallPythonModuleZip "$PYTHON_AMD64" "setuptools" "50.3.2"
#InstallPythonModule "$PYTHON_AMD64" "setuptools" "2.2"

Set-Location -Path ${START_DIR}
& $PYTHON_AMD64 setup.py "sdist" "--formats=zip"
Copy-Item ".\dist\*" "$Env:MTX_COLLECTION_PATH"





