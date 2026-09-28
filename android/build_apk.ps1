# 做出手機版 APK（不用 Gradle）：gen_data.py -> aapt2 -> javac -> d8 -> zipalign -> apksigner。
# 需要 JDK 17 和 Android SDK（build-tools 35.0.0、platforms android-35），放在 <Tools>\jdk-17*\ 和 <Tools>\sdk\，
# 或自己設定 JAVA_HOME / ANDROID_HOME。
# 簽章：第一次建置會產生 android\release.keystore 和隨機密碼 android\signing.txt（都不會上傳 GitHub）。
#   一定要留著：手機只接受同一把鑰匙簽的更新版。
# 用法：powershell -ExecutionPolicy Bypass -File android\build_apk.ps1 -VersionCode 1 -VersionName 1.4.0
param(
    [int]$VersionCode = 1,
    [string]$VersionName = "1.0",
    [string]$Tools = (Join-Path $HOME "AndroidBuild")
)
$ErrorActionPreference = "Stop"

if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME\bin\javac.exe")) {
    $env:JAVA_HOME = (Get-ChildItem "$Tools\jdk-*" -Directory -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
}
if (-not $env:JAVA_HOME) { throw "JDK 17 not found: set JAVA_HOME or put it in $Tools\jdk-17..." }
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
$Sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$Tools\sdk" }
$BT = "$Sdk\build-tools\35.0.0"
$Jar = "$Sdk\platforms\android-35\android.jar"
if (-not (Test-Path $Jar)) { throw "Android SDK not found: $Jar" }

$Src = $PSScriptRoot
$Root = Split-Path $Src -Parent
# aapt2 讀不了中文路徑（專案資料夾叫「耳機調音台通用版」）→ 先複製到暫存的英文路徑再建置
$A = Join-Path $env:TEMP "hptuner-android"
if (Test-Path $A) { Remove-Item $A -Recurse -Force }
New-Item -ItemType Directory -Force $A | Out-Null
$Out = Join-Path $A "build"
New-Item -ItemType Directory -Force "$Out\gen", "$Out\classes", "$Out\dex" | Out-Null

function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "failed: $exe" }
}

Write-Host "0/6 data (from the PC version)"
Run "python" @("$Src\gen_data.py")
foreach ($d in "res", "assets", "src") { Copy-Item "$Src\$d" "$A\$d" -Recurse }
Copy-Item "$Src\AndroidManifest.xml" "$A\AndroidManifest.xml"

Write-Host "1/6 resources"
Run "$BT\aapt2.exe" @("compile", "--dir", "$A\res", "-o", "$Out\res.zip")
Run "$BT\aapt2.exe" @("link", "-I", $Jar, "--manifest", "$A\AndroidManifest.xml", "--java", "$Out\gen", "-A", "$A\assets",
    "--min-sdk-version", "29", "--target-sdk-version", "34",
    "--version-code", "$VersionCode", "--version-name", $VersionName,
    "-o", "$Out\unsigned.apk", "$Out\res.zip")

Write-Host "2/6 javac"
$javaFiles = Get-ChildItem "$A\src", "$Out\gen" -Recurse -Filter *.java | ForEach-Object { $_.FullName }
Run "javac" (@("-nowarn", "-Xlint:-options", "-encoding", "UTF-8", "--release", "8", "-classpath", $Jar, "-d", "$Out\classes") + $javaFiles)

Write-Host "3/6 d8"
$classes = Get-ChildItem "$Out\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName }
Run "$BT\d8.bat" (@("--release", "--min-api", "29", "--lib", $Jar, "--output", "$Out\dex") + $classes)

Write-Host "4/6 add classes.dex"
python -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'a',zipfile.ZIP_DEFLATED); z.write(sys.argv[2],'classes.dex'); z.close()" "$Out\unsigned.apk" "$Out\dex\classes.dex"
if ($LASTEXITCODE -ne 0) { throw "zip failed" }

Write-Host "5/6 zipalign"
Run "$BT\zipalign.exe" @("-p", "-f", "4", "$Out\unsigned.apk", "$Out\aligned.apk")

Write-Host "6/6 sign"
$ks = Join-Path $Src "release.keystore"
$pwFile = Join-Path $Src "signing.txt"
if (-not (Test-Path $ks)) {
    $pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Set-Content -Path $pwFile -Value $pw -Encoding ascii
    Run "keytool" @("-genkeypair", "-keystore", $ks, "-alias", "headphonetuner", "-keyalg", "RSA", "-keysize", "2048",
        "-validity", "36500", "-storepass", $pw, "-keypass", $pw, "-dname", "CN=HeadphoneTuner")
}
$pw = (Get-Content $pwFile -Raw).Trim()
$dist = Join-Path $Root "installer\dist"
New-Item -ItemType Directory -Force $dist | Out-Null
$apk = Join-Path $dist "HeadphoneTuner-Android-v$VersionName.apk"
Run "$BT\apksigner.bat" @("sign", "--ks", $ks, "--ks-pass", "pass:$pw", "--key-pass", "pass:$pw", "--out", $apk, "$Out\aligned.apk")
Write-Host ("OK: {0} ({1:N0} KB)" -f $apk, ((Get-Item $apk).Length / 1KB))
