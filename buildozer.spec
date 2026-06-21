[app]

# Application metadata
title = TizenCommander
package.name = tizencommander
package.domain = org.tizencommander
version = 1.0.0

# Application source
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt,json,xml

# Version tracking
version.regex = __version__ = ['\"](.*)['\"]
version.filename = %(source.dir)s/main.py

# Requirements
# python3: Core Python runtime
# flet: UI framework
# requests: HTTP library for binary downloads
requirements = python3,flet,requests

# Architecture and platform settings
[buildozer]
log_level = 2
warn_on_root = 1

# ============================================================================
# ANDROID-SPECIFIC CONFIGURATION
# ============================================================================

[app:android]

# Target Android version and architecture
android.api = 35                          # Android 15 (latest stable)
android.minapi = 21                       # Minimum Android 5.0
android.ndk = 27b                         # NDK version
android.arch = arm64-v8a                  # 64-bit ARM architecture

# Android permissions required for TizenCommander
# INTERNET: Network connectivity for SDB protocol (port 26101)
# READ_EXTERNAL_STORAGE: Access to app files for installation
# WRITE_EXTERNAL_STORAGE: Temporary storage for downloads
# REQUEST_INSTALL_PACKAGES: Necessary for sideloading management
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,REQUEST_INSTALL_PACKAGES

# Features (optional but recommended)
android.features = android.hardware.usb.host

# Orientation
android.orientation = portrait
android.window = normal
android.fullscreen = 0

# Application icon and presplash (optional)
android.icon = assets/icon.png
android.presplash = assets/presplash.png

# Gradle configuration
android.gradle_dependencies = 

# Android manifest additions
android.add_src = 

# Assets to include in APK
# Include the SDB binary here if you want it bundled in the APK
android.add_assets = assets/bin/sdb

# gradle_options configuration
android.gradle_options = org.gradle.jvmargs=-Xmx4096m

# Google Play Console configuration (optional)
android.logcat_filters = *:S python:D

# Release configuration (for signed APK)
android.release_artifact = apk
android.release_artifact = bundle

# Application is debuggable (set to 0 for release builds)
android.debuggable = 1

# Custom Java code (optional)
android.add_src = 

# ============================================================================
# BUILD CONFIGURATION
# ============================================================================

[buildozer:build]

# Build directory
build_dir = .buildozer
bin_dir = ./bin

# Use cached builds
use_old_toolchain = 0

# Verbose output
log_level = 2

# ============================================================================
# PYTHON-SPECIFIC SETTINGS
# ============================================================================

[app:python]

# Main entry point
source.dir = .
main = main

# Python version
python_version = 3.11

# Cython optimization
cython_directives = language_level=3,binding=True,boundscheck=False

# Include patterns
requirements.txt_python_version = python3.11

# ============================================================================
# COMPILATION FLAGS
# ============================================================================

[buildozer:compile]

# Compiler optimization level
optimization_level = 2

# Strip symbols (reduces APK size)
strip_debug = 0

# Crypto support (not needed for this app)
use_openssl = 0
use_sqlite = 0

# ============================================================================
# DEPLOYMENT NOTES
# ============================================================================

# To build this APK:
# 1. Install buildozer: pip install buildozer
# 2. Install dependencies: sudo apt-get install default-jdk android-sdk-build-tools
# 3. Set ANDROID_SDK_ROOT and ANDROID_NDK_ROOT environment variables
# 4. Run: buildozer android debug
# 5. Output APK will be in bin/
#
# For GitHub Actions CI/CD:
# See .github/workflows/build_apk.yml for automated builds
#
# Testing on Android:
# adb install -r bin/tizencommander-1.0-debug.apk
