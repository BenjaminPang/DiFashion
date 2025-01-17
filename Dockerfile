FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 替换为阿里云源
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

# 安装基础工具
RUN apt-get update && apt-get install -y \
    git \
    vim \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    libcurl4-openssl-dev \
    libssl-dev \
    curl \
    pkg-config \
#    libopencv-dev \
    libpng-dev \
    libjpeg-dev \
    libtiff-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgtk2.0-dev \
    ffmpeg \
    ninja-build \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# 安装Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

RUN python3 -m pip install --upgrade pip

# 设置工作目录
WORKDIR /workspace

# 在所有pip install命令之前设置pip源
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

# 复制requirements文件
COPY requirements.txt .
# 首先安装CUDA版本的PyTorch
RUN pip3 install torch==2.2.1 torchvision==0.17.1 --index-url https://download.pytorch.org/whl/cu121
# 然后安装其他依赖
RUN pip install -r requirements.txt

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# 启动命令
CMD ["/bin/bash"]
