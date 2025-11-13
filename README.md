# 📄 Invoice Processing Platform

> **Plataforma unificada de procesamiento inteligente de facturas con OCR, LLM y asistente conversacional**

---

## 🎯 Descripción

Sistema empresarial completo para automatizar el procesamiento y análisis de facturas mediante:

- **🔄 Pipeline OCR/LLM**: Extracción automática de datos estructurados de facturas
- **💬 Asistente Conversacional**: Q&A en lenguaje natural sobre facturas procesadas
- **🎨 Interfaz Web Unificada**: UI moderna con tabs para ambas funcionalidades

## ✨ Características Principales

### Pipeline de Procesamiento
- ✅ Soporte multi-formato: PDF, JPG, PNG, BMP
- ✅ OCR con Tesseract (inglés y español)
- ✅ Extracción con Groq LLM (llama-3.1-8b-instant) para máxima precisión
- ✅ Almacenamiento estructurado en SQLite
- ✅ Procesamiento concurrente controlado

### Asistente Conversacional
- ✅ Preguntas en lenguaje natural
- ✅ MCP (Model Context Protocol) para consultas SQL seguras
- ✅ Tool calling automático
- ✅ Sesiones con historial de conversación
- ✅ Respuestas contextualizadas en español

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────┐
│      Frontend (SPA con Tabs)           │
│  ┌─────────────┐  ┌─────────────────┐  │
│  │  Pipeline   │  │   Assistant     │  │
│  │    Tab      │  │      Tab        │  │
│  └─────────────┘  └─────────────────┘  │
└────────────┬────────────────────────────┘
             │ HTTP/REST
             ▼
┌─────────────────────────────────────────┐
│    Unified API (FastAPI)                │
│  ┌──────────────────────────────────┐   │
│  │  Routers (Modular)               │   │
│  │  • /api/pipeline/extract         │   │
│  │  • /api/assistant/chat           │   │
│  │  • /api/health                   │   │
│  └──────────────────────────────────┘   │
│  ┌───────────┐  ┌──────────────────┐   │
│  │ Pipeline  │  │   Assistant      │   │
│  │  Module   │  │    Module        │   │
│  │           │  │  • Orchestrator  │   │
│  │  • OCR    │  │  • MCP Server    │   │
│  │  • LLM    │  │  • Sessions      │   │
│  └───────────┘  └──────────────────┘   │
└────────────┬────────────────────────────┘
             │
             ▼
      ┌─────────────┐
      │   SQLite    │
      │   app.db    │
      └─────────────┘
```

## 🚀 Quick Start

### Prerequisitos

- Docker Desktop / Docker Engine (24+)
- (Opcional) Drivers NVIDIA + `nvidia-container-toolkit` si quieres probar la GPU MX130 (Maxwell)

### 1. Configurar entorno

```bash
cp configs/env/.env.example configs/env/.env
# Define PIPELINE_LLM_API_KEY y/o LLM_API_KEY con tu token de Groq
# Ajusta PIPELINE_LLM_MODEL o LLM_MODEL si quieres otro modelo hospedado en Groq
```

### 2. Levantar el servicio

```bash
docker compose up -d
```

### 3. Acceder a la plataforma

```
http://localhost:7000
```

### 4. (Opcional) Ajustar límites de Groq

- Sube `RATE_LIMIT_RPM` o `RATE_LIMIT_TPM` solo si tu plan de Groq lo permite.
- Si recibes errores de rate limit, reduce la concurrencia (`MAX_CONCURRENCY`) o aumenta los intervalos entre peticiones.

## 📚 Uso

### Tab 1: Procesar Facturas

1. Arrastra una factura (PDF/imagen) al área de carga
2. Espera el procesamiento (OCR + LLM)
3. Visualiza los datos extraídos:
   - Vendor
   - Fecha
   - Total
   - Items

### Tab 2: Asistente Conversacional

**Preguntas sugeridas**:
```
¿Cuántas facturas hay en total?
¿Cuál es el monto total de todas las facturas?
¿Cuáles son los principales proveedores?
Muéstrame las facturas más recientes
¿Cuánto gastamos con el proveedor X en enero?
```

## 🔌 API REST

### Pipeline

```http
POST /api/pipeline/extract
Content-Type: multipart/form-data

file: <invoice.pdf>
```

**Respuesta**:
```json
{
  "vendor": "Acme Corp",
  "date": "2024-01-15",
  "total_cents": 150000,
  "currency": "USD",
  "items": [
    {
      "description": "Product A",
      "quantity": 2,
      "price_cents": 50000
    }
  ]
}
```

### Assistant

#### Chat Stateless
```http
POST /api/assistant/chat
Content-Type: application/json

{
  "question": "¿Cuántas facturas hay?"
}
```

**Respuesta**:
```json
{
  "success": true,
  "answer": "Hay 25 facturas en total.",
  "session_id": null
}
```

#### Chat con Sesión
```http
# 1. Crear sesión
POST /api/assistant/sessions
{
  "user_id": "user123"
}

# 2. Chat en sesión
POST /api/assistant/sessions/{session_id}/chat
{
  "question": "¿Cuáles son los principales proveedores?"
}

# 3. Obtener info de sesión
GET /api/assistant/sessions/{session_id}
```

#### Otros endpoints
```http
GET /api/assistant/sessions     # Listar sesiones activas
GET /api/assistant/stats         # Estadísticas del asistente
GET /api/health                  # Health check
```

## 🛡️ Seguridad MCP

El MCP implementa seguridad a nivel de queries:

- ✅ **Solo lectura**: SELECT, PRAGMA, EXPLAIN
- ❌ **Bloqueados**: INSERT, UPDATE, DELETE, DROP, CREATE
- 🔍 **Validación**: Todas las queries son validadas
- 📝 **Logging**: Operaciones registradas

## 🎨 Estructura del Proyecto

```
pipeline-python/
├── src/                         # Código fuente
│   ├── main.py                  # FastAPI principal
│   ├── routers/                 # Endpoints modulares
│   │   ├── pipeline.py
│   │   ├── assistant.py
│   │   └── health.py
│   ├── modules/                 # Lógica de negocio
│   │   ├── pipeline/            # Pipeline OCR/LLM
│   │   │   ├── config/
│   │   │   ├── extract/
│   │   │   ├── llm/
│   │   │   ├── service/
│   │   │   └── storage/
│   │   └── assistant/           # Asistente conversacional
│   │       ├── orchestrator.py
│   │       ├── mcp_server.py
│   │       ├── session_manager.py
│   │       ├── models.py
│   │       └── config.py
│   └── static/
│       └── index.html           # Frontend SPA
├── configs/                     # Configuraciones
│   └── env/.env
├── data/                        # Persistencia
│   ├── app.db
│   ├── uploads/
│   └── processed/
├── datasets/                    # Datos de prueba
├── Dockerfile
└── docker-compose.yml
```

## 📊 Performance

- **Pipeline**: ~3-5 segundos por factura
- **Assistant**: ~1 segundo por pregunta
- **Concurrencia**: Configurable (default: 1)
- **Base de datos**: SQLite (file-based)

## 🔧 Configuración Avanzada

### Variables de Entorno

```bash
# Pipeline
MAX_CONCURRENCY=2                    # Procesos paralelos
PDF_OCR_DPI=300                      # Calidad OCR
PDF_OCR_MAX_PAGES=5                  # Páginas a procesar

# Pipeline LLM (Groq)
PIPELINE_LLM_PROVIDER=groq
PIPELINE_LLM_MODEL=llama-3.1-8b-instant
PIPELINE_LLM_API_BASE=https://api.groq.com/openai/v1
PIPELINE_LLM_API_KEY=tu_clave_groq
PIPELINE_LLM_ALLOW_STUB=false

# Assistant LLM (Groq)
LLM_API_BASE=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.1-8b-instant
LLM_API_KEY=${GROQ_API_KEY:-}

# Rate limits Groq (free tier seguros)
RATE_LIMIT_RPM=24
RATE_LIMIT_RPD=11500
RATE_LIMIT_TPM=4800
RATE_LIMIT_TPD=400000

# Assistant
MAX_HISTORY_MESSAGES=10              # Mensajes en historial
SESSION_TIMEOUT_SECONDS=1800         # Timeout de sesiones (30min)
ENABLE_DEBUG_MODE=false              # Modo debug
# LLM_REQUEST_TIMEOUT=180            # Timeout en segundos para llamadas del assistant
```

### Cambiar modelos LLM

`configs/env/.env` expone dos bloques:

```bash
# Pipeline (Groq)
PIPELINE_LLM_MODEL=llama-3.1-8b-instant
# También puedes usar mixtral-8x7b-32768, gemma2-9b-it, etc.

# Assistant (Groq)
# LLM_MODEL=llama-3.1-8b-instant   # default balanceado
# LLM_MODEL=mixtral-8x7b-32768     # mayor contexto (puede ser más costoso)
# LLM_MODEL=gemma2-9b-it           # alternativa conversacional
```

Modelos sugeridos:
- Pipeline: `llama-3.1-8b-instant` (Groq, buen balance velocidad/calidad)
- Assistant: `llama-3.1-8b-instant` (Groq, respuesta consistente), `mixtral-8x7b-32768` (más contexto), `gemma2-9b-it` (tono más conversacional)

## 🧪 Testing

```bash
# Health check
curl http://localhost:7000/api/health

# Procesar factura
curl -X POST http://localhost:7000/api/pipeline/extract \
  -F "file=@invoice.pdf"

# Chat
curl -X POST http://localhost:7000/api/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Cuántas facturas hay?"}'
```

## 🧠 MCP Oficial

El servidor MCP se implementó con el SDK oficial (`mcp.server.fastmcp`) y queda montado en el mismo proceso FastAPI:

- **Transport HTTP**: `http://localhost:7000/mcp` (compatibilidad Streamable HTTP).
- **Herramientas expuestas**: `execute_sql_query`, `get_invoice_by_id`, `search_invoices_by_vendor`, `get_top_vendors`, `search_by_text`, `get_invoices_by_date_range`, `get_database_schema`.
- **Uso**: cualquier cliente MCP (por ejemplo `mcp-cli` o integraciones editoriales) puede conectarse a esa URL y consumir la base SQLite en modo solo lectura.

> Nota: el transport SSE se puede habilitar montando el `FastMCP.sse_app()` en otra ruta si se requiere compatibilidad completa.

## 📈 Monitoreo

```bash
# Ver logs
docker logs -f invoice-platform

# Estadísticas
curl http://localhost:7000/api/assistant/stats

# Estado del servicio
docker ps
```

## 🐛 Troubleshooting

### El servicio no inicia
```bash
# Ver logs
docker logs invoice-platform

# Verificar salud
curl http://localhost:7000/api/health
```

### Error de API Key
- Solo aplica si configuraste `LLM_API_BASE` hacia un proveedor remoto (Groq).
- Verifica que `LLM_API_KEY` esté definido en `configs/env/.env`.
- Prueba la key directamente contra el dashboard del proveedor (p.ej. https://console.groq.com/).

### ⏱️ Error "Límite de peticiones alcanzado"
**Causa**: El proveedor remoto (Groq u OpenAI-compatible) aplicó rate limiting

**Solución**:
- ⏸️ Espera 1-2 minutos entre peticiones
- 💡 El sistema hace **4 reintentos automáticos** con backoff exponencial
- 📊 Límites típicos: ~30 peticiones por minuto
- 💾 Las facturas ya procesadas se cachean automáticamente (no consumen API)

**Tips para evitar límites**:
1. No subas muchas facturas seguidas
2. Espera unos segundos entre cada carga
3. Las facturas duplicadas no consumen API (cache por hash)

### Base de datos vacía
- Procesa facturas primero con el Pipeline tab
- Verifica que exista `/app/data/app.db`

### Factura con poco texto legible
- Asegúrate que la imagen/PDF tenga buena calidad
- El OCR requiere texto claro y legible
- PDFs nativos funcionan mejor que imágenes escaneadas

## 🧹 Mantenimiento

```bash
# Detener servicio
docker compose down

# Limpiar todo (incluye datos)
docker compose down -v

# Reiniciar
docker compose restart

# Ver uso de recursos
docker stats invoice-platform
```

## 📖 Documentación API Interactiva

Accede a Swagger UI:
```
http://localhost:7000/docs
```

Accede a ReDoc:
```
http://localhost:7000/redoc
```

## 🎯 Roadmap

- [ ] Soporte para más formatos (Excel, CSV)
- [ ] API de webhooks para procesamiento asíncrono
- [ ] Dashboard de analytics
- [ ] Multi-tenancy
- [ ] Export a PDF/Excel
- [ ] Integración con sistemas ERP

## 🤝 Contribución

Este proyecto sigue una arquitectura modular. Para contribuir:

1. Los endpoints van en `src/routers/`
2. La lógica de negocio en `src/modules/`
3. El frontend en `src/static/`
4. Las configuraciones en `configs/env/`

## 📝 Licencia

MIT License

## 🙋 Soporte

Para reportar bugs o solicitar features:
- Issues: GitHub Issues
- Docs: `/docs` endpoint
- Logs: `docker logs invoice-platform`

---

**Desarrollado con ❤️ usando FastAPI, Groq, Tesseract y MCP**
