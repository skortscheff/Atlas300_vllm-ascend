# Guía de uso de la API de inferencia local

Este servidor expone una API compatible con OpenAI en la red local. Cualquier herramienta o script que soporte la API de OpenAI puede apuntar a esta dirección sin modificaciones mayores.

## Endpoint

| Modelo | URL base |
|--------|----------|
| `Qwen2.5-Coder-14B-Instruct-abliterated` | `http://<HOST_IP>:8002/v1` |

**API key:** No se requiere autenticación. Si tu cliente lo exige, usa cualquier cadena de texto, por ejemplo `sk-local`.

**Ventana de contexto:** 32 768 tokens (entrada + salida combinados) — es el límite nativo del modelo (`max_position_embeddings`), no se puede ampliar sin degradar la calidad (YaRN rope-scaling) y además chocaría con el límite de memoria de la 310P (ver `CLAUDE.md`).

**Velocidad:** ~9.6 tok/s en una sola conversación (limitado por ancho de banda de memoria en este hardware, no por cómputo). Con varias peticiones concurrentes el rendimiento agregado escala bien (~44 tok/s con 8 peticiones simultáneas) — para un solo usuario no hay ganancia posible con la configuración actual.

**Tool-calling / function calling:** el servidor está configurado con `--enable-auto-tool-choice --tool-call-parser hermes`, pero **actualmente no funciona correctamente** — el modelo emite el texto de la llamada a función como texto plano (`<tools>{...}</tools>`) dentro de `message.content` en vez de rellenar el campo estructurado `tool_calls`. Si tu integración depende de `tool_calls`, no confíes en él todavía (ver `CLAUDE.md`, sección de baseline de rendimiento).

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
      "id": "Qwen2.5-Coder-14B-Instruct-abliterated",
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
    "model": "Qwen2.5-Coder-14B-Instruct-abliterated",
    "messages": [
      {"role": "user", "content": "Explica qué es una API REST en dos párrafos."}
    ],
    "max_tokens": 300
  }'
```

### Parámetros útiles

| Parámetro | Descripción | Valor típico |
|-----------|-------------|--------------|
| `model` | ID del modelo | `Qwen2.5-Coder-14B-Instruct-abliterated` |
| `messages` | Lista de mensajes del hilo de conversación | obligatorio |
| `max_tokens` | Límite de tokens en la respuesta | `512` |
| `temperature` | Creatividad (0 = determinista, 1 = creativo) | `0.7` |
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
    model="Qwen2.5-Coder-14B-Instruct-abliterated",
    messages=[
        {"role": "system", "content": "Eres un asistente de programación experto."},
        {"role": "user", "content": "Escribe una función en Python que invierta una cadena de texto."},
    ],
    max_tokens=512,
    temperature=0.2,
)

print(respuesta.choices[0].message.content)
```

### Ejemplo con streaming

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<HOST_IP>:8002/v1",
    api_key="sk-local",
)

stream = client.chat.completions.create(
    model="Qwen2.5-Coder-14B-Instruct-abliterated",
    messages=[{"role": "user", "content": "¿Cuál es la diferencia entre una lista y una tupla en Python?"}],
    max_tokens=512,
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
  model: "Qwen2.5-Coder-14B-Instruct-abliterated",
  messages: [
    { role: "user", content: "¿Cómo funciona el event loop en JavaScript?" },
  ],
  max_tokens: 512,
});

console.log(respuesta.choices[0].message.content);
```

---

## 5. Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `Connection refused` | El modelo no está iniciado | Ejecutar `docker compose up -d` en el servidor |
| `Connection timed out` | Puerto bloqueado o IP incorrecta | Verificar IP con `hostname -I` en el servidor |
| Respuesta muy lenta al inicio | El modelo aún está cargando | Esperar hasta ver `Application startup complete.` en los logs |
| Error `model not found` | El `model` no coincide con el cargado | Consultar `/v1/models` para obtener el ID exacto |
