# Guía de uso de la API de inferencia local

Este servidor expone una API compatible con OpenAI en la red local. Cualquier herramienta o script que soporte la API de OpenAI puede apuntar a esta dirección sin modificaciones mayores.

## Endpoint

| Modelo activo | URL base |
|--------|----------|
| `qwen3.6-moe` (Huihui-Qwen3.6-35B-A3B-abliterated-w8a8, MoE, self-quantized) | `http://<HOST_IP>:8002/v1` |

> **Nota:** el stack soporta dos modelos intercambiables mediante *Compose profiles* (`prod` y `qwen36`) — ambos comparten el mismo puerto 8002, así que solo uno está activo a la vez. Este documento describe el modelo **actualmente activo** (`qwen36`, desde 2026-08-19 en su variante w8a8 auto-cuantizada). El otro modelo disponible es `Qwen2.5-Coder-14B-Instruct-abliterated` (perfil `prod`) — mismo endpoint, mismo formato de API, pero más lento (~9.5 tok/s), sin tool-calling funcional, y sin razonamiento (`reasoning_content`). Ver `CLAUDE.md`, sección "Switching Models", para cambiar entre ambos.

**API key:** No se requiere autenticación. Si tu cliente lo exige, usa cualquier cadena de texto, por ejemplo `sk-local`.

**Ventana de contexto:** **24576 tokens** (entrada + salida combinados) — un +50% respecto al bf16 original (16384), gracias a la cuantización w8a8 (auto-generada con `msmodelslim` a partir de los mismos pesos abliterados) que reduce el footprint de pesos de ~34 GiB/chip a ~19 GiB/chip, liberando memoria para más contexto (ver `CLAUDE.md`, sección "Self-quantized abliterated w8a8").

**Velocidad:** ~31 tok/s en una sola conversación — gracias a la arquitectura MoE (35B totales, ~3B activos por token), la cuantización w8a8, y el modo ACLGraph (no-eager) de `v0.23.0-310p-openeuler` (release estable, ya no release-candidate).

**Razonamiento (chain-of-thought):** este modelo "piensa" antes de responder — el contenido de razonamiento llega en el campo **`message.reasoning_content`** (no en `content`), gracias a `--reasoning-parser qwen3`. Es normal ver respuestas con `reasoning_content` largo (600-1600+ tokens) antes de la respuesta final en `content`. **Usa siempre `max_tokens >= 2000-3000`** — con límites bajos (ej. 512) la respuesta puede cortarse a mitad del razonamiento sin llegar a producir contenido útil.

**Estabilidad del razonamiento:** el servidor tiene fijados por defecto `temperature: 0.2` y `repetition_penalty: 1.1` (vía `--override-generation-config`) para evitar un bug conocido en el que el modelo podía quedarse divagando indefinidamente en el razonamiento sin nunca concluir. Estos valores ya se aplican automáticamente — no hace falta pasarlos en cada petición, pero puedes sobreescribirlos si tu cliente los especifica explícitamente.

**Tool-calling / function calling:** el servidor está configurado con `--enable-auto-tool-choice --tool-call-parser qwen3_coder` y **esto sí funciona correctamente** (a diferencia del modelo anterior) — las llamadas a función llegan correctamente estructuradas en `message.tool_calls`, confirmado con pruebas reales.

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
      "id": "qwen3.6-moe",
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
    "model": "qwen3.6-moe",
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
| `model` | ID del modelo | `qwen3.6-moe` |
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
    model="qwen3.6-moe",
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
    model="qwen3.6-moe",
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
  model: "qwen3.6-moe",
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
| `Connection refused` | El modelo no está iniciado | Ejecutar `docker compose --profile qwen36 up -d` en el servidor (o `--profile prod` para el modelo anterior) |
| `Connection timed out` | Puerto bloqueado o IP incorrecta | Verificar IP con `hostname -I` en el servidor |
| Respuesta muy lenta al inicio | El modelo aún está cargando | Esperar hasta ver `Application startup complete.` en los logs |
| Error `model not found` | El `model` no coincide con el cargado | Consultar `/v1/models` para obtener el ID exacto (puede ser `qwen3.6-moe` o `Qwen2.5-Coder-14B-Instruct-abliterated` según el perfil activo) |
| Respuesta vacía con `finish_reason: length` | `max_tokens` demasiado bajo — el razonamiento se cortó antes de producir respuesta | Subir `max_tokens` a 3000-4000 |
