#!/bin/bash

UNAME=$(uname -a)
COMMIT_HASH="$(git rev-parse --short HEAD)"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. sudo ./start.sh"
    exit 1
fi

if [[ -d ./chipper ]]; then
    cd chipper
fi

ROOT="/root"
if [[ ${UNAME} == *"Darwin"* ]]; then
    if [[ -n ${SUDO_USER} ]]; then
        ROOT="$(eval echo "~${SUDO_USER}")"
    else
        ROOT="$HOME"
    fi
fi
VOSK_DIR="${ROOT}/.vosk/libvosk"

#if [[ ! -f ./chipper ]]; then
#   if [[ -f ./go.mod ]]; then
#     echo "You need to build chipper first. This can be done with the setup.sh script."
#   else
#     echo "You must be in the chipper directory."
#   fi
#   exit 0
#fi

if [[ ! -f ./source.sh ]]; then
    echo "You need to make a source.sh file. This can be done with the setup.sh script."
    exit 0
fi

source source.sh

function upsertSourceExport() {
    local key="$1"
    local value="$2"
    local file="./source.sh"
    local escaped_value=""
    printf -v escaped_value '%q' "${value}"

    awk -v key="${key}" -v line="export ${key}=${escaped_value}" '
        BEGIN { found = 0 }
        $0 ~ "^export " key "=" {
            print line
            found = 1
            next
        }
        { print }
        END {
            if (!found) {
                print line
            }
        }
    ' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}"
}

function persistSttSelection() {
    upsertSourceExport "STT_SERVICE" "${STT_SERVICE}"
    if [[ "${STT_SERVICE}" == "groq" ]] || [[ "${STT_SERVICE}" == "whisper.cpp" ]]; then
        upsertSourceExport "STT_FALLBACK_SERVICE" "vosk"
    else
        upsertSourceExport "STT_FALLBACK_SERVICE" "${STT_SERVICE}"
    fi
    if [[ "${STT_SERVICE}" == "whisper.cpp" ]] && [[ -n "${WHISPER_MODEL}" ]]; then
        upsertSourceExport "WHISPER_MODEL" "${WHISPER_MODEL}"
    fi
}

function promptSttSelection() {
    local current_stt="${STT_SERVICE:-vosk}"
    local stt_choice=""

    echo
    echo "Select the speech-to-text engine to use for this launch:"
    echo "1: VOSK (local, default)"
    echo "2: Whisper.cpp (local)"
    echo "3: Groq Whisper (cloud)"
    echo
    read -p "Enter a number (${current_stt}): " stt_choice

    case "${stt_choice}" in
        "") ;;
        "1") STT_SERVICE="vosk" ;;
        "2") STT_SERVICE="whisper.cpp" ;;
        "3") STT_SERVICE="groq" ;;
        *)
            echo "Invalid selection. Using ${current_stt}."
        ;;
    esac

    if [[ -z "${STT_SERVICE}" ]]; then
        STT_SERVICE="vosk"
    fi

    if [[ "${STT_SERVICE}" == "groq" ]] && [[ -z "${GROQ_API_KEY}" ]]; then
        echo
        echo "Groq requires an API key."
        read -p "Enter your Groq API key for this launch: " GROQ_API_KEY
    fi

    if [[ "${STT_SERVICE}" == "whisper.cpp" ]] && [[ -z "${WHISPER_MODEL}" ]]; then
        echo
        read -p "Enter the Whisper.cpp model to use (tiny): " whisper_model_choice
        if [[ -n "${whisper_model_choice}" ]]; then
            WHISPER_MODEL="${whisper_model_choice}"
        else
            WHISPER_MODEL="tiny"
        fi
    fi

    export STT_SERVICE
    export GROQ_API_KEY
    export WHISPER_MODEL

    persistSttSelection

    echo
    echo "Launching wire-pod with STT: ${STT_SERVICE}"
}

if [[ -t 0 ]] && [[ -t 1 ]] && [[ "${WIREPOD_SKIP_STT_PROMPT}" != "true" ]]; then
    promptSttSelection
fi

# set go tags
export GOTAGS="nolibopusfile"

if [[ ${USE_INBUILT_BLE} == "true" ]]; then
    GOTAGS="${GOTAGS},inbuiltble"
fi

export GOLDFLAGS="-X 'github.com/kercre123/wire-pod/chipper/pkg/vars.CommitSHA=${COMMIT_HASH}'"

#./chipper
if [[ ${STT_SERVICE} == "leopard" ]]; then
    if [[ -f ./chipper ]]; then
        ./chipper
    else
        /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/leopard/main.go
    fi
    elif [[ ${STT_SERVICE} == "rhino" ]]; then
    if [[ -f ./chipper ]]; then
        ./chipper
    else
        /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/experimental/rhino/main.go
    fi
    elif [[ ${STT_SERVICE} == "houndify" ]]; then
    if [[ -f ./chipper ]]; then
        ./chipper
    else
        /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/experimental/houndify/main.go
    fi
    elif [[ ${STT_SERVICE} == "whisper" ]]; then
    if [[ -f ./chipper ]]; then
        ./chipper
    else
        /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/experimental/whisper/main.go
    fi
    elif [[ ${STT_SERVICE} == "groq" ]]; then
    if [[ -f ./chipper ]]; then
        export CGO_ENABLED=1
        export CGO_CFLAGS="-I${VOSK_DIR}"
        export CGO_LDFLAGS="-L${VOSK_DIR} -lvosk -ldl -lpthread"
        export LD_LIBRARY_PATH="${VOSK_DIR}:${LD_LIBRARY_PATH}"
        export DYLD_LIBRARY_PATH="${VOSK_DIR}:${DYLD_LIBRARY_PATH}"
        ./chipper
    else
        export CGO_ENABLED=1
        export CGO_CFLAGS="-I${VOSK_DIR}"
        export CGO_LDFLAGS="-L${VOSK_DIR} -lvosk -ldl -lpthread"
        export LD_LIBRARY_PATH="${VOSK_DIR}:${LD_LIBRARY_PATH}"
        export DYLD_LIBRARY_PATH="${VOSK_DIR}:${DYLD_LIBRARY_PATH}"
        if [[ ${UNAME} == *"Darwin"* ]]; then
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" -exec "env DYLD_LIBRARY_PATH=${VOSK_DIR}" cmd/groq/main.go
        else
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/groq/main.go
        fi
    fi
    elif [[ ${STT_SERVICE} == "whisper.cpp" ]]; then
    if [[ -f ./chipper ]]; then
        export C_INCLUDE_PATH="../whisper.cpp"
        export LIBRARY_PATH="../whisper.cpp"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$(pwd)/../whisper.cpp:$(pwd)/../whisper.cpp/build:$(pwd)/../whisper.cpp/build/src:${VOSK_DIR}"
        export DYLD_LIBRARY_PATH="$DYLD_LIBRARY_PATH:$(pwd)/../whisper.cpp:$(pwd)/../whisper.cpp/build:$(pwd)/../whisper.cpp/build/src:${VOSK_DIR}"
        export CGO_LDFLAGS="-L$(pwd)/../whisper.cpp/build_go/src -L${VOSK_DIR} -lvosk -ldl -lpthread"
        export CGO_CFLAGS="-I$(pwd)/../whisper.cpp -I${VOSK_DIR}"
        ./chipper
    else
        export C_INCLUDE_PATH="../whisper.cpp"
        export LIBRARY_PATH="../whisper.cpp"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$(pwd)/../whisper.cpp:$(pwd)/../whisper.cpp/build:$(pwd)/../whisper.cpp/build_go/src:$(pwd)/../whisper.cpp/build_go/ggml/src:${VOSK_DIR}"
        export DYLD_LIBRARY_PATH="$DYLD_LIBRARY_PATH:$(pwd)/../whisper.cpp:$(pwd)/../whisper.cpp/build:$(pwd)/../whisper.cpp/build_go/src:$(pwd)/../whisper.cpp/build_go/ggml/src:${VOSK_DIR}"
        export CGO_LDFLAGS="-L$(pwd)/../whisper.cpp -L$(pwd)/../whisper.cpp/build -L$(pwd)/../whisper.cpp/build/src -L$(pwd)/../whisper.cpp/build_go/ggml/src -L$(pwd)/../whisper.cpp/build_go/src -L${VOSK_DIR} -lvosk -ldl -lpthread"
        export CGO_CFLAGS="-I$(pwd)/../whisper.cpp -I$(pwd)/../whisper.cpp/include -I$(pwd)/../whisper.cpp/ggml/include -I${VOSK_DIR}"
        if [[ ${UNAME} == *"Darwin"* ]]; then
            export GGML_METAL_PATH_RESOURCES="../whisper.cpp"
            whisper_dyld_libs="$(pwd)/../whisper.cpp:$(pwd)/../whisper.cpp/build:$(pwd)/../whisper.cpp/build_go/src:$(pwd)/../whisper.cpp/build_go/ggml/src:${VOSK_DIR}"
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags "-extldflags '-framework Foundation -framework Metal -framework MetalKit'" -exec "env DYLD_LIBRARY_PATH=${whisper_dyld_libs}" cmd/experimental/whisper.cpp/main.go
        else
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/experimental/whisper.cpp/main.go
        fi
    fi
    elif [[ ${STT_SERVICE} == "vosk" ]]; then
    if [[ -f ./chipper ]]; then
        export CGO_ENABLED=1
        export CGO_CFLAGS="-I${VOSK_DIR}"
        export CGO_LDFLAGS="-L${VOSK_DIR} -lvosk -ldl -lpthread"
        export LD_LIBRARY_PATH="${VOSK_DIR}:${LD_LIBRARY_PATH}"
        export DYLD_LIBRARY_PATH="${VOSK_DIR}:${DYLD_LIBRARY_PATH}"
        ./chipper
    else
        export CGO_ENABLED=1
        export CGO_CFLAGS="-I${VOSK_DIR}"
        export CGO_LDFLAGS="-L${VOSK_DIR} -lvosk -ldl -lpthread"
        export LD_LIBRARY_PATH="${VOSK_DIR}:${LD_LIBRARY_PATH}"
        export DYLD_LIBRARY_PATH="${VOSK_DIR}:${DYLD_LIBRARY_PATH}"
        if [[ ${UNAME} == *"Darwin"* ]]; then
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" -exec "env DYLD_LIBRARY_PATH=${VOSK_DIR}" cmd/vosk/main.go
        else
            /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/vosk/main.go
        fi
    fi
else
    if [[ -f ./chipper ]]; then
        export CGO_LDFLAGS="-L/root/.coqui/"
        export CGO_CXXFLAGS="-I/root/.coqui/"
        export LD_LIBRARY_PATH="/root/.coqui/:$LD_LIBRARY_PATH"
        ./chipper
    else
        export CGO_LDFLAGS="-L$HOME/.coqui/"
        export CGO_CXXFLAGS="-I$HOME/.coqui/"
        export LD_LIBRARY_PATH="$HOME/.coqui/:$LD_LIBRARY_PATH"
        /usr/local/go/bin/go run -tags $GOTAGS -ldflags="${GOLDFLAGS}" cmd/coqui/main.go
    fi
fi
