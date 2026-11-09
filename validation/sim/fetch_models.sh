#!/usr/bin/env bash
# Fetch the vendor SPICE models used by the simulations into models/vendor/.
#
# The vendor files are NOT committed: TI ("All rights reserved") and Vishay/Thomatronik
# (copyright notice, no redistribution grant) don't allow it. This script downloads them
# and checks each against a pinned sha256. The pinned files were read by hand: they are
# plain .SUBCKT/.MODEL text with no .control blocks. A changed upstream file fails the
# check and is deleted instead of being used.
#
# Usage: validation/sim/fetch_models.sh        (idempotent; skips files already verified)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="$here/models/vendor"
mkdir -p "$dest"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# name | url | sha256
MODELS=(
  "ss34.txt|https://www.vishay.com/docs/88170/ss34.txt|1a0e30b8ccfd69ee5a69b3cd8c08c6c30f2be4c86a50a0e6234aa6827ad4ddf9"
  "smbj22a.txt|https://www.vishay.com/docs/89800/smbj22a.txt|30cdbc0cc8341190faf74964d2842179a413661309fdb84bf9fefe0dfaf2474d"
  "smbj30a.txt|https://www.vishay.com/docs/89545/smbj30a.txt|ecbfd7b4c26031a608cf85da209eab529484fb613da8200a10e9e8ec5ae443fe"
  "smbj33a.txt|https://www.vishay.com/docs/88150/smbj33a.txt|d2377e8790bd7e2f492c43dd158aef50a0e952d33dee5171de32108634fd0df3"
  "smbj36a.txt|https://www.vishay.com/docs/89579/smbj36a.txt|1fe25705b7f2dd76f2934ca7f1d1175550bac155e63acae6663b4444c426ee7b"
)
# TI TPS7B6933-Q1 unencrypted PSpice transient model (zip SLVMCQ7 -> one .lib)
TI_ZIP_URL="https://www.ti.com/lit/zip/slvmcq7"
TI_ZIP_SHA="85466468b0add12fabe051a9f84dee0e95bd94cd29edfe374232868f2435bb01"
TI_LIB="TPS7B6933-Q1_TRANS.lib"
TI_LIB_SHA="4b00e065fb82b4a4a333892dfab9237f675d32b45749d470104e309a07dc433d"

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
ok()  { [[ -f "$1" && "$(sha "$1")" == "$2" ]]; }

fail=0
for m in "${MODELS[@]}"; do
  IFS='|' read -r name url want <<<"$m"
  f="$dest/$name"
  if ok "$f" "$want"; then echo "ok      $name"; continue; fi
  curl -sSfL -A "$UA" --max-time 60 -o "$f.part" "$url" || { echo "FETCH FAILED $name ($url)"; rm -f "$f.part"; fail=1; continue; }
  if [[ "$(sha "$f.part")" == "$want" ]]; then mv "$f.part" "$f"; echo "fetched $name"
  else echo "SHA MISMATCH $name: upstream changed; review it by hand before updating the pin"; rm -f "$f.part"; fail=1; fi
done

if ok "$dest/$TI_LIB" "$TI_LIB_SHA"; then echo "ok      $TI_LIB"
else
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  if curl -sSfL -A "$UA" --max-time 60 -o "$tmp/ti.zip" "$TI_ZIP_URL" && [[ "$(sha "$tmp/ti.zip")" == "$TI_ZIP_SHA" ]]; then
    unzip -q -o -j "$tmp/ti.zip" "$TI_LIB" -d "$tmp/x"
    if [[ "$(sha "$tmp/x/$TI_LIB")" == "$TI_LIB_SHA" ]]; then mv "$tmp/x/$TI_LIB" "$dest/$TI_LIB"; echo "fetched $TI_LIB"
    else echo "SHA MISMATCH $TI_LIB"; fail=1; fi
  else echo "FETCH/SHA FAILED TI zip ($TI_ZIP_URL)"; fail=1; fi
fi
exit $fail
