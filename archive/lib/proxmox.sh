validate_storage() {
    local storage="$1"
    if ! pvesm status 2>/dev/null | awk '{print $1}' | grep -qx "$storage"; then
        echo "ERROR: Storage '$storage' not found."
        exit 1
    fi
}

get_ubuntu_template() {
    pveam list local 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1
}