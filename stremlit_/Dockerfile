# Dockerfile (clang-19 preferred, fallback to clang-18)
FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul \
    HOME=/app \
    STREAMLIT_HOME=/app/.streamlit \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false \
    # LLM defaults
    OLLAMA_BASE_URL="http://localhost:11434/v1" \
    LLM_READ_TIMEOUT="600" \
    LLM_NUM_PREDICT="512" \
    MAX_FINDINGS_FOR_PROMPT="12" \
    MAX_EXCERPT_LINES_PER_FILE="80" \
    MAX_FILES_IN_CONTEXT="3" \
    LLM_RETRIES="2" \
    # SDK Path moved to /opt to avoid override by volume mount
    PICO_SDK_PATH=/opt/pico-sdk \
    PICO_SDK_FETCH_FROM_GIT=0

ENV ARM_TOOLCHAIN_VER=12.2.rel1
ENV ARM_TOOLCHAIN_URL=https://developer.arm.com/-/media/Files/downloads/gnu/12.2.rel1/binrel/arm-gnu-toolchain-12.2.rel1-x86_64-arm-none-eabi.tar.xz
ENV ARM_TOOLCHAIN_PATH=/opt/gcc-arm-none-eabi-12.2.rel1
ENV PATH="${ARM_TOOLCHAIN_PATH}/bin:${PATH}"

# 0. Base deps + add LLVM apt repository
# - bookworm 기준으로 작성
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg apt-transport-https \
    ; \
    rm -rf /var/lib/apt/lists/*

# LLVM repo key & list (optional)
# - If apt.llvm.org does not provide the current Debian codename (e.g., trixie),
#   skip adding the repo to avoid apt-get update failures.
RUN set -eux; \
    . /etc/os-release; \
    CODENAME="${VERSION_CODENAME:-bookworm}"; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/llvm.gpg; \
    rm -f /etc/apt/sources.list.d/llvm.list; \
    if curl -fsSL "https://apt.llvm.org/${CODENAME}/dists/llvm-toolchain-${CODENAME}-19/Release" >/dev/null 2>&1; then \
        echo "deb [signed-by=/etc/apt/keyrings/llvm.gpg] https://apt.llvm.org/${CODENAME}/ llvm-toolchain-${CODENAME}-19 main" > /etc/apt/sources.list.d/llvm.list; \
        echo "deb [signed-by=/etc/apt/keyrings/llvm.gpg] https://apt.llvm.org/${CODENAME}/ llvm-toolchain-${CODENAME}-18 main" >> /etc/apt/sources.list.d/llvm.list; \
        echo "INFO: Enabled LLVM repo for ${CODENAME} (18/19)"; \
    elif curl -fsSL "https://apt.llvm.org/${CODENAME}/dists/llvm-toolchain-${CODENAME}-18/Release" >/dev/null 2>&1; then \
        echo "deb [signed-by=/etc/apt/keyrings/llvm.gpg] https://apt.llvm.org/${CODENAME}/ llvm-toolchain-${CODENAME}-18 main" > /etc/apt/sources.list.d/llvm.list; \
        echo "INFO: Enabled LLVM repo for ${CODENAME} (18)"; \
    else \
        echo "INFO: apt.llvm.org does not provide '${CODENAME}' - skipping LLVM repo"; \
    fi


# 1. Install System Dependencies & Tools
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git \
        subversion \
        build-essential gcc g++ make \
        cmake ninja-build pkg-config \
        cppcheck \
        gcovr \
        doxygen graphviz clang-format \
        qemu-system-arm \
        xxd tar xz-utils \
        fonts-nanum \
    ; \
    \
    if apt-cache show clang-19 >/dev/null 2>&1; then \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            clang-19 llvm-19 lld-19 \
            clang-tidy-19 \
            libclang-rt-19-dev \
        ; \
        update-alternatives --install /usr/bin/clang clang /usr/bin/clang-19 100; \
        update-alternatives --install /usr/bin/clang++ clang++ /usr/bin/clang++-19 100; \
        update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-19 100; \
        update-alternatives --install /usr/bin/clang-tidy clang-tidy /usr/bin/clang-tidy-19 100; \
        update-alternatives --install /usr/bin/ld.lld ld.lld /usr/bin/ld.lld-19 100; \
    elif apt-cache show clang-18 >/dev/null 2>&1; then \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            clang-18 llvm-18 lld-18 \
            clang-tidy-18 \
            libclang-rt-18-dev \
        ; \
        update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 100; \
        update-alternatives --install /usr/bin/clang++ clang++ /usr/bin/clang++-18 100; \
        update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-18 100; \
        update-alternatives --install /usr/bin/clang-tidy clang-tidy /usr/bin/clang-tidy-18 100; \
        update-alternatives --install /usr/bin/ld.lld ld.lld /usr/bin/ld.lld-18 100; \
    else \
        echo "WARN: clang-18/19 packages not found even with LLVM repo. Installing default clang stack."; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            clang llvm clang-tidy libclang-rt-dev \
        ; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# 2. Install ARM Toolchain
RUN set -eux; \
    curl -L ${ARM_TOOLCHAIN_URL} -o /tmp/arm.tar.xz; \
    mkdir -p ${ARM_TOOLCHAIN_PATH}; \
    tar -xf /tmp/arm.tar.xz -C ${ARM_TOOLCHAIN_PATH} --strip-components=1; \
    rm /tmp/arm.tar.xz

WORKDIR /app
RUN mkdir -p /app/.streamlit

# 3. Install Python Dependencies
COPY requirements*.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 4. Pico SDK Setup
RUN set -eux; \
    mkdir -p /opt; \
    git clone -b 1.5.1 --depth=1 https://github.com/raspberrypi/pico-sdk.git ${PICO_SDK_PATH}; \
    git -C ${PICO_SDK_PATH} submodule update --init --recursive

# 5. Copy Source Code
COPY . /app

EXPOSE 8501

# 6. Run Application
CMD ["python", "-m", "streamlit", "run", "gui/app.py", "--server.headless=true", "--server.port=8501"]
