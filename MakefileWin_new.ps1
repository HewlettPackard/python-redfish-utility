$START_DIR = "$(get-location)"
$product_version = $Env:MTX_PRODUCT_VERSION
if (!"$product_version") {
    $product_version = "9.9.9.9"
}

$build_number = $Env:MTX_BUILD_NUMBER
if (!"$build_number") {
    $build_number = "999"
}

Get-WinSystemLocale
Get-Command python.exe | Select-Object -ExpandProperty Definition

if (-Not (Test-Path "$HOME\appdata\local\programs\python\python310")) {
    Write-Host "Python Not Installed"
    Set-Location -Path "${START_DIR}\packaging\python3"
    #& .\python-3.10.9-amd64.exe /quiet TargetDir="C:\python3109_ilorest" PrependPath=1 Include_test=0 Include_launcher=0
    Start-Process .\python-3.10.9-amd64.exe -ArgumentList '/quiet Include_test=0 Include_launcher=0 InstallAllUsers=0 PrependPath=1' -Wait
    #Start-Process .\python-3.10.9-amd64.exe -ArgumentList '/quiet TargetDir=C:\python3109_ilorest Include_test=0 Include_launcher=0 PrependPath=1' -Wait
    if ( $LastExitCode ) { exit 1 }
    Start-Sleep -Seconds 120
    Write-Host "Python Installed Now"
} else {
    Write-Host "Python Already Installed"
}
Get-ChildItem -Path $HOME\appdata\local\programs\python\python310

if (-Not (Test-Path "$HOME\appdata\local\programs\python\python310")) {
    exit 1
}

$PYTHON_AMD64 = "$HOME\appdata\local\programs\python\python310\python.exe"
$PIP_AMD64 = "$HOME\appdata\local\programs\python\python310\Scripts\pip.exe"
$PYINST_AMD64 = "$HOME\appdata\local\programs\python\python310\Scripts\pyinstaller.exe"

Get-Command python.exe | Select-Object -ExpandProperty Definition


#$PYTHON_AMD64 -m venv venv
#& venv\Scripts\activate

Set-Location -Path "${START_DIR}"

$Env:PYTHONHOME="$HOME\appdata\local\programs\python\python310"

# Add FIPS requirements
#$Env:PYTHONIOENCODING = "UTF-8"
# Add ssl, _ssl, and _hashlib which point to morpheus project OPENSSL
Copy-Item "${START_DIR}\packaging\python3\windows\*.pyd" "$HOME\appdata\local\programs\python\python310\DLLs" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\*.dll" "$HOME\appdata\local\programs\python\python310\DLLs" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\*.cnf" "$HOME\appdata\local\programs\python\python310\DLLs" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\ssl.py" "$HOME\appdata\local\programs\python\python310\Lib" -Recurse -Force
Write-Host "OpenSSL 3 Copied"
& $PYTHON_AMD64 --version

Set-Location -Path $START_DIR

Copy-Item "${START_DIR}\packaging\python3\windows\print_ssl_version.py"  "$(get-location)" -Recurse -Force
& $PYTHON_AMD64 print_ssl_version.py

Function InstallPythonModule($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.tar.gz
    if (Test-Path .\${name}\dist ) {
        & 7z x -y "-o${name}" "${START_DIR}\${name}\dist\${name}-${version}.tar"
    }
    else {
        & 7z x -y "-o${name}" "${START_DIR}\${name}\${name}-${version}.tar"
    }
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}"
    & $python setup.py install
    Set-Location -Path "${START_DIR}"
}

Function InstallPyInstallerModule($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.tar.gz
    & 7z x -y "-o${name}" "${START_DIR}\${name}\dist\${name}-${version}.tar"
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}\bootloader"
    & $python ./waf distclean all
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}"
    & $python setup.py install
    Set-Location -Path "${START_DIR}"
}

Function InstallPythonModuleZip($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.zip
    Set-Location -Path "${START_DIR}\${name}\${name}-${version}"
    & $python setup.py install
    Set-Location -Path "${START_DIR}"
}

Function InstallPythonModuleWheel($pip, $name, $version) {
    Set-Location -Path "${START_DIR}\packaging\ext"
    & $pip install ${name}_wheel-${version}-py3-none-any.whl
    Set-Location -Path "${START_DIR}"
}

Function InstallPythonModuleBin($python, $name, $version) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\${name} ) { Remove-Item .\${name} -Recurse -Force }
    New-Item -ItemType directory -Path "${START_DIR}\${name}"
    & 7z x -y "-o${name}" .\packaging\ext\${name}-${version}.exe
    Set-Location -Path "${START_DIR}\${name}"
    Copy-Item "${START_DIR}\${name}\PLATLIB\*"  "$HOME\appdata\local\programs\python\python310\Lib\site-packages" -Recurse -Force
    Set-Location -Path "${START_DIR}"
}

Function InstallUPX() {
    Set-Location -Path "${START_DIR}"
    if( Test-Path .\upx ) { Remove-Item .\upx -Recurse -Force }
    & 7z e -y "-oupx" .\packaging\ext\upx394w.zip
    Set-Location -Path "${START_DIR}\upx"
    Copy-Item "${START_DIR}\upx\upx.exe"  "${START_DIR}\src" -Recurse -Force
    Set-Location -Path "${START_DIR}"
}

InstallPythonModule "$PYTHON_AMD64" "setuptools" "63.1.0"
InstallPythonModule "$PYTHON_AMD64" "pip" "22.3.1"
InstallPythonModule "$PYTHON_AMD64" "wheel" "0.38.4"
Set-Location -Path "${START_DIR}\packaging\ext"
& $PIP_AMD64 install jsonpointer-2.3.tar.gz
& $PIP_AMD64 install python-dotenv-0.21.0.tar.gz
& $PIP_AMD64 install six-1.16.0.tar.gz
& $PIP_AMD64 install ply-3.11.tar.gz
& $PIP_AMD64 install future-0.18.2.tar.gz
& $PIP_AMD64 install altgraph-0.17.3.tar.gz
& $PIP_AMD64 install decorator-5.1.1.tar.gz
& $PIP_AMD64 install jsonpatch-1.32.tar.gz
& $PIP_AMD64 install jsonpath-rw-1.4.0.tar.gz
& $PIP_AMD64 install jsondiff-2.0.0.tar.gz
& $PIP_AMD64 install pyaes-1.6.1.tar.gz
& $PIP_AMD64 install urllib3-1.26.12.tar.gz
& $PIP_AMD64 install colorama-0.4.4.tar.gz
& $PIP_AMD64 install tabulate-0.8.9.tar.gz
& $PIP_AMD64 install wcwidth-0.2.5.tar.gz
& $PIP_AMD64 install pefile-2022.5.30.tar.gz
& $PIP_AMD64 install prompt_toolkit-3.0.36.tar.gz
& $PIP_AMD64 install pywin32-ctypes-0.2.0.tar.gz
& $PIP_AMD64 install certifi-2022.12.7.tar.gz
& $PIP_AMD64 install pywin32-ctypes-0.2.0.tar.gz
& $PIP_AMD64 install requests-2.28.1.tar.gz
& $PIP_AMD64 install pypiwin32-223.tar.gz
& $PIP_AMD64 install pywin32-305-cp310-cp310-win_amd64.whl
& $PIP_AMD64 install pyinstaller-hooks-contrib-2022.10.tar.gz
& $PIP_AMD64 install pyinstaller-5.7.0.tar.gz
Set-Location -Path "${START_DIR}"
Copy-Item "$Env:MTX_STAGING_PATH\externals\*.zip" "${START_DIR}\packaging\ext"
InstallPythonModuleZip "$PYTHON_AMD64" "python-ilorest-library" "$Env:MX_ILOREST_LIB_VERSION"
Set-Location -Path $START_DIR

Function CreateMSI($python, $pyinstaller, $pythondir, $arch) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path $START_DIR\dist ) { Remove-Item $START_DIR\dist -Recurse -Force }
    if( Test-Path $START_DIR\build ) { Remove-Item $START_DIR\build -Recurse -Force }
    Set-Location -Path $START_DIR

    $DOUBLE_START_DIR =  $START_DIR.replace("\", "\\")
    $DOUBLE_PYTHONDIR =  $pythondir.replace("\", "\\")

    cat win32\rdmc-pyinstaller.spec.in | %{$_ -replace '\$pwd',"${DOUBLE_START_DIR}" } | %{$_ -replace '\$pythondir',"${DOUBLE_PYTHONDIR}" } > rdmc-pyinstaller.spec

    # kill the BOM (stupid powershell)
    $MyFile = Get-Content "${START_DIR}\rdmc-pyinstaller.spec"
    $Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding($False)
    [System.IO.File]::WriteAllLines("${START_DIR}\rdmc-pyinstaller.spec", $MyFile, $Utf8NoBomEncoding)

    Set-Location -Path "${START_DIR}\src"
    & $pyinstaller $START_DIR\rdmc-pyinstaller.spec
    perl C:\ABSbuild\CodeSigning\SignFile.pl "${START_DIR}\src\dist\ilorest.exe"
    Copy-Item "${START_DIR}\src\dist\ilorest.exe" "${START_DIR}\ilorest.exe"
    Copy-Item "$Env:MTX_STAGING_PATH\externals\*.dll" "${START_DIR}\src\dist\"
    Copy-Item "${START_DIR}\packaging\packages\*.dll" "${START_DIR}\src\dist\"
    Copy-Item "${START_DIR}\rdmc-windows.conf" "${START_DIR}\src\dist\redfish.conf"
    Copy-Item "${START_DIR}\src\dist" "${START_DIR}" -Recurse -Force

    Set-Location -Path "${START_DIR}"
    $product_version

    cat win32\rdmc.${arch}.wxs | %{$_ -replace '\$product_version',"${product_version}" } > rdmc.wxs
    & c:\ABSbuild\WiX36\candle.exe "-dsrcFolder=$(get-location)" rdmc.wxs
    & c:\ABSbuild\WiX36\light.exe -b $(get-location) rdmc.wixobj -ext WixUIExtension  -out "ilorest-${product_version}-${build_number}.${arch}.msi"

    if ("$Env:MTX_COLLECTION_PATH") {
        & perl C:\ABSbuild\CodeSigning\SignFile.pl "ilorest-${product_version}-${build_number}.${arch}.msi"
        Copy-Item "ilorest-${product_version}-${build_number}.${arch}.msi" "$Env:MTX_COLLECTION_PATH"
    }
    Set-Location -Path "${START_DIR}"
}

Set-Location -Path "${START_DIR}"
CreateMSI "$PYTHON_AMD64" "$PYINST_AMD64" "$HOME\appdata\local\programs\python\python310" "x86_64"
