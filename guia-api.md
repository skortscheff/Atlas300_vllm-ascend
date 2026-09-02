# Guía de uso de la API de inferencia local

Este servidor expone una API compatible con OpenAI en la red local. Cualquier herramienta o script que soporte la API de OpenAI puede apuntar a esta dirección sin modificaciones mayores.

## Endpoint

| Modelo activo | URL base |
|--------|----------|
| `qwen3.8-27b` (Huihui-Qwen3.8-27B-abliterated, bf16, híbrido linear+full-attention) | `http://<HOST_IP>:8002/v1` |

> **Nota:** el stack soporta dos modelos intercambiables mediante *Compose profiles* (`prod` y `qwen36`) — ambos comparten el mismo puerto 8002, así que solo uno está activo a la vez. Este documento describe el modelo **actualmente activo** (`qwen36`, desde 2026-09-01 sirviendo Qwen3.8-27B). El otro modelo disponible es `Qwen2.5-Coder-14B-Instruct-abliterated` (perfil `prod`) — mismo endpoint, mismo formato de API, más rápido (~9.5 tok/s) y con más contexto (32768), pero sin tool-calling funcional y sin razonamiento (`reasoning_content`). Ver `CLAUDE.md`, sección "Switching profiles", para cambiar entre ambos.

**API key:** No se requiere autenticación. Si tu cliente lo exige, usa cualquier cadena de texto, por ejemplo `sk-local`.

**Ventana de contexto:** **16384 tokens** (entrada + salida combinados) — deliberadamente limitado por debajo de los 32768 ya probados como viables, para dejar margen de memoria (este modelo corre en modo `--enforce-eager`, obligatorio en este hardware para su arquitectura).

**Velocidad:** ~5.9 tok/s en una sola conversación — más lento que el modelo MoE anterior, pero es un trade-off deliberado: este modelo alcanza 10/10 en el benchmark de precisión de código, el mejor resultado de cualquier modelo probado en este hardware.

**Razonamiento (chain-of-thought):** este modelo "piensa" antes de responder — el contenido de razonamiento llega en el campo **`message.reasoning_content`** (no en `content`), gracias a `--reasoning-parser qwen3`. **Usa siempre `max_tokens >= 2000-3000`** — con límites bajos (ej. 512) la respuesta puede cortarse a mitad del razonamiento sin llegar a producir contenido útil.

**Estabilidad del razonamiento:** el servidor tiene fijados por defecto `temperature: 0.2` y `repetition_penalty: 1.1` (vía `--override-generation-config`) — necesario porque los valores por defecto del modelo (`temperature: 1.0`, sin repetition penalty) permiten que el modelo divague indefinidamente sin concluir su razonamiento. Estos valores ya se aplican automáticamente — no hace falta pasarlos en cada petición, pero puedes sobreescribirlos si tu cliente los especifica explícitamente.

**Tool-calling / function calling:** el servidor está configurado con `--enable-auto-tool-choice --tool-call-parser qwen3_coder` y funciona correctamente — las llamadas a función llegan correctamente estructuradas en `message.tool_calls`.

---

## 1. Verificar que el servidor está activo

```bash
curl http://<HOST_IP>:8002/v1/models
```

Respuesta esperada:

```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen3.8-27b",
      "object": "model"
    }
  ]
}
```

---

## 2. Hacer una consulta desde la terminal (curl)

```bash
curl http://<HOST_IP>:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.8-27b",
    "messages": [
      {"role": "user", "content": "Explica qué es una API REST en dos párrafos."}
    ],
    "max_tokens": 3000
  }'
```

La respuesta incluirá `message.reasoning_content` (el razonamiento interno del modelo) además de `message.content` (la respuesta final). Si usas un cliente que no distingue ambos campos, revisa que esté leyendo `content`, no `reasoning_content`.

### Parámetros útiles

| Parámetro | Descripción | Valor típico |
|-----------|-------------|--------------|
| `model` | ID del modelo | `qwen3.8-27b` |
| `messages` | Lista de mensajes del hilo de conversación | obligatorio |
| `max_tokens` | Límite de tokens en la respuesta — **usar 2000-3000 mínimo**, este modelo razona extensamente antes de responder | `3000` |
| `temperature` | Creatividad (0 = determinista, 1 = creativo) — ya fijado en `0.2` por defecto en el servidor | `0.2` (por defecto) |
| `stream` | Devuelve la respuesta en tiempo real (streaming) | `true` / `false` |

---

## 3. Uso desde Python

### Instalación

```bash
pip install openai
```

### Ejemplo básico

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<HOST_IP>:8002/v1",
    api_key="sk-local",
)

respuesta = client.chat.completions.create(
    model="qwen3.8-27b",
    messages=[
        {"role": "system", "content": "Eres un asistente de programación experto."},
        {"role": "user", "content": "Escribe una función en Python que invierta una cadena de texto."},
    ],
    max_tokens=3000,
)

print(respuesta.choices[0].message.content)
# El razonamiento interno (si lo necesitas) está en:
# respuesta.choices[0].message.reasoning_content
```

### Ejemplo con streaming

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<HOST_IP>:8002/v1",
    api_key="sk-local",
)

stream = client.chat.completions.create(
    model="qwen3.8-27b",
    messages=[{"role": "user", "content": "¿Cuál es la diferencia entre una lista y una tupla en Python?"}],
    max_tokens=3000,
    stream=True,
)

for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
print()
```

---

## 4. Uso desde JavaScript / Node.js

### Instalación

```bash
npm install openai
```

### Ejemplo básico

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://<HOST_IP>:8002/v1",
  apiKey: "sk-local",
});

const respuesta = await client.chat.completions.create({
  model: "qwen3.8-27b",
  messages: [
    { role: "user", content: "¿Cómo funciona el event loop en JavaScript?" },
  ],
  max_tokens: 3000,
});

console.log(respuesta.choices[0].message.content);
```

---

## 5. Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `Connection refused` | El modelo no está iniciado | Ejecutar `docker compose --profile qwen36 up -d` en el servidor (o `--profile prod` para el modelo denso alternativo) |
| `Connection timed out` | Puerto bloqueado o IP incorrecta | Verificar IP con `hostname -I` en el servidor |
| Respuesta muy lenta al inicio | El modelo aún está cargando | Esperar hasta ver `Application startup complete.` en los logs |
| Error `model not found` | El `model` no coincide con el cargado | Consultar `/v1/models` para obtener el ID exacto (puede ser `qwen3.8-27b` o `Qwen2.5-Coder-14B-Instruct-abliterated` según el perfil activo) |
| Respuesta vacía con `finish_reason: length` | `max_tokens` demasiado bajo — el razonamiento se cortó antes de producir respuesta | Subir `max_tokens` a 3000-4000 |
| Respuesta lenta en general | Es esperado — este modelo prioriza precisión sobre velocidad (~5.9 tok/s) | Si necesitas más velocidad, contacta al administrador sobre el perfil alternativo |
