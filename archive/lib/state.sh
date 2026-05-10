get_state() {
    local phase="$1"
    [[ -f "$PHASE_FILE" ]] && grep -qx "$phase" "$PHASE_FILE" 2>/dev/null
}

set_state() {
    local phase="$1"
    echo "$phase" >> "$PHASE_FILE"
}

reset_phases() {
    rm -f "$PHASE_FILE"
}