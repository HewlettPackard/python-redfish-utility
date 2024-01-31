
$START_DIR = "$(get-location)"
$product_version = $Env:MTX_PRODUCT_VERSION
if (!"$product_version") {
    $product_version = "9.9.9.9"
}

$build_number = $Env:MTX_BUILD_NUMBER
if (!"$build_number") {
    $build_number = "999"
}

Set-Location -Path "${START_DIR}"

$PYTHON_BASE="${START_DIR}\python310"
$PYTHONPATH="${START_DIR}\python310"
$PYTHON="${PYTHON_BASE}\python.exe"
$PIP="${PYTHON_BASE}\Scripts\pip.exe"
$PYINSTALLER="${PYTHON} -m PyInstaller"
$SIGNER="C:\Program Files\HPE\signing\signinghelper.exe"

Set-Location -Path "${START_DIR}"
if( Test-Path .\python310 ) { Remove-Item .\python310 -Recurse -Force }
New-Item -ItemType directory -Path .\python310

& 7z x -y -opython310 .\packaging\python3\windows\Python310.zip

Get-ChildItem -Path ${PYTHON_BASE}

# Add FIPS requirements
# Add ssl, _ssl, and _hashlib which point to morpheus project OPENSSL
Copy-Item "${START_DIR}\packaging\python3\windows\*.pyd" "$PYTHON_BASE\DLLs" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\ssl.py" "$PYTHON_BASE\Lib" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\*.DLL" "$PYTHON_BASE\DLLs" -Recurse -Force
Copy-Item "${START_DIR}\packaging\python3\windows\*.cnf" "$PYTHON_BASE\DLLs" -Recurse -Force

#& ${PIP} -V
Set-Location -Path $START_DIR

Copy-Item "${START_DIR}\packaging\python3\windows\print_ssl_version.py"  "$(get-location)" -Recurse -Force
& ${PYTHON} print_ssl_version.py

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

Function InstallPythonModulePIP($pip, $name, $version) {
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
    & $pip install .
    Set-Location -Path "${START_DIR}"
}

Copy-Item "$Env:MTX_STAGING_PATH\externals\*.zip" "${START_DIR}\packaging\ext"
InstallPythonModuleZip "${PYTHON}" "python-ilorest-library" "$Env:MX_ILOREST_LIB_VERSION"
InstallPythonModulePIP "${PIP}" "pyinstaller" "5.7.0"
#InstallPythonModule "${PYTHON}" "pyinstaller" "5.7.0"
#Set-Location -Path "${START_DIR}\packaging\ext"
#& ${PIP} install pyinstaller-5.7.0.tar.gz
Set-Location -Path "${START_DIR}"

Function CreateMSI($python, $pyinstaller, $pythondir, $arch) {
    Set-Location -Path "${START_DIR}"
    if( Test-Path $START_DIR\dist ) { Remove-Item $START_DIR\dist -Recurse -Force }
    if( Test-Path $START_DIR\build ) { Remove-Item $START_DIR\build -Recurse -Force }
    Set-Location -Path "${START_DIR}"

    $DOUBLE_START_DIR =  $START_DIR.replace("\", "\\")
    $DOUBLE_PYTHONDIR =  $pythondir.replace("\", "\\")

    cat win32\rdmc-pyinstaller.spec.in | %{$_ -replace '\$pwd',"${DOUBLE_START_DIR}" } | %{$_ -replace '\$pythondir',"${DOUBLE_PYTHONDIR}" } > rdmc-pyinstaller.spec

    # kill the BOM (stupid powershell)
    $MyFile = Get-Content "${START_DIR}\rdmc-pyinstaller.spec"
    $Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding($False)
    [System.IO.File]::WriteAllLines("${START_DIR}\rdmc-pyinstaller.spec", $MyFile, $Utf8NoBomEncoding)

    Write-Host "PyInstaller Begin"

    Set-Location -Path "${START_DIR}\ilorest"
    & ${PYTHON} -m PyInstaller --clean --log-level DEBUG "${START_DIR}\rdmc-pyinstaller.spec"

    Write-Host "PyInstaller END"

   & ${SIGNER} -i "${START_DIR}\ilorest\dist\ilorest.exe" -o $Env:MTX_COLLECTION_PATH -p $Env:MX_SIGN_PROJECT
    Copy-Item "$Env:MTX_COLLECTION_PATH\ilorest.exe" "${START_DIR}\ilorest\dist\"
    Copy-Item "$Env:MTX_STAGING_PATH\externals\ilorest_chif.dll" "${START_DIR}\ilorest\dist\"

    #& ${SIGNER} -i "${START_DIR}\ilorest\dist\ilorest_chif.dll" -o $Env:MTX_COLLECTION_PATH -p $Env:MX_SIGN_PROJECT
    #Copy-Item "${START_DIR}\packaging\packages\*.dll" "${START_DIR}\ilorest\dist\"
    Copy-Item "${START_DIR}\rdmc-windows.conf" "${START_DIR}\ilorest\dist\redfish.conf"
    Copy-Item "${START_DIR}\ilorest\dist" "${START_DIR}" -Recurse -Force


    Set-Location -Path "${START_DIR}"
    $product_version

    cat win32\rdmc.${arch}.wxs | %{$_ -replace '\$product_version',"${product_version}" } > rdmc.wxs
    & c:\ABSbuild\WiX36\candle.exe "-dsrcFolder=$(get-location)" rdmc.wxs
    & c:\ABSbuild\WiX36\light.exe -b $(get-location) rdmc.wixobj -ext WixUIExtension -ext WixUtilExtension.dll -out "ilorest-${product_version}-${build_number}.${arch}.msi"

    if ("$Env:MTX_COLLECTION_PATH") {
        & ${SIGNER} -i "ilorest-${product_version}-${build_number}.${arch}.msi" -o $Env:MTX_COLLECTION_PATH -p $Env:MX_SIGN_PROJECT -a="-noextract -r noappend"
        #Copy-Item "ilorest-${product_version}-${build_number}.${arch}.msi" "$Env:MTX_COLLECTION_PATH"
        Remove-Item $Env:MTX_COLLECTION_PATH\ilorest.exe
        Remove-Item $Env:MTX_COLLECTION_PATH\ilorest_chif.dll
    }
    Set-Location -Path "${START_DIR}"
}

Set-Location -Path "${START_DIR}"
#Copy-Item "${START_DIR}\pywin32amd64\PLATLIB\pywin32_system32\*" .
CreateMSI "${PYTHON}" "${PYINSTALLER}" "${PYTHON_BASE}" "x86_64"
