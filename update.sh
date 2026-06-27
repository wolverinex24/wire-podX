#!/bin/bash

# ensure all required packages are installed
if [[ $(uname -a) == *"Darwin"* ]]; then
    TARGET="darwin"
    if [[ -n ${SUDO_USER} ]]; then
        ROOT="$(eval echo "~${SUDO_USER}")"
    else
        ROOT="$HOME"
    fi
    echo "macOS detected."
elif [[ -f /usr/bin/apt ]]; then
    TARGET="debian"
    ROOT="/root"
    echo "Debian-based Linux detected."
elif [[ -f /usr/bin/pacman ]]; then
    TARGET="arch"
    ROOT="/root"
    echo "Arch Linux detected."
elif [[ -f /usr/bin/dnf ]]; then
    TARGET="fedora"
    ROOT="/root"
    echo "Fedora/openSUSE detected."
fi

if [[ ${TARGET} == "debian" ]]; then
    sudo apt update -y
    sudo apt install -y wget openssl net-tools libsox-dev libopus-dev make iproute2 xz-utils libopusfile-dev pkg-config gcc curl g++ unzip avahi-daemon git libasound2-dev libsodium-dev
elif [[ ${TARGET} == "arch" ]]; then
    sudo pacman -Sy --noconfirm
    sudo pacman -S --noconfirm wget openssl net-tools sox opus make iproute2 opusfile curl unzip avahi git libsodium
elif [[ ${TARGET} == "fedora" ]]; then
    sudo dnf update
    sudo dnf install -y wget openssl net-tools sox opus make opusfile curl unzip avahi git libsodium-devel
elif [[ ${TARGET} == "darwin" ]]; then
    sudo -u $SUDO_USER brew update
    sudo -u $SUDO_USER brew install wget pkg-config opus opusfile
fi

if [[ ! -d ./chipper ]]; then
  echo "This must be run in the wire-pod/ directory."
  exit 1
fi

function setLibraryPathVar() {
    if [[ ${TARGET} == "darwin" ]]; then
        echo "DYLD_LIBRARY_PATH"
    else
        echo "LD_LIBRARY_PATH"
    fi
}

function appendLibraryPath() {
    local lib_var
    lib_var="$(setLibraryPathVar)"
    local current_value="${!lib_var}"
    if [[ -n "${current_value}" ]]; then
        export "${lib_var}=$1:${current_value}"
    else
        export "${lib_var}=$1"
    fi
}

function configureVoskBuildEnv() {
    local vosk_root="${ROOT}/.vosk/libvosk"
    export CGO_ENABLED=1
    export CGO_CFLAGS="-I${vosk_root}"
    export CGO_LDFLAGS="-L${vosk_root} -lvosk -ldl -lpthread"
    appendLibraryPath "${vosk_root}"
}

function configureWhisperBuildEnv() {
    local whisper_root="$(pwd)/../whisper.cpp"
    local whisper_build="${whisper_root}/build_go"
    local vosk_root="${ROOT}/.vosk/libvosk"
    export CGO_ENABLED=1
    export CGO_CFLAGS="-I${whisper_root} -I${whisper_root}/include -I${whisper_root}/ggml/include -I${vosk_root}"
    export CGO_LDFLAGS="-L${whisper_build}/src -L${whisper_build}/ggml/src -L${whisper_build}/ggml/src/ggml-blas -L${whisper_build}/ggml/src/ggml-metal -L${vosk_root} -lwhisper -lggml -lggml-base -lggml-cpu -lggml-blas -lggml-metal -lvosk -ldl -lpthread"
    appendLibraryPath "${whisper_build}/src"
    appendLibraryPath "${whisper_build}/ggml/src"
    appendLibraryPath "${whisper_build}/ggml/src/ggml-blas"
    appendLibraryPath "${whisper_build}/ggml/src/ggml-metal"
    appendLibraryPath "${vosk_root}"
}

git fetch --all
git reset --hard origin/main
if [[ -f ./chipper/chipper ]]; then
    cd chipper
    source source.sh
    sudo systemctl stop wire-pod
    if [[ ${STT_SERVICE} == "leopard" ]]; then
        echo "wire-pod.service created, building chipper with Picovoice STT service..."
        sudo /usr/local/go/bin/go build cmd/leopard/main.go
    elif [[ ${STT_SERVICE} == "vosk" ]]; then
        echo "wire-pod.service created, building chipper with VOSK STT service..."
        configureVoskBuildEnv
        sudo env CGO_ENABLED="${CGO_ENABLED}" CGO_CFLAGS="${CGO_CFLAGS}" CGO_LDFLAGS="${CGO_LDFLAGS}" DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH}" LD_LIBRARY_PATH="${LD_LIBRARY_PATH}" /usr/local/go/bin/go build cmd/vosk/main.go
    elif [[ ${STT_SERVICE} == "whisper.cpp" ]]; then
        echo "wire-pod.service created, building chipper with Whisper.CPP STT service..."
        configureWhisperBuildEnv
        sudo env CGO_ENABLED="${CGO_ENABLED}" CGO_CFLAGS="${CGO_CFLAGS}" CGO_LDFLAGS="${CGO_LDFLAGS}" DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH}" LD_LIBRARY_PATH="${LD_LIBRARY_PATH}" /usr/local/go/bin/go build cmd/experimental/whisper.cpp/main.go
    elif [[ ${STT_SERVICE} == "groq" ]]; then
        echo "wire-pod.service created, building chipper with Groq cloud STT service..."
        configureVoskBuildEnv
        sudo env CGO_ENABLED="${CGO_ENABLED}" CGO_CFLAGS="${CGO_CFLAGS}" CGO_LDFLAGS="${CGO_LDFLAGS}" DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH}" LD_LIBRARY_PATH="${LD_LIBRARY_PATH}" /usr/local/go/bin/go build cmd/groq/main.go
    elif [[ ${STT_SERVICE} == "coqui" ]]; then
        echo "wire-pod.service created, building chipper with Coqui STT service..."
        sudo LD_LIBRARY_PATH="/root/.coqui/:$LD_LIBRARY_PATH" CGO_CXXFLAGS="-I/root/.coqui/" CGO_LDFLAGS="-L/root/.coqui/" /usr/local/go/bin/go build cmd/coqui/main.go
    else
	echo "Unsupported STT ${STT_SERVICE}. You must build this manually. The code has been updated, though."
	exit 1
    fi
    echo "Syncing..."
    sync
    sudo systemctl daemon-reload
    sudo systemctl start wire-pod
    echo "wire-pod is now running with the updated code!"
fi
echo
echo "Updated successfully!"
echo
