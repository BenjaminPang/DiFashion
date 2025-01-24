FROM python:3.10-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    wget \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 升级pip和setuptools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 安装Python依赖
RUN pip install --no-cache-dir \
    huggingface_hub \
    img2dataset \
    pandas \
    pyarrow \
    wandb \
    hf_transfer

# 创建工作目录
WORKDIR /workspace

# 设置环境变量
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV WANDB_API_KEY=13a431a3eec762cf4f2029a64a6078788baf7252

# 设置默认命令
CMD ["/bin/bash"]