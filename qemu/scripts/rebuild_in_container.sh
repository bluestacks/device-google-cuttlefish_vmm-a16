#!/bin/sh
# Starts an isolated build in a container
set -e

ARCH="x86_64"
FROM_EXISTING_SOURCES=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --arch)
      ARCH="$2"
      shift 2
      ;;
    --from_existing_sources)
      FROM_EXISTING_SOURCES=1
      shift
      ;;
    *)
      echo "Build QEMU from sources in a container."
      echo
      echo "usage: $0 [--from_existing_sources] [--arch x86_64|aarch64]"
      echo
      echo "Options:"
      echo "  --from_existing_sources: Do not checkout sources with repo,"
      echo "    and do not copy the prebuild back to the source directory."
      shift
      exit 1
      ;;
  esac
done

readonly SCRIPT_DIR="$(realpath "$(dirname "$0")")"
readonly GIT_ROOT="$(realpath "${SCRIPT_DIR}/../..")"
readonly WORK_DIR="/tmp/qemu-build-output"

echo "Clear the working directory: ${WORK_DIR}"
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

if [ "$FROM_EXISTING_SOURCES" -eq 0 ]; then
  readonly SRC_DIR="${HOME}/qemu-build-checkout"
  echo "Check out sources with repo at: ${SRC_DIR}"
  rm -rf "${SRC_DIR}"
  mkdir -p "${SRC_DIR}"
  cd "${SRC_DIR}"
  repo init --manifest-url "${GIT_ROOT}" \
    --manifest-name=qemu/manifest.xml

  repo sync
else
  readonly SRC_DIR="$GIT_ROOT"
  echo "Reuse existing source checkout at: ${SRC_DIR}"
fi

readonly COMMON_APT_PACKAGES="autoconf libgbm-dev libtool texinfo"
readonly AARCH64_APT_PACKAGES="clang cmake curl libc++-dev libc++abi-dev \
  libegl-dev libgcc-12-dev libxml2-utils llvm make ninja-build \
  patchelf pkg-config python3 python3-distutils python3-venv"

APT_PACKAGES="${COMMON_APT_PACKAGES}"
RUSTUP_COMMAND=":"
PYTHON_BIN="/src/qemu/third_party/python/bin/python3"
if [[ "$ARCH" == "aarch64" ]]; then
  APT_PACKAGES="${APT_PACKAGES} ${AARCH64_APT_PACKAGES}"
  RUSTUP_COMMAND="curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -q -y"
  PYTHON_BIN="python3"
fi

readonly COMMAND="apt-get update && \
apt-get -qy install ${APT_PACKAGES} && \
${RUSTUP_COMMAND} && \
${PYTHON_BIN} /src/qemu/scripts/rebuild.py --arch ${ARCH} --build-dir /out"

# Note: `/src` is mounted with a file overlay so that cargo can write
# `third_party/crossvm/rutabaga_gfx/ffi/Cargo.lock` file. We didn't find
# a way to prevent cargo from writing it.

podman run --name qemu-build \
    --replace \
    --pids-limit=-1 \
    --volume "${SRC_DIR}:/src:O" \
    --volume "${WORK_DIR}:/out" \
    --arch ${ARCH} \
    docker.io/debian:12-slim \
    bash -c "${COMMAND}"

# Tip: Use `--interactive`, `--tty` and
# `bash -c "${COMMAND};$SHELL"` for interactive debug.

if [ "$FROM_EXISTING_SOURCES" -eq 0 ]; then
  readonly DEST="${GIT_ROOT}/qemu/${ARCH}-linux-gnu"
  echo "Overwrite prebuilt at: ${DEST}"
  rm -rf "${DEST}/*"
  tar -xvf "${WORK_DIR}/qemu-portable.tar.gz" -C "${DEST}"

fi

echo "Binary available at: ${WORK_DIR}/qemu-portable/bin"
echo "Done."
