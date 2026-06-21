[app]
# Application metadata
title = TizenCommander
package.name = tizencommander
package.domain = org.tizencommander
version = 1.0.0
# Entry point (module:callable or filename without .py)
# buildozer expects the module name (main -> main.py)
# If your main entry is different, aggiorna questa riga.
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt,json,xml
# Main module (without .py)
# If main.py contains if __name__ == '__main__': main(), keep as 'main'
entrypoint = main

# Requirements (Python packages)
requirements = python3,flet,requests,pexpect,cython

# (Optional) Additional Python packages to compile with native extensions:
# garden packages, kivy deps, etc. Add here only what you need.

# -----------------------------------------------------------------------------
[buildozer]
log_level = 2
warn_on_root = 1

# -----------------------------------------------------------------------------
# ANDROID-SPECIFIC CONFIGURATION
# -----------------------------------------------------------------------------
[app:android]
# Android API and NDK
android.api = 35
android.minapi = 21
# NDK version string (buildozer expects the format used by your toolchain)
android.ndk = 27b

# Architectures to build for. Multiple separated by comma.
# arm64-v8a is preferred for modern devices; include armeabi-v7a for compat if needed.
android.arch = arm64-v8a,armeabi-v7a

# Permissions (adjust as minimum required)
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,REQUEST_INSTALL_PACKAGES

# Optional features
android.features = android.hardware.usb.host

# UI / orientation
android.orientation = portrait
android.window = normal
android.fullscreen = 0

# Icons / presplash (put files under assets/)
android.icon = assets/icon.png
android.presplash = assets/presplash.png

# Assets to include in the APK (e.g., SDB binary placeholder)
android.add_assets = assets/bin/sdb

# Debug / release artifact
# Choose one: apk (debug or release) or bundle. We keep apk for CI/debug builds.
android.release_artifact = apk

# Make the app debuggable for CI debug builds; set to 0 for release artifacts
android.debuggable = 1

# Gradle options (tune memory if build fails on runner)
android.gradle_options = org.gradle.jvmargs=-Xmx4096m

# -----------------------------------------------------------------------------
# BUILD SETTINGS
# -----------------------------------------------------------------------------
[buildozer:build]
build_dir = .buildozer
bin_dir = ./bin
use_old_toolchain = 0
log_level = 2

# -----------------------------------------------------------------------------
# PYTHON-SPECIFIC SETTINGS
# -----------------------------------------------------------------------------
[app:python]
source.dir = .
main = main
python_version = 3.11
cython_directives = language_level=3,binding=True,boundscheck=False

# -----------------------------------------------------------------------------
# COMPILATION FLAGS
# -----------------------------------------------------------------------------
[buildozer:compile]
optimization_level = 2
strip_debug = 0
use_openssl = 0
use_sqlite = 0

# -----------------------------------------------------------------------------
# NOTES
# - If you prefer to produce an Android App Bundle (.aab), change
#   android.release_artifact = bundle
# - If you bundle the SDB binary, ensure assets/bin/sdb is executable (chmod 755)
# - Update SDB_SHA256_EXPECTED in main.py with the real SHA-256 if you verify it at runtime
# -----------------------------------------------------------------------------