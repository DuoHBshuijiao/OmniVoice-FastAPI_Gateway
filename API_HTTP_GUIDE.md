# OmniVoice HTTP API 接入指南

本文说明如何将本仓库提供的 **FastAPI TTS 网关**（`omnivoice.api.server`）接入本地或局域网内的其它应用。该服务 **不依赖 Gradio**，通过标准 HTTP 返回 WAV 音频。

---

## 1. 服务概览

| 项目 | 说明 |
|------|------|
| 实现位置 | `omnivoice/api/server.py` |
| 默认监听 | `0.0.0.0:8080`（可通过参数或环境变量修改） |
| 交互式文档 | 服务启动后访问 `http://<主机>:<端口>/docs`（Swagger UI） |
| 备用文档 | `http://<主机>:<端口>/redoc` |
| 认证 | 当前实现 **无鉴权**；若暴露到公网，请在前面加反向代理（HTTPS、API Key、防火墙等） |

**三种合成模式**（与 Python API / CLI 一致）：

1. **自动音色**：仅提供 `text`，不提供 `ref_audio` / `instruct`。
2. **音色设计**：提供 `instruct`（如 `female, British accent`），无需参考音频。
3. **声音克隆**：提供参考音频 + 可选 `ref_text`（可省略，由模型侧 ASR 自动转写，与官方行为一致）。

---

## 2. 启动服务

在仓库根目录激活虚拟环境后执行其一即可。

### 2.1 使用控制台脚本（推荐）

```powershell
Set-Location E:\OmniVoice
.\.venv\Scripts\Activate.ps1
$env:OMNIVOICE_DEVICE = "cuda:0"
omnivoice-api --host 0.0.0.0 --port 8080 --model k2-fsa/OmniVoice
```

### 2.2 使用 uvicorn

若使用 `uvicorn` 直接启动，需在进程环境中设置模型与设备（脚本参数不会自动生效）：

```powershell
$env:OMNIVOICE_MODEL = "k2-fsa/OmniVoice"
$env:OMNIVOICE_DEVICE = "cuda:0"
uvicorn omnivoice.api.server:app --host 0.0.0.0 --port 8080
```

### 2.3 环境变量一览

| 变量 | 含义 | 默认 |
|------|------|------|
| `OMNIVOICE_MODEL` | Hugging Face 仓库 ID 或本地权重路径 | `k2-fsa/OmniVoice` |
| `OMNIVOICE_DEVICE` | 推理设备，如 `cuda:0`、`cuda`、`mps`、`cpu` | 未设置时 **自动**：CUDA → MPS → CPU |
| `OMNIVOICE_CORS_ORIGINS` | 允许的浏览器来源；`*` 表示全部；多个用英文逗号分隔 | `*` |
| `OMNIVOICE_API_HOST` | 仅在被 `omnivoice-api` 读取时的默认 host | `0.0.0.0` |
| `OMNIVOICE_API_PORT` | 仅在被 `omnivoice-api` 读取时的默认端口 | `8080` |

**Hugging Face 下载较慢时**（中国大陆常见），可在启动前设置镜像（与官方 README 一致）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

首次启动会从网络拉取模型，耗时取决于带宽；完成后推理在本地执行。

---

## 3. 通用约定

### 3.1 Base URL

下文以 `http://127.0.0.1:8080` 为例。局域网内其它机器请将 `127.0.0.1` 换为运行服务的主机 IP，并确保防火墙放行端口。

### 3.2 成功响应

- **HTTP 状态码**：`200`
- **`Content-Type`**：`audio/wav`
- **Body**：WAV 文件二进制流（采样率一般为 **24000 Hz**，以服务端实际模型为准）

客户端应把响应体 **原样写入文件**（如 `output.wav`）或交给音频解码器播放。

### 3.3 错误响应

| 场景 | 典型状态码 | 说明 |
|------|------------|------|
| JSON 字段校验失败 | `422` | 请求体不符合 schema（如缺少 `text`） |
| Base64 音频非法 | `400` | `ref_audio_base64` 无法解码 |
| 模型未就绪 | `503` | 极少见；例如启动阶段异常 |

错误体一般为 JSON，`detail` 字段含说明；以 `/docs` 中实际返回为准。

### 3.4 跨域（CORS）

服务已挂载 `CORSMiddleware`。浏览器网页前端调用时：

- 开发环境可将 `OMNIVOICE_CORS_ORIGINS` 设为 `*` 或具体前端 origin（如 `http://localhost:5173`）。
- 生产环境建议 **收窄** 为实际前端地址，避免任意网站调用。

---

## 4. 接口说明

### 4.1 `GET /health`

**用途**：健康检查、编排系统探活。

**响应示例**（`200`，`application/json`）：

```json
{
  "status": "ok",
  "model_loaded": true
}
```

`model_loaded` 为 `true` 表示启动阶段已加载权重，可对外提供合成。

---

### 4.2 `POST /v1/tts`

**用途**：以 **JSON** 提交参数；可选 **Base64** 内联参考音频（适合无文件上传能力的客户端）。

**请求头**：

- `Content-Type: application/json`

**请求体字段**（Pydantic 模型 `TTSRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 待合成文本 |
| `ref_audio_base64` | string \| null | 否 | 参考音频 WAV 的 Base64；支持纯 Base64 或 `data:audio/wav;base64,...` 形式 |
| `ref_text` | string \| null | 否 | 参考音频对应文本（克隆模式） |
| `instruct` | string \| null | 否 | 音色设计描述（与设计模式一致） |
| `language` | string \| null | 否 | 语言名或代码，如 `English`、`en` |
| `num_step` | integer | 否 | 扩散步数，默认 `32`（可改为 `16` 提速） |
| `guidance_scale` | number | 否 | 默认 `2.0` |
| `speed` | number | 否 | 语速因子，默认 `1.0` |
| `duration` | number \| null | 否 | 固定输出时长（秒）；设置后会覆盖与时长相关的速度策略 |
| `t_shift` | number | 否 | 默认 `0.1` |
| `denoise` | boolean | 否 | 默认 `true` |
| `postprocess_output` | boolean | 否 | 默认 `true` |
| `layer_penalty_factor` | number | 否 | 默认 `5.0` |
| `position_temperature` | number | 否 | 默认 `5.0` |
| `class_temperature` | number | 否 | 默认 `0.0` |

**模式组合**：

- 仅 `text` → 自动音色。
- `text` + `instruct` → 音色设计。
- `text` + `ref_audio_base64`（+ 可选 `ref_text`）→ 声音克隆。

**响应**：`200` + `audio/wav` 二进制。

---

### 4.3 `POST /v1/tts/upload`

**用途**：以 **multipart/form-data** 上传参考音频文件（适合浏览器 `FormData`、curl `-F`）。

**请求头**：

- `Content-Type: multipart/form-data`（由客户端库自动带 boundary，勿手写为固定字符串）

**表单字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 待合成文本 |
| `ref_audio` | file | 否 | 参考音频文件（一般为 WAV） |
| `ref_text` | string | 否 | 参考文本 |
| `instruct` | string | 否 | 音色设计 |
| `language` | string | 否 | 语言 |
| 其余数值/布尔参数 | 与 `/v1/tts` JSON 中同名字段一致 | 否 | 缺省值与 JSON API 相同 |

未上传 `ref_audio` 且未传 `instruct` 时，行为等价于仅文本的自动音色（与设计取决于模型默认）。

**响应**：`200` + `audio/wav` 二进制。

---

## 5. 调用示例

### 5.1 curl：JSON（音色设计）

```bash
curl -sS -X POST "http://127.0.0.1:8080/v1/tts" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Hello from OmniVoice.\",\"instruct\":\"female, British accent\"}" ^
  -o output.wav
```

（Linux / macOS 将 `^` 换为 `\` 并相应调整引号。）

### 5.2 curl：multipart（声音克隆）

```bash
curl -sS -X POST "http://127.0.0.1:8080/v1/tts/upload" ^
  -F "text=This is a cloned voice test." ^
  -F "ref_audio=@D:\refs\speaker.wav" ^
  -F "ref_text=Optional transcript of the reference." ^
  -o cloned.wav
```

### 5.3 Python（`requests`）

```python
import pathlib

import requests

BASE = "http://127.0.0.1:8080"

# JSON：自动或设计模式
r = requests.post(
    f"{BASE}/v1/tts",
    json={
        "text": "你好，这是测试。",
        "instruct": "female, low pitch",
        "language": "Chinese",
    },
    timeout=600,
)
r.raise_for_status()
pathlib.Path("out.wav").write_bytes(r.content)

# 上传文件：克隆
with open("ref.wav", "rb") as f:
    r = requests.post(
        f"{BASE}/v1/tts/upload",
        data={
            "text": "使用参考音频克隆的声音。",
            "ref_text": "参考音频对应的文字。",
        },
        files={"ref_audio": ("ref.wav", f, "audio/wav")},
        timeout=600,
    )
r.raise_for_status()
pathlib.Path("clone.wav").write_bytes(r.content)
```

说明：长句或慢盘第一次合成可能较慢，`timeout` 建议 **数百秒** 量级，按实际调整。

### 5.4 JavaScript（浏览器 / Electron：`fetch` + `Blob`）

```javascript
const base = "http://127.0.0.1:8080";

async function ttsDesign() {
  const res = await fetch(`${base}/v1/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: "Hello from the browser.",
      instruct: "male, American accent",
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  // 播放或 <a download> 下载
  const a = document.createElement("a");
  a.href = url;
  a.download = "out.wav";
  a.click();
  URL.revokeObjectURL(url);
}

async function ttsClone(file) {
  const fd = new FormData();
  fd.append("text", "This uses an uploaded reference.");
  fd.append("ref_audio", file, file.name);
  fd.append("ref_text", "Optional reference transcript.");
  const res = await fetch(`${base}/v1/tts/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(await res.text());
  return await res.blob();
}
```

注意：浏览器会受 CORS 约束，请配置 `OMNIVOICE_CORS_ORIGINS`。Electron 若禁用 web 安全策略需自行评估风险。

### 5.5 Base64 参考音频（JSON）

适用于不便使用 `multipart` 的客户端：将 WAV 文件读入字节后 Base64 编码，放入 `ref_audio_base64`。

```python
import base64
import pathlib
import requests

wav_bytes = pathlib.Path("ref.wav").read_bytes()
payload = {
    "text": "克隆这段参考音色的朗读。",
    "ref_audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
    "ref_text": "可选参考文本。",
}
r = requests.post("http://127.0.0.1:8080/v1/tts", json=payload, timeout=600)
r.raise_for_status()
pathlib.Path("out.wav").write_bytes(r.content)
```

---

## 6. 接入架构建议

1. **仅本机**：客户端使用 `127.0.0.1` 或 `localhost`，无需改服务配置。
2. **局域网多终端**：服务 `--host 0.0.0.0`，客户端访问 `http://<服务器局域网IP>:8080`。
3. **与现有桌面 / 后端共存**：同一机器上注意 **端口冲突**；可改 `--port` 或设置 `OMNIVOICE_API_PORT`。
4. **公网**：务必 **不要** 直接裸奔；应使用 HTTPS 网关、鉴权、限流，并收紧 CORS。
5. **异步 UI**：合成可能耗时数秒到数十秒，请在应用中 **异步请求** 并显示进度或取消策略（HTTP 层当前未实现取消，需断开连接）。

---

## 7. 常见问题

| 现象 | 可能原因 | 处理方向 |
|------|----------|----------|
| 连接被拒绝 | 服务未启动或端口错误 | 检查进程与 `GET /health` |
| 首次很慢 | 下载权重或 CUDA 初始化 | 等待完成；预热线程可先发短请求 |
| 浏览器报 CORS | Origin 不在允许列表 | 设置 `OMNIVOICE_CORS_ORIGINS` |
| 422 Unprocessable | JSON 缺字段或类型错误 | 对照 `/docs` 与本文字段表 |
| 400 Invalid base64 | `ref_audio_base64` 损坏 | 检查编码是否为标准 Base64 WAV |
| 显存不足 | GPU 资源占用过高 | 换更大显存、关闭其它占用，或改用 `OMNIVOICE_DEVICE=cpu`（速度较慢） |

---

## 8. 与官方 CLI / Python API 的关系

- 网关内部调用 `OmniVoice.from_pretrained` 与 `model.generate`，参数含义与仓库内 `omnivoice-infer`、README 中的 Python 示例 **对齐**。
- 更细的生成参数说明见仓库内 `docs/generation-parameters.md`；音色设计用语见 `docs/voice-design.md`。

---

## 9. 版本信息

- 本文档针对仓库内 **FastAPI 应用**（`omnivoice.api.server`）编写。
- OpenAPI 与实现不完全一致时，以运行中的 **`/docs`** 为准。

若你扩展了鉴权、异步任务队列或 WebSocket，请在内部文档中同步更新接口约定。
