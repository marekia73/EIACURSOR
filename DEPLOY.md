# Despliegue del Generador EIA

## ⚠️ Importante: Netlify no es compatible

**Netlify** sirve sitios estáticos (HTML, CSS, JS). Esta aplicación es una **app Streamlit** que requiere:
- Servidor Python en ejecución
- WebSockets para comunicación en tiempo real
- Procesamiento de documentos (PDF, Word)

**Opciones recomendadas** (gratuitas o de bajo coste):

---

## 1. Streamlit Community Cloud (recomendado, gratuito)

1. Sube el proyecto a **GitHub** (repositorio público o privado).
2. Entra en [share.streamlit.io](https://share.streamlit.io).
3. Conecta tu cuenta de GitHub.
4. Selecciona el repositorio y configura:
   - **Main file:** `app.py`
   - **Branch:** `main` (o la que uses)
5. En **Advanced settings** añade variables de entorno:
   - `OPENAI_API_KEY` (si usas generación con IA)
   - `AEMET_API_KEY` (opcional, para climatología)
6. Despliega. Obtendrás una URL tipo `https://tu-app.streamlit.app`.

### Archivos necesarios (ya incluidos)
- `requirements.txt`
- `app.py` como punto de entrada
- `.streamlit/config.toml` (tema y configuración)

---

## 2. Railway

1. Crea cuenta en [railway.app](https://railway.app).
2. **New Project** → **Deploy from GitHub**.
3. Conecta el repositorio y selecciona el proyecto.
4. Railway detecta el `Procfile`:
   ```
   web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
   ```
5. Añade variables de entorno en **Variables**.
6. Despliega. Obtendrás una URL pública.

---

## 3. Render

1. Crea cuenta en [render.com](https://render.com).
2. **New** → **Web Service**.
3. Conecta GitHub y selecciona el repositorio.
4. Configuración:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`
5. Añade variables de entorno.
6. Despliega.

---

## 4. Docker (VPS, AWS, etc.)

Si tienes un servidor con Docker:

```bash
docker build -t generador-eia .
docker run -p 8501:8501 -e OPENAI_API_KEY=tu_clave generador-eia
```

---

## Paquete para despliegue (estructura)

El proyecto ya incluye todo lo necesario:

```
PROYECTO_EIA_APP/
├── app.py                 # Punto de entrada
├── requirements.txt       # Dependencias Python
├── Procfile              # Para Railway/Heroku
├── Dockerfile            # Para Docker
├── .streamlit/
│   ├── config.toml       # Tema y configuración
│   └── styles.css       # Estilos profesionales
├── generador.py
├── exportador.py
├── persistencia_archivos.py
├── analista.py
├── mapas.py
├── clima_agent.py
└── archivos_proyecto/    # Datos de proyectos (opcional en cloud)
```

---

## Rendimiento y navegación

- **Caché:** `@st.cache_data` con TTL 30 s para listados y estados.
- **Fragmentos:** `st.fragment` usado donde está disponible para reruns parciales.
- **Tema:** `fastReruns = true` en config para reducir parpadeos.
- **Errores:** Mensajes suaves (warning) en lugar de cuadros rojos agresivos.

---

## Nota sobre Netlify

Si quieres una **página de aterrizaje** en Netlify que enlace a tu app desplegada en Streamlit Cloud:

1. Crea una carpeta `netlify-landing/` con un `index.html` simple.
2. Configura Netlify para publicar esa carpeta.
3. En el HTML incluye un enlace a tu URL de Streamlit Cloud.

Ejemplo: `netlify-landing/index.html` con enlace a `https://tu-app.streamlit.app`.
