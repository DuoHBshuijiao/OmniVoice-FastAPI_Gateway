#!/usr/bin/env python3
# Copyright    2026  Xiaomi Corp.
#
# Licensed under the Apache License, Version 2.0

"""FastAPI HTTP gateway for OmniVoice TTS (no Gradio).

Environment (optional):
  OMNIVOICE_MODEL   HuggingFace repo id or local path (default: k2-fsa/OmniVoice)
  OMNIVOICE_DEVICE  e.g. cuda:0, cuda, mps, cpu — unset = auto (CUDA > MPS > CPU)
  OMNIVOICE_CORS_ORIGINS  Comma-separated origins, or * (default)
"""

from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

import torch
import torchaudio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from omnivoice.models.omnivoice import OmniVoice

logger = logging.getLogger(__name__)

_model: Optional[OmniVoice] = None


def get_best_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model(model_id: str, device: Optional[str]) -> OmniVoice:
    dev = device if device else get_best_device()
    logger.info("Loading OmniVoice from %s on %s ...", model_id, dev)
    return OmniVoice.from_pretrained(model_id, device_map=dev, dtype=torch.float16)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    model_id = os.environ.get("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
    device = os.environ.get("OMNIVOICE_DEVICE")
    if device is not None and device.strip() == "":
        device = None
    _model = _load_model(model_id, device)
    try:
        yield
    finally:
        _model = None


app = FastAPI(
    title="OmniVoice API",
    description="Zero-shot TTS over HTTP (voice clone / design / auto).",
    version="0.1.0",
    lifespan=lifespan,
)

_origins = os.environ.get("OMNIVOICE_CORS_ORIGINS", "*")
_cors_list = ["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    """JSON body for POST /v1/tts."""

    text: str = Field(..., min_length=1, description="Text to synthesize.")
    ref_audio_base64: Optional[str] = Field(
        None,
        description="Optional WAV bytes as standard base64 (or data:audio/...;base64,...).",
    )
    ref_text: Optional[str] = None
    instruct: Optional[str] = None
    language: Optional[str] = None
    num_step: int = 32
    guidance_scale: float = 2.0
    speed: float = 1.0
    duration: Optional[float] = None
    t_shift: float = 0.1
    denoise: bool = True
    postprocess_output: bool = True
    layer_penalty_factor: float = 5.0
    position_temperature: float = 5.0
    class_temperature: float = 0.0


def _wav_bytes(waveform: torch.Tensor, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    torchaudio.save(buf, waveform, sample_rate, format="wav")
    return buf.getvalue()


def _synthesize(req: TTSRequest, ref_audio_path: Optional[str]) -> Response:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded.")

    audios = _model.generate(
        text=req.text,
        language=req.language,
        ref_audio=ref_audio_path,
        ref_text=req.ref_text,
        instruct=req.instruct,
        duration=req.duration,
        num_step=req.num_step,
        guidance_scale=req.guidance_scale,
        speed=req.speed,
        t_shift=req.t_shift,
        denoise=req.denoise,
        postprocess_output=req.postprocess_output,
        layer_penalty_factor=req.layer_penalty_factor,
        position_temperature=req.position_temperature,
        class_temperature=req.class_temperature,
    )
    sr = getattr(_model, "sampling_rate", 24000)
    return Response(content=_wav_bytes(audios[0], sr), media_type="audio/wav")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/v1/tts")
def tts_json(body: TTSRequest) -> Response:
    tmp_path: Optional[str] = None
    try:
        if body.ref_audio_base64:
            raw = body.ref_audio_base64.strip()
            if raw.startswith("data:") and "," in raw:
                raw = raw.split(",", 1)[1]
            try:
                data = base64.b64decode(raw, validate=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}") from e
            fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(data)
        return _synthesize(body, tmp_path)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/v1/tts/upload")
async def tts_upload(
    text: str = Form(..., description="Text to synthesize."),
    ref_audio: Optional[UploadFile] = File(None),
    ref_text: Optional[str] = Form(None),
    instruct: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    num_step: int = Form(32),
    guidance_scale: float = Form(2.0),
    speed: float = Form(1.0),
    duration: Optional[float] = Form(None),
    t_shift: float = Form(0.1),
    denoise: bool = Form(True),
    postprocess_output: bool = Form(True),
    layer_penalty_factor: float = Form(5.0),
    position_temperature: float = Form(5.0),
    class_temperature: float = Form(0.0),
) -> Response:
    tmp_path: Optional[str] = None
    try:
        if ref_audio is not None:
            content = await ref_audio.read()
            if content:
                fd, tmp_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                with open(tmp_path, "wb") as f:
                    f.write(content)
        req = TTSRequest(
            text=text,
            ref_audio_base64=None,
            ref_text=ref_text,
            instruct=instruct,
            language=language,
            num_step=num_step,
            guidance_scale=guidance_scale,
            speed=speed,
            duration=duration,
            t_shift=t_shift,
            denoise=denoise,
            postprocess_output=postprocess_output,
            layer_penalty_factor=layer_penalty_factor,
            position_temperature=position_temperature,
            class_temperature=class_temperature,
        )
        return _synthesize(req, tmp_path)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniVoice FastAPI HTTP gateway (no Gradio).")
    parser.add_argument("--host", default=os.environ.get("OMNIVOICE_API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OMNIVOICE_API_PORT", "8080")))
    parser.add_argument(
        "--model",
        default=os.environ.get("OMNIVOICE_MODEL", "k2-fsa/OmniVoice"),
        help="HuggingFace repo id or local checkpoint path.",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("OMNIVOICE_DEVICE", ""),
        help="Inference device (e.g. cuda:0). Empty = auto.",
    )
    args = parser.parse_args()

    os.environ["OMNIVOICE_MODEL"] = args.model
    if args.device.strip():
        os.environ["OMNIVOICE_DEVICE"] = args.device.strip()
    else:
        os.environ.pop("OMNIVOICE_DEVICE", None)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import uvicorn

    uvicorn.run(
        "omnivoice.api.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
