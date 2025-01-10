#!/bin/bash

# 确保 Git 安全目录配置存在
git config --global --add safe.directory /workspace/DiFashion/show-o

export PYTHONPATH=/workspace/DiFashion/show-o

# 设置 WANDB API KEY
export WANDB_API_KEY=13a431a3eec762cf4f2029a64a6078788baf7252

# 执行传入的命令
exec "$@"