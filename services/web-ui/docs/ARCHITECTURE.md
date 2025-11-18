# Web UI Service — Arquitectura y Diseño

## Propósito
Proporcionar una interfaz mínima para operar la plataforma: subir facturas al pipeline OCR y conversar con el agente. El objetivo es no depender de frameworks pesados y mantener el despliegue como un contenedor Nginx estático que también reexpone los endpoints backend necesarios.

## Vista general
- **Assets estáticos** (`static/index.html`, `styles.css`, `app.js`) servidos desde `/usr/share/nginx/html`.
- **Reverse proxy**: `nginx.conf` reenvía `/api/pipeline/*` a `pipeline-api`, `/api/agent/*` y `/api/assistant/chat` a `invoice-agent-api`, y expone `/docs`, `/openapi.json` y `/api/health` del pipeline.
- **Sin build step**: no hay bundlers; los archivos están listos para copiarse en el contenedor.

```
Navegador → Nginx (web-ui)
  ├─ /            → archivos estáticos
  ├─ /api/pipeline/* → pipeline-api:8000
  ├─ /api/agent/*    → invoice-agent-api:7003 (rewrite /api/agent/ask → /ask)
  └─ /docs,/openapi  → pipeline-api
```

## Frontend
### `index.html`
- Contiene dos tabs (`Procesar Facturas`, `Asistente`).
- Área drag & drop (`uploadArea`) más vista de resultados (`resultGrid`).
- Sección de chat con mensajes iniciales, sugerencias precargadas y textarea con envío `Enter`.

### `app.js`
- Gestiona el cambio de tabs y los listeners drag/drop.
- `processFile(file)`: construye `FormData`, hace `fetch` a `/api/pipeline/extract`, interpreta errores (rate limit, payload grande) y actualiza la UI.
- `displayResult(data)`: compone tarjetas resumen, tabla de ítems, alertas y JSON en bruto.
- Chat: genera `session_id`, mantiene historial en DOM y usa `fetch('/api/agent/ask')` (ver `sendMessage`, `appendMessage`).
- Helpers (`formatCurrency`, `escapeHtml`, `formatConfidence`) se encargan de la presentación.

### Diseño visual
- `styles.css` define layout responsivo basado en flexbox y CSS grid para tarjetas/tabla.
- Secciones bien diferenciadas para totales, items y advertencias; las clases `.tab`, `.result-section`, `.stat-card` facilitan ajustes locales.

## Nginx / infra
- `Dockerfile`: parte de `nginx:alpine`, copia `static/` y `nginx.conf`, expone puerto 80.
- `nginx.conf`:
  - Define variables `$pipeline_api` y `$assistant_api` para enlazar servicios usando DNS interno de Docker.
  - `client_max_body_size 25m` permite subir archivos grandes sin 413.
  - `resolver 127.0.0.11 valid=30s` asegura que los nombres de servicio se actualicen tras reinicios.
  - `location /api/agent/` realiza `rewrite` para transformar `/api/agent/ask` en `/ask` antes de `proxy_pass`.
  - Mantiene un endpoint legado `/api/assistant/chat` para compatibilidad con clientes antiguos.

## Decisiones clave
- **Vanilla JS**: se prioriza cero dependencias para reducir peso y simplificar debugging.
- **Dos tabs en una sola página**: evita navegar a otras rutas o recargar el browser.
- **Exposición de Swagger y health**: facilita soporte y reduce la necesidad de abrir el puerto del pipeline directamente.
- **Mensajes de error amigables**: `processFile` inspecciona `status` y `content-type` para mostrar causas frecuentes (rate limit, archivo grande, OCR pobre).
- **Sesiones de chat efímeras**: el `session_id` se genera al cargar la página y cambia cuando el usuario refresca; suficiente para demos.

## Operación
- Componente final en Compose: `web-ui` escucha en `7000` y depende del pipeline + agente.
- No requiere variables de entorno; la configuración del proxy está en `nginx.conf`.
- Regenerar assets implica editar `static/` y rebuild del contenedor.

## Mejoras futuras sugeridas
- Persistir `session_id` en `localStorage` para mantener la conversación tras recargar.
- Añadir barra de progreso durante la subida de archivos grandes.
- Internationalizar textos para ambientes bilingües.
