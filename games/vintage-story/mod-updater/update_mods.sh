#!/bin/bash

# =========================================================================
# Vintage Story Mod Update Script
# This script reads settings from a config file to update mods
# locally and then transfer them to an FTP server or a local test folder.
# =========================================================================

# --- ANSI COLORS FOR OUTPUT ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- SCRIPT EXECUTION ---
scriptPath="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
configPath="$scriptPath/config.sh"

# Check if the configuration file exists.
if [[ ! -f "$configPath" ]]; then
    echo -e "${RED}Error: The configuration file 'config.sh' was not found.${NC}"
    exit 1
fi

# Load the configuration data.
echo -e "${CYAN}Loading settings from configuration...${NC}"
source "$configPath"

echo -e "${CYAN}Hello! Let's start updating your mods...${NC}"

# 1. Prepare the local folder
echo -e "Step 1/3: Preparing the local mods folder..."
if [[ ! -d "$LocalModsFolder" ]]; then
    echo -e "${YELLOW}Folder not found. Creating it now...${NC}"
    mkdir -p "$LocalModsFolder"
fi

# 2. Execute Modsupdater
echo -e "Step 2/3: Updating mods with Modsupdater..."
execute_modsupdater() {
    modsupdaterDirectory=$(dirname "$ModsupdaterPath")
    arguments="$ModsupdaterArguments --modspath \"$LocalModsFolder\""

    chmod +x "$ModsupdaterPath"
    cd "$modsupdaterDirectory" || return 1
    eval "$ModsupdaterPath $arguments"
}

if ! execute_modsupdater; then
    echo -e "${RED}An error occurred while running Modsupdater.${NC}"
    exit 1
fi

# 3. Synchronization (FTP or Local Simulation)
# =========================================================================
echo -e "Step 3/3: Synchronizing files..."

execute_sync() {
    if [[ "$TestMode" == "true" ]]; then
        # --- TEST MODE LOGIC ---
        echo -e "${YELLOW}[TEST MODE] Simulating transfer to local folder...${NC}"
        echo -e "${YELLOW}Target: $LocalMockRemotePath${NC}"
        
        # Create the simulation folder if it doesn't exist
        mkdir -p "$LocalMockRemotePath"
        
        # Use rsync if available as it perfectly mimics lftp's mirror --delete
        if command -v rsync >/dev/null 2>&1; then
            rsync -av --delete "$LocalModsFolder/" "$LocalMockRemotePath/"
        else
            # Fallback to cp if rsync is not installed
            cp -r "$LocalModsFolder/." "$LocalMockRemotePath/"
        fi
        return 0
    else
        # --- REAL FTP LOGIC ---
        echo -e "${CYAN}Connecting to FTP server: $FtpServer...${NC}"
        
        scriptContent="
set sftp:auto-confirm yes
set net:timeout 10
open -u $FtpUsername,$FtpPassword $FtpServer
mirror -R --delete --verbose \"$LocalModsFolder\" \"$RemoteModsPath\"
close
exit
"
        tempScript=$(mktemp)
        echo "$scriptContent" > "$tempScript"

        "$LftpPath" -f "$tempScript"
        local exit_status=$?
        rm -f "$tempScript"
        return $exit_status
    fi
}

if ! execute_sync; then
    echo -e "${RED}An error occurred during synchronization.${NC}"
    exit 1
fi

echo -e "${GREEN}Update completed successfully!${NC}"
if [[ "$TestMode" == "true" ]]; then
    echo -e "${YELLOW}Note: Files were synced to your local test folder (Test Mode).${NC}"
fi