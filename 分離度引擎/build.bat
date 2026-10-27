@echo off
rem Build the separation VST2 plugin (64-bit, static CRT)
cd /d "%~dp0"
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /O2 /fp:fast /MT /LD /EHsc /utf-8 sep.cpp /Fe:sep_v1.dll /link /NOLOGO
del sep.obj sep_v1.exp sep_v1.lib 2>nul
