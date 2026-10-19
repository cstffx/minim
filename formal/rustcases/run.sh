#!/bin/sh
# Qué acepta y qué rechaza el rustc instalado en estos casos.
# Todos los ficheros .rs son PROGRAMAS SEGUROS: los "RECHAZA" son falsos rechazos.
# Uso: sh formal/rustcases/run.sh          (RUSTC=... para otro compilador)
#
# NOTA: esto es una comprobación manual/opcional contra el rustc real, para contrastar
# el borrow checker de Minim con el de Rust. No forma parte de la suite automática de
# tests en Python (tools/test_*.py) ni se ejecuta en CI. Ver también formal/CASES.md.
# Requiere rustc instalado (`which rustc` para comprobarlo).
set -u
cd "$(dirname "$0")"
RUSTC=${RUSTC:-rustc}
printf 'rustc: %s\n' "$("$RUSTC" --version)"
for f in a_disjoint_index.rs b_polonius3.rs c_slice_two.rs d_fields_ok.rs \
         e_two_phase_ok.rs f_selfref.rs g_lending.rs h_split_ok.rs i_gdm_ok.rs; do
  if "$RUSTC" --edition 2021 -o /tmp/minim_rustcase.bin "$f" 2>/tmp/minim_rustcase.err; then
    printf 'ACEPTA   %-22s\n' "$f"
  else
    printf 'RECHAZA  %-22s %s\n' "$f" "$(grep -m1 '^error' /tmp/minim_rustcase.err)"
  fi
done
printf -- '--- motor declarativo (Datalog), nightly:\n'
for f in b_polonius3.rs; do
  if "$RUSTC" --edition 2021 -Zpolonius -o /tmp/minim_rustcase.bin "$f" 2>/dev/null; then
    printf 'ACEPTA   %-22s %s\n' "$f" "(con -Zpolonius)"
  else
    printf 'RECHAZA  %-22s %s\n' "$f" "(con -Zpolonius)"
  fi
done
