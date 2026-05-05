# DGX Spark Parakeet CUDA deployment

This profile runs the web UI as a local Parakeet transcription queue on an
NVIDIA DGX Spark or another Linux CUDA host. It is intentionally separate from
the macOS MLX release path.

## Runtime

- Image: built from `Dockerfile.spark`
- Base image: `nvcr.io/nvidia/nemo:26.02.01` by default
- Backend: `parakeet_nemo_cuda`
- Experimental gate: `PARAKEET_NEMO_CUDA_EXPERIMENTAL=1`
- Default model: `nvidia/parakeet-tdt-0.6b-v3`
- Default bind: `127.0.0.1:32000`
- App data: `./data-spark`
- Hugging Face cache: `~/.cache/huggingface`
- Container user: root by default, because the NGC NeMo image ships some
  Megatron/NeMo files without world-readable permissions

## Start

```bash
./docker-run-spark.sh
```

The script writes `data-spark/settings.json` on first run with:

- `engine=parakeet_tdt_v3`
- `output_formats=["txt","srt","vtt","json"]`
- `default_language=auto`
- `parakeet_batch_size=1`

It does not overwrite an existing settings file.

## Common overrides

```bash
PARAKEET_MODEL=nvidia/parakeet-unified-en-0.6b ./docker-run-spark.sh
PORT=32100 DATA_DIR=/home/neo/services/parakeet-webui/data ./docker-run-spark.sh
HF_CACHE_DIR=/home/neo/.cache/huggingface ./docker-run-spark.sh
RUN_AS_ROOT=0 ./docker-run-spark.sh
```

Use `RUN_AS_ROOT=0` only with a base image whose NeMo/Megatron files are readable
by arbitrary UIDs.

## Media handling

The NeMo/CUDA Parakeet backend now checks whether the upload is already a
16 kHz mono PCM WAV. If not, it uses `ffmpeg` to create a temporary
16 kHz mono WAV and sends that to NeMo. This covers typical video uploads and
also normalizes stereo or non-16 kHz audio before inference.

Set `PARAKEET_FFMPEG_PATH` inside the container if `ffmpeg` is not on `PATH`.

## home-spark notes

Keep this service bound to `127.0.0.1`. If it is exposed through FRP or a
reverse proxy, put it behind the existing authentication layer. A natural local
port assignment next to the current Qwen endpoint is:

- Qwen/vLLM: `127.0.0.1:31000`
- Parakeet UI: `127.0.0.1:32000`

Parakeet is much smaller than the current Qwen model, but DGX Spark unified
memory is still shared. Use `parakeet_batch_size=1` while Qwen is running.
