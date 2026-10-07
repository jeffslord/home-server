#!/bin/sh
# Builds SaveAndStop.dll against the installed SE server and drops it into the
# plugins dir, where the image's entrypoint adds it to <Plugins> on next start.
# Rebuild after a big SE update if the server log shows a plugin load error.
set -e
cd "$(dirname "$0")"
SSD_PATH=$(grep "^SSD_PATH=" ../../../.env | cut -d= -f2)
SE="$SSD_PATH/games/space-engineers"
docker run --rm \
  -v "$PWD":/src -w /src \
  -v "$SE/SpaceEngineersDedicated/DedicatedServer64":/se:ro \
  -v "$SE/plugins":/plugins \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  sh -c 'dotnet build -c Release -o /tmp/out -nologo -v q && cp /tmp/out/SaveAndStop.dll /plugins/ && rm -rf bin obj'
echo "Installed $SE/plugins/SaveAndStop.dll — restart space-engineers to load it."
