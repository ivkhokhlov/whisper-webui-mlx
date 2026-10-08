# DGX Spark Parakeet CUDA deployment

This profile runs the web UI as a local Parakeet transcription queue on an
NVIDIA DGX Spark or another Linux CUDA host. It is intentionally separate from
the macOS MLX release path.

## Runtime

- Image: built from `Dockerfile.spark`
- Base image: official `nvcr.io/nvidia/nemo:26.02.01`, pinned by manifest digest
  in `Dockerfile.spark` and `docker-run-spark.sh`
- Backend: `parakeet_nemo_cuda`
- Experimental gate: `PARAKEET_NEMO_CUDA_EXPERIMENTAL=1`
- Default model: `nvidia/parakeet-tdt-0.6b-v3`
- Default bind: `127.0.0.1:32000`
- App data: `./data-spark`
- Hugging Face cache: `~/.cache/huggingface`
- CUDA watchdog: enabled, probes GPU access every 15 seconds
- CUDA execution is strict: CUDA OOM remains a visible job failure
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

JSON transcript artifacts contain the automatically classified ISO 639-1
`language` and a normalized `language_confidence` when the completed transcript
is long and distinctive enough. The detector is restricted to Parakeet TDT
v3's 25 supported languages. Ambiguous or very short transcripts keep both
fields null instead of echoing the request mode `auto`.

## Common overrides

```bash
PARAKEET_MODEL=nvidia/parakeet-unified-en-0.6b ./docker-run-spark.sh
PORT=32100 DATA_DIR=/home/neo/services/parakeet-webui/data ./docker-run-spark.sh
HF_CACHE_DIR=/home/neo/.cache/huggingface ./docker-run-spark.sh
RUN_AS_ROOT=0 ./docker-run-spark.sh
```

Use `RUN_AS_ROOT=0` only with a base image whose NeMo/Megatron files are readable
by arbitrary UIDs.

On home-spark, direct NGC access returns HTTP 403. The production build instead
uses the private [NeMo image cache](../deploy/nemo-registry/README.md) on vps-nl,
with the same NVIDIA digest. `NEMO_BASE_IMAGE` is a build-time Coolify variable;
Docker credentials belong to Coolify's SSH user on the build host. For the
standalone launcher, select the mirror explicitly:

```bash
docker login registry.m10a.space
NEMO_BASE_IMAGE=registry.m10a.space/nvidia/nemo:26.02.01@sha256:5852a213751955315a5dd54ce50eff69ac87d474f33968135fc88f1cdbb1dd06 ./docker-run-spark.sh
```

Build from this upstream image. A prior application image, or an exported and
imported filesystem, is not a NeMo base and must not be assigned its official
tag. The cache configuration and recovery procedure are versioned with the app.

The web app uses FastAPI 0.121.3 and Uvicorn 0.42, compatible with the newer
Starlette required by this NeMo image. Do not downgrade the container's web
stack to FastAPI 0.115/Starlette 0.46. The upstream NVIDIA image also contains
unrelated training/inference packages with pre-existing `pip check` warnings.
The application does not claim that every optional package in this full NeMo
image has a consistent dependency set; validate the ASR path with real GPU
inference when changing its base.

## Media handling

The NeMo/CUDA Parakeet backend now checks whether the upload is already a
16 kHz mono PCM WAV. If not, it uses `ffmpeg` to create a temporary
16 kHz mono WAV and sends that to NeMo. This covers typical video uploads and
also normalizes stereo or non-16 kHz audio before inference.

Set `PARAKEET_FFMPEG_PATH` inside the container if `ffmpeg` is not on `PATH`.

## CUDA access recovery

The Spark image starts the app through a small CUDA supervisor. It checks
`nvidia-smi -L` before Uvicorn starts and then every 15 seconds. Two consecutive
probe failures stop the app and exit the container so an `unless-stopped` (or
equivalent) restart policy can restore the NVIDIA device bindings. The image
healthcheck verifies both GPU access and `/api/state`.

The defaults can be adjusted when diagnosing a host:

```bash
PARAKEET_CUDA_PROBE_INTERVAL=30
PARAKEET_CUDA_PROBE_TIMEOUT=10
PARAKEET_CUDA_PROBE_FAILURES=3
```

Set `PARAKEET_CUDA_WATCHDOG=0` only for debugging. A job that was active at the
instant GPU access disappeared can still be marked failed; retry it after the
container becomes healthy again.

If CUDA remains visible but another service has reserved too much unified
memory, model loading or inference fails explicitly with CUDA OOM. The Spark
profile does not silently retry on CPU: selecting the CUDA backend is an
execution contract, and on DGX Spark the CPU and GPU already share the same
physical memory pool. The normal queue failure/retry path remains responsible
for surfacing and retrying the job after memory pressure is resolved.

### `NVML: Unknown Error` or `CUFFT_INTERNAL_ERROR`

NVIDIA documents a container-toolkit failure mode where a container launched
through the legacy `--gpus` hook loses its GPU cgroup access after a container
update or `systemctl daemon-reload`. Typical evidence is:

```text
Failed to initialize NVML: Unknown Error
CUDA_ERROR_NO_DEVICE
cuFFT error: CUFFT_INTERNAL_ERROR
```

The immediate recovery is to recreate the affected container. The repository
launcher also maps the available `/dev/nvidia*` compute devices explicitly by
default, so `runc` knows about them when cgroups are updated. Disable that only
when isolating a launch problem:

```bash
SPARK_EXPLICIT_GPU_DEVICES=0 ./docker-run-spark.sh
```

For orchestrators that do not use `docker-run-spark.sh`, fix the host as well:
prefer NVIDIA CDI device injection, or configure Docker's `cgroupfs` cgroup
driver as described in the official
[NVIDIA Container Toolkit troubleshooting guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html#containers-losing-access-to-gpus-with-error-failed-to-initialize-nvml-unknown-error).
The watchdog is a recovery guard, not a substitute for that host-level
prevention.

## home-spark notes

Keep this service bound to `127.0.0.1`. If it is exposed through FRP or a
reverse proxy, put it behind the existing authentication layer. A natural local
port assignment next to the current Qwen endpoint is:

- Qwen/vLLM: `127.0.0.1:31000`
- Parakeet UI: `127.0.0.1:32000`

Parakeet is much smaller than the current Qwen model, but DGX Spark unified
memory is still shared. Use `parakeet_batch_size=1` while Qwen is running.
