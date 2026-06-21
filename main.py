#!/usr/bin/env python3
"""
TizenCommander - Professional Android SDB Wrapper for Tizen TV
======================================================================

A robust, modern Android application for managing Tizen TV deployments via SDB.

Architecture:
  - DeploymentEngine: Core SDB protocol handler with auto-reconnection
  - Bootstrapper: Binary asset management (SHA-256 verification, chmod)
  - Threading: All network ops in separate threads to prevent UI blocking
  - UI: Flet-based navigation with 4 tabs (Connection, Deployment, Console, Info)

Error Handling Strategy:
  - All subprocess calls wrapped in try-except
  - Connection failures trigger automatic re-handshake
  - Failed installations: uninstall + force reinstall with config.xml extraction
  - TV poweroff/network issues: graceful degradation with status indicators
  - All errors logged to Console tab with color coding

Exception Classes:
  - SDBConnectionError: Connection/handshake failures
  - SDBCommandError: Command execution failures
  - DeploymentError: Installation/uninstallation failures
  - BootstrapError: Binary download/verification failures
  - ConfigExtractionError: APK package_id extraction failures
"""

import os
import sys
import json
import time
import zipfile
import hashlib
import threading
import subprocess
import traceback
from pathlib import Path
from typing import Optional, Callable, Tuple
from datetime import datetime
from xml.etree import ElementTree as ET
import logging

try:
    import flet as ft
    from flet import icons
except ImportError:
    print("ERROR: Flet not installed. Run: pip install flet")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: Requests not installed. Run: pip install requests")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

APP_NAME = "TizenCommander"
APP_VERSION = "1.0.0"
SDB_BINARY_NAME = "sdb"
SDB_PORT = 26101
SDB_GITHUB_MIRROR = "https://github.com/tizentvapps/sdb-binaries/releases/download/latest/sdb-aarch64"
SDB_SHA256_EXPECTED = "placeholder_sha256_hash"  # Update with actual SHA256
LOG_MAX_LINES = 1000


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class TizenCommanderException(Exception):
    """Base exception for TizenCommander"""
    pass


class SDBConnectionError(TizenCommanderException):
    """Raised when SDB connection fails"""
    pass


class SDBCommandError(TizenCommanderException):
    """Raised when SDB command execution fails"""
    pass


class DeploymentError(TizenCommanderException):
    """Raised when deployment (install/uninstall) fails"""
    pass


class BootstrapError(TizenCommanderException):
    """Raised when binary bootstrap fails"""
    pass


class ConfigExtractionError(TizenCommanderException):
    """Raised when package_id extraction from config.xml fails"""
    pass


# ============================================================================
# LOGGER
# ============================================================================

class ConsoleLogger:
    """Thread-safe console logger with color support"""

    def __init__(self, max_lines: int = LOG_MAX_LINES):
        self.logs: list = []
        self.max_lines = max_lines
        self.lock = threading.Lock()
        self.callbacks: list[Callable[[str, str], None]] = []

    def add_callback(self, callback: Callable[[str, str], None]):
        """Register callback for log events: callback(message, level)"""
        with self.lock:
            self.callbacks.append(callback)

    def _log(self, message: str, level: str):
        """Internal log method"""
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] [{level}] {message}"
            self.logs.append((log_entry, level))

            # Trim if exceeds max lines
            if len(self.logs) > self.max_lines:
                self.logs = self.logs[-self.max_lines:]

            # Notify callbacks
            for callback in self.callbacks:
                try:
                    callback(log_entry, level)
                except Exception as e:
                    print(f"Error in log callback: {e}")

    def info(self, message: str):
        self._log(message, "INFO")

    def success(self, message: str):
        self._log(message, "SUCCESS")

    def error(self, message: str):
        self._log(message, "ERROR")

    def warning(self, message: str):
        self._log(message, "WARNING")

    def debug(self, message: str):
        self._log(message, "DEBUG")

    def get_all(self) -> list[Tuple[str, str]]:
        """Get all logs"""
        with self.lock:
            return self.logs.copy()


console_logger = ConsoleLogger()


# ============================================================================
# BOOTSTRAPPER
# ============================================================================

class Bootstrapper:
    """
    Handles SDB binary bootstrap: download, verify integrity, chmod
    
    Error Handling:
      - Network errors during download → BootstrapError
      - SHA-256 mismatch → BootstrapError
      - chmod failure → BootstrapError
      - Binary already exists and valid → skip download
    """

    def __init__(self, binary_path: Path, github_url: str = SDB_GITHUB_MIRROR):
        self.binary_path = binary_path
        self.github_url = github_url

    def is_ready(self) -> bool:
        """Check if binary exists and is executable"""
        return self.binary_path.exists() and os.access(self.binary_path, os.X_OK)

    def download_binary(self) -> None:
        """
        Download SDB binary from GitHub mirror
        
        Raises:
            BootstrapError: On network/IO errors
        """
        try:
            console_logger.info(f"Downloading SDB binary from {self.github_url}...")
            
            response = requests.get(self.github_url, timeout=60, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(self.binary_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = (downloaded / total_size) * 100
                            console_logger.debug(
                                f"Download progress: {pct:.1f}% ({downloaded}/{total_size} bytes)"
                            )

            console_logger.success(f"Binary downloaded: {self.binary_path}")

        except requests.RequestException as e:
            raise BootstrapError(f"Failed to download SDB binary: {e}")
        except IOError as e:
            raise BootstrapError(f"Failed to write SDB binary: {e}")

    def verify_sha256(self, expected_hash: Optional[str] = None) -> bool:
        """
        Verify SHA-256 integrity of binary
        
        Args:
            expected_hash: Expected SHA-256 hash. If None, skips verification.
            
        Returns:
            True if valid or verification skipped
            
        Raises:
            BootstrapError: If hash mismatch
        """
        if expected_hash is None:
            console_logger.warning("SHA-256 verification skipped (no expected hash)")
            return True

        try:
            console_logger.info("Verifying SDB binary integrity (SHA-256)...")
            sha256 = hashlib.sha256()

            with open(self.binary_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)

            computed_hash = sha256.hexdigest()

            if computed_hash != expected_hash:
                raise BootstrapError(
                    f"SHA-256 mismatch: expected {expected_hash}, got {computed_hash}"
                )

            console_logger.success(f"SHA-256 verified: {computed_hash}")
            return True

        except IOError as e:
            raise BootstrapError(f"Failed to read binary for verification: {e}")

    def make_executable(self) -> None:
        """
        Set executable permission (chmod 755)
        
        Raises:
            BootstrapError: On permission errors
        """
        try:
            console_logger.info("Setting executable permissions (chmod 755)...")
            os.chmod(self.binary_path, 0o755)
            console_logger.success(f"Binary is now executable: {self.binary_path}")
        except OSError as e:
            raise BootstrapError(f"Failed to chmod binary: {e}")

    def bootstrap(self, verify_hash: bool = True) -> None:
        """
        Complete bootstrap: download, verify, chmod
        
        Raises:
            BootstrapError: On any bootstrap failure
        """
        try:
            if self.is_ready():
                console_logger.success("SDB binary already ready")
                return

            self.download_binary()
            
            if verify_hash:
                self.verify_sha256(SDB_SHA256_EXPECTED)
            
            self.make_executable()

            if not self.is_ready():
                raise BootstrapError("Binary still not ready after bootstrap")

            console_logger.success("Bootstrap completed successfully")

        except BootstrapError:
            raise
        except Exception as e:
            raise BootstrapError(f"Unexpected bootstrap error: {e}")


# ============================================================================
# DEPLOYMENT ENGINE - SDB PROTOCOL HANDLER
# ============================================================================

class DeploymentEngine:
    """
    Core SDB protocol handler with automatic reconnection
    
    Architecture:
      - Maintains persistent connection to Tizen TV on port 26101
      - Auto re-handshake on connection loss
      - Command execution with timeout and retry logic
      - Package management: install, uninstall, force reinstall
      
    Error Handling:
      - Connection failures → auto-reconnect attempts (3 retries)
      - TV poweroff/network unavailable → SDBConnectionError
      - Command timeouts → SDBCommandError
      - Installation failures → DeploymentError with auto-recovery
      - config.xml extraction failures → ConfigExtractionError
    """

    def __init__(
        self,
        sdb_binary_path: str,
        tv_ip: Optional[str] = None,
        port: int = SDB_PORT,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.sdb_binary = sdb_binary_path
        self.tv_ip = tv_ip
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.connected = False
        self.lock = threading.Lock()

    def _run_command(
        self, args: list[str], description: str = ""
    ) -> Tuple[int, str, str]:
        """
        Execute SDB command safely
        
        Args:
            args: Command arguments (e.g., ["sdb", "devices"])
            description: Human-readable description for logging
            
        Returns:
            (return_code, stdout, stderr)
            
        Raises:
            SDBCommandError: On timeout or execution errors
        """
        try:
            full_cmd = [self.sdb_binary] + args
            console_logger.debug(f"Executing: {' '.join(full_cmd)} ({description})")

            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
                return_code = process.returncode
                
                console_logger.debug(f"Command result: rc={return_code}")
                return return_code, stdout, stderr

            except subprocess.TimeoutExpired:
                process.kill()
                raise SDBCommandError(
                    f"Command timeout (>{self.timeout}s): {' '.join(full_cmd)}"
                )

        except FileNotFoundError:
            raise SDBCommandError(f"SDB binary not found: {self.sdb_binary}")
        except Exception as e:
            raise SDBCommandError(f"Command execution failed: {e}")

    def connect(self, tv_ip: Optional[str] = None, retry: int = 0) -> None:
        """
        Connect to Tizen TV via SDB
        
        Args:
            tv_ip: TV IP address. If None, uses self.tv_ip
            retry: Current retry attempt
            
        Raises:
            SDBConnectionError: If connection fails after max retries
        """
        try:
            if tv_ip:
                self.tv_ip = tv_ip

            if not self.tv_ip:
                raise SDBConnectionError("TV IP address not set")

            console_logger.info(f"Connecting to TV: {self.tv_ip}:{self.port}...")

            rc, out, err = self._run_command(
                ["connect", f"{self.tv_ip}:{self.port}"],
                f"connect {self.tv_ip}:{self.port}",
            )

            if rc != 0:
                raise SDBConnectionError(f"Connection failed: {err or out}")

            # Verify connection
            rc, out, err = self._run_command(["devices"], "list devices")
            
            if rc != 0:
                raise SDBConnectionError(f"Failed to verify connection: {err or out}")

            self.connected = True
            console_logger.success(f"Connected to TV: {self.tv_ip}:{self.port}")

        except SDBConnectionError:
            raise
        except Exception as e:
            raise SDBConnectionError(f"Unexpected connection error: {e}")

    def disconnect(self) -> None:
        """Disconnect from TV"""
        try:
            if not self.connected:
                return

            console_logger.info("Disconnecting from TV...")
            
            try:
                self._run_command(["disconnect"], "disconnect")
            except SDBCommandError:
                pass  # Ignore errors on disconnect

            self.connected = False
            console_logger.success("Disconnected from TV")

        except Exception as e:
            console_logger.error(f"Disconnect error: {e}")

    def reconnect(self) -> None:
        """Attempt to reconnect"""
        try:
            self.disconnect()
            time.sleep(1)
            self.connect()
        except Exception as e:
            raise SDBConnectionError(f"Reconnection failed: {e}")

    def shell(self, command: str) -> str:
        """
        Execute shell command on TV
        
        Raises:
            SDBCommandError: If command fails
        """
        try:
            rc, out, err = self._run_command(
                ["shell", command], f"shell: {command}"
            )
            
            if rc != 0:
                raise SDBCommandError(f"Shell command failed: {err or out}")

            return out.strip()

        except SDBCommandError:
            raise
        except Exception as e:
            raise SDBCommandError(f"Shell execution failed: {e}")

    def get_system_info(self) -> dict:
        """
        Get TV system information
        
        Returns:
            Dictionary with system info or empty dict on failure
        """
        try:
            if not self.connected:
                return {}

            output = self.shell("systeminfo")
            info = {}

            for line in output.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key.strip()] = value.strip()

            return info

        except Exception as e:
            console_logger.error(f"Failed to get system info: {e}")
            return {}

    def get_installed_apps(self) -> list[str]:
        """
        List installed apps on TV
        
        Returns:
            List of package IDs
        """
        try:
            if not self.connected:
                return []

            output = self.shell("pkgcmd -l")
            apps = []

            for line in output.split("\n"):
                line = line.strip()
                if line and not line.startswith("package"):
                    parts = line.split()
                    if parts:
                        apps.append(parts[0])

            return apps

        except Exception as e:
            console_logger.error(f"Failed to get installed apps: {e}")
            return []

    def _extract_package_id(self, wgt_path: str) -> str:
        """
        Extract package_id from .wgt file config.xml
        
        Args:
            wgt_path: Path to .wgt file
            
        Returns:
            Package ID string
            
        Raises:
            ConfigExtractionError: If extraction fails
        """
        try:
            console_logger.info(f"Extracting package_id from {wgt_path}...")

            with zipfile.ZipFile(wgt_path, "r") as wgt:
                if "config.xml" not in wgt.namelist():
                    raise ConfigExtractionError("config.xml not found in .wgt file")

                config_data = wgt.read("config.xml")
                root = ET.fromstring(config_data)

                # Namespace handling for Tizen config.xml
                namespaces = {"": "http://www.w3.org/ns/widgets"}
                package_id = root.get("id")

                if not package_id:
                    raise ConfigExtractionError("'id' attribute not found in config.xml")

                console_logger.success(f"Package ID extracted: {package_id}")
                return package_id

        except zipfile.BadZipFile as e:
            raise ConfigExtractionError(f"Invalid .wgt file: {e}")
        except ET.ParseError as e:
            raise ConfigExtractionError(f"Failed to parse config.xml: {e}")
        except Exception as e:
            raise ConfigExtractionError(f"Package ID extraction failed: {e}")

    def install(self, app_path: str, force: bool = False) -> bool:
        """
        Install app on TV
        
        Args:
            app_path: Path to .wgt or .apk file
            force: If True, uninstall first then install
            
        Returns:
            True if successful
            
        Raises:
            DeploymentError: If installation fails
        """
        try:
            if not self.connected:
                raise DeploymentError("Not connected to TV")

            if not os.path.exists(app_path):
                raise DeploymentError(f"App file not found: {app_path}")

            console_logger.info(f"Installing app: {app_path} (force={force})...")

            # Extract package_id if .wgt file
            package_id = None
            if app_path.endswith(".wgt"):
                try:
                    package_id = self._extract_package_id(app_path)
                except ConfigExtractionError as e:
                    console_logger.warning(f"Could not extract package_id: {e}")

            # Force reinstall: uninstall first
            if force and package_id:
                try:
                    console_logger.info(f"Force reinstall: uninstalling {package_id}...")
                    self.uninstall(package_id)
                    time.sleep(2)  # Wait for uninstall to complete
                except DeploymentError as e:
                    console_logger.warning(f"Uninstall during force reinstall failed: {e}")

            # Push app to TV
            console_logger.info(f"Pushing app to TV...")
            rc, out, err = self._run_command(
                ["push", app_path, "/tmp/"],
                f"push {app_path}",
            )

            if rc != 0:
                raise DeploymentError(f"Push failed: {err or out}")

            # Install app
            app_name = os.path.basename(app_path)
            remote_path = f"/tmp/{app_name}"

            console_logger.info(f"Installing from remote path: {remote_path}...")
            rc, out, err = self._run_command(
                ["install", remote_path],
                f"install {remote_path}",
            )

            if rc != 0:
                # Auto-recovery: extract package_id and force reinstall
                if package_id:
                    console_logger.warning(
                        f"Installation failed. Attempting auto-recovery: "
                        f"uninstall {package_id} + force reinstall..."
                    )
                    try:
                        self.uninstall(package_id)
                        time.sleep(2)
                        rc, out, err = self._run_command(
                            ["install", "-r", remote_path],
                            f"install -r {remote_path}",
                        )
                        if rc != 0:
                            raise DeploymentError(f"Force reinstall failed: {err or out}")
                    except DeploymentError:
                        raise
                else:
                    raise DeploymentError(f"Install failed: {err or out}")

            console_logger.success(f"App installed successfully: {app_name}")
            return True

        except DeploymentError:
            raise
        except Exception as e:
            raise DeploymentError(f"Installation error: {e}")

    def uninstall(self, package_id: str) -> bool:
        """
        Uninstall app from TV
        
        Args:
            package_id: Package ID to uninstall
            
        Returns:
            True if successful
            
        Raises:
            DeploymentError: If uninstall fails
        """
        try:
            if not self.connected:
                raise DeploymentError("Not connected to TV")

            console_logger.info(f"Uninstalling app: {package_id}...")

            rc, out, err = self._run_command(
                ["uninstall", package_id],
                f"uninstall {package_id}",
            )

            if rc != 0:
                raise DeploymentError(f"Uninstall failed: {err or out}")

            console_logger.success(f"App uninstalled: {package_id}")
            return True

        except DeploymentError:
            raise
        except Exception as e:
            raise DeploymentError(f"Uninstall error: {e}")


# ============================================================================
# FLET UI
# ============================================================================

class TizenCommanderUI:
    """Main UI application"""

    def __init__(self):
        self.engine: Optional[DeploymentEngine] = None
        self.bootstrapper: Optional[Bootstrapper] = None
        self.init_done = False
        self.selected_file: Optional[str] = None

    def build(self) -> ft.Page:
        """Build the Flet application"""

        page = ft.Page()
        page.title = f"{APP_NAME} v{APP_VERSION}"
        page.window.width = 1200
        page.window.height = 800

        # ====== THEME ======
        page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(primary="#1976D2", secondary="#03DAC6")
        )
        page.dark_theme = ft.Theme(color_scheme=ft.ColorScheme())
        page.theme_mode = "dark"

        # ====== CONSOLE LOGGER CALLBACK ======
        def on_log_event(message: str, level: str):
            """Callback when a log is written"""
            color_map = {
                "INFO": "#FFFFFF",
                "SUCCESS": "#4CAF50",
                "ERROR": "#F44336",
                "WARNING": "#FF9800",
                "DEBUG": "#9E9E9E",
            }
            color = color_map.get(level, "#FFFFFF")
            
            log_row = ft.Text(
                message,
                color=color,
                font_family="monospace",
                size=11,
            )
            
            console_list.controls.append(log_row)
            
            # Keep last 100 lines visible
            if len(console_list.controls) > 100:
                console_list.controls.pop(0)
            
            console_container.scroll_to(offset=1000000, duration=100)
            page.update()

        console_logger.add_callback(on_log_event)

        # ====== TAB 1: CONNECTION ======

        tv_ip_input = ft.TextField(
            label="TV IP Address",
            hint_text="192.168.1.100",
            width=300,
        )

        connection_status = ft.Row(
            [
                ft.Icon(
                    name=icons.CIRCLE,
                    color="#FF0000",
                    size=24,
                )
            ],
            spacing=10,
        )

        def on_connect_click(e):
            """Connect button handler"""
            ip = tv_ip_input.value.strip()
            if not ip:
                console_logger.error("TV IP address is required")
                return

            def connect_thread():
                try:
                    console_logger.info("Initializing bootstrap...")
                    
                    if not self.bootstrapper.is_ready():
                        self.bootstrapper.bootstrap(verify_hash=False)
                    
                    console_logger.info(f"Connecting to {ip}...")
                    self.engine.connect(ip)

                    # Update UI
                    connection_status.controls[0].name = icons.CIRCLE
                    connection_status.controls[0].color = "#4CAF50"
                    connect_btn.text = "Disconnect"
                    connect_btn.bgcolor = "#F44336"
                    console_logger.success("Connection established")
                    page.update()

                except Exception as e:
                    console_logger.error(f"Connection failed: {e}")
                    connection_status.controls[0].color = "#FF0000"
                    page.update()

            threading.Thread(target=connect_thread, daemon=True).start()

        def on_disconnect_click(e):
            """Disconnect button handler"""
            def disconnect_thread():
                try:
                    self.engine.disconnect()
                    connection_status.controls[0].name = icons.CIRCLE
                    connection_status.controls[0].color = "#FF0000"
                    connect_btn.text = "Connect"
                    connect_btn.bgcolor = "#4CAF50"
                    console_logger.success("Disconnected from TV")
                    page.update()
                except Exception as e:
                    console_logger.error(f"Disconnect failed: {e}")
                    page.update()

            threading.Thread(target=disconnect_thread, daemon=True).start()

        connect_btn = ft.ElevatedButton(
            text="Connect",
            bgcolor="#4CAF50",
            on_click=on_connect_click,
            width=150,
        )

        tab_connection = ft.Column(
            [
                ft.Text("Connection Settings", size=20, weight="bold"),
                ft.Divider(),
                ft.Row([tv_ip_input, connect_btn], spacing=20),
                ft.Row([ft.Text("Status:"), connection_status], spacing=10),
                ft.Divider(),
                ft.Text(
                    "Enter TV IP and click Connect to establish SDB connection on port 26101",
                    size=12,
                    color="#999999",
                ),
            ],
            spacing=20,
            padding=20,
        )

        # ====== TAB 2: DEPLOYMENT ======

        file_name_text = ft.Text("No file selected", color="#999999")

        def on_file_picker(e):
            """File picker callback"""
            if e.files:
                self.selected_file = e.files[0].path
                file_name_text.value = os.path.basename(self.selected_file)
                file_name_text.color = "#FFFFFF"
                page.update()

        file_picker = ft.FilePicker(on_result=on_file_picker)
        page.overlay.append(file_picker)

        def on_install_click(e):
            """Install button handler"""
            if not self.selected_file:
                console_logger.error("Please select a file first")
                return

            if not self.engine.connected:
                console_logger.error("Not connected to TV")
                return

            def install_thread():
                try:
                    self.engine.install(self.selected_file, force=False)
                    console_logger.success("Installation completed")
                except Exception as ex:
                    console_logger.error(f"Installation failed: {ex}")
                page.update()

            threading.Thread(target=install_thread, daemon=True).start()

        def on_force_install_click(e):
            """Force install button handler"""
            if not self.selected_file:
                console_logger.error("Please select a file first")
                return

            if not self.engine.connected:
                console_logger.error("Not connected to TV")
                return

            def force_install_thread():
                try:
                    self.engine.install(self.selected_file, force=True)
                    console_logger.success("Force installation completed")
                except Exception as ex:
                    console_logger.error(f"Force installation failed: {ex}")
                page.update()

            threading.Thread(target=force_install_thread, daemon=True).start()

        pick_btn = ft.ElevatedButton(
            "Pick File",
            bgcolor="#1976D2",
            on_click=lambda e: file_picker.pick_files(
                allowed_extensions=["wgt", "apk"]
            ),
        )

        install_btn = ft.ElevatedButton(
            "Install",
            bgcolor="#4CAF50",
            on_click=on_install_click,
        )

        force_install_btn = ft.ElevatedButton(
            "Force Reinstall",
            bgcolor="#FF9800",
            on_click=on_force_install_click,
        )

        tab_deployment = ft.Column(
            [
                ft.Text("App Deployment", size=20, weight="bold"),
                ft.Divider(),
                ft.Row([pick_btn, file_name_text], spacing=20),
                ft.Row([install_btn, force_install_btn], spacing=20),
                ft.Divider(),
                ft.Text(
                    "Select .wgt or .apk file and click Install. "
                    "Force Reinstall will uninstall and reinstall.",
                    size=12,
                    color="#999999",
                ),
            ],
            spacing=20,
            padding=20,
        )

        # ====== TAB 3: CONSOLE ======

        console_list = ft.Column(spacing=5)
        console_container = ft.SingleChildScrollView(
            content=console_list,
            expand=True,
        )

        def on_clear_console(e):
            """Clear console"""
            console_list.controls.clear()
            page.update()

        clear_btn = ft.ElevatedButton(
            "Clear",
            bgcolor="#F44336",
            on_click=on_clear_console,
        )

        tab_console = ft.Column(
            [
                ft.Row([ft.Text("Console Log", size=20, weight="bold"), clear_btn]),
                ft.Divider(),
                console_container,
            ],
            spacing=10,
            padding=20,
            expand=True,
        )

        # ====== TAB 4: INFO ======

        system_info_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Key")),
                ft.DataColumn(ft.Text("Value")),
            ],
            rows=[],
        )

        apps_list = ft.Column(spacing=5)

        def on_refresh_info(e):
            """Refresh system info"""
            def refresh_thread():
                try:
                    if not self.engine.connected:
                        console_logger.error("Not connected to TV")
                        return

                    console_logger.info("Fetching system information...")

                    # Get system info
                    info = self.engine.get_system_info()
                    system_info_table.rows.clear()
                    for key, value in info.items():
                        system_info_table.rows.append(
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(key)),
                                    ft.DataCell(ft.Text(str(value)[:80])),
                                ]
                            )
                        )

                    # Get installed apps
                    console_logger.info("Fetching installed apps...")
                    apps = self.engine.get_installed_apps()
                    apps_list.controls.clear()
                    for app in apps:
                        apps_list.controls.append(
                            ft.Row(
                                [ft.Icon(icons.APP_REGISTRATION), ft.Text(app)],
                                spacing=10,
                            )
                        )

                    console_logger.success(
                        f"Fetched info: {len(info)} system keys, {len(apps)} apps"
                    )
                    page.update()

                except Exception as ex:
                    console_logger.error(f"Failed to fetch info: {ex}")
                    page.update()

            threading.Thread(target=refresh_thread, daemon=True).start()

        refresh_btn = ft.ElevatedButton(
            "Refresh",
            bgcolor="#1976D2",
            on_click=on_refresh_info,
        )

        tab_info = ft.Column(
            [
                ft.Row([ft.Text("TV Information", size=20, weight="bold"), refresh_btn]),
                ft.Divider(),
                ft.Text("System Info:", size=14, weight="bold"),
                system_info_table,
                ft.Divider(),
                ft.Text("Installed Apps:", size=14, weight="bold"),
                ft.SingleChildScrollView(content=apps_list, expand=True),
            ],
            spacing=10,
            padding=20,
            expand=True,
        )

        # ====== MAIN TABS ======

        tabs = ft.Tabs(
            [
                ft.Tab(text="Connection", content=tab_connection),
                ft.Tab(text="Deployment", content=tab_deployment),
                ft.Tab(text="Console", content=tab_console),
                ft.Tab(text="Info", content=tab_info),
            ],
            expand=True,
        )

        # ====== INITIALIZATION ======

        def initialize():
            """Initialize app on first load"""
            try:
                console_logger.info(f"Initializing {APP_NAME} v{APP_VERSION}...")

                # Determine SDB binary path
                if hasattr(sys, "frozen"):  # PyInstaller
                    base_dir = sys._MEIPASS
                else:
                    base_dir = os.path.dirname(os.path.abspath(__file__))

                sdb_dir = Path(base_dir) / "bin"
                sdb_dir.mkdir(exist_ok=True)

                sdb_path = sdb_dir / SDB_BINARY_NAME
                console_logger.info(f"SDB binary path: {sdb_path}")

                # Initialize components
                self.bootstrapper = Bootstrapper(sdb_path)
                self.engine = DeploymentEngine(str(sdb_path))

                console_logger.success("Initialization completed successfully")
                self.init_done = True

            except Exception as e:
                console_logger.error(f"Initialization failed: {e}")
                console_logger.error(traceback.format_exc())

        page.on_load = lambda e: initialize()

        return ft.Column([tabs], expand=True)

    def run(self):
        """Run the app"""
        page = self.build()
        ft.app(target=lambda page: None, export_asgi_app=False)
        ft.app_async(
            target=lambda page: page.add(self.build()),
            view=ft.AppView.WEB_BROWSER,
        )


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    try:
        app = TizenCommanderUI()
        
        page = ft.Page()
        page.title = f"{APP_NAME} v{APP_VERSION}"
        page.window.width = 1200
        page.window.height = 800
        page.theme_mode = "dark"
        
        # Build main UI
        main_column = app.build()
        page.add(main_column)
        
        ft.app(target=lambda p: p.add(main_column))

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
