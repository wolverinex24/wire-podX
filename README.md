# wire-pod

`wire-pod` is fully-featured server software for the Anki (now Digital Dream Labs) [Vector](https://web.archive.org/web/20190417120536if_/https://www.anki.com/en-us/vector) robot. It was created thanks to Digital Dream Labs' [open-sourced code](https://github.com/digital-dream-labs/chipper).

It allows voice commands to work with any Vector 1.0 or 2.0 for no fee, including regular production robots.

## Installation

The installation guide exists on the wiki: [Installation guide](https://github.com/kercre123/wire-pod/wiki/Installation)

## Wiki

Check out the [wiki](https://github.com/kercre123/wire-pod/wiki) for more information on what wire-pod is, a guide on how to install wire-pod, troubleshooting, how to develop for it, and for some generally helpful tips.

## macOS Native STT Build

For native macOS builds that use Vosk fallback, the scripts expect the Vosk SDK at `$HOME/.vosk/libvosk` with `vosk_api.h` and `libvosk.dylib` inside it.

For Whisper.cpp builds, the scripts expect a repo-local checkout at `./whisper.cpp`, built with CMake into `./whisper.cpp/build_go`. The Go build uses headers from `./whisper.cpp`, `./whisper.cpp/include`, and `./whisper.cpp/ggml/include`, and libraries from `./whisper.cpp/build_go/src`, `./whisper.cpp/build_go/ggml/src`, `./whisper.cpp/build_go/ggml/src/ggml-blas`, and `./whisper.cpp/build_go/ggml/src/ggml-metal`.

`setup.sh` and `update.sh` now export these macOS CGO paths automatically for Groq, Vosk, and Whisper.cpp builds.

## Donate

If you want to :P

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/kercre123)

## Credits

- [Digital Dream Labs](https://github.com/digital-dream-labs) for open sourcing chipper and creating escape pod (which made this possible)
- [bliteknight](https://github.com/bliteknight) for making wire-pod more accessible with his easy-to-use pre-setup Linux boxes
- [dietb](https://github.com/dietb) for rewriting chipper and giving tips
- [fforchino](https://github.com/fforchino) for adding many features such as localization and multilanguage, and for helping out
- [xanathon](https://github.com/xanathon) for the publicity and web interface help
- Anyone who has opened an issue and/or created a pull request for wire-pod
