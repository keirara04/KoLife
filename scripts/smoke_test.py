"""Day-1 smoke test: one live call per model, prints status + usage + cost.

Run from repo root:
    cd api && uv run --with meta-sam-parser python ../scripts/smoke_test.py

Checks: Wonder (expected 404 from KR), Spark 1.3 plain + structured output (text.format),
Muse Image -> SAM 3.1 on that image (mask decoded in Python), Voice Transcribe on a
Korean WAV made with macOS `say`, Baseten Spark Open (skipped without BASETEN_API_KEY).
Media goes to a temp dir, never the repo. Usage appended to logs/usage.jsonl.
Expected total < $0.05.
"""

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# python.org macOS builds ship without CA certs; use the system bundle
if not os.environ.get("SSL_CERT_FILE") and Path("/etc/ssl/cert.pem").exists():
    os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"
os.chdir(ROOT / "api")  # Settings reads ../.env relative to api/
sys.path.insert(0, str(ROOT / "api"))

from app.config import settings  # noqa: E402
from app.core import models as m  # noqa: E402

BASETEN_URL = "https://inference.baseten.co/v1"
TMP = Path(tempfile.mkdtemp(prefix="kolife-smoke-"))
LOG = ROOT / "logs" / "usage.jsonl"
results: list[tuple[str, str, float, str]] = []  # (check, status, cost, note)


def http(method: str, url: str, key: str, body: bytes | None = None,
         ctype: str = "application/json") -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": ctype, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            status, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def meta(path: str, body: dict) -> tuple[int, dict | str, float]:
    t = time.time()
    status, data = http("POST", f"{settings.meta_base_url}{path}", settings.meta_api_key,
                        json.dumps(body).encode())
    if status == 401:
        sys.exit("401 from Meta — check META_API_KEY in .env (rotated key?)")
    return status, data, time.time() - t


def output_text(resp: dict) -> str:
    return "".join(c.get("text", "") for item in resp.get("output", [])
                   if item.get("type") == "message" for c in item.get("content", []))


def log(model: str, usage: dict, cost: float, secs: float) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "source": "smoke_test", "model": model,
                            "usage": usage, "cost_usd": round(cost, 6), "secs": round(secs, 2)}) + "\n")


def record(check: str, ok: bool | None, cost: float = 0.0, note: str = "") -> None:
    status = "INFO" if ok is None else ("OK" if ok else "FAIL")
    results.append((check, status, cost, note))
    print(f"[{status}] {check}  ${cost:.5f}  {note}")


def responses(model: str, effort: str, **extra) -> tuple[int, dict | str, float]:
    body = {"model": model, "reasoning": {"effort": effort}, "store": False,
            "include": ["reasoning.encrypted_content"], **extra}
    return meta("/responses", body)


def usage_note(u: dict) -> str:
    cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
    reasoning = (u.get("output_tokens_details") or {}).get("reasoning_tokens", "?")
    return f"in={u.get('input_tokens')} cached={cached} out={u.get('output_tokens')} reasoning={reasoning}"


def check_wonder() -> None:
    status, data, _ = responses(m.WONDER, "minimal", input="Reply with OK", max_output_tokens=50)
    if status == 200:
        cost = m.token_cost(m.WONDER, data["usage"])
        log(m.WONDER, data["usage"], cost, 0)
        record("wonder", True, cost, "AVAILABLE from here — revisit decision on orchestrator")
    else:
        record("wonder", None, 0, f"HTTP {status} (expected from KR): {str(data)[:120]}")


def check_spark() -> bool:
    status, data, secs = responses(m.SPARK, "minimal", input="Reply with OK", max_output_tokens=200)
    if status != 200:
        record("spark plain", False, 0, f"HTTP {status}: {str(data)[:300]}")
        return False
    u = data["usage"]
    cost = m.token_cost(m.SPARK, u)
    log(m.SPARK, u, cost, secs)
    record("spark plain", True, cost, f"{secs:.1f}s {usage_note(u)} text={output_text(data)[:40]!r}")
    return True


def check_structured() -> None:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["deadline", "amount_krw"],
              "properties": {"deadline": {"type": "string", "description": "YYYY-MM-DD"},
                             "amount_krw": {"type": "integer"}}}
    status, data, secs = responses(
        m.SPARK, "low", max_output_tokens=500,
        input="Extract fields. Notice: NHIS premium of ₩123,400 is due by 2026-11-25.",
        text={"format": {"type": "json_schema", "name": "notice", "schema": schema, "strict": True}})
    if status != 200:
        record("spark text.format", False, 0, f"HTTP {status}: {str(data)[:400]}")
        return
    u = data["usage"]
    cost = m.token_cost(m.SPARK, u)
    log(m.SPARK, u, cost, secs)
    try:
        parsed = json.loads(output_text(data))
        ok = parsed == {"deadline": "2026-11-25", "amount_krw": 123400}
        record("spark text.format", ok, cost, f"{secs:.1f}s parsed={parsed}")
    except json.JSONDecodeError:
        record("spark text.format", False, cost, f"not JSON: {output_text(data)[:200]!r}")


def check_image() -> Path | None:
    status, data, secs = meta("/images/generations", {
        "model": m.IMAGE, "prompt": "a photo of one red apple on a plain white table",
        "n": 1, "size": "1024x1024", "output_format": "png"})
    if status != 200:
        record("muse image", False, 0, f"HTTP {status}: {str(data)[:300]}")
        return None
    path = TMP / "apple.png"
    path.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
    cost = m.IMAGE_PER_IMAGE * len(data["data"])
    log(m.IMAGE, data.get("usage", {}), cost, secs)
    record("muse image", True, cost, f"{secs:.1f}s {path.stat().st_size // 1024} KB -> {path}")
    return path


def check_sam(image: Path) -> None:
    url = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
    status, data, secs = meta("/responses", {"model": m.SAM, "store": False, "input": [
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "apple"},
            {"type": "input_image", "image_url": url}]}]})
    if status != 200:
        record("sam 3.1", False, 0, f"HTTP {status}: {str(data)[:300]}")
        return
    cost = m.SAM_PER_IMAGE
    log(m.SAM, data.get("usage", {}), cost, secs)
    text = output_text(data)
    boxes = re.findall(r"<\|box;([^|]*)\|>", text)
    masks = re.findall(r"<\|mask;[^|]*?data=(\d+),(\d+),([^|]+)\|>", text)
    if not boxes:
        record("sam 3.1", False, cost, f"no detections; raw={text[:200]!r}")
        return
    note = f"{secs:.1f}s {len(boxes)} box(es), first: {boxes[0]}"
    try:
        from meta_sam_parser import SegmentationMask, decode_mask_to_raster
    except ImportError:
        record("sam 3.1", True, cost, note + " | mask NOT decoded (run with --with meta-sam-parser)")
        return
    h, w, payload = masks[0]
    enc = "lossless" if payload.startswith("~") else "one_bit"
    raster = decode_mask_to_raster(SegmentationMask(enc, payload, int(w), int(h)))
    ok = len(raster) == int(h) * int(w) and sum(raster) > 0
    record("sam 3.1", ok, cost, note + f" | mask {h}x{w} {enc}, {sum(raster)} px on")


def check_voice() -> None:
    wav = TMP / "hello.wav"
    subprocess.run(["say", "-v", "Yuna", "-o", str(wav), "--file-format=WAVE",
                    "--data-format=LEI16@16000",
                    "안녕하세요. 건강보험료 납부 기한은 십일월 이십오일입니다."], check=True)
    if wav.stat().st_size < 16000:  # some voices (Flo, Eddy) silently write empty WAVs
        record("voice transcribe", False, 0, f"`say` produced near-empty WAV: {wav}")
        return
    boundary = uuid.uuid4().hex
    req_json = json.dumps({"model": m.VOICE, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                           "languageBias": ["Korean"]})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n"
            f"Content-Type: application/json\r\n\r\n{req_json}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"hello.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    t = time.time()
    status, data = http("POST", f"{settings.meta_base_url}/asr/transcribe", settings.meta_api_key,
                        body, f"multipart/form-data; boundary={boundary}")
    secs = time.time() - t
    if status != 200 or not isinstance(data, dict):
        record("voice transcribe", False, 0, f"HTTP {status}: {str(data)[:300]}")
        return
    cost = m.voice_cost(data.get("audioDurationMs", 0))
    log(m.VOICE, {"audioDurationMs": data.get("audioDurationMs")}, cost, secs)
    record("voice transcribe", bool(data.get("transcript")), cost,
           f"{secs:.1f}s {data.get('audioDurationMs')}ms turns={len(data.get('turns', []))} "
           f"text={data.get('transcript', '')[:60]!r}")


def check_baseten() -> None:
    if not settings.baseten_api_key:
        record("baseten spark open", None, 0, "SKIPPED: BASETEN_API_KEY empty")
        return
    t = time.time()
    status, data = http("POST", f"{BASETEN_URL}/responses", settings.baseten_api_key, json.dumps(
        {"model": settings.baseten_model, "input": "Reply with OK", "max_output_tokens": 50}).encode())
    secs = time.time() - t
    if status == 200 and isinstance(data, dict):
        u = data.get("usage", {})
        log(settings.baseten_model, u, 0.0, secs)
        record("baseten spark open", True, 0, f"{secs:.1f}s (Baseten credits) {usage_note(u)} "
               f"text={output_text(data)[:40]!r}")
        return
    note = f"HTTP {status}: {str(data)[:200]}"
    if status == 404:
        _, models = http("GET", f"{BASETEN_URL}/models", settings.baseten_api_key)
        ids = [x.get("id") for x in models.get("data", [])] if isinstance(models, dict) else models
        note += f" | available: {ids}"
    record("baseten spark open", False, 0, note)


def main() -> None:
    if not settings.meta_api_key:
        sys.exit("META_API_KEY empty — set it in .env")
    check_wonder()
    spark_ok = check_spark()
    check_structured()
    image = check_image()
    if image:
        check_sam(image)
    else:
        record("sam 3.1", None, 0, "SKIPPED: no image")
    check_voice()
    check_baseten()
    total = sum(r[2] for r in results)
    print(f"\nTotal Meta spend this run: ${total:.4f}  (media in {TMP})")
    sys.exit(0 if spark_ok else 1)


if __name__ == "__main__":
    main()
