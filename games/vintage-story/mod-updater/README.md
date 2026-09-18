# Vintage Story Server Utilities

A collection of utility scripts for managing a Vintage Story server. This repository includes tools for automating mod updates and file synchronization between a local machine and a remote server.

## Features

*   **Local Update**: Automatically runs `ModsUpdater` to fetch the latest versions of your mods.
*   **Automatic Sync**: Synchronizes your local mods folder with a remote server via FTP/SFTP.
*   **Smart Mirroring**: 
    *   On **Linux**, uses `lftp` (remote) and `rsync` (test mode).
    *   On **Windows**, uses `WinSCP` (remote) and `robocopy` (test mode).
*   **Test Mode**: Allows you to simulate the entire process locally without any FTP connection to verify your setup.

## Project Structure

*   `linux/`: Bash scripts for Linux users.
*   `windows/`: PowerShell scripts for Windows users.

---

## Getting Started

### Prerequisites

1.  **ModsUpdater**: Download the latest version of ModsUpdater:
- [ModsUpdater for Windows](https://mods.vintagestory.at/modsupdater)
- [ModsUpdater for Linux](https://mods.vintagestory.at/modsupdaterforlinux)
2.  **FTP Client**:
    *   **Windows**: Install [WinSCP](https://winscp.net/).
    *   **Linux**: Install `lftp` (e.g., `sudo apt install lftp`).

### 1. Test Mode (Highly Recommended)

Before connecting to your production server, you can test the logic locally:
1.  Open your configuration file (`linux/config.sh` or `windows/config.psd1`).
2.  Set `TestMode` to `true`.
3.  Set `LocalMockRemotePath` to a local folder that will act as your "fake" server.
4.  Run the script. It will update the mods and "transfer" them to your mock folder.

### 2. Production Setup

Once satisfied with the test:
1.  Set `TestMode` to `false` in the config file.
2.  Fill in your actual FTP/SFTP credentials (`Username`, `Password`, `Server Address`).
3.  Ensure the `RemoteModsPath` is correct for your hosting provider.

---

## Usage

### Windows
1.  Navigate to the `windows/` folder.
2.  Edit `config.psd1` with your settings.
3.  Right-click `update_mods.ps1` and select **Run with PowerShell**.

### Linux
1.  Navigate to the `linux/` folder.
2.  Edit `config.sh` with your settings.
3.  Make the script executable: `chmod +x update_mods.sh`.
4.  Run the script: `./update_mods.sh`.

---

## Compatibility

*   **Windows**: Requires PowerShell 5.1+ and WinSCP.
*   **Linux**: Requires Bash, lftp, and rsync (for local simulation).
