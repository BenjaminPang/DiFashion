import os
import subprocess
import argparse
from huggingface_hub import login, hf_hub_download
import time


def download_and_process(num_files, hf_token, processes_count=16, thread_count=64):
    # 启用 Hugging Face 的进度条
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    # 登录到 Hugging Face
    login(hf_token)

    for i in range(num_files):
        # 下载parquet文件
        filename = f"part-{str(i).zfill(5)}-cad4a140-cebd-46fa-b874-e8968f93e32e-c000.snappy.parquet"

        try:
            if not os.path.exists(f"laion2B-en-aesthetic/{filename}"):
                filename = hf_hub_download(
                    repo_id="laion/laion2B-en-aesthetic",
                    filename=filename,
                    repo_type="dataset",
                    local_dir="",
                    force_download=True,
                    resume_download=True,
                )
                time.sleep(1)
                print(f"\nDownloading {filename}...")
            else:
                print(f"\n{filename} Existed...")

            # 处理下载的文件
            print(f"\nProcessing {filename}...")
            cmd = [
                "img2dataset",
                "--url_list", f"laion2B-en-aesthetic/{filename}",
                "--input_format", "parquet",
                "--url_col", "URL",
                "--caption_col", "TEXT",
                "--output_format", "webdataset",
                "--output_folder", f"laion2B-en-aesthetic/data",
                "--processes_count", str(processes_count),
                "--thread_count", str(thread_count),
                "--image_size", "512",
                "--resize_only_if_bigger", "True",
                "--resize_mode", "keep_ratio",
                "--skip_reencode", "True",
                "--save_additional_columns", '["similarity","hash","punsafe","pwatermark","aesthetic"]',
                # "--enable_wandb", "True"
            ]

            subprocess.run(cmd, check=True)

        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Download and process LAION dataset files')
    parser.add_argument('--num_files', type=int, default=1, help='Number of parquet files to download and process')
    parser.add_argument('--hf_token', type=str, required=True, help='Hugging Face API token')
    parser.add_argument('--processes_count', type=int, default=16, help='Number of processes for img2dataset')
    parser.add_argument('--thread_count', type=int, default=64, help='Number of threads for img2dataset')

    args = parser.parse_args()

    download_and_process(
        num_files=args.num_files,
        hf_token=args.hf_token,
        processes_count=args.processes_count,
        thread_count=args.thread_count
    )