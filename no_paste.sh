#!/bin/bash

BOM="$1"

DNP=$(grep .*:.*:.*:.*:1:.* "$BOM" | cut -f 1 -d ':' | sed 's/,/ /g')
for i in $DNP; do echo "Select(ElementByName, $i)"; done
echo "ClearPaste(SelectedPads)"
echo "wq"
