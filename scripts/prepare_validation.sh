#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_DISTRO_REQUIRED="jazzy"
BUILD_WORKERS="${COLCON_BUILD_WORKERS:-2}"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

source_ros_setup() {
  set +u
  # ROS setup hooks reference optional variables that may be unset under nounset.
  # shellcheck disable=SC1091
  source "/opt/ros/${ROS_DISTRO_REQUIRED}/setup.bash"
  set -u
}

require_ubuntu_noble() {
  [[ -r /etc/os-release ]] || fail "No encuentro /etc/os-release. Este script espera Ubuntu 24.04 Noble."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || \
    fail "Se requiere Ubuntu 24.04; detecté ${PRETTY_NAME:-un sistema desconocido}."
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker y el plugin Compose ya están instalados."
    return
  fi

  log "Instalando Docker Engine y el plugin Docker Compose desde el repositorio oficial."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
  sudo docker run --rm hello-world
  sudo docker compose version
}

prepare_ros_tools() {
  [[ -r "/opt/ros/${ROS_DISTRO_REQUIRED}/setup.bash" ]] || \
    fail "Falta ROS 2 Jazzy en /opt/ros/${ROS_DISTRO_REQUIRED}; instala ROS 2 Jazzy para Ubuntu 24.04 y vuelve a ejecutar."

  # ROS Jazzy on Noble uses system Python 3.12; do not let an activated Conda
  # environment select its Python (often 3.13) for CMake/ament discovery.
  export PATH="/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
  unset PYTHONHOME PYTHONPATH
  export Python3_EXECUTABLE=/usr/bin/python3
  export Python_EXECUTABLE=/usr/bin/python3

  log "Comprobando herramientas del workspace ROS."
  local missing=()
  command -v colcon >/dev/null 2>&1 || missing+=(python3-colcon-common-extensions)
  command -v vcs >/dev/null 2>&1 || missing+=(python3-vcstool)
  command -v rosdep >/dev/null 2>&1 || missing+=(python3-rosdep)
  if ((${#missing[@]})); then
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
  fi

  if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
    sudo rosdep init
  fi
  rosdep update
}

build_ros_workspace() {
  log "Importando el driver Piper fijado por el repositorio y resolviendo dependencias ROS."
  cd "$ROOT/ros2_ws"
  source_ros_setup
  vcs import --recursive src < src/agilex.repos
  # These two keys are absent from Jazzy's rosdep rules. ament_python is
  # provided by the installed colcon/ament build tooling; the upstream
  # warehouse_ros_mongo dependency is only for the optional MoveIt DB feature.
  rosdep install --from-paths src --ignore-src --rosdistro "$ROS_DISTRO_REQUIRED" \
    --skip-keys="ament_python warehouse_ros_mongo" -r -y

  log "Compilando ROS 2 (paralelismo: ${BUILD_WORKERS})."
  colcon build --symlink-install --parallel-workers "$BUILD_WORKERS" \
    --cmake-clean-cache \
    --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3 -DPython_EXECUTABLE=/usr/bin/python3
  set +u
  # shellcheck disable=SC1091
  source install/setup.bash
  set -u
  ros2 pkg prefix agx_arm_ctrl
  ros2 pkg prefix moveit_servo
  ros2 pkg prefix dream1_piper_ros
}

build_app_image() {
  log "Construyendo la imagen de estación/worker sin arrancar servicios."
  cd "$ROOT"
  sudo docker build --tag dream1-piper:validation --file docker/app.Dockerfile .
}

compose_env_ready() {
  local required=(
    DREAM_API_KEY RSTACK_UI_OPERATOR_TOKEN RSTACK_WORKER_TOKEN RSTACK_SESSION_SECRET
    POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL
    CAMERA_LEFT_HOST CAMERA_TOP_HOST CAMERA_RIGHT_HOST
  )
  local key missing=0
  [[ -f "$ROOT/.env" ]] || { printf 'Falta %s/.env\n' "$ROOT"; return 1; }
  for key in "${required[@]}"; do
    if ! awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); if ($0 !~ /^[[:space:]]*$/) found=1 } END { exit !found }' "$ROOT/.env"; then
      printf 'Falta completar en .env: %s\n' "$key"
      missing=1
    fi
  done
  return "$missing"
}

check_compose_config() {
  cd "$ROOT"
  if compose_env_ready; then
    log "Validando interpolación de Docker Compose (no imprime valores del .env)."
    sudo docker compose --env-file .env config -q
  else
    printf '\nCompose aún no se valida: completa las variables señaladas en .env.\n'
  fi
}

show_hardware_state() {
  log "Diagnóstico de cámaras y CAN; no se habilitan motores."
  if [[ -d /dev/v4l/by-path ]]; then
    ls -l /dev/v4l/by-path
  else
    printf 'No existe /dev/v4l/by-path\n'
  fi
  ip -brief link show type can || true
  for dev in can0 can1; do
    if ip link show "$dev" >/dev/null 2>&1; then
      ip -details link show "$dev"
    else
      printf '%s: no detectado\n' "$dev"
    fi
  done
}

main() {
  require_ubuntu_noble
  log "Validando permisos sudo para las dependencias del sistema."
  sudo -v
  install_docker
  prepare_ros_tools
  build_ros_workspace
  build_app_image
  check_compose_config
  show_hardware_state
  log "Preparación terminada. No se inició ROS launch ni Docker Compose; revisa la asignación de cámaras y CAN antes del arranque local."
}

main "$@"
