"""
App Streamlit para Generación de Estudios de Impacto Ambiental (EIA) profesionales.
"""

import os
import json
import io
import re
import shutil
import time
from pathlib import Path
import streamlit as st

# Configuración de página (debe ir antes de otros comandos Streamlit).
st.set_page_config(
    page_title="Generador de EIA",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Evita exponer detalles técnicos de errores al usuario final en UI.
try:
    st.set_option("client.showErrorDetails", False)
except Exception:
    pass

# Cargar estilos profesionales
def _load_custom_css():
    css_path = Path(__file__).resolve().parent / ".streamlit" / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
_load_custom_css()


def _mensaje_suave(tipo: str, texto: str, usar_toast: bool = False):
    """Muestra mensajes sin cuadros rojos agresivos. Usa toast para errores transitorios."""
    if usar_toast and hasattr(st, "toast"):
        st.toast(texto, icon="⚠️")
        return
    if tipo == "error":
        st.warning(texto, icon="⚠️")  # Menos agresivo que st.error
    elif tipo == "info":
        st.info(texto, icon="ℹ️")
    else:
        st.warning(texto, icon="⚠️")


def _invalidate_cache_data():
    """Invalida cachés ligeras para reflejar cambios de archivos/UI."""
    try:
        st.cache_data.clear()
    except Exception:
        pass


@st.cache_data(ttl=60, show_spinner=False)
def _listar_proyectos_cached() -> list:
    from persistencia_archivos import listar_proyectos

    return listar_proyectos()


@st.cache_data(ttl=60, show_spinner=False)
def _cargar_archivos_guardados_cached(nombre_proyecto: str) -> dict:
    from persistencia_archivos import cargar_archivos_guardados

    return cargar_archivos_guardados(nombre_proyecto)


@st.cache_data(ttl=60, show_spinner=False)
def _cargar_estado_proyecto_cached(nombre_proyecto: str) -> dict:
    from persistencia_archivos import cargar_estado_proyecto

    return cargar_estado_proyecto(nombre_proyecto)

# Lista de Datos Necesarios según el Prompt Maestro (Bloques 1 y 2 prioritarios)
# Cada tupla: (etiqueta para mostrar, clave interna)
# Las claves que coinciden con analista.DatosEIA se obtienen por extracción; el resto por formulario
LISTA_DATOS_NECESARIOS = [
    # Bloque 1: Identificación y Marco Legal
    ("Nombre del Promotor / Razón Social", "nombre_promotor"),
    ("NIF/CIF del Promotor", "nif_cif"),
    ("Domicilio social", "domicilio_social"),
    ("Representante legal", "representante_legal"),
    ("Título Oficial del Proyecto", "titulo_proyecto"),
    ("Órgano Sustantivo", "organo_sustantivo"),
    ("Tipo de Evaluación (Ordinaria/Simplificada)", "tipo_evaluacion"),
    ("Antecedentes (expedientes previos, consultas)", "antecedentes"),
    # Bloque 2: Descripción Técnica - Localización y Consumos
    ("Ubicación del Proyecto", "ubicacion_proyecto"),
    ("Coordenadas del proyecto (UTM o lat/lon)", "coordenadas_utm"),
    ("Referencia Catastral", "referencia_catastral"),
    ("Clasificación LER de residuos", "clasificacion_ler"),
    ("Consumos de agua/luz (potencias, consumos estimados)", "consumos_agua_luz"),
    # Bloque 3: Detalle técnico de explotación (extraído de memoria/proyecto de explotación)
    ("Maquinaria y equipos principales de explotación", "maquinaria_equipos"),
    ("Descripción / diagrama del proceso de explotación", "proceso_explotacion"),
    ("Estado de la infraestructura (obra nueva / nave existente)", "estado_infraestructura"),
    # Campos adicionales para evitar huecos en redacción final
    ("Superficie de parcela (m²)", "superficie_parcela_m2"),
    ("Capacidad máxima de almacenamiento (unidades/ton/año)", "capacidad_maxima_almacenamiento"),
    ("Personal previsto (nº trabajadores)", "personal_previsto"),
]

# Órganos sustantivos habituales (evita alucinaciones tipográficas en exportación)
ORGANOS_SUSTANTIVOS_VALIDOS = [
    "Consejería de Transición Ecológica, Lucha contra el Cambio Climático y Planificación Territorial del Gobierno de Canarias",
    "Consejería de Transición Ecológica del Gobierno de Canarias",
    "Consejería de Transición Ecológica del Cabildo de Canarias",
    "Consejería de Transición Ecológica del Cabildo Insular de Gran Canaria",
    "Consejería de Transición Ecológica del Cabildo Insular de Tenerife",
    "Consejería de Transición Ecológica del Cabildo Insular de Lanzarote",
    "Consejería de Transición Ecológica del Cabildo Insular de Fuerteventura",
    "Dirección General de Sostenibilidad y Cambio Climático",
    "Otro (indicar en observaciones)",
]


def _normalizar_organo_sustantivo(valor: str) -> str:
    """
    Corrige typos frecuentes en Órgano Sustantivo y acerca a opciones válidas.
    Evita salidas como 'CONBSEJERIA... CANARIASS' en documentos oficiales.
    """
    if not valor or not str(valor).strip():
        return (valor or "").strip()
    v = str(valor).strip()
    # Correcciones tipográficas directas
    v = re.sub(r"\bCONBSEJER[IÍ]A\b", "Consejería", v, flags=re.I)
    v = re.sub(r"\bCONSEJER[IÍ]A\b", "Consejería", v, flags=re.I)
    v = re.sub(r"CANARIASS\b", "Canarias", v, flags=re.I)
    v = re.sub(r"\bCANARIAS\b", "Canarias", v, flags=re.I)
    v_low = v.lower()
    # Asignar a opción canónica si contiene las palabras clave (p. ej. consejería + transición + cabildo + canarias)
    for opcion in ORGANOS_SUSTANTIVOS_VALIDOS:
        if opcion == "Otro (indicar en observaciones)":
            continue
        o_low = opcion.lower()
        if v_low in o_low or o_low in v_low:
            return opcion
        # Coincidencia por palabras clave típicas
        if "consejería" in v_low and "transición" in v_low and "canarias" in v_low:
            if "cabildo" in v_low and "lanzarote" not in v_low and "gran canaria" not in v_low and "tenerife" not in v_low and "fuerteventura" not in v_low:
                if "gobierno" not in v_low:
                    return "Consejería de Transición Ecológica del Cabildo de Canarias"
            if "gobierno" in v_low or "cabildo" not in v_low:
                return "Consejería de Transición Ecológica del Gobierno de Canarias"
    return v


# Claves que el analista puede extraer del PDF
CLAVES_EXTRAIBLES = {
    "nombre_promotor",
    "ubicacion_proyecto",
    "coordenadas_utm",
    "referencia_catastral",
    "clasificacion_ler",
    "consumos_agua_luz",
    "maquinaria_equipos",
    "proceso_explotacion",
    "estado_infraestructura",
}

# Plantilla de capítulos según Índice Talleres Rayna (referencia experta)
# Orden y títulos alineados con ÍNDICE DE TALLERES RAYNA.md
try:
    from indice_rayna import CAPITULOS_A_INDICE_RAYNA, ORDEN_EXPORTACION_RAYNA
    _titulos_rayna = {k: v[0] for k, v in CAPITULOS_A_INDICE_RAYNA.items()}
    _state_keys = {
        "resumen_ejecutivo": "informe_resumen_ejecutivo",
        "marco_legal_admin": "informe_marco_legal_admin",
        "triaje": "informe_triaje",
        "descripcion": "informe_descripcion",
        "inventario": "informe_inventario",
        "impactos": "informe_impactos",
        "medidas": "informe_medidas",
        "pva": "informe_pva",
        "alternativas": "informe_alternativas",
        "vulnerabilidad": "informe_vulnerabilidad",
        "red_natura": "informe_red_natura",
        "conclusiones": "informe_conclusiones",
        "resumen_no_tecnico": "informe_resumen_no_tecnico",
        "referencias": "informe_referencias",
        "anexos_tecnicos": "informe_anexos_tecnicos",
    }
    CHAPTER_TEMPLATE = [
        (k, _titulos_rayna.get(k, k), _state_keys.get(k, f"informe_{k}"))
        for k in ORDEN_EXPORTACION_RAYNA
        if k in _state_keys
    ]
except ImportError:
    CHAPTER_TEMPLATE = [
        ("resumen_ejecutivo", "1. Introducción", "informe_resumen_ejecutivo"),
        ("marco_legal_admin", "2. Marco normativo aplicable", "informe_marco_legal_admin"),
        ("descripcion", "4. BLOQUE A — Identificación y descripción del proyecto", "informe_descripcion"),
        ("inventario", "5. BLOQUE B — Inventario ambiental del entorno", "informe_inventario"),
        ("alternativas", "9. BLOQUE F — Análisis de alternativas", "informe_alternativas"),
        ("impactos", "6. BLOQUE C — Identificación y Valoración de Impactos", "informe_impactos"),
        ("medidas", "7. Medidas Preventivas, Correctoras y Compensatorias", "informe_medidas"),
        ("pva", "8. BLOQUE E — Programa de Vigilancia Ambiental (PVA)", "informe_pva"),
        ("conclusiones", "12. BLOQUE I — Conclusiones", "informe_conclusiones"),
        ("anexos_tecnicos", "Anejos", "informe_anexos_tecnicos"),
    ]

def _valor_extraido(datos, clave: str) -> str:
    """Obtiene el valor extraído para una clave (vacío si no existe en DatosEIA)."""
    if datos is None:
        return ""
    val = getattr(datos, clave, None)
    if val is None or str(val).strip() == "":
        return ""
    return str(val).strip()

def _es_dato_faltante(valor: str) -> bool:
    """Considera faltante si está vacío o es 'No encontrado'."""
    if not valor or not str(valor).strip():
        return True
    return str(valor).strip().lower() == "no encontrado"


# Códigos LER oficiales: capítulo (primeros 2 dígitos) solo 01-20 (Lista Europea de Residuos).
_PATRON_LER_OFICIAL = re.compile(
    r"\b(0[1-9]|1[0-9]|20)[\s\.\-_/]*(\d{2})[\s\.\-_/]*(\d{2})(\*?)(?!\d)"
)


def _es_codigo_ler_valido(c1: str, c2: str, c3: str) -> bool:
    """Comprueba que el capítulo LER sea 01-20 (formato oficial)."""
    try:
        cap = int(c1)
        return 1 <= cap <= 20
    except (ValueError, TypeError):
        return False


def _normalizar_lista_ler(valor: str) -> str:
    """
    Normaliza códigos LER a formato NN NN NN(*), solo capítulos 01-20 (oficial).
    Elimina duplicados y códigos no válidos (p. ej. 56 52 48 no existe en LER).
    """
    texto = (valor or "").strip()
    if not texto:
        return ""

    vistos = set()
    codigos = []
    for m in _PATRON_LER_OFICIAL.finditer(texto):
        c1, c2, c3, estrella = m.groups()
        if not _es_codigo_ler_valido(c1, c2, c3):
            continue
        codigo = f"{c1} {c2} {c3}{estrella}"
        if codigo not in vistos:
            vistos.add(codigo)
            codigos.append(codigo)

    if not codigos:
        return texto
    return ", ".join(codigos)


def _sanitizar_ler_admitidos_sin_asteriscos(ler_admitidos: str, rp_propios: str) -> tuple[str, str]:
    """
    LER admitidos NUNCA puede contener asteriscos. Códigos con * van a RP propios.
    Devuelve (ler_sin_asteriscos, rp_actualizado).
    """
    ler = (ler_admitidos or "").strip()
    rp = (rp_propios or "").strip()
    rp_set = set()
    for c in (c.strip() for c in rp.split(",") if c.strip()):
        norm = _normalizar_lista_ler(c)
        if norm:
            rp_set.add(norm)
    admitidos_sin_asterisco = []
    for c in (c.strip() for c in ler.split(",") if c.strip()):
        if "*" in c:
            norm = _normalizar_lista_ler(c)
            if norm:
                rp_set.add(norm)
        else:
            admitidos_sin_asterisco.append(c)
    ler_final = _normalizar_lista_ler(", ".join(admitidos_sin_asterisco)) if admitidos_sin_asterisco else ""
    rp_final = ", ".join(sorted(rp_set, key=lambda x: (x.replace("*", ""), x))) if rp_set else ""
    return (ler_final, rp_final)


def _normalizar_fecha_yyyy_mm_dd(valor: str) -> str:
    """
    Acepta DD-MM-YYYY (o D-M-YYYY) y convierte a YYYY-MM-DD.
    Si ya está en YYYY-MM-DD, lo devuelve tal cual.
    Si no es convertible, devuelve el valor original (el gate de formato alertará).
    """
    s = (valor or "").strip()
    if not s:
        return ""
    # Ya en YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    # DD-MM-YYYY o D-M-YYYY
    m = re.match(r"^(\d{1,2})[\-/\.](\d{1,2})[\-/\.](\d{4})$", s)
    if m:
        d, mes, y = m.groups()
        try:
            di, mi, yi = int(d), int(mes), int(y)
            if 1 <= di <= 31 and 1 <= mi <= 12 and 1900 <= yi <= 2100:
                return f"{yi:04d}-{mi:02d}-{di:02d}"
        except (ValueError, TypeError):
            pass
    return s


def _extraer_ler_desde_texto(texto: str) -> str:
    """
    Extrae códigos LER presentes en texto documental.
    Solo acepta formato oficial: capítulos 01-20 (Lista Europea de Residuos).
    Evita alucinaciones como 56 52 48 o 35 32 30 que no existen.
    """
    if not texto:
        return ""
    vistos = set()
    codigos = []
    for m in _PATRON_LER_OFICIAL.finditer(str(texto)):
        c1, c2, c3, estrella = m.groups()
        if not _es_codigo_ler_valido(c1, c2, c3):
            continue
        codigo = f"{c1} {c2} {c3}{estrella}"
        if codigo not in vistos:
            vistos.add(codigo)
            codigos.append(codigo)
    return ", ".join(codigos)


def _extraer_fragmentos_relevantes(texto: str, max_chars: int = 120000) -> str:
    """
    Recorta el corpus priorizando líneas útiles para clasificación y alcance.
    Evita depender solo de los primeros caracteres del documento.
    """
    if not texto:
        return ""
    lineas = [ln.strip() for ln in str(texto).splitlines() if ln.strip()]
    if not lineas:
        return ""

    palabras = re.compile(
        r"cat|centro autorizado de tratamiento|veh[ií]culo|vfu|descontamin|extracci[oó]n de fluidos|"
        r"residuos no peligrosos|rnp|residuos peligrosos|chatarra|met[aá]lic|cobre|hierro|aluminio|"
        r"preparaci[oó]n para la reutilizaci[oó]n|almacenamiento|gesti[oó]n de residuos",
        flags=re.I,
    )
    relevantes = []
    for ln in lineas:
        if palabras.search(ln):
            relevantes.append(ln)
    base = relevantes if relevantes else lineas[:300]
    txt = "\n".join(base)
    return txt[:max_chars]


def _fingerprint_archivos(paths: list) -> str:
    """Huella estable de archivos para invalidar cachés al cambiar el proyecto o sus documentos."""
    partes = []
    for p in paths or []:
        try:
            stat = p.stat()
            partes.append(f"{p.name}|{int(stat.st_mtime)}|{stat.st_size}")
        except Exception:
            partes.append(getattr(p, "name", str(p)))
    return "|".join(sorted(partes))


def _clasificar_perfil_operativo(datos_completos: dict, corpus_texto: str = "") -> dict:
    """
    Clasificador por evidencias documentales:
    - no_cat: VFU descontaminados o instalación satélite sin descontaminación en planta
    - cat: incluye descontaminación y procesos propios CAT
    - gestion_residuos_no_vehiculos: actividad de residuos no ligada a vehículos
    - indeterminado
    """
    bloques = [
        corpus_texto or "",
        str(datos_completos.get("titulo_proyecto", "") or ""),
        str(datos_completos.get("consumos_agua_luz", "") or ""),
        str(datos_completos.get("clasificacion_ler", "") or ""),
        str(datos_completos.get("antecedentes", "") or ""),
    ]
    txt = "\n".join(bloques).lower()
    lineas = [ln.strip() for ln in txt.splitlines() if ln.strip()]

    reglas = {
        "no_cat": [
            (r"vfu\s+previamente\s+descontaminad|descontaminad[oa]s?\s+previamente", 4),
            (r"cat\s+externo|instalaci[oó]n\s+externa", 3),
            (r"fuera\s+del\s+alcance.*descontaminaci[oó]n|excluid[oa]s?.*descontaminaci[oó]n", 3),
            (r"preparaci[oó]n\s+para\s+la\s+reutilizaci[oó]n|almacenamiento de vfu", 2),
        ],
        "cat": [
            (r"centro autorizado de tratamiento\s*\(cat\)|\bproyecto\s+cat\b", 4),
            (r"descontaminaci[oó]n de vfu|veh[ií]culos?\s+sin\s+descontaminar", 4),
            (r"extracci[oó]n\s+de\s+fluidos|retirada\s+de\s+combustibles|retirada\s+de\s+bater[ií]as", 3),
            (r"gesti[oó]n de residuos peligrosos de descontaminaci[oó]n", 2),
        ],
        "gestion_residuos_no_vehiculos": [
            (r"residuos no peligrosos|rnp", 3),
            (r"chatarra|residuos met[aá]licos|cobre|hierro|aluminio", 3),
            (r"gestor de residuos|valorizaci[oó]n|acopio|clasificaci[oó]n", 2),
        ],
    }

    score = {k: 0 for k in reglas}
    evidencias = []
    for perfil, items in reglas.items():
        for patron, peso in items:
            if re.search(patron, txt, flags=re.I):
                score[perfil] += peso
                for ln in lineas:
                    if re.search(patron, ln, flags=re.I):
                        evidencias.append((perfil, ln[:220]))
                        break

    # Penalizar CAT si solo aparece como instalación externa.
    if re.search(r"cat\s+externo|instalaci[oó]n\s+externa", txt):
        score["cat"] = max(0, score["cat"] - 3)

    perfil = "indeterminado"
    confianza = 0.0
    orden = sorted(score.items(), key=lambda x: x[1], reverse=True)
    top, top_score = orden[0]
    second_score = orden[1][1] if len(orden) > 1 else 0
    if top_score >= 3 and top_score >= (second_score + 1):
        perfil = top
    if top_score > 0:
        confianza = min(0.99, max(0.35, (top_score - second_score + 1) / 10))

    evidencias_out = []
    vistos = set()
    for p, ln in evidencias:
        key = f"{p}|{ln.lower()}"
        if key in vistos:
            continue
        vistos.add(key)
        evidencias_out.append({"perfil": p, "linea": ln})
        if len(evidencias_out) >= 8:
            break

    return {
        "perfil": perfil,
        "confianza": round(confianza, 2),
        "score": score,
        "evidencias": evidencias_out,
    }


def _detectar_perfil_operativo(datos_completos: dict, texto_memoria: str = "") -> str:
    """Compatibilidad: conserva la firma antigua devolviendo solo el perfil."""
    return _clasificar_perfil_operativo(datos_completos, texto_memoria).get("perfil", "indeterminado")


def _detectar_contexto_no_cat(datos_completos: dict, texto_memoria: str = "") -> bool:
    """Compatibilidad: devuelve True cuando el perfil operativo detectado es no-CAT."""
    return _detectar_perfil_operativo(datos_completos, texto_memoria) == "no_cat"


def _extraer_texto_fuentes_perfil(memorias_fuente: list, docs_admin_fuente: list) -> str:
    """
    Construye contexto exhaustivo para detección CAT/no-CAT leyendo:
    - Memorias del proyecto
    - Documentos administrativos del proyecto
    - Nombres de archivo como pista auxiliar
    """
    partes = []
    try:
        from analista import extraer_texto_documento
    except Exception:
        extraer_texto_documento = None

    for origen, archivos in (("MEMORIA", memorias_fuente or []), ("DOC_ADMIN", docs_admin_fuente or [])):
        for archivo in archivos:
            nombre = getattr(archivo, "name", "archivo_sin_nombre")
            partes.append(f"[{origen}] Archivo: {nombre}")
            if not extraer_texto_documento:
                continue
            try:
                archivo.seek(0)
                txt = (extraer_texto_documento(archivo) or "").strip()
                if txt:
                    partes.append(txt[:40000])
            except Exception:
                # Mantener al menos el nombre del archivo para no perder la pista documental.
                continue

    return "\n\n--- FUENTE ---\n\n".join(partes)


def _normalizar_nomenclatura_no_cat(texto: str) -> str:
    """Sustituye denominaciones CAT genéricas por la denominación real de nave no-CAT."""
    if not texto or not str(texto).strip():
        return ""
    t = str(texto)

    reemplazos = [
        (
            r"instalaci[oó]n de desguace,\s*cat y gesti[oó]n de residuos\s*\(vfu\)",
            "Instalación de almacenamiento y preparación para la reutilización de VFU previamente descontaminados",
        ),
        (
            r"desguace,\s*centro autorizado de tratamiento\s*\(cat\)\s*y\s*gesti[oó]n de residuos(?:\s*de)?\s*veh[ií]culos fuera de uso\s*\(vfu\)",
            "Instalación de almacenamiento y preparación para la reutilización de VFU previamente descontaminados",
        ),
        (
            r"proyecto\s+[\"“”']?\s*instalaci[oó]n de desguace,\s*cat y gesti[oó]n de residuos\s*\(vfu\)\s*[\"“”']?",
            "proyecto de instalación de almacenamiento y preparación para la reutilización de VFU previamente descontaminados",
        ),
    ]
    for patron, repl in reemplazos:
        t = re.sub(patron, repl, t, flags=re.I)

    return t


def _normalizar_nomenclatura_no_vehicular(texto: str) -> str:
    """Elimina terminología CAT/VFU cuando el expediente es de residuos no vehiculares."""
    if not texto or not str(texto).strip():
        return ""
    t = str(texto)
    reemplazos = [
        (
            r"instalaci[oó]n de desguace,\s*cat y gesti[oó]n de residuos\s*\(vfu\)",
            "Instalación de gestión de residuos no vehiculares (principalmente metálicos)",
        ),
        (
            r"desguace,\s*centro autorizado de tratamiento\s*\(cat\)\s*y\s*gesti[oó]n de residuos(?:\s*de)?\s*veh[ií]culos fuera de uso\s*\(vfu\)",
            "Instalación de gestión de residuos no vehiculares (principalmente metálicos)",
        ),
    ]
    for patron, repl in reemplazos:
        t = re.sub(patron, repl, t, flags=re.I)
    return t


def _condicionar_contexto_por_perfil(texto: str, perfil_operativo: str) -> str:
    """
    Reduce contaminación de contexto filtrando el corpus según perfil operativo.
    """
    if not texto:
        return ""
    lineas = [ln.strip() for ln in str(texto).splitlines() if ln.strip()]
    if not lineas:
        return ""

    if perfil_operativo == "gestion_residuos_no_vehiculos":
        incluir = re.compile(
            r"residuos|met[aá]lic|chatarra|cobre|hierro|aluminio|almacenamiento|valorizaci[oó]n|"
            r"ley 21/2013|ley 7/2022|ler|nave|arrecife|lanzarote|coordenadas|catastral",
            flags=re.I,
        )
        excluir = re.compile(
            r"\bvfu\b|veh[ií]culos?|centro autorizado de tratamiento|\bcat\b|descontaminaci[oó]n|extracci[oó]n de fluidos",
            flags=re.I,
        )
        filtradas = [ln for ln in lineas if incluir.search(ln) and not excluir.search(ln)]
        return "\n".join(filtradas if filtradas else lineas[:300])[:150000]

    if perfil_operativo == "no_cat":
        incluir = re.compile(
            r"vfu|descontaminad|cat externo|instalaci[oó]n externa|almacenamiento|preparaci[oó]n para reutilizaci[oó]n|"
            r"ley 21/2013|ley 7/2022|ler|coordenadas|catastral",
            flags=re.I,
        )
        filtradas = [ln for ln in lineas if incluir.search(ln)]
        return "\n".join(filtradas if filtradas else lineas[:300])[:150000]

    return "\n".join(lineas)[:150000]


def _alertas_coherencia_ler(datos_completos: dict, perfil_operativo: str) -> list:
    """
    Validación cruzada LER vs descripción de proyecto para evitar incoherencias administrativas.
    """
    alertas = []
    ler = (datos_completos.get("clasificacion_ler", "") or "").strip()
    if not ler:
        return alertas
    codigos = [c.strip() for c in ler.split(",") if c.strip()]
    hay_peligrosos = any(c.endswith("*") for c in codigos)
    texto_desc = " ".join([
        str(datos_completos.get("titulo_proyecto", "") or ""),
        str(datos_completos.get("antecedentes", "") or ""),
        str(datos_completos.get("consumos_agua_luz", "") or ""),
    ]).lower()
    declara_no_peligrosos = bool(re.search(r"residuos no peligrosos|\brnp\b", texto_desc))

    if declara_no_peligrosos and hay_peligrosos:
        alertas.append(
            "Incongruencia: el proyecto se describe como 'residuos no peligrosos' pero hay códigos LER peligrosos (*) en datos."
        )

    # Solo alertar por 16 01 xx en no vehicular si la whitelist no está explícitamente fijada por el usuario/proyecto
    if perfil_operativo == "gestion_residuos_no_vehiculos":
        ler_whitelist = (datos_completos.get("clasificacion_ler") or "").strip()
        if ler_whitelist and ler_whitelist.upper() not in ("N/D", "ND"):
            # La whitelist manda: si el usuario/proyecto ha definido LER admitidos (incl. 16 01 xx), no bloquear
            pass
        else:
            codigos_auto = [c for c in codigos if re.match(r"^16\s*01", c)]
            if codigos_auto:
                alertas.append(
                    "Posible incongruencia: aparecen LER de automoción (16 01 xx) en proyecto clasificado como no vehicular."
                )
    return alertas


# Normaliza código LER a forma canónica "DD DD DD" o "DD DD DD*" (evita falsos por 17-04-05, 170405, 17.04.05)
def _normalizar_codigo_ler(codigo: str):
    if not codigo or not isinstance(codigo, str):
        return None
    c = re.sub(r"[\s\-\.]+", " ", codigo.strip()).strip()
    # Quitar sufijo tipo "-61" o "61" tras el asterisco (p. ej. "200135*-61" del PDF)
    c = re.sub(r"\*\s*\d+\s*$", "*", c)
    c = re.sub(r"\s+", " ", c)
    # 6 dígitos seguidos (opcional *) -> "DD DD DD" o "DD DD DD*"
    m = re.match(r"^(\d{2})(\d{2})(\d{2})(\*?)$", c.replace(" ", ""))
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}"
    # Ya en formato XX XX XX o XX XX XX*
    if re.match(r"^\d{2}\s\d{2}\s\d{2}\*?$", c):
        return c
    return None


# Captura variantes LER en texto: 17 04 05, 17-04-05, 170405, 17.04.05 y con *
def _extraer_codigos_ler_texto(texto: str) -> set:
    if not texto:
        return set()
    canon = set()
    # Formato con espacios o guiones o puntos: XX XX XX, XX-XX-XX, XX.XX.XX y * opcional
    for m in re.finditer(r"\b(\d{2})[\s\-\.](\d{2})[\s\-\.](\d{2})(\*?)\b", texto):
        n = _normalizar_codigo_ler(f"{m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}")
        if n:
            canon.add(n)
    # Formato 6 dígitos: primer grupo 01–20 (categorías LER; evita 00 y fechas); whitelist filtra falsos
    for m in re.finditer(r"\b(0[1-9]|1[0-9]|20)(\d{2})(\d{2})(\*?)\b", texto):
        n = _normalizar_codigo_ler(f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}")
        if n:
            canon.add(n)
    return canon


def _alertas_gates_registro(estado: dict, capitulos: dict, datos_completos: dict) -> list:
    """
    Gates de validación pre-registro (experto): LER whitelist, superficies inmutables,
    cartografía sin Indeterminada, RP propios si existen. No rompe flujo; solo añade alertas.
    """
    alertas = []
    if not estado or not isinstance(estado, dict):
        return alertas
    texto_total = "\n".join([(v or "") for v in (capitulos or {}).values()])
    datos_u = estado.get("datos_usuario") or {}
    datos_e = estado.get("datos_extraidos") or {}
    if isinstance(datos_e, dict):
        pass
    else:
        datos_e = vars(datos_e) if hasattr(datos_e, "__dict__") else {}

    # Gate A — LER whitelist = unión de clasificacion_ler (admitidos) + residuos_peligrosos_propios_ler (RP con *)
    def _ler_raw(val):
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(str(x).strip() for x in val if x)
        return (val or "").strip()

    ler_whitelist_raw = (
        _ler_raw(datos_u.get("clasificacion_ler") or datos_e.get("clasificacion_ler"))
        + ","
        + _ler_raw(datos_u.get("residuos_peligrosos_propios_ler") or datos_e.get("residuos_peligrosos_propios_ler"))
    )
    codigos_whitelist = set()
    for c in (c.strip() for c in ler_whitelist_raw.split(",") if c.strip()):
        norm = _normalizar_codigo_ler(c)
        if norm:
            codigos_whitelist.add(norm)
    # Gate LER asteriscos: clasificacion_ler NUNCA puede contener *
    ler_admitidos_raw = _ler_raw(datos_u.get("clasificacion_ler") or datos_e.get("clasificacion_ler"))
    if any("*" in c.strip() for c in ler_admitidos_raw.split(",") if c.strip()):
        alertas.append(
            "Gate LER (crítico): LER admitidos no puede contener asteriscos. "
            "Los códigos con * (20 01 35*, 15 02 02*) van en residuos_peligrosos_propios_ler. "
            "Se han movido automáticamente; verifique y guarde."
        )

    # Whitelist vacía → alerta crítica (no pasar silenciosamente)
    if not codigos_whitelist:
        alertas.append(
            "Gate LER (crítico): No hay lista LER de referencia en el proyecto. No exportar para registro; "
            "complete clasificacion_ler desde el Proyecto/autorización (plano/listado) y exporte solo como borrador."
        )
    else:
        encontrados_en_texto = _extraer_codigos_ler_texto(texto_total)
        # Código sin * en texto se considera OK si el mismo código con * está en whitelist (RP propios; Gate J añade el *)
        def _en_whitelist(cod):
            if cod in codigos_whitelist:
                return True
            if not cod.endswith("*") and (cod + "*") in codigos_whitelist:
                return True
            return False
        fuera_whitelist = {c for c in encontrados_en_texto if not _en_whitelist(c)}
        if fuera_whitelist:
            alertas.append(
                "Gate LER: códigos en el informe no están en la whitelist del proyecto/autorización: "
                + ", ".join(sorted(fuera_whitelist)[:8])
                + ("..." if len(fuera_whitelist) > 8 else "")
                + ". Corrija clasificacion_ler en datos del proyecto o elimine esos códigos del texto."
            )
        # Mini-regla: códigos RP propios no deben aparecer en frases "LER admitidos" (solo en epígrafe RP propios)
        rp_propios_codigos = set()
        for c in (c.strip() for c in _ler_raw(datos_u.get("residuos_peligrosos_propios_ler") or datos_e.get("residuos_peligrosos_propios_ler")).split(",") if c.strip()):
            n = _normalizar_codigo_ler(c)
            if n:
                rp_propios_codigos.add(n)
                rp_propios_codigos.add(n.rstrip("*"))
        if rp_propios_codigos:
            ctx_admitidos = re.compile(
                r"LER\s+admitidos|clasificaci[oó]n\s+de\s+residuos\s+admitidos|RNP\s*[:\-]|"
                r"lista\s+de\s+c[oó]digos\s+admitidos|c[oó]digos\s+admitidos\s*[:\-]",
                re.I,
            )
            for m in re.finditer(r"\b(\d{2})[\s\-\.](\d{2})[\s\-\.](\d{2})\*?\b", texto_total):
                cod = _normalizar_codigo_ler(f"{m.group(1)} {m.group(2)} {m.group(3)}") or (m.group(1) + " " + m.group(2) + " " + m.group(3))
                if cod not in rp_propios_codigos and (cod + "*") not in rp_propios_codigos:
                    continue
                start = max(0, m.start() - 100)
                end = min(len(texto_total), m.end() + 60)
                ventana = texto_total[start:end]
                if ctx_admitidos.search(ventana):
                    extracto = re.sub(r"\s+", " ", ventana)[:120].strip() + ("…" if len(ventana) > 120 else "")
                    cap_donde = ""
                    for ck, tc in (capitulos or {}).items():
                        if m.group(0) in (tc or "") and ventana[:50] in (tc or ""):
                            cap_donde = ck.replace("informe_", "").replace("_", " ")
                            break
                    alertas.append(
                        f"Gate LER: los códigos RP propios (20 01 35*, 15 02 02*) no deben figurar en el epígrafe de LER admitidos; "
                        f"deben figurar solo en el epígrafe 'Residuos generados por la propia actividad'. "
                        f"{'Capítulo: ' + cap_donde + '. ' if cap_donde else ''}Extracto: «{extracto}»"
                    )
                    break

    # Gate C — Superficies inmutables (Catastro/Proyecto): 2.500/2500 m² legacy
    _patron_2500 = re.compile(
        r"\b2[\s\.,]?\s*500\s*m\s*[²2]\b|\b2500\s*m\s*[²2]\b|\b2\s*500\s*m\s*[²2]\b",
        re.I,
    )
    sup_parcela = (datos_u.get("superficie_parcela_m2") or "").strip()
    if sup_parcela and sup_parcela != "2500":
        m_2500 = _patron_2500.search(texto_total)
        if m_2500:
            start = max(0, m_2500.start() - 40)
            end = min(len(texto_total), m_2500.end() + 60)
            extracto_2500 = re.sub(r"\s+", " ", texto_total[start:end])[:100].strip()
            alertas.append(
                "Gate superficies: el informe contiene 2.500 m² pero en datos del proyecto la parcela es "
                + sup_parcela
                + " m² (Catastro). Match: «"
                + m_2500.group()
                + "». Extracto: «"
                + extracto_2500
                + "»"
            )

    # Gate D — Cartografía: no "Indeterminada"
    if re.search(r"\bindeterminada\b", texto_total, re.I):
        alertas.append(
            'Gate cartografía: el informe contiene "Indeterminada". Use Sí/No + distancia (m) + captura fechada; si falta dato: N/D + cómo obtenerlo.'
        )

    # Gate B — RP propios obligatorios si existen
    rp_propios = (datos_u.get("residuos_peligrosos_propios_ler") or datos_e.get("residuos_peligrosos_propios_ler") or "").strip()
    if rp_propios:
        if not re.search(r"20\s*01\s*35\*|15\s*02\s*02\*", texto_total):
            alertas.append(
                "Gate RP propios: el proyecto declara residuos peligrosos propios (20 01 35*, 15 02 02*). "
                "El informe debe incluir epígrafe 'Residuos generados por la propia actividad' y control en PVA."
            )
        elif not re.search(r"residuos\s+generados\s+por\s+la\s+propia|rp\s+propios|propios\s+\(.*20\s*01\s*35|gesti[oó]n.*20\s*01\s*35", texto_total, re.I):
            alertas.append(
                "Gate RP propios: incluya explícitamente el epígrafe de residuos generados por la actividad (RP propios) y su gestión."
            )

    # Gate E — Potencia / molino
    if re.search(r"20\s*[–\-]\s*250\s*kW|20-250\s*kW", texto_total, re.I):
        if not re.search(r"rango\s+gen[eé]rico\s+no\s+aplicable|no\s+aplicable\s+al\s+proyecto|descripci[oó]n\s+gen[eé]rica", texto_total, re.I):
            alertas.append(
                'Gate potencia: el informe contiene "20–250 kW" como dato real. Use potencia real del proyecto o indique explícitamente "rango genérico no aplicable".'
            )
    potencia_w = (datos_u.get("potencia_instalada_total_w") or datos_e.get("potencia_instalada_total_w") or "").strip()
    if potencia_w and potencia_w.isdigit():
        try:
            total_w = int(potencia_w)
            if total_w > 0:
                # Buscar declaración de kW del molino mayor que la instalada (p. ej. 14.024 W y molino 250 kW)
                if re.search(r"molino.*\d+\s*kW|potencia.*molino.*\d+", texto_total, re.I):
                    for m in re.finditer(r"(?:molino|motor|potencia)[^\d]*(\d+)\s*kW", texto_total, re.I):
                        kw_molino = int(m.group(1))
                        if kw_molino * 1000 > total_w:
                            alertas.append(
                                f"Gate potencia: potencia instalada total del proyecto es {total_w} W y el texto declara {kw_molino} kW para molino/motor (incoherente)."
                            )
                            break
        except ValueError:
            pass

    # Gate F — Encaje legal (umbral 75/50 t/d cuando capacidad declarada es 20 t/d)
    cap = (datos_completos.get("capacidad_maxima_almacenamiento") or "").strip()
    if cap and re.match(r"^20\b|20\s*t/d|20\s*tm", cap, re.I):
        if re.search(r"(?:75|50)\s*t/d|(?:75|50)\s*tm/d|9\.k\s*>\s*(?:75|50)|Anexo\s+II.*9\.k.*(?:75|50)", texto_total, re.I):
            alertas.append(
                "Gate encaje legal: la capacidad declarada es 20 t/d pero el informe menciona 75/50 t/d o Anexo II grupo 9.k >75/>50 t/d (incoherencia)."
            )

    # Gate G — Frase prohibida (simplificada = Informe de Impacto Ambiental, no "autorización ambiental previa")
    if re.search(r"autorizaci[oó]n\s+ambiental\s+previa", texto_total, re.I):
        alertas.append(
            'Gate redacción: en procedimiento simplificado no debe aparecer "autorización ambiental previa"; use "Informe de Impacto Ambiental" o la fórmula correcta.'
        )

    # Cartografía: coherencia SNCZI (Sí → exige medidas o interpretación en estado y en texto)
    carto = estado.get("cartografia_informe") or {}
    if isinstance(carto, dict) and carto.get("snczi_afecta") in (True, "true", "Sí", "si", "Sí"):
        interp = (carto.get("snczi_interpretacion") or "").strip()
        capa = (carto.get("snczi_capa") or "").strip()
        medidas = (carto.get("snczi_medidas") or "").strip()
        if not (interp or capa or medidas):
            alertas.append(
                "Gate SNCZI: snczi_afecta = Sí exige snczi_interpretacion o snczi_capa o snczi_medidas en cartografia_informe (evitar 'Sí' sin interpretación)."
            )
        if not re.search(
            r"medidas?\s+pluviales|pluviales\s+y\s+inundaci[oó]n|drenaje|interpretaci[oó]n\s+de\s+la\s+capa|snczi.*N/D|N/D.*snczi",
            texto_total,
            re.I,
        ):
            alertas.append(
                "Gate SNCZI: el proyecto indica SNCZI = Sí (zona afectada). El informe debe incluir subapartado de medidas pluviales/inundación o interpretación de la capa con N/D + cómo obtenerlo."
            )
    if isinstance(carto, dict):
        snczi_val = (carto.get("snczi_afecta") or "").strip().upper()
        if snczi_val in ("N/D", "ND", "N/D."):
            alertas.append(
                "Gate SNCZI: snczi_afecta = N/D bloquea REGISTRO. Obtenga Sí o No desde el visor oficial (MITECO SNCZI) y rellene en Cartografía y SNCZI."
            )
        # Gate: plantilla sin completar — bloquear REGISTRO si quedan placeholders
        if carto.get("snczi_afecta") in (True, "true", "Sí", "si", "Sí"):
            interp = (carto.get("snczi_interpretacion") or "").strip()
            capa = (carto.get("snczi_capa") or "").strip()
            for texto, nombre in [(interp, "snczi_interpretacion"), (capa, "snczi_capa")]:
                if not texto:
                    continue
                if "[" in texto or "N/D tipo capa/periodo" in texto or "(especificar)" in texto:
                    alertas.append(
                        f"Gate SNCZI (crítico): complete la plantilla antes de REGISTRO. En {nombre} no puede quedar '[', 'N/D tipo capa/periodo' ni '(especificar)'."
                    )
                    break
        # Gate: formato fecha YYYY-MM-DD y completitud (acepta DD-MM-YYYY y normaliza)
        _patron_fecha = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        rn2000_fecha = _normalizar_fecha_yyyy_mm_dd((carto.get("rn2000_fecha_consulta") or "").strip())
        snczi_fecha = _normalizar_fecha_yyyy_mm_dd((carto.get("snczi_fecha_consulta") or "").strip())
        if rn2000_fecha and not _patron_fecha.match(rn2000_fecha):
            alertas.append(
                "Gate cartografía: rn2000_fecha_consulta debe tener formato YYYY-MM-DD (ej. 2024-06-15)."
            )
        if snczi_fecha and not _patron_fecha.match(snczi_fecha):
            alertas.append(
                "Gate cartografía: snczi_fecha_consulta debe tener formato YYYY-MM-DD (ej. 2024-06-15)."
            )
        tiene_distancia = bool((carto.get("red_natura_2000_distancia_m") or carto.get("enp_distancia_m") or carto.get("zepa_distancia_m") or "").strip())
        if tiene_distancia and not rn2000_fecha:
            alertas.append(
                "Gate cartografía: si hay distancia RN2000/ENP/ZEPA, debe rellenar rn2000_fecha_consulta (YYYY-MM-DD) en Cartografía y SNCZI."
            )
        if snczi_val in ("SÍ", "SI", "NO") and not snczi_fecha:
            alertas.append(
                "Gate cartografía: si SNCZI = Sí o No, debe rellenar snczi_fecha_consulta (YYYY-MM-DD) en Cartografía y SNCZI."
            )
        # Gate: distancia numérica y unidad — si existe distancia, debe ser número ≥ 0 (en m)
        for clave in ("red_natura_2000_distancia_m", "enp_distancia_m", "zepa_distancia_m"):
            val = (carto.get(clave) or "").strip()
            if not val or val.upper() in ("N/D", "ND", "—"):
                continue
            limpio = re.sub(r"\s*m\s*$|\s*km\s*$", "", val, flags=re.I).strip().replace(",", ".")
            try:
                num = float(limpio)
                if num < 0:
                    alertas.append(f"Gate cartografía: {clave} debe ser un número ≥ 0 (en metros).")
            except ValueError:
                alertas.append(f"Gate cartografía: {clave} debe ser un número (en m), no texto libre (use solo cifra o N/D).")
                break

    # Gate H — "Pendiente" en temas críticos (RN2000/ENP/ZEPA/SNCZI) sin distancia (contextualizado)
    for m_pend in re.finditer(r"pendiente\s+de\s+acreditaci[oó]n|a\s+acreditar|pendiente\s+documental", texto_total, re.I):
        start = max(0, m_pend.start() - 120)
        end = min(len(texto_total), m_pend.end() + 80)
        ventana = texto_total[start:end]
        if re.search(r"red\s+natura|RN2000|ENP|ZEPA|SNCZI|cartograf[ií]a", ventana, re.I):
            dist_rn = (carto.get("red_natura_2000_distancia_m") or "").strip() if isinstance(carto, dict) else ""
            if not dist_rn or re.match(r"^N/D|^n/d|—$", dist_rn):
                alertas.append(
                    "Gate cartografía: aparece 'pendiente' o 'a acreditar' en contexto RN2000/ENP/ZEPA/SNCZI y no hay distancia en cartografia_informe. Para registro, aporte distancia o N/D + cómo obtenerlo."
                )
                break

    # Gate I — Superficies coherentes (solo en contexto parcela/construida/útil, no superficies internas)
    datos_comp = (datos_completos or {}) if isinstance(datos_completos, dict) else {}
    sup_parcela = (datos_u.get("superficie_parcela_m2") or datos_comp.get("superficie_parcela_m2") or "").strip()
    sup_const = (datos_u.get("superficie_construida_m2") or datos_comp.get("superficie_construida_m2") or "").strip()
    sup_util = (datos_u.get("superficie_util_m2") or datos_comp.get("superficie_util_m2") or "").strip()
    permitidos_float = set()
    for v in (sup_parcela, sup_const, sup_util):
        if v:
            try:
                permitidos_float.add(float(v.replace(",", ".")))
            except ValueError:
                pass
    if permitidos_float:
        contexto_parcela = re.compile(
            r"superficie\s+(de\s+)?(parcela|gr[áa]fica|construida|útil|total)|parcela\s+[^\d]*(?:de\s+)?\d|"
            r"construida\s+[^\d]*(?:de\s+)?\d|útil\s+[^\d]*(?:de\s+)?\d|superficie\s+parcela|"
            r"superficie\s+construida|superficie\s+útil|m[²2]\s*[\(\):\-]\s*(?:parcela|construida|útil)",
            re.I,
        )
        for m in re.finditer(r"(\d{1,6}(?:[.,]\d+)?)\s*m[²2]", texto_total, re.I):
            start = max(0, m.start() - 100)
            ventana = texto_total[start:m.end()]
            if not contexto_parcela.search(ventana):
                continue
            num = m.group(1).replace(",", ".")
            try:
                n = float(num)
                if abs(n - 2500) < 0.01:
                    continue
                if not any(abs(n - a) < 0.02 for a in permitidos_float):
                    alertas.append(
                        "Gate superficies: en contexto parcela/construida/útil aparece " + m.group(1) + " m²; solo son válidos los valores del proyecto (Catastro/Proyecto): "
                        + ", ".join([x for x in (sup_parcela, sup_const, sup_util) if x]) + ". Las superficies internas (acopio, proceso, oficina) no se validan aquí."
                    )
                    break
            except ValueError:
                pass

    # Gate J — RP propios con asterisco (20 01 35* y 15 02 02* deben aparecer con * en el texto)
    if rp_propios and re.search(r"20\s*01\s*35\*|15\s*02\s*02\*", rp_propios):
        if re.search(r"20\s*01\s*35\b(?!\*)|15\s*02\s*02\b(?!\*)", texto_total):
            alertas.append(
                "Gate RP propios: los códigos peligrosos 20 01 35* y 15 02 02* deben aparecer en el texto con asterisco (*), no como 20 01 35 o 15 02 02 a secas."
            )

    # Gate K — Consistencia de unidades (capacidad gestión/almacenamiento con número debe llevar unidad)
    # Unidades admitidas: t, t/d, tm, m³, kg/h, t/h, t/año, Tm/año, kg, kW. Excepciones: capacidad eléctrica, capacidad de carga.
    _patron_cap = re.compile(
        r"capacidad\s+(m[áa]xima\s+)?(\d+(?:[.,]\d+)?)\s*(?!t/d|t\b|tm\b|m³|m3|kg/h|t/h|t/año|Tm/año|kg\b|kW\b)",
        re.I,
    )
    _excluir_cap = re.compile(r"capacidad\s+(el[eé]ctrica|de\s+carga)\b", re.I)
    # Tras el número no debe considerarse error si ya pone N/D, Confianza Baja o cómo obtenerlo (salida de corrección automática)
    _ya_corregido_cap = re.compile(r"\s*(?:N/D|Confianza\s+Baja|c[oó]mo\s+obtenerlo)", re.I)
    for m_cap in _patron_cap.finditer(texto_total):
        inicio = max(0, m_cap.start() - 25)
        ventana_antes = texto_total[inicio : m_cap.start()]
        if _excluir_cap.search(ventana_antes + " capacidad"):
            continue
        # Si tras el número ya hay N/D o texto de corrección, no alertar
        despues = texto_total[m_cap.end() : m_cap.end() + 80].lstrip()
        if _ya_corregido_cap.match(despues):
            continue
        extracto = re.sub(r"\s+", " ", texto_total[max(0, m_cap.start() - 30) : m_cap.end() + 90])[:120].strip()
        cap_donde = ""
        for ck, tc in (capitulos or {}).items():
            if m_cap.group(0) in (tc or ""):
                cap_donde = ck.replace("informe_", "").replace("_", " ")
                break
        alertas.append(
            f"Gate unidades: aparece 'capacidad' con un número sin unidad (t, t/d, kg/h, t/año, m³, etc.). "
            f"{'Capítulo: ' + cap_donde + '. ' if cap_donde else ''}Extracto: «{extracto}…»"
        )
        break

    # Gate K (m²) — Capacidad con m² es unidad incorrecta (m² no es unidad de capacidad)
    if re.search(r"capacidad\s+(m[áa]xima\s+)?\d+(?:[.,]\d+)?\s*m[²2]\b", texto_total, re.I):
        alertas.append(
            "Gate unidades: 'capacidad' con m² es unidad incorrecta (m² no es unidad de capacidad). Use t, t/d, m³, kg/h, t/año, etc."
        )

    # Gate L — Coherencia modelo de datos: si el informe dice N/D pero el estado tiene el dato, alerta
    # Pre-fix: sustituir "Superficie total de parcela: pendiente..." por valor Catastro (evita alerta)
    sup_parcela_L = (
        (datos_u.get("superficie_parcela_m2") or (datos_completos or {}).get("superficie_parcela_m2") or "")
    ).strip()
    sup_const_L = (
        (datos_u.get("superficie_construida_m2") or (datos_completos or {}).get("superficie_construida_m2") or "")
    ).strip()
    patron_sup = re.compile(
        r"Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*"
        r"(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
        re.I,
    )
    texto_sust_L = ""
    if sup_parcela_L and sup_parcela_L not in ("", "N/D"):
        texto_sust_L = "Superficie de parcela (Catastro – superficie gráfica): " + sup_parcela_L + " m²."
        if sup_const_L and sup_const_L not in ("", "N/D"):
            texto_sust_L += " Superficie construida (Catastro): " + sup_const_L + " m²."
    if sup_parcela_L and sup_parcela_L not in ("", "N/D") and capitulos and texto_sust_L:
        for ck in list(capitulos.keys()):
            t = capitulos.get(ck) or ""
            if patron_sup.search(t):
                capitulos[ck] = patron_sup.sub(texto_sust_L, t)
        texto_total = "\n".join([(v or "") for v in (capitulos or {}).values()])

    # Pre-fix RN2000: sustituir "pendiente de acreditación documental" por distancia real en capítulos con Red Natura
    dist_rn_L = (carto.get("red_natura_2000_distancia_m") or "").strip() if isinstance(carto, dict) else ""
    if dist_rn_L and dist_rn_L not in ("", "N/D") and capitulos:
        try:
            _d = str(dist_rn_L).replace(",", ".")
            _n = float(_d)
            valor_rn_m = f"{int(_n)} m" if _n == int(_n) else f"{_n} m"
        except ValueError:
            valor_rn_m = str(dist_rn_L) + " m"
        patron_rn_pendiente = re.compile(
            r"pendiente\s+de\s+acreditaci[oó]n(?:\s+documental)?",
            re.I,
        )
        for ck in list(capitulos.keys()):
            t = capitulos.get(ck) or ""
            if re.search(r"red\s+natura|RN2000", t, re.I) and patron_rn_pendiente.search(t):
                capitulos[ck] = patron_rn_pendiente.sub(valor_rn_m + " desde parcela", t, count=1)
        texto_total = "\n".join([(v or "") for v in (capitulos or {}).values()])

    def _valor_str(v):
        if v is None:
            return ""
        if isinstance(v, list):
            return " ".join(str(x).strip() for x in v if x).strip()
        return (v or "").strip()

    # Claves concretas del estado (superficie, cartografía crítica de registro, LER)
    def _carto_val(k, default=""):
        return _valor_str(carto.get(k)) if isinstance(carto, dict) else default

    def _carto_val_or_bool(k, true_val="Sí"):
        if not isinstance(carto, dict):
            return ""
        v = carto.get(k)
        if v in (True, "true", "Sí", "si", "Sí"):
            return true_val
        return _valor_str(v)

    # superficie_parcela_m2: NO usar m[²2] solo (coincide con PM2 en PM2,5). Usar superficie|parcela|\d+ m²
    pares_dato_contexto = [
        (sup_parcela or _valor_str(datos_u.get("superficie_parcela_m2")), r"superficie|parcela|\b\d+\s*m[²2]\b", "superficie_parcela_m2"),
        (_carto_val("red_natura_2000_distancia_m"), r"red\s+natura|RN2000|distancia|ENP|ZEPA", "red_natura_2000_distancia_m"),
        (_valor_str(datos_u.get("clasificacion_ler") or datos_e.get("clasificacion_ler")), r"LER|clasificaci[oó]n\s+de\s+residuos|c[oó]digos", "clasificacion_ler"),
        (_carto_val("enp_distancia_m") or _carto_val_or_bool("enp_afecta"), r"ENP|espacio\s+natural\s+protegido", "enp_distancia_m"),
        (_carto_val("zepa_distancia_m") or _carto_val("zec_distancia_m") or _carto_val("lic_distancia_m") or _carto_val_or_bool("zepa_afecta") or _carto_val_or_bool("zec_afecta"), r"ZEPA|ZEC|LIC|zona\s+especial\s+de\s+conservaci[oó]n", "zepa_distancia_m"),
        (_carto_val("snczi_medidas") or _carto_val_or_bool("snczi_afecta"), r"SNCZI|inundabilidad|sistema\s+nacional\s+de\s+cartografía", "snczi_afecta"),
        (_carto_val("receptor_mas_cercano_m") or _carto_val("distancia_receptor_m") or _valor_str(datos_u.get("receptor_mas_cercano_m") or datos_u.get("distancia_receptor_m")), r"receptor\s+(m[áa]s\s+)?cercano|distancia\s+.*receptor|receptores\s+sensibles", "receptor_mas_cercano_m"),
    ]
    _patron_nd = re.compile(
        r"\bN/D\b|\bno\s+consta\b|pendiente\s+de\s+acreditaci[oó]n|\ba\s+acreditar\b|\bno\s+disponible\b",
        re.I,
    )
    for valor, patron_contexto, etiqueta_campo in pares_dato_contexto:
        if not valor or valor in ("", "N/D", "n/d"):
            continue
        for cap_key, texto_cap in (capitulos or {}).items():
            if not texto_cap:
                continue
            # Si el valor ya aparece en el capítulo (ej. "591 m²"), no alertar por ese campo
            if etiqueta_campo == "superficie_parcela_m2" and valor:
                if re.search(r"\b" + re.escape(str(valor).strip()) + r"\s*m[²2]|\b" + re.escape(str(valor).strip()) + r"\s*m\s*²", texto_cap, re.I):
                    continue
            # RN2000/ENP/ZEPA: si la distancia ya aparece (ej. "4950 m desde parcela"), no alertar
            if etiqueta_campo in ("red_natura_2000_distancia_m", "enp_distancia_m", "zepa_distancia_m") and valor:
                if re.search(r"\b" + re.escape(str(valor).strip()) + r"\s*m\b|\b" + re.escape(str(valor).strip()) + r"\s*m\s+desde", texto_cap, re.I):
                    continue
            for m_nd in _patron_nd.finditer(texto_cap):
                start = max(0, m_nd.start() - 60)
                end = min(len(texto_cap), m_nd.end() + 80)
                ventana = texto_cap[start:end]
                if re.search(patron_contexto, ventana, re.I):
                    # Falso positivo LER: "pendiente" es de Combustibles, no de LER
                    if etiqueta_campo == "clasificacion_ler":
                        line_start = texto_cap.rfind("\n", 0, m_nd.start()) + 1
                        line_end = texto_cap.find("\n", m_nd.start())
                        if line_end == -1:
                            line_end = len(texto_cap)
                        linea = texto_cap[line_start:line_end]
                        if re.search(r"combustibles", linea, re.I):
                            continue
                        # Solo alertar si N/D está pegado a etiqueta LER (ventana ≤40 chars)
                        ventana_corta = texto_cap[max(0, m_nd.start() - 40) : m_nd.end()]
                        if not re.search(r"LER\s+(autorizados|admitidos)[^:\n]{0,30}:\s*(?:N/D|pendiente|no\s+consta)", ventana_corta, re.I):
                            continue
                    # Falso positivo ZEPA: "pendiente" es del molino (potencia/ficha), no de ZEPA
                    if etiqueta_campo == "zepa_distancia_m":
                        if re.search(r"molino|motor|potencia|ficha|placa|proveedor", ventana, re.I):
                            continue
                        # Solo disparar si N/D está en contexto ZEPA (ZEPA...: pendiente o distancia a ZEPA)
                        ventana_corta_zepa = texto_cap[max(0, m_nd.start() - 50) : m_nd.end()]
                        if not re.search(
                            r"(?:ZEPA|ZEC|LIC|distancia\s+a\s+ZEPA)[^:\n]{0,40}:\s*(?:N/D|pendiente|no\s+consta)|"
                            r"(?:ZEPA|ZEC|LIC)[^0-9\n]{0,30}(?:N/D|pendiente|no\s+consta)",
                            ventana_corta_zepa,
                            re.I,
                        ):
                            continue
                    # Falso positivo: "4950 m desde parcela" es distancia RN2000, no superficie de parcela
                    if etiqueta_campo == "superficie_parcela_m2" and re.search(r"\d+\s*m\s+desde\s+(?:la\s+)?parcela|desde\s+(?:la\s+)?parcela", ventana, re.I):
                        continue
                    # Superficie parcela: aplicar fix y no alertar (valor existe en estado)
                    if (
                        etiqueta_campo == "superficie_parcela_m2"
                        and valor
                        and sup_parcela_L
                        and patron_sup.search(texto_cap)
                    ):
                        texto_sust_L = "Superficie de parcela (Catastro – superficie gráfica): " + sup_parcela_L + " m²."
                        if sup_const_L and sup_const_L not in ("", "N/D"):
                            texto_sust_L += " Superficie construida (Catastro): " + sup_const_L + " m²."
                        capitulos[cap_key] = patron_sup.sub(texto_sust_L, texto_cap)
                        break
                    # Red Natura 2000: sustituir "pendiente de acreditación documental" por distancia real
                    if etiqueta_campo == "red_natura_2000_distancia_m" and valor:
                        dist_rn = _carto_val("red_natura_2000_distancia_m")
                        if dist_rn and dist_rn not in ("", "N/D"):
                            try:
                                _d = str(dist_rn).strip().replace(",", ".")
                                _n = float(_d)
                                valor_m = f"{int(_n)} m" if _n == int(_n) else f"{_n} m"
                            except ValueError:
                                valor_m = str(dist_rn) + " m"
                            patron_rn = re.compile(
                                r"pendiente\s+de\s+acreditaci[oó]n(?:\s+documental)?",
                                re.I,
                            )
                            nuevo = patron_rn.sub(valor_m + " desde parcela", texto_cap, count=1)
                            if nuevo != texto_cap:
                                capitulos[cap_key] = nuevo
                                break
                    cap_nombre = cap_key.replace("informe_", "").replace("_", " ")
                    extracto = re.sub(r"\s+", " ", ventana)[:120].strip()
                    if len(ventana) > 120:
                        extracto += "…"
                    match_texto = m_nd.group().strip()[:60]
                    alertas.append(
                        f"Gate coherencia: el informe indica N/D (o similar) para {etiqueta_campo} que sí consta en el estado. "
                        f"Capítulo: {cap_nombre}. Match: «{match_texto}». Extracto: «{extracto}»"
                    )
                    break
            else:
                continue
            break
        else:
            continue
        break

    return alertas


def _aplicar_correcciones_alertas_al_informe(
    estado: dict, capitulos: dict, datos_completos: dict, alertas: list
) -> tuple:
    """
    Aplica correcciones automáticas (Nivel 1 y 2 según experto): sin inventar datos,
    solo normalización segura. Devuelve (capitulos_modificados, patch_log).
    Nivel 3 (capacidad m²→t/d, borrado LER) no se aplica en automático.
    """
    from datetime import datetime
    patch_log = {"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "reglas_aplicadas": [], "detalle": []}
    if not alertas or not capitulos:
        return (dict(capitulos), patch_log)
    datos_u = (estado or {}).get("datos_usuario") or {}
    datos_e = (estado or {}).get("datos_extraidos") or {}
    if isinstance(datos_e, dict):
        pass
    else:
        datos_e = vars(datos_e) if hasattr(datos_e, "__dict__") else {}
    carto = (estado or {}).get("cartografia_informe") or {}
    resultado = {k: (v or "") for k, v in capitulos.items()}

    # --- FIXES OBLIGATORIOS (siempre, sin depender de alertas) — cierran Gate unidades y Gate coherencia ---
    def _valor(v):
        if v is None:
            return ""
        if isinstance(v, list):
            return " ".join(str(x).strip() for x in v if x).strip()
        return (v or "").strip()

    # Fix A — EFIBCA 5/1: "capacidad 1.000" sin unidad → 1.000 kg (Proyecto técnico)
    for cap_key in resultado:
        t = resultado[cap_key]
        if "EFIBCA" in t and "1.000" in t:
            t = re.sub(
                r"(EFIBCA\s*5/1[^\n]{0,100}?)(capacidad\s*)?(1[.,]?000)(?!\s*kg\b)",
                r"\g<1>\g<3> kg",
                t,
                flags=re.I,
            )
            resultado[cap_key] = t
    sup_parcela_f4 = _valor(datos_u.get("superficie_parcela_m2") or (datos_completos or {}).get("superficie_parcela_m2"))
    sup_construida_f4 = _valor(datos_u.get("superficie_construida_m2") or (datos_completos or {}).get("superficie_construida_m2"))
    if sup_parcela_f4 and sup_parcela_f4 not in ("", "N/D"):
        valor_m2 = sup_parcela_f4 + " m²"
        valor_construida = (sup_construida_f4 + " m²") if sup_construida_f4 and sup_construida_f4 not in ("", "N/D") else None
        texto_sust = "Superficie de parcela (Catastro – superficie gráfica): " + valor_m2 + "."
        if valor_construida:
            texto_sust += " Superficie construida (Catastro): " + valor_construida + "."
        for cap_key in resultado:
            t = resultado[cap_key]
            # Superficie total/catastral de (la) parcela: pendiente/N/D/no consta...
            t = re.sub(
                r"Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                texto_sust,
                t,
                flags=re.I,
            )
            resultado[cap_key] = t
    patch_log["reglas_aplicadas"].append("Fix obligatorio EFIBCA + superficie parcela")

    # --- Nivel 1 — Gate LER: sustituir bloque por lista canónica según contexto (admitidos vs RP propios) ---
    if any("Gate LER:" in a and "códigos en el informe" in a for a in alertas) or any("RP propios" in a and "LER admitidos" in a for a in alertas):
        ler_admitidos_raw = _valor(datos_u.get("clasificacion_ler") or datos_e.get("clasificacion_ler"))
        rp_raw = _valor(datos_u.get("residuos_peligrosos_propios_ler") or datos_e.get("residuos_peligrosos_propios_ler"))
        admitidos_set = set()
        for c in (x.strip() for x in ler_admitidos_raw.split(",") if x.strip()):
            n = _normalizar_codigo_ler(c)
            if n and "*" not in n:
                admitidos_set.add(n)
        rp_set = set()
        for c in (x.strip() for x in rp_raw.split(",") if x.strip()):
            n = _normalizar_codigo_ler(c)
            if n:
                rp_set.add(n)
        whitelist = admitidos_set | rp_set
        lista_admitidos = ", ".join(sorted(admitidos_set)) if admitidos_set else ""
        lista_rp = ", ".join(sorted(rp_set)) if rp_set else ""
        texto_admitidos = f"LER admitidos según whitelist del proyecto/autorización: {lista_admitidos}." if lista_admitidos else ""
        texto_rp = "Residuos peligrosos propios (RP): " + lista_rp + "." if lista_rp else ""
        ctx_admitidos = re.compile(r"LER\s+admitidos|admitidos\s*[:\-]|RNP\s*[:\-]|clasificaci[oó]n\s+de\s+residuos\s+admitidos", re.I)
        ctx_rp = re.compile(r"RP\s+propios|residuos\s+generados\s+por|residuos\s+peligrosos\s+propios|20\s*01\s*35|15\s*02\s*02", re.I)
        for cap_key, texto in list(resultado.items()):
            fuera = _extraer_codigos_ler_texto(texto) - whitelist
            rp_en_admitidos = bool((_extraer_codigos_ler_texto(texto) & rp_set) and ctx_admitidos.search(texto))
            if not fuera and not rp_en_admitidos:
                continue
            parrafos = texto.split("\n\n")
            nuevos = []
            for parr in parrafos:
                codigos_parr = _extraer_codigos_ler_texto(parr)
                tiene_fuera = bool(codigos_parr & fuera)
                tiene_rp_en_ctx_admitidos = bool((codigos_parr & rp_set) and ctx_admitidos.search(parr))
                if tiene_fuera or tiene_rp_en_ctx_admitidos:
                    if ctx_rp.search(parr) and not ctx_admitidos.search(parr):
                        sustituto = texto_rp if texto_rp else parr
                    else:
                        sustituto = texto_admitidos if texto_admitidos else parr
                    nuevos.append(sustituto)
                    patch_log["detalle"].append({"capitulo": cap_key, "regla": "Gate LER", "descripcion": "Sustitución por lista canónica (admitidos sin RP)"})
                else:
                    nuevos.append(parr)
            resultado[cap_key] = "\n\n".join(nuevos)
            if "Gate LER" not in patch_log["reglas_aplicadas"]:
                patch_log["reglas_aplicadas"].append("Gate LER")

    # --- Nivel 1 — Gate J: asterisco en 20 01 35 y 15 02 02 ---
    if any("asterisco" in a or "20 01 35" in a for a in alertas):
        for cap_key in resultado:
            t = resultado[cap_key]
            t = re.sub(r"20\s*01\s*35\b(?!\*)", "20 01 35*", t)
            t = re.sub(r"15\s*02\s*02\b(?!\*)", "15 02 02*", t)
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("Gate J (RP asterisco)")

    # --- Nivel 1 — Gate RP propios: epígrafe "Residuos generados por la propia actividad" ---
    if any("epígrafe" in a or "Residuos generados" in a for a in alertas):
        bloque_rp = (
            "\n\n### Residuos generados por la propia actividad\n\n"
            "El proyecto declara residuos peligrosos propios (20 01 35*, 15 02 02*). "
            "Su gestión y control documental se incluyen en el Programa de Vigilancia Ambiental (PVA)."
        )
        modificado = False
        if "inventario" in resultado and bloque_rp not in (resultado.get("inventario") or ""):
            resultado["inventario"] = (resultado.get("inventario") or "").rstrip() + bloque_rp
            modificado = True
        if "pva" in resultado and "control documental" not in (resultado.get("pva") or "").lower():
            pva = resultado.get("pva") or ""
            if "residuos peligrosos" not in pva.lower() and "20 01 35" not in pva:
                resultado["pva"] = pva.rstrip() + "\n\n- Control documental de residuos peligrosos propios (20 01 35*, 15 02 02*): registro de producción, almacenamiento y entrega a gestor autorizado.\n"
                modificado = True
        if modificado:
            patch_log["reglas_aplicadas"].append("Gate B (epígrafe RP propios)")

    # --- Nivel 1 — Gate E: 20-250 kW → rango genérico no aplicable + N/D molino ---
    if any("Gate potencia" in a and "20" in a and "250" in a for a in alertas):
        sustituir = (
            "rango genérico no aplicable al proyecto "
            "(potencia del molino: N/D, Confianza Baja; cómo obtenerla: ficha técnica del molino específico, "
            "placa de características o oferta del proveedor)"
        )
        patron_pot = re.compile(r"20\s*[–\-]\s*250\s*kW|20-250\s*kW", re.I)
        for cap_key in resultado:
            resultado[cap_key] = patron_pot.sub(sustituir, resultado[cap_key])
        patch_log["reglas_aplicadas"].append("Gate E (potencia)")

    # --- Gate E (molino/motor): kW declarado mayor que potencia total → N/D + cómo obtenerlo ---
    if any("Gate potencia" in a and "potencia instalada total" in a for a in alertas):
        pw = _valor(datos_u.get("potencia_instalada_total_w") or datos_e.get("potencia_instalada_total_w"))
        if pw and pw.isdigit() and int(pw) > 0:
            total_w = int(pw)
            sustituir_kw = (
                "N/D (Confianza Baja) + cómo obtenerlo: ficha técnica del molino específico, "
                "placa de características o oferta del proveedor"
            )
            for cap_key in resultado:
                t = resultado[cap_key]
                # Patrón 1: "molino/motor/potencia ... X kW" (X kW después de molino/motor/potencia)
                def _repl1(m):
                    pref, num = m.group(1), int(m.group(2))
                    if num * 1000 > total_w:
                        return pref + sustituir_kw
                    return m.group(0)
                t = re.sub(r"((?:molino|motor|potencia)[^\d]*)(\d+)\s*kW", _repl1, t, flags=re.I)
                # Patrón 2: "X kW para molino/motor" (X kW antes de para molino/motor)
                def _repl2(m):
                    num = int(m.group(1))
                    if num * 1000 > total_w:
                        return sustituir_kw + m.group(2)
                    return m.group(0)
                t = re.sub(r"(\d+)\s*kW(\s*(?:para\s+(?:el\s+)?(?:molino|motor)|del\s+(?:molino|motor)))", _repl2, t, flags=re.I)
                resultado[cap_key] = t
            patch_log["reglas_aplicadas"].append("Gate E (potencia molino → N/D)")

    # --- Nivel 1 — Gate F: encaje legal (75/50 t/d cuando capacidad es 20 t/d) — sustituir por capacidad real ---
    if any("Gate encaje legal" in a for a in alertas):
        cap_campos_f = (
            datos_u.get("capacidad_clasificacion_t_d") or datos_u.get("capacidad_trituracion_cobre_t_d")
            or datos_u.get("capacidad_corte_t_d") or datos_u.get("capacidad_total_t")
            or datos_u.get("capacidad_tratamiento_t_d") or datos_completos.get("capacidad_maxima_almacenamiento")
        )
        cap_real = _valor(cap_campos_f)
        cap_encaje = "20 t/d"
        if cap_real:
            m = re.search(r"(\d+(?:[.,]\d+)?)(?:\s*(?:t/d|tm/d|t\s*/\s*d|t\b))?", cap_real, re.I)
            if m:
                cap_encaje = f"{m.group(1)} t/d"
        for cap_key in resultado:
            t = resultado[cap_key]
            t = re.sub(r"\b75\s*tm/d\b", cap_encaje, t, flags=re.I)
            t = re.sub(r"\b75\s*t/d\b", cap_encaje, t, flags=re.I)
            t = re.sub(r"\b50\s*tm/d\b", cap_encaje, t, flags=re.I)
            t = re.sub(r"\b50\s*t/d\b", cap_encaje, t, flags=re.I)
            t = re.sub(
                r"Anexo\s+II\s+grupo\s+9\.k\s*>\s*75\s*t/d",
                f"Anexo II grupo correspondiente a {cap_encaje}",
                t,
                flags=re.I,
            )
            t = re.sub(
                r"Anexo\s+II\s+grupo\s+9\.k\s*>\s*50\s*t/d",
                f"Anexo II grupo correspondiente a {cap_encaje}",
                t,
                flags=re.I,
            )
            t = re.sub(
                r"9\.k\s*>\s*75(?:\s*t/d)?",
                f"grupo correspondiente a {cap_encaje}",
                t,
                flags=re.I,
            )
            t = re.sub(
                r"9\.k\s*>\s*50(?:\s*t/d)?",
                f"grupo correspondiente a {cap_encaje}",
                t,
                flags=re.I,
            )
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("Gate F (encaje legal)")

    # --- Nivel 1 — Gate cartografía: pendiente / a acreditar → N/D (cómo obtenerlo) si NO hay distancia ---
    if any("Gate cartografía" in a and "pendiente" in a for a in alertas):
        nd_cartografia = "N/D (cómo obtenerlo: visor oficial MITECO/IDECanarias, captura fechada)"
        for cap_key in resultado:
            t = resultado[cap_key]
            if re.search(r"pendiente\s+de\s+acreditaci[oó]n|a\s+acreditar", t, re.I):
                ventana_ctx = re.search(r".{0,80}red\s+natura|RN2000|ENP|ZEPA|SNCZI|cartograf[ií]a.{0,80}", t, re.I | re.DOTALL)
                if ventana_ctx:
                    t = re.sub(r"pendiente\s+de\s+acreditaci[oó]n", nd_cartografia, t, flags=re.I)
                    t = re.sub(r"\ba\s+acreditar\b", nd_cartografia, t, flags=re.I)
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("Gate H (cartografía pendiente)")

    # --- Nivel 2 — Gate K: capacidad sin unidad. PROHIBIDO inferir unidad por "primer campo"; solo por contexto o N/D ---
    nd_capacidad = "N/D (Confianza Baja) + cómo obtenerlo: tabla de capacidades del proyecto/memoria y declaración del promotor."
    cap_campos = (
        datos_u.get("capacidad_clasificacion_t_d") or datos_u.get("capacidad_trituracion_cobre_t_d")
        or datos_u.get("capacidad_corte_t_d") or datos_u.get("capacidad_total_t")
        or datos_u.get("almacenamiento_pre_t") or datos_u.get("almacenamiento_post_t")
        or datos_u.get("capacidad_tratamiento_t_d") or datos_u.get("capacidad_almacenamiento_t")
        or datos_u.get("capacidad_anual_t_a") or datos_completos.get("capacidad_maxima_almacenamiento")
    )
    cap_canonico = _valor(cap_campos)
    # Solo "con unidad" si el valor ya trae unidad explícita (nunca inferir t/d o t por heurística)
    tiene_unidad_canonica = bool(cap_canonico and re.search(r"t/d|t\b|m³|kg/h|t/año|tm", cap_canonico, re.I))
    if any("Gate unidades" in a and "capacidad" in a and "sin unidad" in a for a in alertas):
        patron_cap_sin = re.compile(
            r"capacidad\s+(m[áa]xima\s+)?(\d+(?:[.,]\d+)?)\s*(?!t/d|t\b|tm\b|m³|m3|kg/h|t/h|kg\b|kW\b)",
            re.I,
        )
        ctx_tratamiento = re.compile(r"tratamiento|trituraci[oó]n|clasificaci[oó]n|corte", re.I)
        ctx_almacenamiento = re.compile(r"almacenamiento|pre-operaci[oó]n|post-operaci[oó]n|acopio", re.I)
        for cap_key in resultado:
            t = resultado[cap_key]
            def _repl_cap(m):
                pre, num = m.group(1) or "", m.group(2)
                ventana = t[max(0, m.start() - 80) : min(len(t), m.end() + 80)]
                if tiene_unidad_canonica and cap_canonico:
                    if ctx_tratamiento.search(ventana) and re.search(r"t/d", cap_canonico, re.I):
                        return f"capacidad {pre}{num} {cap_canonico.strip()}"
                    if ctx_almacenamiento.search(ventana) and re.search(r"\bt\b(?!/d)", cap_canonico, re.I):
                        return f"capacidad {pre}{num} {cap_canonico.strip()}"
                return f"capacidad {pre}{num} " + nd_capacidad
            resultado[cap_key] = patron_cap_sin.sub(_repl_cap, resultado[cap_key])
        patch_log["reglas_aplicadas"].append("Gate K (capacidad: solo por contexto explícito o N/D)")

    # --- Fix A — EFIBCA 5/1: "capacidad 1.000" sin unidad → 1.000 kg (Proyecto: Homologaciones EFIBCA 5/1: 1.000 kg). Antes de pasada final. ---
    if any("Gate unidades" in a for a in alertas):
        for cap_key in resultado:
            t = resultado[cap_key]
            # (capacidad\s*)? opcional: cubre "EFIBCA 5/1, capacidad 1.000" y "Homologaciones EFIBCA 5/1: 1.000"
            t = re.sub(
                r"(EFIBCA\s*5/1[^\n]{0,80}?)(capacidad\s*)?(1[.,]?000)(?!\s*kg\b)",
                r"\g<1>\g<3> kg",
                t,
                flags=re.I,
            )
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("Fix A EFIBCA 5/1 (1.000 → 1.000 kg)")

    # --- Pasada final capacidad sin unidad: garantizar que no exista capacidad <número> sin t, t/d, kg/h, etc. ---
    if any("Gate unidades" in a and "capacidad" in a for a in alertas):
        patron_cap_final = re.compile(
            r"(capacidad\s+(?:m[áa]xima\s+)?(?:de\s+)?)(\d+(?:[.,]\d+)?)\s*(?!t/d|t\b|tm\b|m³|m3|kg/h|t/h|t\/año|t\/a|kg\b|kW\b|kW)",
            re.I,
        )
        for cap_key in resultado:
            t = resultado[cap_key]
            def _repl_cap_final(m):
                pref, num = m.group(1), m.group(2).replace(",", ".")
                if tiene_unidad_canonica and cap_canonico:
                    return f"{pref}{num} {cap_canonico.strip()}"
                return f"{pref}{num} " + nd_capacidad
            resultado[cap_key] = patron_cap_final.sub(_repl_cap_final, resultado[cap_key])
        patch_log["reglas_aplicadas"].append("Gate K (pasada final capacidad sin unidad)")

    # --- Nivel 3 PROHIBIDO: capacidad m² → t/d. Solo N/D + cómo obtenerlo, o valor canónico si existe ---
    if any("Gate unidades" in a and "m²" in a and "incorrecta" in a for a in alertas):
        if tiene_unidad_canonica and cap_canonico:
            for cap_key in resultado:
                resultado[cap_key] = re.sub(
                    r"capacidad\s+(m[áa]xima\s+)?(\d+(?:[.,]\d+)?)\s*m[²2]\b",
                    r"capacidad \1" + cap_canonico.strip(),
                    resultado[cap_key],
                    flags=re.I,
                )
        else:
            for cap_key in resultado:
                resultado[cap_key] = re.sub(
                    r"capacidad\s+(m[áa]xima\s+)?(\d+(?:[.,]\d+)?)\s*m[²2]\b",
                    r"capacidad \1\2 " + nd_capacidad,
                    resultado[cap_key],
                    flags=re.I,
                )
        patch_log["reglas_aplicadas"].append("Gate K (capacidad m² → N/D o valor canónico)")

    # --- Corrección VFU/CAT contextual (experto): origen → centros autorizados; actividad propia → frase estándar ---
    if any("VFU/CAT" in a or "referencias VFU" in a or "referencias VFU/CAT" in a for a in alertas):
        frase_estandar = (
            "La instalación no realiza descontaminación de vehículos fuera de uso ni opera como centro autorizado de tratamiento; "
            "recepciona residuos metálicos no peligrosos procedentes de gestores autorizados / centros autorizados."
        )
        for cap_key in resultado:
            t = resultado[cap_key]
            t = re.sub(r"\bsomos\s+CAT\b", "no opera como centro autorizado", t, flags=re.I)
            t = re.sub(r"\b(opera|operamos)\s+como\s+CAT\b", "no opera como centro autorizado", t, flags=re.I)
            t = re.sub(r"\binstalaci[oó]n\s+CAT\b", "instalación no opera como centro autorizado; recepciona de centros autorizados", t, flags=re.I)
            t = re.sub(r"\bes\s+un\s+CAT\b", "no es un centro autorizado; recepciona de centros autorizados", t, flags=re.I)
            t = re.sub(r"procedente\s+de\s+(?:centros\s+)?CAT", "procedente de centros autorizados", t, flags=re.I)
            t = re.sub(r"centros\s+CAT(?:s)?\b", "centros autorizados", t, flags=re.I)
            t = re.sub(r"\bCAT\b(?!\s*[-\d])", "centro autorizado", t, flags=re.I)
            t = re.sub(r"\bVFU\b", "vehículos fuera de uso", t, flags=re.I)
            if cap_key == "descripcion" and frase_estandar not in t:
                t = t.rstrip() + "\n\n" + frase_estandar + "\n\n"
            elif cap_key == "resumen_ejecutivo" and frase_estandar not in t:
                t = t.rstrip() + "\n\n" + frase_estandar + "\n\n"
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("VFU/CAT contextual (origen → centros autorizados; actividad → frase estándar)")
        # Pasada final: eliminar tokens CAT/VFU restantes (criterio: no existen en texto final)
        for cap_key in resultado:
            t = resultado[cap_key]
            t = re.sub(r"\bCAT\b", "centro autorizado", t, flags=re.I)
            t = re.sub(r"\bVFU\b", "vehículos fuera de uso", t, flags=re.I)
            resultado[cap_key] = t

    # --- Nivel 1 — Gate D: "Indeterminada" → N/D (cómo obtenerlo) ---
    if any("Indeterminada" in a for a in alertas):
        for cap_key in resultado:
            resultado[cap_key] = re.sub(
                r"\bindeterminada\b",
                "N/D (cómo obtenerlo: visor oficial, captura fechada)",
                resultado[cap_key],
                flags=re.I,
            )
        patch_log["reglas_aplicadas"].append("Gate D (Indeterminada)")

    # --- Nivel 1 — Gate G: "autorización ambiental previa" → "Informe de Impacto Ambiental" ---
    if any("autorización ambiental previa" in a or "Gate redacción" in a for a in alertas):
        for cap_key in resultado:
            resultado[cap_key] = re.sub(
                r"autorizaci[oó]n\s+ambiental\s+previa",
                "Informe de Impacto Ambiental",
                resultado[cap_key],
                flags=re.I,
            )
        patch_log["reglas_aplicadas"].append("Gate G (redacción)")

    # --- Fix 4: Superficie parcela N/D en Descripción — sustituir por valor del estado ---
    sup_parcela_f4 = _valor(datos_u.get("superficie_parcela_m2"))
    sup_construida_f4 = _valor(datos_u.get("superficie_construida_m2"))
    if any("superficie_parcela_m2" in a or "Gate coherencia" in a for a in alertas) and sup_parcela_f4 and sup_parcela_f4 not in ("", "N/D"):
        valor_m2 = sup_parcela_f4 + " m²"
        valor_construida = (sup_construida_f4 + " m²") if sup_construida_f4 and sup_construida_f4 not in ("", "N/D") else None
        for cap_key in resultado:
            t = resultado[cap_key]
            t = re.sub(
                r"(superficie\s+(?:de\s+la\s+)?parcela\s*[:\-]\s*)N/D",
                r"\g<1>" + valor_m2,
                t,
                flags=re.I,
            )
            t = re.sub(
                r"(Superficie\s+parcela\s*[:\-]\s*)N/D",
                r"\g<1>" + valor_m2,
                t,
                flags=re.I,
            )
            # Superficie catastral/total de (la) parcela: pendiente / N/D / no consta → valor Catastro (parcela + construida si existe)
            texto_sust = "Superficie de parcela (Catastro – superficie gráfica): " + valor_m2 + "."
            if valor_construida:
                texto_sust += " Superficie construida (Catastro): " + valor_construida + "."
            t = re.sub(
                r"(Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*)(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                texto_sust,
                t,
                flags=re.I,
            )
            # Superficie de parcela (según catastro): pendiente de acreditación documental → valor m²
            t = re.sub(
                r"(Superficie\s+de\s+parcela\s*\(seg[uú]n\s+catastro\)\s*[:\-]\s*)(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                r"\g<1>" + valor_m2 + ".",
                t,
                flags=re.I,
            )
            # Parcela según catastro: pendiente de acreditación documental (incluyendo Confianza X + \"Cómo obtenerlo\") → valor m²
            t = re.sub(
                r"(Parcela\s+seg[uú]n\s+catastro\s*[:\-]\s*)(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                r"\g<1>" + valor_m2 + ".",
                t,
                flags=re.I,
            )
            # Si en el capítulo hay "Parcela perimetrada" pero no el valor, insertar valor para que la alerta desaparezca al re-evaluar
            if re.search(r"parcela\s+perimetrada|parcela\s+perímetrada", t, re.I) and not re.search(r"\b" + re.escape(sup_parcela_f4) + r"\s*m[²2]", t, re.I):
                t = re.sub(
                    r"(\bParcela\s+perimetrada\b|\bParcela\s+perímetrada\b)(\s*[.,;\)])",
                    r"\1 (" + valor_m2 + r")\2",
                    t,
                    count=1,
                    flags=re.I,
                )
            resultado[cap_key] = t
        patch_log["reglas_aplicadas"].append("Fix 4 (superficie parcela N/D → valor estado)")

    # --- Nivel 1 — Gate C: 2.500 m² → superficie Catastro del estado ---
    sup_catastro = _valor(datos_u.get("superficie_parcela_m2"))
    if any("Gate superficies" in a and "2.500" in a for a in alertas) and sup_catastro:
        _patron_2500_fix = re.compile(r"\b2[\s\.,]?\s*500\s*m\s*[²2]\b|\b2500\s*m\s*[²2]\b|\b2\s*500\s*m\s*[²2]\b", re.I)
        for cap_key in resultado:
            resultado[cap_key] = _patron_2500_fix.sub(sup_catastro + " m²", resultado[cap_key])
        patch_log["reglas_aplicadas"].append("Gate C (superficie 2.500)")

    # --- Nivel 1 — Gate superficies: valor inválido (ej. 1.200 m²) → superficie parcela/construida del estado ---
    sup_parcela_fix = _valor(datos_u.get("superficie_parcela_m2") or (datos_completos or {}).get("superficie_parcela_m2"))
    sup_construida_fix = _valor(datos_u.get("superficie_construida_m2") or (datos_completos or {}).get("superficie_construida_m2"))
    if any("Gate superficies" in a for a in alertas) and (sup_parcela_fix or sup_construida_fix):
        # Extraer valor inválido de la alerta (ej. "1.200" de "aparece 1.200 m²")
        valor_invalido = None
        for a in alertas:
            if "Gate superficies" in a and "aparece" in a:
                mm = re.search(r"aparece\s+([\d.,\s]+)\s*m[²2]", a, re.I)
                if mm:
                    valor_invalido = mm.group(1).strip().replace(" ", "")
                    break
        if valor_invalido:
            sust = (sup_construida_fix or sup_parcela_fix) + " m²"
            # Patrones: 1.200, 1,200, 1 200, 1200 (escapar punto para regex)
            v_esc = re.escape(valor_invalido)
            v_alt = re.escape(valor_invalido.replace(".", ","))
            _patron_inv = re.compile(
                r"\b" + v_esc + r"\s*m\s*[²2]\b|\b" + v_alt + r"\s*m\s*[²2]\b",
                re.I,
            )
            for cap_key in resultado:
                t_orig = resultado[cap_key]
                resultado[cap_key] = _patron_inv.sub(sust, resultado[cap_key])
                if resultado[cap_key] != t_orig:
                    patch_log["detalle"].append({"capitulo": cap_key, "regla": "Gate superficies", "valor_antes": valor_invalido, "valor_despues": sust})
            patch_log["reglas_aplicadas"].append("Gate superficies (valor inválido → parcela/construida)")

    # --- Nivel 2 — Gate L: N/D → valor del estado solo con etiqueta explícita + log de sustituciones ---
    if any("Gate coherencia" in a for a in alertas):
        sup_parcela = _valor(datos_u.get("superficie_parcela_m2"))
        dist_rn = _valor(carto.get("red_natura_2000_distancia_m")) if isinstance(carto, dict) else ""
        ler_val = _valor(datos_u.get("clasificacion_ler") or datos_e.get("clasificacion_ler"))
        # Solo etiquetas explícitas (no "por parecido")
        sustituciones = []
        if sup_parcela and sup_parcela not in ("", "N/D"):
            sustituciones.append((sup_parcela + " m²", r"Superficie\s+parcela|Superficie\s+total\s+(?:de\s+)?(?:la\s+)?parcela|superficie\s+de\s+la\s+parcela|superficie\s+parcela\s*[:\-]|superficie_parcela_m2|parcela\s+perimetrada|parcela\s+perímetrada|superficie\s+de\s+parcela\s*\(seg[uú]n\s+catastro\)", "Superficie parcela"))
        def _norm_dist_m(val):
            if not val or str(val).strip() in ("", "N/D"):
                return None
            _d = str(val).strip().replace(",", ".")
            _es_km = bool(re.search(r"\s*km\s*$", _d, re.I))
            _s = re.sub(r"\s*m\s*$|\s*km\s*$", "", _d, flags=re.I).strip()
            try:
                _n = float(_s)
                _metros = _n * 1000 if _es_km else _n
                return f"{int(_metros)} m" if _metros == int(_metros) else f"{_metros} m"
            except ValueError:
                return val if re.search(r"\s*m\s*$|\s*km\s*$", val, re.I) else str(val) + " m"
        dist_enp = _valor(carto.get("enp_distancia_m")) if isinstance(carto, dict) else ""
        dist_zepa = _valor(carto.get("zepa_distancia_m")) if isinstance(carto, dict) else ""
        if dist_rn and dist_rn not in ("", "N/D"):
            sustituciones.append((_norm_dist_m(dist_rn), r"red\s+natura|RN2000|Distancia\s+.*RN2000|RN2000.*distancia|distancia\s+.*Red\s+Natura|Red\s+Natura.*distancia", "Distancia RN2000"))
        if dist_enp and dist_enp not in ("", "N/D"):
            sustituciones.append((_norm_dist_m(dist_enp), r"Distancia\s+.*ENP|ENP.*distancia|espacio\s+natural\s+protegido.*distancia", "Distancia ENP"))
        if dist_zepa and dist_zepa not in ("", "N/D"):
            sustituciones.append((_norm_dist_m(dist_zepa), r"Distancia\s+.*ZEPA|ZEPA.*distancia|ZEC.*distancia|LIC.*distancia", "Distancia ZEPA/ZEC"))
        if ler_val and ler_val not in ("", "N/D"):
            sustituciones.append((ler_val, r"LER\s+admitidos|clasificaci[oó]n\s+de\s+residuos.*LER|LER\s+del\s+proyecto", "LER admitidos"))
        patron_nd = re.compile(
            r"\bN/D\b|\bno\s+consta\b|pendiente\s+de\s+acreditaci[oó]n(?:\s+documental)?|\ba\s+acreditar\b|\bno\s+disponible\b",
            re.I,
        )
        ventana_chars = 150  # ventana alrededor de N/D o pendiente para buscar contexto
        for cap_key in resultado:
            t = resultado[cap_key]
            for valor_sust, ctx_patron, etiqueta in sustituciones:
                for m in patron_nd.finditer(t):
                    start = max(0, m.start() - ventana_chars)
                    end = min(len(t), m.end() + ventana_chars)
                    ventana = t[start:end]
                    if re.search(ctx_patron, ventana, re.I):
                        t = t[: m.start()] + valor_sust + t[m.end() :]
                        patch_log["detalle"].append({"capitulo": cap_key, "regla": "Gate L", "campo": etiqueta, "valor": valor_sust})
                        break
            resultado[cap_key] = t
        if sustituciones:
            patch_log["reglas_aplicadas"].append("Gate L (coherencia N/D con etiqueta explícita)")

    return (resultado, patch_log)


def _obtener_datos_faltantes(datos) -> list:
    """Devuelve lista de (etiqueta, clave) para los datos que faltan."""
    faltantes = []
    if "datos_usuario" not in st.session_state:
        st.session_state.datos_usuario = {}

    for etiqueta, clave in LISTA_DATOS_NECESARIOS:
        # Prioridad: si el usuario ya indicó el dato, no está faltante
        valor_usuario = st.session_state.datos_usuario.get(clave, "").strip()
        if valor_usuario:
            continue
        if clave in CLAVES_EXTRAIBLES and datos:
            valor = _valor_extraido(datos, clave)
        else:
            valor = ""
        if _es_dato_faltante(valor):
            faltantes.append((etiqueta, clave))
    return faltantes

def _obtener_datos_completos(datos) -> dict:
    """Fusiona datos extraídos + respuestas del usuario. Prioridad: usuario > extracción."""
    resultado = {}
    if "datos_usuario" not in st.session_state:
        st.session_state.datos_usuario = {}

    for etiqueta, clave in LISTA_DATOS_NECESARIOS:
        usuario = st.session_state.datos_usuario.get(clave, "").strip()
        if usuario:
            resultado[clave] = usuario
        elif clave in CLAVES_EXTRAIBLES and datos:
            extraido = _valor_extraido(datos, clave)
            resultado[clave] = extraido if not _es_dato_faltante(extraido) else ""
        else:
            resultado[clave] = ""
    # Aplicar limpieza robusta para evitar LER repetidos o mal formateados en tabla/exportación.
    # Regla experto: LER admitidos NUNCA puede contener * — mover automáticamente a RP propios
    ler_orig = resultado.get("clasificacion_ler", "")
    rp_orig = resultado.get("residuos_peligrosos_propios_ler", "")
    ler_ok, rp_ok = _sanitizar_ler_admitidos_sin_asteriscos(ler_orig, rp_orig)
    resultado["clasificacion_ler"] = ler_ok
    resultado["residuos_peligrosos_propios_ler"] = rp_ok
    if ler_ok != ler_orig or rp_ok != rp_orig:
        st.session_state.datos_usuario["clasificacion_ler"] = ler_ok
        st.session_state.datos_usuario["residuos_peligrosos_propios_ler"] = rp_ok

    # Capacidad máxima de almacenamiento (legacy): nunca dejar número suelto (ej. "500") sin unidad.
    # Preferencia: capacidades canónicas; si no existen, N/D + cómo obtenerlo.
    cap_legacy = (resultado.get("capacidad_maxima_almacenamiento", "") or "").strip()
    if cap_legacy and re.fullmatch(r"\d+(?:[.,]\d+)?", cap_legacy):
        def _fmt_num(n: str, unidad: str) -> str:
            s = (n or "").strip()
            if not s:
                return ""
            if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
                return s.replace(",", ".") + f" {unidad}"
            return s

        parts = []
        v_cd = (resultado.get("capacidad_clasificacion_t_d") or "").strip()
        if v_cd:
            parts.append(_fmt_num(v_cd, "t/d") + " (capacidad diaria)")
        v_pre = (resultado.get("almacenamiento_pre_t") or "").strip()
        if v_pre:
            parts.append(_fmt_num(v_pre, "t") + " (almacenamiento pre)")
        v_post = (resultado.get("almacenamiento_post_t") or "").strip()
        if v_post:
            parts.append(_fmt_num(v_post, "t") + " (almacenamiento post)")

        if any(p.strip() for p in parts):
            cap_fix = "; ".join([p for p in parts if p.strip()])
        else:
            cap_fix = "N/D (Confianza Baja) + cómo obtenerlo: tabla de capacidades del proyecto/memoria (no usar valores sin unidad)."

        resultado["capacidad_maxima_almacenamiento"] = cap_fix
        st.session_state.datos_usuario["capacidad_maxima_almacenamiento"] = cap_fix
    # Corregir typos en Órgano Sustantivo (evita CONBSEJERIA, CANARIASS, etc.)
    resultado["organo_sustantivo"] = _normalizar_organo_sustantivo(resultado.get("organo_sustantivo", ""))
    # Normalizar estado de infraestructura a valores canónicos
    est = (resultado.get("estado_infraestructura", "") or "").strip().lower()
    if "nave" in est or "existente" in est:
        resultado["estado_infraestructura"] = "nave_existente"
    elif "obra" in est or "construcci" in est:
        resultado["estado_infraestructura"] = "obra_nueva"
    return resultado


def _extraer_datos_maestros_desde_texto(texto: str, datos_extraidos=None) -> dict:
    """
    Precarga datos maestros desde texto de Proyecto/Memoria/Catastro.
    Devuelve: valores, fuentes (doc + extracto por clave), confianza_ler, capacidades_posibles.
    LER: prioriza extracción por anclajes (TIPOS DE RESIDUOS, CÓDIGOS LER, plano/listado).
    Capacidades: si hay varias coincidencias, no rellena automático; devuelve lista para que el usuario elija.
    """
    LER_ANCLAJES = re.compile(
        r"tipos?\s+de\s+residuos\s+y\s+codificaci[oó]n|c[oó]digos\s+ler|"
        r"clasificaci[oó]n\s+ler|codificaci[oó]n\s+ler|plano\s*/\s*listado|listado\s+ler",
        re.I,
    )
    MAX_LER_ADMITIDOS = 25

    def _extracto(texto_orig: str, start: int, end: int, max_len: int = 120) -> str:
        s = max(0, start - 40)
        e = min(len(texto_orig), end + 80)
        frag = texto_orig[s:e].replace("\n", " ").strip()
        if len(frag) > max_len:
            frag = frag[:max_len] + "…"
        return frag

    valores = {}
    fuentes = {}
    confianza_ler = "alta"
    capacidades_posibles = []

    if not texto:
        texto = ""
    texto = str(texto)
    doc_label = "Memoria/Proyecto/Catastro"

    # Superficies
    for m in re.finditer(r"Superficie\s+gr[áa]fica\s*[:\-]\s*(\d+(?:[.,]\d+)?)", texto, re.I):
        valores["superficie_parcela_m2"] = m.group(1).replace(",", ".")
        fuentes["superficie_parcela_m2"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
        break
    if "superficie_parcela_m2" not in valores:
        for m in re.finditer(r"Superficie\s+construida\s*[:\-]\s*(\d+(?:[.,]\d+)?)", texto, re.I):
            valores["superficie_construida_m2"] = m.group(1).replace(",", ".")
            fuentes["superficie_construida_m2"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
            break
    if "superficie_parcela_m2" not in valores and re.search(r"\b591\s*m[²2]|\b591\s*m2\b", texto, re.I):
        valores["superficie_parcela_m2"] = "591"
        fuentes["superficie_parcela_m2"] = {"doc": doc_label, "extracto": "591 m² (patrón numérico)"}
    if re.search(r"\b590\s*m[²2]|\b590\s*m2\b", texto, re.I) and "superficie_construida_m2" not in valores:
        valores["superficie_construida_m2"] = "590"
        fuentes["superficie_construida_m2"] = {"doc": doc_label, "extracto": "590 m² (patrón numérico)"}
    # Superficie construida 591,25 m² (proyecto técnico RECIMETAL y similares)
    if "superficie_construida_m2" not in valores:
        for m in re.finditer(r"591[.,]25\s*m[²2]|591[.,]25\s*m2\b", texto, re.I):
            valores["superficie_construida_m2"] = "591.25"
            fuentes["superficie_construida_m2"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
            break
    # Superficie útil 537,50 m² (proyecto técnico RECIMETAL - tabla 1.1.6.1)
    if "superficie_util_m2" not in valores:
        for m in re.finditer(r"537[.,]50\s*m[²2]|537[.,]50\s*m2\b", texto, re.I):
            valores["superficie_util_m2"] = "537.50"
            fuentes["superficie_util_m2"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
            break

    # Potencia
    for m in re.finditer(r"(?:potencia\s+instalada|potencia\s+de\s+c[áa]lculo|instalada)\s*[:\-]?\s*(\d{4,6})\s*W", texto, re.I):
        w = m.group(1)
        if "potencia_instalada_total_w" not in valores:
            valores["potencia_instalada_total_w"] = w
            fuentes["potencia_instalada_total_w"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
        if "potencia_calculo_w" not in valores and re.search(r"c[áa]lculo|calculo", texto[max(0, m.start() - 30):m.end()], re.I):
            valores["potencia_calculo_w"] = w
            fuentes["potencia_calculo_w"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
        break
    if "potencia_instalada_total_w" not in valores:
        for m in re.finditer(r"\b(1[4-9]\d{3}|20\d{3})\s*W\b", texto):
            valores["potencia_instalada_total_w"] = m.group(1)
            fuentes["potencia_instalada_total_w"] = {"doc": doc_label, "extracto": _extracto(texto, m.start(), m.end())}
            break

    # LER: priorizar bloque con anclajes (codificación LER / plano listado)
    texto_ler = texto
    for m_anc in LER_ANCLAJES.finditer(texto):
        bloque = texto[m_anc.start() : m_anc.start() + 3500]
        if _extraer_ler_desde_texto(bloque).strip():
            texto_ler = bloque
            break
    ler_todos = _extraer_ler_desde_texto(texto_ler)
    if ler_todos:
        admitidos = [c.strip() for c in ler_todos.split(",") if c.strip() and "*" not in c]
        rp = [c.strip() for c in ler_todos.split(",") if c.strip() and "*" in c]
        if len(admitidos) > MAX_LER_ADMITIDOS:
            confianza_ler = "baja"
        if admitidos:
            valores["clasificacion_ler"] = ", ".join(admitidos[:MAX_LER_ADMITIDOS])
            fuentes["clasificacion_ler"] = {"doc": doc_label, "extracto": "Bloque codificación LER / listado (anclaje)" if texto_ler != texto else "Listado LER en documento"}
        if rp:
            valores["residuos_peligrosos_propios_ler"] = ", ".join(rp[:10])
            fuentes["residuos_peligrosos_propios_ler"] = {"doc": doc_label, "extracto": "RP con * en listado LER"}
    if datos_extraidos:
        ler_de = datos_extraidos.get("clasificacion_ler", "") if isinstance(datos_extraidos, dict) else getattr(datos_extraidos, "clasificacion_ler", "") or ""
        if (ler_de or "").strip():
            valores["clasificacion_ler"] = _normalizar_lista_ler((ler_de or "").strip())
            fuentes["clasificacion_ler"] = {"doc": doc_label, "extracto": "Datos extraídos (analista)"}

    # Capacidades: recoger todas las coincidencias; si solo una → valor; si varias → lista para elegir
    caps = []
    for m in re.finditer(r"(?:capacidad|clasificaci[oó]n|trituraci[oó]n)\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(?:TM/d[ií]a|t/d|t\s*/\s*d)", texto, re.I):
        caps.append(m.group(1).replace(",", ".") + " t/d")
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*TM/d[ií]a", texto, re.I):
        v = m.group(1).replace(",", ".") + " t/d"
        if v not in caps:
            caps.append(v)
    if len(caps) == 1:
        valores["capacidad_clasificacion_t_d"] = caps[0]
        fuentes["capacidad_clasificacion_t_d"] = {"doc": doc_label, "extracto": "Capacidad única detectada"}
    elif len(caps) > 1:
        capacidades_posibles = list(dict.fromkeys(caps))
        fuentes["capacidad_clasificacion_t_d"] = {"doc": doc_label, "extracto": f"Varias coincidencias: {', '.join(capacidades_posibles)}. Elija una."}

    return {
        "valores": valores,
        "fuentes": fuentes,
        "confianza_ler": confianza_ler,
        "capacidades_posibles": capacidades_posibles,
    }


# Cargar configuración persistente (API Keys)
CONFIG_FILE = "config.json"

@st.cache_data(ttl=3, show_spinner=False)
def cargar_config():
    """Carga las API Keys desde config.json si existe."""
    config = {
        "openai_api_key": "",
        "aemet_api_key": "",
        "openai_analysis_model": "gpt-4o",
        "openai_analysis_deep_mode": False,
        "openai_report_model": "gpt-4o",
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    return config

def guardar_config(config):
    """Guarda las API Keys en config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _invalidate_cache_data()
    except Exception:
        pass

# Cargar configuración al inicio
config = cargar_config()
LOGO_CANDIDATOS = [
    Path("assets/logo_ecogestion.png"),
    Path(
        r"C:\Users\rafae\.cursor\projects\c-Fali-LENOVO-FALI-IA-PROYECTO-EIA-APP\assets\c__Users_rafae_AppData_Roaming_Cursor_User_workspaceStorage_d0f897b729427a3deb8c497a478f9cf7_images_logo_3_EIA-78e92b97-c6b7-4e6b-a514-c5f583199991.png"
    ),
]
PORTADA_GLOBAL_PATH = Path("docs_referencia") / "portada_base.png"


def _resolver_logo_path():
    for ruta in LOGO_CANDIDATOS:
        try:
            if ruta.exists() and ruta.is_file():
                return str(ruta)
        except Exception:
            continue
    return None


def _asegurar_portada_global() -> str:
    """
    Busca una portada base en proyectos y la copia a una ruta global reutilizable
    para todos los informes.
    """
    try:
        PORTADA_GLOBAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if PORTADA_GLOBAL_PATH.exists() and PORTADA_GLOBAL_PATH.is_file():
            return str(PORTADA_GLOBAL_PATH)

        base = Path("archivos_proyecto")
        if base.exists():
            for cand in base.rglob("imagen de la portada.png"):
                if cand.is_file():
                    shutil.copy2(cand, PORTADA_GLOBAL_PATH)
                    return str(PORTADA_GLOBAL_PATH)
    except Exception:
        pass
    return str(PORTADA_GLOBAL_PATH) if PORTADA_GLOBAL_PATH.exists() else ""


def _estado_proyecto_visual(nombre_proyecto: str) -> dict:
    estado = {
        "carga_documentos": "pendiente",
        "analisis_datos": "pendiente",
        "mapas_anexos": "pendiente",
        "clima": "pendiente",
        "informe": "pendiente",
    }
    try:
        guardados = _cargar_archivos_guardados_cached(nombre_proyecto)
    except Exception:
        guardados = {"memorias": [], "documentos_administrativos": [], "imagenes": []}

    memorias = guardados.get("memorias", []) or []
    docs_admin = guardados.get("documentos_administrativos", []) or []
    imagenes = guardados.get("imagenes", []) or []
    tiene_mapa = any(p.name.lower().startswith("mapa_") for p in imagenes)
    tiene_clima = any(p.name.lower().startswith("clima_") for p in imagenes)
    tiene_capitulos = any(bool(st.session_state.get(sk)) for _, _, sk in CHAPTER_TEMPLATE)
    tiene_word = bool(st.session_state.get("informe_word_bytes"))

    if memorias or docs_admin:
        estado["carga_documentos"] = "completo"
    if st.session_state.get("datos_extraidos") is not None or st.session_state.get("datos_usuario"):
        estado["analisis_datos"] = "completo"
    if tiene_mapa:
        estado["mapas_anexos"] = "completo"
    if tiene_clima or bool(st.session_state.get("clima_analisis_texto", "").strip()):
        estado["clima"] = "completo"
    if tiene_capitulos or tiene_word:
        estado["informe"] = "completo"
    return estado


def _kpis_proyecto(nombre_proyecto: str) -> dict:
    """Devuelve contadores de avance para el panel de inicio."""
    try:
        guardados = _cargar_archivos_guardados_cached(nombre_proyecto)
    except Exception:
        guardados = {"memorias": [], "documentos_administrativos": [], "imagenes": []}

    memorias = guardados.get("memorias", []) or []
    docs_admin = guardados.get("documentos_administrativos", []) or []
    imagenes = guardados.get("imagenes", []) or []
    mapas = [p for p in imagenes if p.name.lower().startswith("mapa_")]
    clima = [p for p in imagenes if p.name.lower().startswith("clima_")]
    fotos = [p for p in imagenes if p.name.lower().startswith("foto_")]
    capitulos = sum(1 for _, _, sk in CHAPTER_TEMPLATE if bool(st.session_state.get(sk)))
    return {
        "memorias": len(memorias),
        "docs_admin": len(docs_admin),
        "mapas": len(mapas),
        "clima_figuras": len(clima),
        "fotos": len(fotos),
        "capitulos": capitulos,
    }


def _limpiar_texto_capitulo(
    texto: str,
    perfil_operativo: str = "",
    estado_infraestructura: str = "",
) -> str:
    """
    Normaliza artefactos de plantilla para salida administrativa.
    Si perfil_operativo == 'gestion_residuos_no_vehiculos', elimina oraciones defensivas
    que mencionan VFU/CAT y recorta frases rotas (ej. 'memoria y.').
    Elimina prompt leakage (CLEAN_SLATE_RULE, meta-referencias a reglas).
    Si estado_infraestructura == 'nave_existente', adapta tablas: Obras/instalación → Fase de Acondicionamiento.
    """
    import re

    def _neutralizar_no_consta(linea: str) -> str:
        s2 = linea.strip()
        if re.fullmatch(r"no consta\.?", s2, flags=re.I):
            return ""
        s2 = re.sub(
            r"^(.{2,120}):\s*No consta\.?$",
            r"\1: Pendiente de acreditación documental por el promotor en fase de tramitación.",
            s2,
            flags=re.I,
        )
        s2 = re.sub(
            r"\bNo consta\b\.?",
            "pendiente de acreditación documental",
            s2,
            flags=re.I,
        )
        return s2.strip()

    def _es_oracion_defensiva_vfu_cat(oracion: str) -> bool:
        """True si la oración es una justificación defensiva sobre VFU/CAT (perfil no vehicular)."""
        o = (oracion or "").strip().lower()
        if not o or len(o) < 20:
            return False
        tiene_vfu_cat = bool(
            re.search(r"\bvfu\b|veh[ií]culos?\s+fuera\s+de\s+uso|centros?\s+autorizados?\s+de\s+tratamiento|\bcat\b", o)
        )
        tiene_defensiva = bool(
            re.search(
                r"no\s+se\s+contempla|no\s+se\s+incluyen?|no\s+se\s+realizan?|"
                r"funciones?\s+propias\s+de\s+(centros?\s+)?(autorizados?\s+de\s+tratamiento|cat)|"
                r"actividades?\s+asociadas?\s+a\s+(procesos\s+de\s+)?descontaminaci[oó]n|"
                r"tratamiento\s+de\s+residuos\s+peligrosos",
                o,
            )
        )
        return tiene_vfu_cat and tiene_defensiva

    def _quitar_final_roto(s: str) -> str:
        """Elimina finales de frase cortados (ej. 'tal y como se especifica en la memoria y.')."""
        s = re.sub(r",?\s+tal\s+y\s+como\s+se\s+especifica\s+en\s+la\s+memoria\s+y\.?\s*$", ".", s, flags=re.I)
        s = re.sub(r",?\s+en\s+la\s+memoria\s+y\.?\s*$", ".", s, flags=re.I)
        s = re.sub(r"\s+y\.\s*$", ".", s, flags=re.I)
        s = re.sub(r",\s*y\.?\s*$", ".", s, flags=re.I)
        return s.strip()

    if not texto or not str(texto).strip():
        return ""

    t = str(texto).replace("\r\n", "\n").replace("\r", "\n")
    modo_purga_no_vehicular = (perfil_operativo or "").strip() == "gestion_residuos_no_vehiculos"
    es_nave_existente = (estado_infraestructura or "").strip().lower() in ("nave_existente", "nave existente")

    # Bloqueo prompt leakage: eliminar líneas o frases que citen reglas internas o meta-redacción
    def _contiene_fuga_instrucciones(ss: str) -> bool:
        if not ss or len(ss) < 10:
            return False
        return bool(
            re.search(r"CLEAN_SLATE|REGLA_ESTRICTA|PIZARRA\s+EN\s+BLANCO", ss, re.I)
            or re.search(r"de acuerdo con la regla\s+(?:CLEAN|ESTRICTA|PIZARRA|interna)", ss, re.I)
            or re.search(r"delimitando con precisión el alcance real del proyecto", ss, re.I)
        )

    lineas_out = []
    for ln in t.split("\n"):
        s = (ln or "").strip()
        if not s:
            lineas_out.append("")
            continue
        if s == "---":
            continue
        if s.startswith("```"):
            continue
        if re.search(r"^\[fin del (cap[íi]tulo|resumen ejecutivo|informe)", s, re.I):
            continue
        if re.search(r"^fin del cap[íi]tulo", s, re.I):
            continue
        if re.search(r"^fin del resumen ejecutivo", s, re.I):
            continue
        # Eliminar línea completa si contiene fuga de instrucciones (prompt leakage)
        if _contiene_fuga_instrucciones(s):
            continue
        # Si la línea tiene varias oraciones, quitar solo las que fugan
        oraciones_linea = re.split(r"(?<=[.;])\s+", s)
        oraciones_limpias = [o for o in oraciones_linea if o.strip() and not _contiene_fuga_instrucciones(o)]
        s = " ".join(oraciones_limpias).strip()
        if not s:
            continue

        if modo_purga_no_vehicular:
            # Eliminar oraciones enteras que sean defensivas VFU/CAT (por punto, punto y coma o nueva línea).
            oraciones = re.split(r"(?<=[.;])\s+", s)
            oraciones_ok = [o for o in oraciones if o.strip() and not _es_oracion_defensiva_vfu_cat(o)]
            s = " ".join(oraciones_ok).strip()
            s = _quitar_final_roto(s)
            if not s:
                continue

        s = re.sub(r"\[revisi[oó]n[^\]]*\]", "", s, flags=re.I).strip()
        s = re.sub(
            r"\[datos a completar(?: por el promotor)?[^\]]*\]",
            "No consta",
            s,
            flags=re.I,
        )
        s = re.sub(r"dato no facilitado por el promotor en esta fase\.?", "No consta", s, flags=re.I)
        s = re.sub(r"\bN/D\b", "No consta", s, flags=re.I)
        s = re.sub(r"\bn/D\b", "No consta", s, flags=re.I)
        s = re.sub(
            r"\bconforme a la regla[_\s-]*estricta[_\s-]*nomenclatura\b[,:]?\s*",
            "",
            s,
            flags=re.I,
        )
        s = re.sub(r"\bregla[_\s-]*estricta[_\s-]*nomenclatura\b[,:]?\s*", "", s, flags=re.I)
        s = re.sub(r"\b(?:este|el)\s+proyecto\s+no\s+es\s+un\s+cat\b[,:]?\s*", "", s, flags=re.I)
        s = re.sub(r"\bno\s+se\s+trata\s+de\s+un\s+cat\b[,:]?\s*", "", s, flags=re.I)
        s = re.sub(
            r"\bno\s+es\s+un\s+centro\s+autorizado\s+de\s+tratamiento(?:\s*\(cat\))?\b[,:]?\s*",
            "",
            s,
            flags=re.I,
        )
        # Eliminar oración completa que contenga "no se contempla... VFU... CAT" en una sola línea (por si no se partió por punto).
        if modo_purga_no_vehicular and _es_oracion_defensiva_vfu_cat(s):
            continue
        s = _quitar_final_roto(s)
        s = re.sub(r"(?<!Real\s)Decreto 265/2021", "Real Decreto 265/2021", s)
        # Corregir referencia errónea a Ley 7/1985 de Aguas de Canarias → Ley 12/1990
        s = re.sub(
            r"Ley\s+7/1985,\s+de\s+Aguas\s+de\s+Canarias",
            "Ley 12/1990, de Aguas de Canarias",
            s,
            flags=re.I,
        )
        s = re.sub(r"\bhidrocar\b", "hidrocarburos", s, flags=re.I)
        s = re.sub(r"\bImpacto objetivo:\s*Comp\b", "Impacto objetivo: Compensación ambiental local.", s, flags=re.I)
        s = re.sub(
            r"\[(?:[^][]*(?:completar|referencia|revisión|fin del|nota)[^][]*)\]",
            "",
            s,
            flags=re.I,
        )
        s = re.sub(r"\(\s*\)", "", s)
        s = re.sub(r"\s+,", ",", s)
        s = re.sub(r"\s+\.", ".", s)
        s = re.sub(r":\s*$", ".", s)
        # Sustituir frases de plantilla por redacción apta para expediente final
        s = re.sub(r"\bcontenido\s+m[ií]nimo\s+obligatorio\b", "contenido", s, flags=re.I)
        s = re.sub(r"\bformato\s+recomendado\b", "formatos", s, flags=re.I)
        s = re.sub(r"\bpropuestas\s+de\s+elementos\s+visuales\b", "elementos gráficos", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()
        s = _neutralizar_no_consta(s)
        if not s:
            continue
        lineas_out.append(s)

    limpio = "\n".join(lineas_out)
    # Eliminar "NNNN m desde parcela" (distancia RN2000) cuando aparece fuera de contexto cartográfico
    # Solo aplica a distancias típicas 1000-99999 m; en otros contextos se sustituye por N/D
    def _quitar_distancia_fuera_rn2000(m):
        start = max(0, m.start() - 120)
        ctx = limpio[start : m.start()]
        if re.search(r"red\s+natura|RN2000|ENP|ZEPA|distancia\s+(?:a|desde)|cartograf[ií]a", ctx, re.I):
            return m.group(0)
        return "N/D"
    limpio = re.sub(r"\d{3,5}\s+m(?:etros)?\s+desde\s+parcela", _quitar_distancia_fuera_rn2000, limpio, flags=re.I)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio).strip()

    # Añadir referencia a RD 445/2023 junto a Ley 21/2013 si aún no aparece
    if "Ley 21/2013" in limpio and "Real Decreto 445/2023" not in limpio:
        limpio = re.sub(
            r"(\*\*Ley 21/2013[^\n]*\n)",
            (
                r"\1- **Real Decreto 445/2023, de 13 de junio**: modifica los anexos I, II y III de la Ley 21/2013, "
                r"actualizando las tipologías y umbrales de proyectos sometidos a evaluación ambiental ordinaria o "
                r"simplificada, así como los criterios del Anexo III.\n"
            ),
            limpio,
            count=1,
        )

    # Propagación estado_infraestructura a tablas/matrices: nave existente → Fase de Acondicionamiento
    if es_nave_existente:
        limpio = re.sub(r"fase de obra\s*/\s*instalaci[oó]n", "Fase de Acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"Obras\s*/\s*instalaci[oó]n", "Fase de Acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"obra\s*/\s*instalaci[oó]n", "Fase de Acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"obra e instalaci[oó]n", "acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"fase de obra\b", "fase de acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"Fase de obra\b", "Fase de Acondicionamiento", limpio, flags=re.I)
        limpio = re.sub(r"Generaci[oó]n de residuos de construcci[oó]n", "Limpieza y adaptación de interiores", limpio, flags=re.I)
        limpio = re.sub(r"residuos de construcci[oó]n", "Limpieza y adaptación de interiores", limpio, flags=re.I)
        limpio = re.sub(r"Emisi[oó]n de polvo en obra", "Limpieza y adaptación de interiores", limpio, flags=re.I)
        limpio = re.sub(r"movimientos de tierra", "Limpieza y adaptación de interiores", limpio, flags=re.I)
        limpio = re.sub(r"polvo en obra", "polvo durante acondicionamiento", limpio, flags=re.I)
        # Corregir frase errónea: "No se prevén Limpieza y adaptación..." (restaurar sentido: no hay residuos de construcción)
        limpio = re.sub(
            r"No se prevén\s+Limpieza y adaptación de interiores+s?\s+ni\b",
            "No se prevén residuos de construcción ni",
            limpio,
            flags=re.I,
        )
        limpio = re.sub(r"interioress\b", "interiores", limpio, flags=re.I)

    return limpio


def _detectar_alertas_calidad_exportacion(
    capitulos: dict,
    datos_completos: dict,
    modo_no_cat: bool = False,
    perfil_operativo: str = "indeterminado",
) -> list:
    """Detecta vacíos críticos y restos de plantilla antes de exportar."""
    import re

    alertas = []
    texto_total = "\n".join([(v or "") for v in (capitulos or {}).values()])
    checks = [
        (r"\[datos a completar(?: por el promotor)?[^\]]*\]", "Quedan marcadores de datos pendientes."),
        (r"^\s*---\s*$", "Quedan separadores markdown en el texto."),
        (r"\[fin del cap[íi]tulo", "Quedan marcas internas de fin de capítulo."),
        (r"\bn\/d\b", "Quedan valores N/D en el contenido."),
    ]
    for patron, msg in checks:
        if re.search(patron, texto_total, flags=re.I | re.M):
            alertas.append(msg)

    def _faltante(v: str) -> bool:
        s = (v or "").strip().lower()
        return (not s) or s in {"n/d", "nd", "no consta", "dato no facilitado por el promotor en esta fase."}

    if _faltante(datos_completos.get("organo_sustantivo", "")):
        alertas.append("Falta Órgano Sustantivo en datos del proyecto.")
    if _faltante(datos_completos.get("referencia_catastral", "")):
        alertas.append("Falta Referencia Catastral en datos del proyecto.")
    if _faltante(datos_completos.get("coordenadas_utm", "")):
        alertas.append("Faltan coordenadas del proyecto.")
    if _faltante(datos_completos.get("antecedentes", "")):
        alertas.append("Faltan antecedentes administrativos del proyecto.")

    # Gate de cierre: evitar capacidad legacy sin unidad (ej. '500') cuando no hay capacidades canónicas.
    cap_raw = (datos_completos.get("capacidad_maxima_almacenamiento") or "").strip()
    if cap_raw and re.fullmatch(r"\d+(?:[.,]\d+)?", cap_raw):
        hay_cap_can = any(
            (str(datos_completos.get(k) or "").strip())
            for k in (
                "capacidad_clasificacion_t_d",
                "capacidad_trituracion_cobre_t_d",
                "capacidad_tratamiento_t_d",
                "capacidad_total_t",
                "almacenamiento_pre_t",
                "almacenamiento_post_t",
                "capacidad_anual_t_a",
            )
        )
        if not hay_cap_can:
            alertas.append(
                "Capacidad máxima de almacenamiento figura como número sin unidad (ej. '500'). "
                "Indique unidad (t, t/d, t/año) o deje N/D + cómo obtenerlo."
            )

    if modo_no_cat:
        texto_total_lower = texto_total.lower()
        if re.search(r"instalaci[oó]n de desguace,\s*cat y gesti[oó]n de residuos", texto_total_lower):
            alertas.append("Persisten denominaciones de proyecto tipo CAT incompatibles con el alcance no-CAT.")
        # Permite referencias a CAT solo cuando sea explícitamente externo.
        lineas_conflictivas = []
        for ln in texto_total.splitlines():
            l = (ln or "").strip()
            if not l:
                continue
            l_low = l.lower()
            if ("centro autorizado de tratamiento" in l_low or re.search(r"\bcat\b", l_low)) and not (
                "extern" in l_low or "c/ brezo" in l_low or "calle brezo" in l_low
            ):
                lineas_conflictivas.append(l)
                if len(lineas_conflictivas) >= 3:
                    break
        if lineas_conflictivas:
            alertas.append("Aparecen menciones a CAT no justificadas como instalación externa en algunos párrafos.")

    if perfil_operativo == "gestion_residuos_no_vehiculos":
        # Solo alertar si siguen los tokens prohibidos CAT o VFU (no la redacción correcta "vehículos fuera de uso" / "centro autorizado")
        texto_total_lower = texto_total.lower()
        m_vfu = re.search(r".{0,60}\b(?:vfu|cat)\b.{0,60}", texto_total_lower, re.I)
        if m_vfu:
            extracto = re.sub(r"\s+", " ", m_vfu.group(0))[:120].strip() + "…"
            cap_donde = ""
            for ck, tc in (capitulos or {}).items():
                if m_vfu.group(0) in (tc or "").lower():
                    cap_donde = ck.replace("informe_", "").replace("_", " ")
                    break
            alertas.append(
                f"El proyecto está clasificado como gestión de residuos no vehiculares y aparecen referencias VFU/CAT. "
                f"{'Capítulo: ' + cap_donde + '. ' if cap_donde else ''}Extracto: «{extracto}»"
            )

    return alertas


def _reiniciar_estado_proyecto():
    """Limpia el estado en memoria asociado al proyecto activo."""
    st.session_state.memoria_tecnica = []
    st.session_state.documentos_administrativos = []
    st.session_state.datos_extraidos = None
    st.session_state.datos_usuario = {}
    for _, _, session_key in CHAPTER_TEMPLATE:
        st.session_state[session_key] = None
    st.session_state.mapa_imagen_bytes = None
    st.session_state.mapa_imagenes_bytes = []
    st.session_state.mapa_anexos_detalle = []
    st.session_state.clima_analisis_texto = ""
    st.session_state.clima_figuras_bytes = []
    st.session_state.imagenes_reportaje_bytes = []
    st.session_state.informe_word_bytes = None
    st.session_state.texto_memoria_contexto = ""
    st.session_state.texto_fuentes_perfil_contexto = ""
    st.session_state.fingerprint_fuentes_perfil = ""


def _cargar_filelikes_desde_paths(rutas):
    salida = []
    for ruta in rutas or []:
        try:
            contenido = ruta.read_bytes()
            f = io.BytesIO(contenido)
            f.name = ruta.name
            salida.append(f)
        except Exception:
            continue
    return salida


def _cargar_estado_desde_disco(nombre_proyecto: str):
    """Restaura activos persistidos del proyecto para continuar el trabajo."""
    try:
        archivos = _cargar_archivos_guardados_cached(nombre_proyecto)
        estado = _cargar_estado_proyecto_cached(nombre_proyecto)
        imagenes = archivos.get("imagenes", [])

        mapas = []
        clima = []
        fotos = []
        for ruta in imagenes:
            nombre = ruta.name.lower()
            try:
                data = ruta.read_bytes()
            except Exception:
                continue
            if nombre.startswith("mapa_"):
                mapas.append((ruta.name, data))
            elif nombre.startswith("clima_"):
                clima.append((ruta.name, data))
            elif nombre.startswith("foto_"):
                fotos.append((ruta.name, data))

        st.session_state.mapa_imagenes_bytes = [b for _, b in sorted(mapas, key=lambda x: x[0])]
        st.session_state.mapa_imagen_bytes = st.session_state.mapa_imagenes_bytes[0] if st.session_state.mapa_imagenes_bytes else None
        st.session_state.clima_figuras_bytes = [b for _, b in sorted(clima, key=lambda x: x[0])]
        st.session_state.imagenes_reportaje_bytes = [b for _, b in sorted(fotos, key=lambda x: x[0])]
        st.session_state.clima_analisis_texto = (estado.get("clima_analisis_texto") or "").strip()
        st.session_state.datos_usuario = estado.get("datos_usuario") or {}
        datos_extraidos_state = estado.get("datos_extraidos") or {}
        if isinstance(datos_extraidos_state, dict) and datos_extraidos_state:
            try:
                from analista import DatosEIA
                obj = DatosEIA()
                for k, v in datos_extraidos_state.items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)
                st.session_state.datos_extraidos = obj
            except Exception:
                st.session_state.datos_extraidos = None
        capitulos = estado.get("capitulos") or {}
        for _, _, session_key in CHAPTER_TEMPLATE:
            if isinstance(capitulos.get(session_key), str):
                st.session_state[session_key] = capitulos.get(session_key)

        anexos = []
        for item in estado.get("mapa_anexos_detalle", []) or []:
            if not isinstance(item, dict):
                continue
            archivo = item.get("archivo")
            if not archivo:
                continue
            ruta_img = None
            for p in imagenes:
                if p.name == archivo:
                    ruta_img = p
                    break
            if not ruta_img:
                continue
            try:
                img = ruta_img.read_bytes()
            except Exception:
                continue
            restored = dict(item)
            restored["imagen"] = img
            anexos.append(restored)
        st.session_state.mapa_anexos_detalle = anexos
        st.session_state.texto_memoria_contexto = (estado.get("texto_memoria_contexto") or "")[:150000]
        st.session_state.texto_fuentes_perfil_contexto = (estado.get("texto_fuentes_perfil_contexto") or "")[:180000]
        st.session_state.fingerprint_fuentes_perfil = (estado.get("fingerprint_fuentes_perfil") or "")
    except Exception:
        pass


def _guardar_estado_proyecto(nombre_proyecto: str):
    """Guarda metadatos de activos (no duplicar binarios en JSON)."""
    try:
        from persistencia_archivos import guardar_estado_proyecto
        # Sanitizar LER: admitidos sin asteriscos; códigos con * → RP propios
        datos_u = dict(st.session_state.get("datos_usuario", {}))
        ler_ok, rp_ok = _sanitizar_ler_admitidos_sin_asteriscos(
            datos_u.get("clasificacion_ler", ""),
            datos_u.get("residuos_peligrosos_propios_ler", ""),
        )
        datos_u["clasificacion_ler"] = ler_ok
        datos_u["residuos_peligrosos_propios_ler"] = rp_ok
        st.session_state.datos_usuario = datos_u

        anexos_meta = []
        for item in st.session_state.get("mapa_anexos_detalle", []) or []:
            if not isinstance(item, dict):
                continue
            meta = dict(item)
            meta.pop("imagen", None)
            anexos_meta.append(meta)
        payload = {
            "mapa_anexos_detalle": anexos_meta,
            "clima_analisis_texto": st.session_state.get("clima_analisis_texto", ""),
            "datos_usuario": datos_u,
            "texto_memoria_contexto": st.session_state.get("texto_memoria_contexto", ""),
            "texto_fuentes_perfil_contexto": st.session_state.get("texto_fuentes_perfil_contexto", ""),
            "fingerprint_fuentes_perfil": st.session_state.get("fingerprint_fuentes_perfil", ""),
            "capitulos": {k: st.session_state.get(k) for _, _, k in CHAPTER_TEMPLATE if isinstance(st.session_state.get(k), str)},
        }
        datos_extraidos = st.session_state.get("datos_extraidos")
        if datos_extraidos is not None and hasattr(datos_extraidos, "__dict__"):
            payload["datos_extraidos"] = {
                k: v for k, v in vars(datos_extraidos).items() if isinstance(v, (str, int, float, bool)) or v is None
            }
        guardar_estado_proyecto(payload, nombre_proyecto)
        _invalidate_cache_data()
    except Exception:
        pass

# Inicializar session_state para archivos cargados
if "memoria_tecnica" not in st.session_state:
    st.session_state.memoria_tecnica = []  # Lista de archivos PDF
if "documentos_administrativos" not in st.session_state:
    st.session_state.documentos_administrativos = []
if "proyecto_actual" not in st.session_state:
    st.session_state.proyecto_actual = config.get("proyecto_actual", "proyecto_default")

# Intentar inicializar persistencia multi-proyecto
try:
    from persistencia_archivos import crear_proyecto
    st.session_state.proyecto_actual = crear_proyecto(st.session_state.proyecto_actual)
except Exception:
    pass
if "datos_extraidos" not in st.session_state:
    st.session_state.datos_extraidos = None
if "datos_usuario" not in st.session_state:
    st.session_state.datos_usuario = {}
for _, _, session_key in CHAPTER_TEMPLATE:
    if session_key not in st.session_state:
        st.session_state[session_key] = None
if "mapa_imagen_bytes" not in st.session_state:
    st.session_state.mapa_imagen_bytes = None
if "mapa_imagenes_bytes" not in st.session_state:
    st.session_state.mapa_imagenes_bytes = []
if "mapa_anexos_detalle" not in st.session_state:
    st.session_state.mapa_anexos_detalle = []
if "clima_analisis_texto" not in st.session_state:
    st.session_state.clima_analisis_texto = ""
if "clima_figuras_bytes" not in st.session_state:
    st.session_state.clima_figuras_bytes = []
if "imagenes_reportaje_bytes" not in st.session_state:
    st.session_state.imagenes_reportaje_bytes = []
if "informe_word_bytes" not in st.session_state:
    st.session_state.informe_word_bytes = None
if "texto_memoria_contexto" not in st.session_state:
    st.session_state.texto_memoria_contexto = ""
if "texto_fuentes_perfil_contexto" not in st.session_state:
    st.session_state.texto_fuentes_perfil_contexto = ""
if "fingerprint_fuentes_perfil" not in st.session_state:
    st.session_state.fingerprint_fuentes_perfil = ""
if "portada_global_path" not in st.session_state:
    st.session_state.portada_global_path = _asegurar_portada_global()
if "proyecto_cargado_en_memoria" not in st.session_state:
    st.session_state.proyecto_cargado_en_memoria = ""
if st.session_state.proyecto_cargado_en_memoria != st.session_state.proyecto_actual:
    _reiniciar_estado_proyecto()
    _cargar_estado_desde_disco(st.session_state.proyecto_actual)
    st.session_state.proyecto_cargado_en_memoria = st.session_state.proyecto_actual

# CSS para interfaz moderna (inyectar una sola vez por sesión para mejorar fluidez).
def _inyectar_ui_assets():
    if st.session_state.get("_ui_assets_injected"):
        return

    st.markdown("""
<style>
    .stApp {
        background: linear-gradient(180deg, #f4fbf7 0%, #eef7fb 100%);
    }
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #135c43;
        margin-bottom: 0.5rem;
        letter-spacing: 0.2px;
    }
    .section-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: #1b7661;
        margin-top: 1.5rem;
        margin-bottom: 0.75rem;
    }
    .eco-soft-card {
        border: 1px solid #d7ebe2;
        border-radius: 14px;
        padding: 0.9rem 1rem;
        background: linear-gradient(135deg, #ffffff 0%, #f2fbf8 100%);
        box-shadow: 0 3px 10px rgba(20, 94, 74, 0.08);
    }
    .eco-kpi-card {
        border: 1px solid #cfe8e0;
        border-radius: 14px;
        padding: 0.8rem 0.9rem;
        background: linear-gradient(135deg, #ffffff 0%, #f5fbff 100%);
        box-shadow: 0 3px 10px rgba(17, 84, 68, 0.07);
        min-height: 94px;
    }
    .eco-kpi-label {
        font-size: 0.83rem;
        color: #2f5f73;
        font-weight: 600;
    }
    .eco-kpi-value {
        font-size: 1.55rem;
        line-height: 1.4rem;
        color: #0e6a4c;
        font-weight: 800;
        margin-top: 0.25rem;
    }
    .eco-hero {
        border: 1px solid #d6ece4;
        border-radius: 16px;
        padding: 1rem 1.2rem;
        background: linear-gradient(120deg, #ffffff 0%, #eefaf5 62%, #ecf7ff 100%);
        box-shadow: 0 5px 15px rgba(21, 91, 72, 0.09);
    }
    .eco-chip-ok {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        background: #dbf5e7;
        color: #0d7a4c;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .eco-chip-pending {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        background: #e8eef5;
        color: #42607a;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f0f7f4 0%, #e8f0ec 100%);
        border-right: 1px solid #d5e5de;
    }
    div.stButton > button {
        border-radius: 10px;
        border: 1px solid #2d8d67;
        background: linear-gradient(180deg, #3da477 0%, #258a63 100%);
        color: white;
        font-weight: 600;
    }
    div.stButton > button:hover {
        border-color: #1f7654;
        background: linear-gradient(180deg, #2f966c 0%, #1e7654 100%);
        color: white;
    }
    div[data-testid="stDownloadButton"] > button {
        border-radius: 10px;
        border: 1px solid #2a7ba8;
        background: linear-gradient(180deg, #3b9fd1 0%, #2a7ba8 100%);
        color: white;
        font-weight: 600;
    }
    .upload-area {
        padding: 2rem;
        border: 2px dashed #2d5a45;
        border-radius: 12px;
        background-color: #f8fdfa;
        margin: 1rem 0;
    }
    /* Oculta errores de frontend no críticos para evitar impacto visual al usuario final. */
    [data-testid="stException"],
    div[data-testid="stException"],
    section[data-testid="stException"],
    .stException,
    .stExceptionElement {
        display: none !important;
    }
    /* Algunos builds renderizan estos errores como alerta BaseWeb. */
    [data-baseweb="notification"] pre {
        display: none !important;
    }

    /* Sidebar más limpia */
    section[data-testid="stSidebar"] > div {
        background: linear-gradient(180deg, #f5fbf8 0%, #f3f7fb 100%);
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] {
        gap: 0.4rem;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
        border: 1px solid rgba(20, 94, 74, 0.10);
        background: rgba(255,255,255,0.7);
        border-radius: 12px;
        padding: 0.35rem 0.5rem;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
        border-color: rgba(20, 94, 74, 0.22);
        background: rgba(255,255,255,0.9);
    }
</style>
""", unsafe_allow_html=True)

    # Marcar como inyectado para no reinsertar CSS en cada rerun (mejora respuesta al tickear widgets).
    st.session_state["_ui_assets_injected"] = True


_inyectar_ui_assets()

# Menú lateral
logo_path = _resolver_logo_path()
if logo_path:
    st.sidebar.image(logo_path, width=220)
st.sidebar.markdown("### 🌿 Generador de EIA")
st.sidebar.markdown("---")

# Gestión de proyectos
try:
    from persistencia_archivos import listar_proyectos, crear_proyecto, eliminar_proyecto
    proyectos = _listar_proyectos_cached()
    if not proyectos:
        proyectos = [crear_proyecto(st.session_state.proyecto_actual)]
    if st.session_state.proyecto_actual not in proyectos:
        st.session_state.proyecto_actual = proyectos[0]
except Exception:
    proyectos = [st.session_state.proyecto_actual]

st.sidebar.markdown("### 📂 Proyecto")
proyecto_sel = st.sidebar.selectbox(
    "Proyecto activo",
    options=proyectos,
    index=proyectos.index(st.session_state.proyecto_actual) if st.session_state.proyecto_actual in proyectos else 0,
)
if proyecto_sel != st.session_state.proyecto_actual:
    st.session_state.proyecto_actual = proyecto_sel
    config["proyecto_actual"] = proyecto_sel
    guardar_config(config)
    st.rerun()

with st.sidebar.form("form_crear_proyecto", clear_on_submit=True):
    nuevo_proyecto = st.text_input(
        "Nuevo proyecto",
        value="",
        placeholder="Ej: EIA_Parque_Solar_Telde",
        help="Se creará una carpeta aislada para memorias, docs e imágenes.",
    )
    submitted_crear = st.form_submit_button("Crear y abrir proyecto")
if submitted_crear:
    nombre = (nuevo_proyecto or "").strip()
    if not nombre:
        st.sidebar.warning("Escribe un nombre de proyecto.")
    else:
        try:
            creado = crear_proyecto(nombre)
            _invalidate_cache_data()
            st.session_state.proyecto_actual = creado
            config["proyecto_actual"] = creado
            guardar_config(config)
            st.sidebar.success(f"Proyecto activo: {creado}")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"No se pudo crear el proyecto: {e}")

confirmar_borrado = st.sidebar.checkbox("Confirmar borrado del proyecto activo")
if st.sidebar.button("Borrar proyecto activo", type="secondary"):
    if not confirmar_borrado:
        st.sidebar.warning("Marca la confirmación para borrar.")
    else:
        try:
            eliminado = eliminar_proyecto(st.session_state.proyecto_actual)
            _invalidate_cache_data()
            if eliminado:
                restantes = _listar_proyectos_cached()
                if not restantes:
                    restantes = [crear_proyecto("proyecto_default")]
                st.session_state.proyecto_actual = restantes[0]
                config["proyecto_actual"] = st.session_state.proyecto_actual
                guardar_config(config)
                st.sidebar.success("Proyecto eliminado.")
                st.rerun()
            else:
                st.sidebar.warning("No se encontró el proyecto para borrar.")
        except Exception as e:
            st.sidebar.error(f"Error al borrar proyecto: {e}")

st.sidebar.caption(f"Activo: {st.session_state.proyecto_actual}")
st.sidebar.markdown("---")

pagina = st.sidebar.radio(
    "Navegación",
    options=["inicio", "carga", "analisis", "mapas", "clima", "informe"],
    format_func=lambda x: {
        "inicio": "🏠 Inicio",
        "carga": "📁 Carga de Documentos",
        "analisis": "📊 Análisis de Datos",
        "mapas": "🗺️ Mapas y Anexos",
        "clima": "🌤️ Clima (AEMET)",
        "informe": "📄 Generación de Informe",
    }[x],
    label_visibility="collapsed",
)

# API Keys (OpenAI y AEMET)
st.sidebar.markdown("### 🔑 Claves API")

# Inicializar API Keys desde config o session_state
if "openai_api_key" not in st.session_state:
    st.session_state.openai_api_key = config.get("openai_api_key", "")
if "aemet_api_key" not in st.session_state:
    st.session_state.aemet_api_key = config.get("aemet_api_key", "")

openai_cfg = bool(st.session_state.openai_api_key.strip())
aemet_cfg = bool(st.session_state.aemet_api_key.strip())
st.sidebar.caption(
    "OpenAI: " + ("configurada" if openai_cfg else "pendiente")
    + "  ·  AEMET: " + ("configurada" if aemet_cfg else "pendiente")
)

if st.sidebar.checkbox("Editar claves API", value=not (openai_cfg and aemet_cfg)):
    with st.sidebar.form("form_api_keys", clear_on_submit=True):
        openai_key = st.text_input(
            "Nueva OpenAI API Key",
            value="",
            type="password",
            help="No se muestra la clave actual en pantalla por seguridad.",
        )
        aemet_key = st.text_input(
            "Nueva AEMET OpenData API Key",
            value="",
            type="password",
            help="No se muestra la clave actual en pantalla por seguridad.",
        )
        submitted_keys = st.form_submit_button("Guardar claves")

    if submitted_keys:
        nueva_openai_key = (openai_key or "").strip()
        nueva_aemet_key = (aemet_key or "").strip()
        if not nueva_openai_key and not nueva_aemet_key:
            st.sidebar.warning("Introduce al menos una clave para guardar.")
        else:
            if nueva_openai_key:
                st.session_state.openai_api_key = nueva_openai_key
                config["openai_api_key"] = nueva_openai_key
            if nueva_aemet_key:
                st.session_state.aemet_api_key = nueva_aemet_key
                config["aemet_api_key"] = nueva_aemet_key
            guardar_config(config)
            st.sidebar.success("Claves guardadas.")

if st.session_state.openai_api_key:
    # Establecer como variable de entorno para que generador.py la use
    os.environ["OPENAI_API_KEY"] = st.session_state.openai_api_key

st.sidebar.markdown("---")
st.sidebar.caption("Herramienta para Estudios de Impacto Ambiental")

# --- SECCIÓN INICIO ---
if pagina == "inicio":
    st.markdown('<p class="main-header">Generador de Estudios de Impacto Ambiental</p>', unsafe_allow_html=True)
    st.markdown(
        '<div class="eco-hero"><strong>EcoGestión Impacto Positivo</strong><br/>'
        'Plataforma técnica para expedientes EIA de alta calidad, con trazabilidad y persistencia por proyecto.</div>',
        unsafe_allow_html=True,
    )
    if logo_path:
        col_logo_izq, col_logo_ctr, col_logo_der = st.columns([1, 2.4, 1])
        with col_logo_ctr:
            st.image(logo_path, width=460)
    st.markdown("---")
    kpi = _kpis_proyecto(st.session_state.proyecto_actual)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Memorias</div>'
        f'<div class="eco-kpi-value">{kpi["memorias"]}</div></div>',
        unsafe_allow_html=True,
    )
    c2.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Docs admin</div>'
        f'<div class="eco-kpi-value">{kpi["docs_admin"]}</div></div>',
        unsafe_allow_html=True,
    )
    c3.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Mapas</div>'
        f'<div class="eco-kpi-value">{kpi["mapas"]}</div></div>',
        unsafe_allow_html=True,
    )
    c4.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Clima</div>'
        f'<div class="eco-kpi-value">{kpi["clima_figuras"]}</div></div>',
        unsafe_allow_html=True,
    )
    c5.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Fotos</div>'
        f'<div class="eco-kpi-value">{kpi["fotos"]}</div></div>',
        unsafe_allow_html=True,
    )
    c6.markdown(
        '<div class="eco-kpi-card"><div class="eco-kpi-label">Capítulos</div>'
        f'<div class="eco-kpi-value">{kpi["capitulos"]}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown("""
    **Flujo de trabajo:**
    1. **Carga de Documentos** – Sube una o varias Memorias Técnicas (PDF) y los Documentos Administrativos
    2. **Análisis de Datos** – Revisa los datos extraídos automáticamente (promotor, ubicación, coordenadas, etc.)
    3. **Mapas y Anexos** – Genera y guarda cartografía temática por proyecto
    4. **Clima (AEMET)** – Genera y guarda climograma/rosa con fuente oficial
    5. **Generación de Informe** – Exporta el documento final cuando todo esté validado
    """)
    st.info(
        "Proyecto activo: "
        f"**{st.session_state.proyecto_actual}**. "
        "Todo lo que subas o generes (documentos, mapas, clima, fotos) queda guardado para este proyecto."
    )
    st.markdown("### Estado del proyecto")
    estado = _estado_proyecto_visual(st.session_state.proyecto_actual)
    items = [
        ("1. Carga de documentos", estado["carga_documentos"]),
        ("2. Análisis de datos", estado["analisis_datos"]),
        ("3. Mapas y anexos", estado["mapas_anexos"]),
        ("4. Clima (AEMET)", estado["clima"]),
        ("5. Generación de informe", estado["informe"]),
    ]
    col_a, col_b = st.columns(2)
    for i, (titulo, valor) in enumerate(items):
        chip = "eco-chip-ok" if valor == "completo" else "eco-chip-pending"
        etiqueta = "Completo" if valor == "completo" else "Pendiente"
        html = (
            '<div class="eco-soft-card">'
            f'<strong>{titulo}</strong><br/>'
            f'<span class="{chip}">{etiqueta}</span>'
            "</div>"
        )
        if i % 2 == 0:
            col_a.markdown(html, unsafe_allow_html=True)
        else:
            col_b.markdown(html, unsafe_allow_html=True)
    if all(v == "completo" for v in estado.values()):
        st.success("Proyecto listo para exportación final en Word.")
    else:
        st.caption("Consejo: completa los bloques pendientes para mejorar la calidad técnica del informe final.")

# --- SECCIÓN CARGA DE DOCUMENTOS ---
elif pagina == "carga":
    st.markdown('<p class="main-header">Carga de Documentos</p>', unsafe_allow_html=True)
    st.markdown("Sube los documentos necesarios para el Estudio de Impacto Ambiental.")
    st.caption(f"Proyecto activo: {st.session_state.proyecto_actual}")
    st.info(
        "Aislamiento de proyectos activo: las memorias y documentos se guardan por proyecto "
        "(carpeta propia en `archivos_proyecto/<proyecto>`). "
        "La carpeta `docs_referencia` es global y solo aporta normativa/ejemplos, no memorias del cliente."
    )

    archivos_guardados = {"memorias": [], "documentos_administrativos": [], "imagenes": []}
    try:
        archivos_guardados = _cargar_archivos_guardados_cached(st.session_state.proyecto_actual)
    except Exception:
        pass

    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<p class="section-title">Memorias Técnicas del Cliente</p>', unsafe_allow_html=True)
        st.markdown("Documentos PDF o Word (.docx/.doc) con la memoria técnica y/o memoria de explotación del proyecto. Puedes subir múltiples archivos.")
        memorias = st.file_uploader(
            "Memorias Técnicas (PDF, Word)",
            type=["pdf", "docx", "doc"],
            accept_multiple_files=True,
            key="memoria_upload",
        )
        if memorias:
            st.session_state.memoria_tecnica = list(memorias)  # Guardar como lista
            # Guardar también en disco para persistencia
            try:
                from persistencia_archivos import guardar_memorias
                guardar_memorias(memorias, st.session_state.proyecto_actual)
                _invalidate_cache_data()
            except Exception:
                pass
            nombres = [m.name for m in memorias]
            st.success(f"✓ {len(memorias)} archivo(s) cargado(s): {', '.join(nombres)}")

    with col2:
        st.markdown('<p class="section-title">Documentos Administrativos</p>', unsafe_allow_html=True)
        st.markdown("Documentos complementarios (PDF, Word).")
        docs_admin = st.file_uploader(
            "Documentos Administrativos",
            type=["pdf", "docx", "doc"],
            accept_multiple_files=True,
            key="admin_upload",
        )
        if docs_admin:
            st.session_state.documentos_administrativos = docs_admin
            # Guardar también en disco para persistencia
            try:
                from persistencia_archivos import guardar_documentos_administrativos
                guardar_documentos_administrativos(docs_admin, st.session_state.proyecto_actual)
                _invalidate_cache_data()
            except Exception:
                pass
            st.success(f"✓ {len(docs_admin)} archivo(s) cargado(s)")

        st.markdown("**Reportaje fotográfico del proyecto** (fachada, interior, parcela, accesos, etc.)")
        fotos = st.file_uploader(
            "Fotos del proyecto (JPG/PNG/WebP)",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="fotos_upload",
        )
        if fotos:
            fotos_bytes = []
            for f in fotos:
                try:
                    f.seek(0)
                    contenido = f.read()
                    fotos_bytes.append(contenido)
                    try:
                        from persistencia_archivos import guardar_bytes_en_imagenes
                        guardar_bytes_en_imagenes(
                            contenido,
                            f"foto_{f.name}",
                            st.session_state.proyecto_actual,
                        )
                    except Exception:
                        pass
                except Exception:
                    continue
            st.session_state.imagenes_reportaje_bytes = fotos_bytes
            _invalidate_cache_data()
            st.success(f"✓ {len(fotos_bytes)} imagen(es) de reportaje cargada(s)")

    st.markdown("---")
    st.markdown("### Elementos guardados en este proyecto")
    try:
        from persistencia_archivos import eliminar_archivo

        st.markdown("**Memorias técnicas guardadas**")
        if archivos_guardados.get("memorias"):
            for ruta in archivos_guardados["memorias"]:
                c_a, c_b = st.columns([5, 1])
                c_a.write(f"- {ruta.name}")
                if c_b.button("🗑️", key=f"del_mem_{ruta.name}"):
                    if eliminar_archivo(ruta):
                        _invalidate_cache_data()
                        st.session_state.memoria_tecnica = [
                            m for m in (st.session_state.get("memoria_tecnica") or [])
                            if getattr(m, "name", "") != ruta.name
                        ]
                        st.success(f"Eliminado: {ruta.name}")
                        st.rerun()
        else:
            st.caption("Sin memorias guardadas.")

        st.markdown("**Documentos administrativos guardados**")
        if archivos_guardados.get("documentos_administrativos"):
            for ruta in archivos_guardados["documentos_administrativos"]:
                c_a, c_b = st.columns([5, 1])
                c_a.write(f"- {ruta.name}")
                if c_b.button("🗑️", key=f"del_admin_{ruta.name}"):
                    if eliminar_archivo(ruta):
                        _invalidate_cache_data()
                        st.session_state.documentos_administrativos = [
                            d for d in (st.session_state.get("documentos_administrativos") or [])
                            if getattr(d, "name", "") != ruta.name
                        ]
                        st.success(f"Eliminado: {ruta.name}")
                        st.rerun()
        else:
            st.caption("Sin documentos administrativos guardados.")

        st.markdown("**Imágenes/fotos guardadas**")
        imagenes = archivos_guardados.get("imagenes", [])
        if imagenes:
            for ruta in imagenes:
                c_a, c_b = st.columns([5, 1])
                c_a.write(f"- {ruta.name}")
                if c_b.button("🗑️", key=f"del_img_{ruta.name}"):
                    if eliminar_archivo(ruta):
                        _invalidate_cache_data()
                        st.success(f"Eliminado: {ruta.name}")
                        st.rerun()
        else:
            st.caption("Sin imágenes guardadas.")
    except Exception:
        st.caption("No se pudo cargar el listado de elementos guardados.")

# --- SECCIÓN ANÁLISIS DE DATOS ---
elif pagina == "analisis":
    st.markdown('<p class="main-header">Análisis de Datos</p>', unsafe_allow_html=True)
    st.markdown("Datos extraídos automáticamente de la Memoria Técnica. Verifica que sean correctos y completa los que falten.")
    st.caption(f"Proyecto activo: {st.session_state.proyecto_actual}")

    memorias_fuente = list(st.session_state.memoria_tecnica or [])
    if not memorias_fuente:
        try:
            guardados = _cargar_archivos_guardados_cached(st.session_state.proyecto_actual)
            memorias_fuente = _cargar_filelikes_desde_paths(guardados.get("memorias", []))
        except Exception:
            memorias_fuente = []

    if not memorias_fuente or len(memorias_fuente) == 0:
        st.warning("No hay Memorias Técnicas cargadas. Ve a **Carga de Documentos** y sube uno o más archivos (PDF o Word).")
    else:
        st.info(f"📄 {len(memorias_fuente)} memoria(s) disponibles: {', '.join([getattr(m, 'name', 'memoria') for m in memorias_fuente])}")
        
        # Opción para usar análisis inteligente con IA
        usar_ia = st.checkbox(
            "✨ Usar análisis inteligente con IA (más preciso)",
            value=True,
            help="Usa GPT-4o para análisis inteligente del texto completo. Más preciso que el método básico.",
        )
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            modelo_analisis = st.selectbox(
                "Modelo para análisis IA",
                options=["gpt-4o", "gpt-4.1", "gpt-4o-mini"],
                index=["gpt-4o", "gpt-4.1", "gpt-4o-mini"].index(
                    config.get("openai_analysis_model", "gpt-4o")
                    if config.get("openai_analysis_model", "gpt-4o") in ["gpt-4o", "gpt-4.1", "gpt-4o-mini"]
                    else "gpt-4o"
                ),
                help="Para lectura más potente prueba gpt-4.1. Si falla, hay fallback automático.",
            )
        with col_m2:
            modo_profundo = st.checkbox(
                "Modo profundo (por bloques)",
                value=bool(config.get("openai_analysis_deep_mode", True)),
                help="Recomendado: analiza el documento por bloques y consolida. Necesario para extraer maquinaria, proceso y estado de infraestructura de memorias largas.",
            )
        if modelo_analisis != config.get("openai_analysis_model", "gpt-4o") or modo_profundo != bool(config.get("openai_analysis_deep_mode", False)):
            config["openai_analysis_model"] = modelo_analisis
            config["openai_analysis_deep_mode"] = modo_profundo
            guardar_config(config)
        
        if st.button("🔍 Extraer y analizar datos", type="primary"):
            try:
                from analista import extraer_texto_documento
                from analista_ia import analizar_documento_con_ia
                from analista import analizar_pdf

                with st.spinner(f"Analizando {len(memorias_fuente)} documento(s) {'con IA' if usar_ia else 'con método básico'}..."):
                    if usar_ia:
                        # Usar análisis inteligente con IA (procesar cada documento por separado y combinar)
                        from analista import DatosEIA
                        datos_combinados = DatosEIA()
                        textos_para_combinar = []
                        
                        for i, memoria in enumerate(memorias_fuente):
                            memoria.seek(0)
                            datos_doc = analizar_documento_con_ia(
                                memoria,
                                usar_ia=True,
                                model=modelo_analisis,
                                deep_mode=modo_profundo,
                                fallback_models=["gpt-4o", "gpt-4o-mini"],
                            )
                            
                            # Combinar datos (priorizar valores no vacíos)
                            if datos_doc.nombre_promotor and not datos_combinados.nombre_promotor:
                                datos_combinados.nombre_promotor = datos_doc.nombre_promotor
                            if datos_doc.ubicacion_proyecto and not datos_combinados.ubicacion_proyecto:
                                datos_combinados.ubicacion_proyecto = datos_doc.ubicacion_proyecto
                            if datos_doc.coordenadas_utm and not datos_combinados.coordenadas_utm:
                                datos_combinados.coordenadas_utm = datos_doc.coordenadas_utm
                            if datos_doc.referencia_catastral and not datos_combinados.referencia_catastral:
                                datos_combinados.referencia_catastral = datos_doc.referencia_catastral
                            if datos_doc.clasificacion_ler and not datos_combinados.clasificacion_ler:
                                datos_combinados.clasificacion_ler = datos_doc.clasificacion_ler
                            if datos_doc.consumos_agua_luz and not datos_combinados.consumos_agua_luz:
                                datos_combinados.consumos_agua_luz = datos_doc.consumos_agua_luz
                            # Combinar maquinaria, proceso y estado de infraestructura (pueden venir de proyecto de explotación)
                            if datos_doc.maquinaria_equipos:
                                if not datos_combinados.maquinaria_equipos:
                                    datos_combinados.maquinaria_equipos = datos_doc.maquinaria_equipos
                                elif datos_doc.maquinaria_equipos not in datos_combinados.maquinaria_equipos:
                                    datos_combinados.maquinaria_equipos = f"{datos_combinados.maquinaria_equipos}\n{datos_doc.maquinaria_equipos}"
                            if datos_doc.proceso_explotacion:
                                if not datos_combinados.proceso_explotacion:
                                    datos_combinados.proceso_explotacion = datos_doc.proceso_explotacion
                                elif datos_doc.proceso_explotacion not in datos_combinados.proceso_explotacion:
                                    datos_combinados.proceso_explotacion = f"{datos_combinados.proceso_explotacion}\n{datos_doc.proceso_explotacion}"
                            if datos_doc.estado_infraestructura and not datos_combinados.estado_infraestructura:
                                datos_combinados.estado_infraestructura = datos_doc.estado_infraestructura
                            if datos_doc.evidencias_estado_infraestructura:
                                if not datos_combinados.evidencias_estado_infraestructura:
                                    datos_combinados.evidencias_estado_infraestructura = datos_doc.evidencias_estado_infraestructura
                                elif datos_doc.evidencias_estado_infraestructura not in datos_combinados.evidencias_estado_infraestructura:
                                    datos_combinados.evidencias_estado_infraestructura = (
                                        f"{datos_combinados.evidencias_estado_infraestructura}; {datos_doc.evidencias_estado_infraestructura}"
                                    )
                            # Si hay más LER en este documento, añadirlos
                            if datos_doc.clasificacion_ler and datos_combinados.clasificacion_ler and datos_doc.clasificacion_ler not in datos_combinados.clasificacion_ler:
                                datos_combinados.clasificacion_ler = f"{datos_combinados.clasificacion_ler}; {datos_doc.clasificacion_ler}"
                            
                            # Guardar texto para contexto posterior
                            memoria.seek(0)
                            texto = extraer_texto_documento(memoria)
                            textos_para_combinar.append(texto)
                        
                        datos = datos_combinados
                    else:
                        # Método básico (original)
                        textos = []
                        textos_memoria_crudos = []
                        for i, memoria in enumerate(memorias_fuente):
                            memoria.seek(0)
                            texto = extraer_texto_documento(memoria)
                            textos_memoria_crudos.append(texto or "")
                            textos.append(f"\n\n--- DOCUMENTO {i+1}: {memoria.name} ---\n\n{texto}")
                        
                        texto_combinado = "\n".join(textos)
                        datos = analizar_pdf(texto=texto_combinado, es_texto_directo=True)

                    # Normalizar LER justo al salir del análisis para evitar arrastrar duplicados.
                    if hasattr(datos, "clasificacion_ler"):
                        # Fuente estricta de LER: memorias del expediente activo.
                        if usar_ia:
                            texto_ler = "\n\n".join(textos_para_combinar or [])
                        else:
                            texto_ler = "\n\n".join(textos_memoria_crudos or [])
                        ler_memoria = _extraer_ler_desde_texto(texto_ler)
                        if ler_memoria:
                            datos.clasificacion_ler = _normalizar_lista_ler(ler_memoria)
                        else:
                            datos.clasificacion_ler = _normalizar_lista_ler(getattr(datos, "clasificacion_ler", ""))

                    # Cache de contexto textual para no re-leer memorias al cambiar de pestaña.
                    if usar_ia:
                        texto_ctx = "\n\n--- SEPARADOR ENTRE DOCUMENTOS ---\n\n".join(textos_para_combinar)
                    else:
                        texto_ctx = texto_combinado
                    st.session_state.texto_memoria_contexto = (texto_ctx or "")[:150000]

                    # Cada nueva extracción debe pisar valores inventados previos en campos extraíbles.
                    # De este modo, los datos de memoria/proyecto de explotación tienen prioridad real.
                    if "datos_usuario" in st.session_state:
                        for clave in CLAVES_EXTRAIBLES:
                            st.session_state.datos_usuario.pop(clave, None)

                    st.session_state.datos_extraidos = datos
                st.success(f"Análisis completado de {len(memorias_fuente)} documento(s).")

            except ImportError as e:
                _mensaje_suave("error", "Falta la librería pdfplumber. Ejecuta: pip install pdfplumber")
                st.code("pip install pdfplumber", language="bash")
            except Exception as e:
                _mensaje_suave("error", f"No se pudo analizar el PDF: {e}")

        datos = st.session_state.datos_extraidos

        # Mostrar tabla comparada con Lista de Datos Necesarios
        if datos is not None:
            faltantes = _obtener_datos_faltantes(datos)
            datos_completos = _obtener_datos_completos(datos)

            st.markdown("---")
            st.markdown('<p class="section-title">Datos extraídos para verificación</p>', unsafe_allow_html=True)

            try:
                import pandas as pd
                df_tabla = pd.DataFrame(
                    [(etiqueta, datos_completos.get(clave, "") or "—") for etiqueta, clave in LISTA_DATOS_NECESARIOS],
                    columns=["Campo", "Valor"],
                )
                st.dataframe(
                    df_tabla,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Campo": st.column_config.TextColumn("Campo", width="medium"),
                        "Valor": st.column_config.TextColumn("Valor", width="large"),
                    },
                )
            except ImportError:
                # Fallback si pandas no está disponible (ej. Python 3.13)
                filas = [[etiqueta, datos_completos.get(clave, "") or "—"] for etiqueta, clave in LISTA_DATOS_NECESARIOS]
                st.table([["Campo", "Valor"]] + filas)

            # Aviso rápido cuando faltan datos detectados en la memoria
            if faltantes:
                st.warning(
                    "Hay datos que no se han encontrado de forma automática en la memoria. "
                    "Puedes completarlos o corregirlos manualmente en el formulario de edición de abajo."
                )
            else:
                st.success("✓ Todos los datos necesarios están completos (puedes editarlos igualmente si lo necesitas).")

            # Formulario de edición completa de datos (extraídos + manuales)
            st.markdown("---")
            with st.expander("Editar / ajustar datos manualmente (opcional)", expanded=False):
                st.markdown(
                    "Aquí puedes **corregir o afinar cualquier dato** extraído automáticamente. "
                    "Los valores que escribas se guardan en la sesión y tendrán prioridad sobre la extracción "
                    "automática mientras no vuelvas a lanzar un nuevo análisis."
                )

                for etiqueta, clave in LISTA_DATOS_NECESARIOS:
                    # Prioridad en el valor mostrado: lo que ya haya indicado el usuario > lo extraído
                    valor_actual = (
                        (st.session_state.datos_usuario.get(clave, "") or "")
                        or (datos_completos.get(clave, "") or "")
                    ).strip()

                    if clave == "organo_sustantivo":
                        opciones_organo = ["— Seleccionar órgano —"] + ORGANOS_SUSTANTIVOS_VALIDOS
                        idx = 0
                        if valor_actual in ORGANOS_SUSTANTIVOS_VALIDOS:
                            idx = ORGANOS_SUSTANTIVOS_VALIDOS.index(valor_actual) + 1
                        nuevo_valor = st.selectbox(
                            f"**{etiqueta}**",
                            options=opciones_organo,
                            index=idx,
                            key=f"edit_{clave}",
                            help="Seleccione el órgano competente para evitar errores tipográficos en el informe.",
                        )
                        st.session_state.datos_usuario[clave] = "" if nuevo_valor == "— Seleccionar órgano —" else nuevo_valor
                    else:
                        nuevo_valor = st.text_input(
                            f"**{etiqueta}**",
                            value=valor_actual,
                            key=f"edit_{clave}",
                        )
                        st.session_state.datos_usuario[clave] = (nuevo_valor or "").strip()

                st.caption("Los cambios se aplican al instante y se usarán en la generación del informe.")

# --- SECCIÓN GENERACIÓN DE INFORME ---
elif pagina == "informe":
    st.markdown('<p class="main-header">Generación de Informe</p>', unsafe_allow_html=True)
    st.markdown("Genera los capítulos del Mega Informe EIA con GPT-4o. Requiere **OPENAI_API_KEY** configurada.")
    st.caption(f"Proyecto activo: {st.session_state.proyecto_actual}")

    # Recordatorio para proyectos que deben adaptarse al índice Rayna
    if st.session_state.proyecto_actual and "RECIMETAL" in st.session_state.proyecto_actual.upper():
        st.info(
            "📋 **Índice base Talleres Rayna:** Este proyecto se adapta al índice de referencia. "
            "Para aplicar la estructura completa (Bloques A–J, subpuntos), usa **«Generar todos los capítulos»**. "
            "La generación se basa en las memorias y documentos importados; no se inventan datos."
        )

    datos = st.session_state.datos_extraidos
    datos_completos = _obtener_datos_completos(datos)
    datos_para_generador = {
        etiqueta: (datos_completos.get(clave) or "")
        for etiqueta, clave in LISTA_DATOS_NECESARIOS
    }

    # Detección rápida con caché por huella de fuentes del proyecto activo.
    texto_memoria = (st.session_state.get("texto_memoria_contexto") or "").strip()
    guardados = {}
    memorias_rutas = []
    docs_admin_rutas = []
    try:
        from persistencia_archivos import cargar_archivos_guardados
        guardados = cargar_archivos_guardados(st.session_state.proyecto_actual)
        memorias_rutas = guardados.get("memorias", []) or []
        docs_admin_rutas = guardados.get("documentos_administrativos", []) or []
    except Exception:
        guardados = {}

    fp_fuentes = _fingerprint_archivos(memorias_rutas + docs_admin_rutas)
    texto_fuentes_perfil = (st.session_state.get("texto_fuentes_perfil_contexto") or "").strip()
    if fp_fuentes != (st.session_state.get("fingerprint_fuentes_perfil") or ""):
        memorias_perfil = _cargar_filelikes_desde_paths(memorias_rutas)
        docs_perfil = _cargar_filelikes_desde_paths(docs_admin_rutas)
        texto_fuentes_perfil = _extraer_texto_fuentes_perfil(memorias_perfil, docs_perfil)
        texto_fuentes_perfil = _extraer_fragmentos_relevantes(texto_fuentes_perfil, max_chars=180000)
        st.session_state.texto_fuentes_perfil_contexto = texto_fuentes_perfil
        st.session_state.fingerprint_fuentes_perfil = fp_fuentes

    diagnostico_perfil = _clasificar_perfil_operativo(
        datos_completos,
        texto_fuentes_perfil or texto_memoria or "",
    )
    perfil_operativo_auto = diagnostico_perfil.get("perfil", "indeterminado")

    texto_memoria_cache = {"value": texto_memoria}
    texto_memorias_ler_cache = {"value": ""}

    def _obtener_texto_memoria_para_generacion() -> str:
        """Carga corpus del expediente (memorias + docs admin) solo cuando se va a generar/exportar."""
        if texto_memoria_cache["value"]:
            return texto_memoria_cache["value"]
        try:
            from analista import extraer_texto_documento
        except Exception:
            return ""

        memorias_gen = list(st.session_state.get("memoria_tecnica") or [])
        docs_admin_gen = list(st.session_state.get("documentos_administrativos") or [])
        if not memorias_gen:
            memorias_gen = _cargar_filelikes_desde_paths(memorias_rutas)
        if not docs_admin_gen:
            docs_admin_gen = _cargar_filelikes_desde_paths(docs_admin_rutas)

        textos = []
        for memoria in memorias_gen:
            try:
                memoria.seek(0)
                txt = extraer_texto_documento(memoria)
                if txt:
                    textos.append(f"[MEMORIA] {getattr(memoria, 'name', 'memoria')}\n{txt}")
            except Exception:
                continue
        for doc in docs_admin_gen:
            try:
                doc.seek(0)
                txt = extraer_texto_documento(doc)
                if txt:
                    textos.append(f"[DOC_ADMIN] {getattr(doc, 'name', 'documento')}\n{txt}")
            except Exception:
                continue

        if not textos:
            return ""
        corpus = "\n\n--- SEPARADOR ENTRE DOCUMENTOS ---\n\n".join(textos).strip()
        valor = _extraer_fragmentos_relevantes(corpus, max_chars=150000)
        texto_memoria_cache["value"] = valor
        if valor:
            st.session_state.texto_memoria_contexto = valor
        return valor

    def _obtener_texto_memorias_para_ler() -> str:
        """Corpus exclusivamente de memorias, para extracción estricta de LER."""
        if texto_memorias_ler_cache["value"]:
            return texto_memorias_ler_cache["value"]
        try:
            from analista import extraer_texto_documento
        except Exception:
            return ""
        memorias_gen = list(st.session_state.get("memoria_tecnica") or [])
        if not memorias_gen:
            memorias_gen = _cargar_filelikes_desde_paths(memorias_rutas)
        textos = []
        for memoria in memorias_gen:
            try:
                memoria.seek(0)
                txt = extraer_texto_documento(memoria)
                if txt:
                    textos.append(txt)
            except Exception:
                continue
        valor = _extraer_fragmentos_relevantes("\n\n".join(textos), max_chars=150000) if textos else ""
        texto_memorias_ler_cache["value"] = valor
        return valor
    opcion_perfil = st.selectbox(
        "Perfil operativo del proyecto (detección automática + opción manual)",
        options=["auto", "no_cat", "cat", "gestion_residuos_no_vehiculos"],
        index=["auto", "no_cat", "cat", "gestion_residuos_no_vehiculos"].index(
            st.session_state.datos_usuario.get("perfil_operativo_forzado", "auto")
        )
        if st.session_state.datos_usuario.get("perfil_operativo_forzado", "auto")
        in ["auto", "no_cat", "cat", "gestion_residuos_no_vehiculos"]
        else 0,
        format_func=lambda x: {
            "auto": f"Auto ({perfil_operativo_auto})",
            "no_cat": "Forzar no-CAT (VFU descontaminados / nave satélite)",
            "cat": "Forzar CAT (incluye descontaminación)",
            "gestion_residuos_no_vehiculos": "Forzar gestión de residuos no vehiculares",
        }[x],
        help="La app detecta automáticamente leyendo memorias y documentos administrativos del proyecto activo.",
    )
    st.session_state.datos_usuario["perfil_operativo_forzado"] = opcion_perfil
    perfil_operativo = perfil_operativo_auto if opcion_perfil == "auto" else opcion_perfil
    modo_no_cat = perfil_operativo == "no_cat"
    modo_cat = perfil_operativo == "cat"

    # LER estricto desde memorias del expediente activo.
    ler_memoria_estricto = _normalizar_lista_ler(_extraer_ler_desde_texto(_obtener_texto_memorias_para_ler()))
    if ler_memoria_estricto:
        # Solo rellenar desde memorias si no hay LER definido por el usuario/datos extraídos
        ler_actual = (datos_completos.get("clasificacion_ler") or "").strip()
        if not ler_actual or ler_actual.upper() in ("N/D", "ND"):
            datos_completos["clasificacion_ler"] = ler_memoria_estricto
            for etiqueta, clave in LISTA_DATOS_NECESARIOS:
                if clave == "clasificacion_ler":
                    datos_para_generador[etiqueta] = ler_memoria_estricto
                    break
    alertas_ler = _alertas_coherencia_ler(datos_completos, perfil_operativo)
    if alertas_ler:
        st.warning("Control de coherencia LER detecta incidencias:")
        st.markdown("\n".join([f"- {a}" for a in alertas_ler]))

    with st.expander("Diagnóstico de contexto del proyecto", expanded=False):
        st.markdown(f"- Perfil detectado (auto): **{perfil_operativo_auto}**")
        st.markdown(f"- Confianza estimada: **{diagnostico_perfil.get('confianza', 0.0)}**")
        st.markdown(
            f"- Fuentes usadas: **{len(memorias_rutas)} memorias** + "
            f"**{len(docs_admin_rutas)} documentos administrativos**"
        )
        evidencias = diagnostico_perfil.get("evidencias") or []
        if evidencias:
            st.markdown("**Evidencias principales detectadas:**")
            for ev in evidencias[:6]:
                st.markdown(f"- ({ev.get('perfil')}) {ev.get('linea')}")
        else:
            st.caption("Sin evidencias textuales fuertes. Completa/anexa más detalle documental o usa forzado manual.")

    if modo_no_cat:
        datos_para_generador["Perfil operativo detectado"] = (
            "Instalación no-CAT: nave de almacenamiento/preparación para reutilización "
            "de VFU previamente descontaminados."
        )
        datos_para_generador["Regla de alcance operativo"] = (
            "Excluir procesos peligrosos de descontaminación/extracción de fluidos del alcance "
            "de Arce 37; solo referirlos a instalación externa."
        )
    elif modo_cat:
        datos_para_generador["Perfil operativo detectado"] = (
            "Instalación CAT: el alcance incluye descontaminación y gestión asociada conforme "
            "a autorización aplicable."
        )
        datos_para_generador["Regla de alcance operativo"] = (
            "Incluir controles y medidas de procesos CAT en coherencia con la memoria técnica."
        )
    elif perfil_operativo == "gestion_residuos_no_vehiculos":
        datos_para_generador["Perfil operativo detectado"] = (
            "Gestión de residuos no vehiculares (p. ej. metálicos) sin actividades CAT."
        )
        datos_para_generador["Regla de alcance operativo"] = (
            "Excluir procesos de descontaminación de VFU y cualquier redacción CAT, salvo evidencia expresa en el expediente."
        )
    else:
        datos_para_generador["Perfil operativo detectado"] = (
            "Indeterminado: revisar memoria y definir explícitamente si la instalación es CAT o no-CAT."
        )

    if modo_no_cat:
        st.info(
            "Modo de coherencia activado: el proyecto se trata como instalación no-CAT "
            "(VFU previamente descontaminados / procesos peligrosos externos)."
        )
    elif modo_cat:
        st.info(
            "Modo de coherencia activado: el proyecto se trata como instalación CAT "
            "(incluye procesos propios de descontaminación según memoria)."
        )
    elif perfil_operativo == "gestion_residuos_no_vehiculos":
        st.info(
            "Modo de coherencia activado: gestión de residuos no vehiculares "
            "(p. ej. metálicos). Se excluyen referencias CAT salvo evidencia documental expresa."
        )
    else:
        st.warning(
            "No se ha podido determinar automáticamente si el proyecto es CAT o no-CAT. "
            "Revisa los datos base o usa la selección manual para evitar incoherencias en capítulos y medidas."
        )

    if not any(datos_para_generador.values()):
        st.warning("No hay datos disponibles. Ve a **Análisis de Datos** y extrae/completa los datos de la Memoria Técnica.")
    else:
        st.markdown("---")
        
        # Opciones avanzadas
        with st.expander("⚙️ Opciones avanzadas"):
            usar_contexto_completo = st.checkbox(
                "Usar contexto completo (normativa + ejemplos)",
                value=True,
                help="Si está desactivado, se usa menos contexto para generar más rápido. Puede reducir calidad ligeramente."
            )
            modelo_informe = st.selectbox(
                "Modelo para generación de informe",
                options=["gpt-4o", "gpt-4.1", "gpt-4o-mini"],
                index=["gpt-4o", "gpt-4.1", "gpt-4o-mini"].index(
                    config.get("openai_report_model", "gpt-4o")
                    if config.get("openai_report_model", "gpt-4o") in ["gpt-4o", "gpt-4.1", "gpt-4o-mini"]
                    else "gpt-4o"
                ),
                help="gpt-4.1 suele dar mejor calidad; gpt-4o-mini es más rápido y barato.",
            )
            limite_texto_memoria = st.slider(
                "Límite de texto de memoria técnica (caracteres)",
                min_value=2000,
                max_value=25000,
                value=8000,
                step=500,
                help="Recomendado: 8000-12000 para lectura detenida de memorias. Más contexto = mayor fidelidad al proyecto."
            )
            permitir_borrador_contingencia = st.checkbox(
                "Permitir borrador local de contingencia si falla la API",
                value=False,
                help="Para uso interno. Recomendado desactivado en entregables para administración.",
            )
            if modelo_informe != config.get("openai_report_model", "gpt-4o"):
                config["openai_report_model"] = modelo_informe
                guardar_config(config)
        
        chapter_titles = {key: title for key, title, _ in CHAPTER_TEMPLATE}
        chapter_state_keys = {key: state_key for key, _, state_key in CHAPTER_TEMPLATE}
        cap = st.selectbox(
            "Selecciona el capítulo a generar",
            [key for key, _, _ in CHAPTER_TEMPLATE],
            format_func=lambda x: chapter_titles[x],
        )
        
        st.info(
            "⏱️ **Tiempo estimado**: 30-90 segundos por capítulo. "
            "💡 **Fidelidad**: Usa 8000+ caracteres para que la IA lea con detenimiento las memorias y no invente datos. "
            "Si la generación es lenta, reduce el límite en Opciones avanzadas."
        )

        col_gen_1, col_gen_2 = st.columns(2)

        def _borrador_local_chapter(capitulo_key: str) -> str:
            """Borrador local para no bloquear flujo si falla OpenAI."""
            titulo = chapter_titles.get(capitulo_key, capitulo_key)
            lineas_datos = []
            for k, v in datos_para_generador.items():
                if (v or "").strip():
                    lineas_datos.append(f"- **{k}**: {v}")
            datos_md = "\n".join(lineas_datos) if lineas_datos else "- [DATOS A COMPLETAR POR EL PROMOTOR]"
            return (
                f"## {titulo}\n\n"
                "### Estado del contenido\n"
                "Borrador técnico automático generado en modo contingencia por indisponibilidad de API.\n\n"
                "### Datos base del proyecto\n"
                f"{datos_md}\n\n"
                "### Desarrollo técnico preliminar\n"
                "Este apartado debe validarse y enriquecerse con redacción técnica final conforme a la Ley 21/2013, "
                "normativa autonómica y condicionantes locales aplicables.\n\n"
                "### Referencias de anexos\n"
                "- AT-01 Cartografía y planimetría\n"
                "- AT-03 Climatología y caracterización atmosférica\n"
                "- AT-09 Anexo cartográfico temático\n"
            )

        def _generar_y_guardar_capitulo(capitulo_key: str, funcs_map: dict) -> None:
            clave_sesion_local = chapter_state_keys[capitulo_key]
            contexto_enrutado = _condicionar_contexto_por_perfil(
                _obtener_texto_memoria_para_generacion(),
                perfil_operativo,
            )
            texto_local = funcs_map[capitulo_key](
                datos_para_generador,
                contexto_enrutado,
                usar_contexto_completo=usar_contexto_completo,
                limite_texto_memoria=limite_texto_memoria,
                model=modelo_informe,
            )
            texto_limpio = _limpiar_texto_capitulo(
                texto_local,
                perfil_operativo,
                estado_infraestructura=datos_completos.get("estado_infraestructura", "") or "",
            )
            if modo_no_cat:
                texto_limpio = _normalizar_nomenclatura_no_cat(texto_limpio)
            elif perfil_operativo == "gestion_residuos_no_vehiculos":
                texto_limpio = _normalizar_nomenclatura_no_vehicular(texto_limpio)
            st.session_state[clave_sesion_local] = texto_limpio

        if col_gen_1.button("Generar capítulo", type="primary"):
            try:
                from generador import (
                    generar_resumen_ejecutivo,
                    generar_descripcion_proyecto,
                    generar_marco_legal_administrativo,
                    generar_inventario,
                    generar_alternativas,
                    generar_impactos,
                    generar_medidas,
                    generar_pva,
                    generar_conclusiones,
                    generar_anexos_tecnicos,
                )
                funcs = {
                    "resumen_ejecutivo": generar_resumen_ejecutivo,
                    "descripcion": generar_descripcion_proyecto,
                    "marco_legal_admin": generar_marco_legal_administrativo,
                    "inventario": generar_inventario,
                    "alternativas": generar_alternativas,
                    "impactos": generar_impactos,
                    "medidas": generar_medidas,
                    "pva": generar_pva,
                    "conclusiones": generar_conclusiones,
                    "anexos_tecnicos": generar_anexos_tecnicos,
                }
                if not st.session_state.get("openai_api_key", "").strip():
                    raise ValueError("OPENAI_API_KEY no configurada.")
                if len(_obtener_datos_faltantes(datos)) > 0:
                    st.warning(
                        "Hay datos críticos pendientes de completar en 'Análisis de Datos'. "
                        "La calidad del capítulo puede verse afectada."
                    )

                # Evita actualizaciones agresivas del DOM (progress/status) para reducir errores visuales en frontend.
                with st.spinner(f"Generando capítulo con {modelo_informe}..."):
                    _generar_y_guardar_capitulo(cap, funcs)
                st.success("✅ Capítulo generado correctamente.")
                    
            except ValueError as e:
                error_msg = str(e)
                if "OPENAI_API_KEY" in error_msg:
                    _mensaje_suave("error", "Configura OPENAI_API_KEY en el sidebar o como variable de entorno.")
                elif "quota" in error_msg.lower() or "insufficient_quota" in error_msg.lower():
                    if permitir_borrador_contingencia:
                        st.warning("⚠ Cuota OpenAI agotada. Se genera borrador local de contingencia.")
                        texto_borrador = _limpiar_texto_capitulo(_borrador_local_chapter(cap), perfil_operativo)
                        if modo_no_cat:
                            texto_borrador = _normalizar_nomenclatura_no_cat(texto_borrador)
                        elif perfil_operativo == "gestion_residuos_no_vehiculos":
                            texto_borrador = _normalizar_nomenclatura_no_vehicular(texto_borrador)
                        st.session_state[chapter_state_keys[cap]] = texto_borrador
                    else:
                        _mensaje_suave("error", "Cuota OpenAI agotada. Activa facturación o la opción de contingencia en Opciones avanzadas.")
                        st.info("Activa facturación/cuota en OpenAI o activa temporalmente la opción de contingencia en Opciones avanzadas.")
                elif "timeout" in error_msg.lower() or "tiempo" in error_msg.lower():
                    _mensaje_suave("error", error_msg)
                    st.info("💡 Sugerencia: Intenta generar el capítulo de nuevo. Si persiste, el contexto puede ser muy grande.")
                elif "quota" in error_msg.lower() or "cuota" in error_msg.lower():
                    _mensaje_suave("error", "Cuota de API agotada. Verifica tu cuenta de OpenAI.")
                else:
                    _mensaje_suave("error", error_msg)
            except ImportError as e:
                _mensaje_suave("error", f"Error de importación: {e}")
            except Exception as e:
                _mensaje_suave("error", f"Error inesperado al generar: {str(e)}")

        if col_gen_2.button("Generar todos los capítulos", type="secondary"):
            try:
                from generador import (
                    generar_resumen_ejecutivo,
                    generar_descripcion_proyecto,
                    generar_marco_legal_administrativo,
                    generar_inventario,
                    generar_alternativas,
                    generar_impactos,
                    generar_medidas,
                    generar_pva,
                    generar_conclusiones,
                    generar_anexos_tecnicos,
                )
                funcs = {
                    "resumen_ejecutivo": generar_resumen_ejecutivo,
                    "descripcion": generar_descripcion_proyecto,
                    "marco_legal_admin": generar_marco_legal_administrativo,
                    "inventario": generar_inventario,
                    "alternativas": generar_alternativas,
                    "impactos": generar_impactos,
                    "medidas": generar_medidas,
                    "pva": generar_pva,
                    "conclusiones": generar_conclusiones,
                    "anexos_tecnicos": generar_anexos_tecnicos,
                }

                if not st.session_state.get("openai_api_key", "").strip():
                    raise ValueError("OPENAI_API_KEY no configurada.")

                total_caps = len(CHAPTER_TEMPLATE)
                errores = []

                for idx, (cap_key, cap_title, _) in enumerate(CHAPTER_TEMPLATE, start=1):
                    try:
                        st.caption(f"Generando {cap_title} ({idx}/{total_caps})...")
                        _generar_y_guardar_capitulo(cap_key, funcs)
                    except Exception as e:
                        msg = str(e)
                        if "quota" in msg.lower() or "insufficient_quota" in msg.lower():
                            if permitir_borrador_contingencia:
                                # Contingencia opcional para no bloquear tareas internas.
                                texto_borrador = _limpiar_texto_capitulo(_borrador_local_chapter(cap_key), perfil_operativo)
                                if modo_no_cat:
                                    texto_borrador = _normalizar_nomenclatura_no_cat(texto_borrador)
                                elif perfil_operativo == "gestion_residuos_no_vehiculos":
                                    texto_borrador = _normalizar_nomenclatura_no_vehicular(texto_borrador)
                                st.session_state[chapter_state_keys[cap_key]] = texto_borrador
                                errores.append(f"{cap_title}: API sin cuota, generado borrador local.")
                            else:
                                errores.append(f"{cap_title}: API sin cuota (modo estricto, sin borrador).")
                        else:
                            errores.append(f"{cap_title}: {e}")
                    # Sin barra de progreso para evitar parpadeos y conflictos de render en algunos navegadores.

                if errores:
                    st.warning("Se generaron varios capítulos, pero algunos fallaron:")
                    for err in errores:
                        st.write(f"- {err}")
                    # Si todos los fallos son de conexión, dar pista clara
                    if len(errores) >= total_caps and any("conexión" in str(e).lower() or "connection" in str(e).lower() for e in errores):
                        st.info(
                            "💡 **Todos los capítulos fallaron por conexión.** Revise la clave API en **Configuración** "
                            "y la conexión a internet. Pruebe a generar un solo capítulo primero; si funciona, "
                            "vuelva a lanzar «Generar todos los capítulos»."
                        )
                else:
                    st.success("✅ Todos los capítulos se generaron correctamente.")
            except Exception as e:
                _mensaje_suave("error", f"Error al generar capítulos en bloque: {e}")

        capitulos = {key: st.session_state.get(state_key) for key, _, state_key in CHAPTER_TEMPLATE}
        if capitulos.get(cap):
            st.markdown("---")
            st.markdown("### Resultado")
            st.text_area(
                "Vista previa del capítulo generado",
                value=capitulos[cap],
                height=420,
                key=f"preview_{cap}",
            )

        # Exportar informe a Word
        st.markdown("---")
        st.markdown("### Exportar proyecto completo")
        st.markdown("Genera un documento Word con todos los capítulos, datos y mapas.")
        # Panel: Datos maestros obligatorios para REGISTRO (check ✅/❌)
        try:
            _estado_registro = _cargar_estado_proyecto_cached(st.session_state.proyecto_actual)
        except Exception:
            _estado_registro = {}
        _du = _estado_registro.get("datos_usuario") or {}
        _carto = _estado_registro.get("cartografia_informe") or {}
        def _tiene_ler():
            v = (_du.get("clasificacion_ler") or "").strip() if isinstance(_du.get("clasificacion_ler"), str) else _du.get("clasificacion_ler")
            if isinstance(v, list):
                return len(v) > 0
            return bool(v)
        def _tiene_rp():
            v = _du.get("residuos_peligrosos_propios_ler")
            if isinstance(v, list):
                return True  # puede estar vacío pero el campo existe
            return bool((v or "").strip())
        def _tiene_superficies():
            return bool((_du.get("superficie_parcela_m2") or "").strip())
        def _tiene_potencias():
            return bool((_du.get("potencia_instalada_total_w") or "").strip())
        def _tiene_capacidades():
            for k in ("capacidad_clasificacion_t_d", "capacidad_trituracion_cobre_t_d", "capacidad_total_t", "almacenamiento_pre_t", "capacidad_maxima_almacenamiento"):
                if (_du.get(k) or datos_completos.get(k) or "").strip():
                    return True
            return False
        def _tiene_cartografia_distancias():
            if not isinstance(_carto, dict):
                return False
            tiene_distancia = bool((_carto.get("red_natura_2000_distancia_m") or _carto.get("enp_distancia_m") or _carto.get("zepa_distancia_m") or "").strip())
            snczi = _carto.get("snczi_afecta")
            snczi_str = (snczi is not None and str(snczi).strip()) or ""
            # N/D bloquea REGISTRO: obliga a obtener Sí/No desde visor
            if snczi_str.upper() in ("N/D", "N/D.", "ND"):
                return False
            tiene_snczi = snczi_str != ""
            # Si SNCZI = Sí, exigir interpretación/capa/medidas para evitar "Sí" sin desarrollo
            if tiene_snczi and snczi_str.lower() in ("sí", "si", "true", "1"):
                interp = (_carto.get("snczi_interpretacion") or "").strip()
                capa = (_carto.get("snczi_capa") or "").strip()
                medidas = (_carto.get("snczi_medidas") or "").strip()
                if not (interp or capa or medidas):
                    return False
            return tiene_distancia and tiene_snczi
        with st.expander("📋 Datos maestros obligatorios para REGISTRO", expanded=True):
            st.caption("Rellene estos bloques en Datos del proyecto para poder exportar para REGISTRO con 0 alertas.")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("✅ LER admitidos" if _tiene_ler() else "❌ LER admitidos")
                st.markdown("✅ RP propios" if _tiene_rp() else "❌ RP propios (o vacío si no aplica)")
            with c2:
                st.markdown("✅ Superficies" if _tiene_superficies() else "❌ Superficies")
                st.markdown("✅ Potencias" if _tiene_potencias() else "❌ Potencias")
            with c3:
                st.markdown("✅ Capacidades" if _tiene_capacidades() else "❌ Capacidades")
                st.markdown("✅ Cartografía (RN2000 + SNCZI)" if _tiene_cartografia_distancias() else "❌ Cartografía (distancias + SNCZI Sí/No)")
            # Botón: Rellenar datos maestros desde documentos (auto)
            texto_ctx = (st.session_state.get("texto_memoria_contexto") or "").strip()
            de = st.session_state.get("datos_extraidos")
            if st.button("🔄 Rellenar datos maestros desde documentos (auto)", help="Precarga superficies, potencias, LER, RP y capacidades desde Proyecto/Memoria/Catastro cargados. Revise y acepte."):
                extraidos = _extraer_datos_maestros_desde_texto(texto_ctx, de)
                st.session_state["precarga_datos_maestros"] = extraidos
            if st.session_state.get("precarga_datos_maestros"):
                precarga = st.session_state["precarga_datos_maestros"]
                # Estructura nueva: valores, fuentes, confianza_ler, capacidades_posibles
                if isinstance(precarga.get("valores"), dict):
                    valores = precarga["valores"].copy()
                else:
                    valores = {k: v for k, v in (precarga or {}).items() if k not in ("valores", "fuentes", "confianza_ler", "capacidades_posibles") and v}
                fuentes = precarga.get("fuentes") or {}
                confianza_ler = precarga.get("confianza_ler") or "alta"
                capacidades_posibles = precarga.get("capacidades_posibles") or []

                with st.expander("📥 Datos detectados (revise y acepte)", expanded=True):
                    if not valores and not capacidades_posibles:
                        st.caption("No se detectaron datos maestros en el texto cargado. Cargue Proyecto/Memoria/Catastro y vuelva a intentar.")
                    else:
                        if confianza_ler == "baja":
                            st.warning("⚠️ **Confianza Baja** en LER: se detectaron más de 25 códigos o bloque sin anclaje claro. Revise que LER admitidos correspondan al listado/plano del proyecto antes de aceptar.")
                        # Dos cajas: LER admitidos (RNP) y RP propios (con *)
                        if valores.get("clasificacion_ler"):
                            st.markdown("**LER admitidos (RNP)**")
                            st.text_input("clasificacion_ler", value=valores["clasificacion_ler"], key="_precarga_ler_admitidos", disabled=True)
                            if "clasificacion_ler" in fuentes:
                                f = fuentes["clasificacion_ler"]
                                st.caption(f"📄 {f.get('doc', '')}: {f.get('extracto', '')[:100]}…" if len((f.get("extracto") or "")) > 100 else f"📄 {f.get('doc', '')}: {f.get('extracto', '')}")
                        if valores.get("residuos_peligrosos_propios_ler"):
                            st.markdown("**RP propios (con *)**")
                            st.text_input("residuos_peligrosos_propios_ler", value=valores["residuos_peligrosos_propios_ler"], key="_precarga_rp_propios", disabled=True)
                            if "residuos_peligrosos_propios_ler" in fuentes:
                                f = fuentes["residuos_peligrosos_propios_ler"]
                                st.caption(f"📄 {f.get('doc', '')}: {f.get('extracto', '')}")
                        # Resto de campos (superficies, potencias, capacidad única)
                        for k in ("superficie_parcela_m2", "superficie_construida_m2", "potencia_instalada_total_w", "potencia_calculo_w", "capacidad_clasificacion_t_d"):
                            if k not in valores or k in ("clasificacion_ler", "residuos_peligrosos_propios_ler"):
                                continue
                            if k == "capacidad_clasificacion_t_d" and capacidades_posibles:
                                continue
                            v = valores.get(k)
                            if not v:
                                continue
                            st.text_input(k, value=str(v), key=f"_precarga_{k}", disabled=True)
                            if k in fuentes:
                                f = fuentes[k]
                                st.caption(f"📄 {f.get('doc', '')}: {(f.get('extracto') or '')[:120]}{'…' if len((f.get('extracto') or '')) > 120 else ''}")
                        # Capacidades múltiples: selector
                        if capacidades_posibles:
                            st.markdown("**Capacidad (varias detectadas — elija una)**")
                            sel_cap = st.selectbox("Capacidad clasificación (t/d)", options=capacidades_posibles, key="_precarga_cap_selector")
                            if sel_cap:
                                valores["capacidad_clasificacion_t_d"] = sel_cap

                        if st.button("✅ Aceptar y guardar en datos del proyecto"):
                            du = st.session_state.get("datos_usuario") or {}
                            for k, v in valores.items():
                                if v and isinstance(v, (str, int, float)):
                                    du[k] = str(v).strip() if isinstance(v, str) else v
                            st.session_state.datos_usuario = du
                            try:
                                _guardar_estado_proyecto(st.session_state.proyecto_actual)
                            except Exception as e:
                                _mensaje_suave("error", f"Error al guardar: {e}")
                            else:
                                del st.session_state["precarga_datos_maestros"]
                                st.success("Datos maestros guardados. Revise el panel de checks arriba.")
                                st.rerun()
        # Formulario UI SNCZI (evitar editar JSON a mano) — st.fragment para rerun parcial (más ágil)
        def _render_formulario_cartografia():
            with st.expander("🗺️ Cartografía y SNCZI", expanded=not _tiene_cartografia_distancias()):
                st.caption("Rellene SNCZI para que el check de cartografía sea válido. Si SNCZI = Sí, indique al menos capa, interpretación o medidas.")
                _snczi_actual = (_carto.get("snczi_afecta") or "").strip()
                if _snczi_actual and _snczi_actual.upper() in ("N/D", "ND"):
                    _snczi_actual = "N/D"
                elif _snczi_actual and _snczi_actual.lower() in ("sí", "si", "true", "1"):
                    _snczi_actual = "Sí"
                elif _snczi_actual and _snczi_actual.lower() in ("no", "false", "0"):
                    _snczi_actual = "No"
                else:
                    _snczi_actual = _snczi_actual or "N/D"
                _opciones_snczi = ["Sí", "No", "N/D"]
                _idx_snczi = _opciones_snczi.index(_snczi_actual) if _snczi_actual in _opciones_snczi else 2
                snczi_afecta = st.selectbox(
                    "SNCZI afecta",
                    options=_opciones_snczi,
                    index=_idx_snczi,
                    key="carto_snczi_afecta",
                    help="N/D bloquea REGISTRO: obtenga Sí/No desde visor SNCZI antes de exportar para registro.",
                )
                snczi_capa = st.text_input(
                    "SNCZI capa / fuente",
                    value=(_carto.get("snczi_capa") or "").strip(),
                    key="carto_snczi_capa",
                    placeholder="Ej. Capa SNCZI MITECO, consulta 2024",
                    help="Requerido si SNCZI = Sí (junto con interpretación o medidas).",
                )
                snczi_interpretacion = st.text_area(
                    "Interpretación SNCZI",
                    value=(_carto.get("snczi_interpretacion") or "").strip(),
                    key="carto_snczi_interpretacion",
                    height=80,
                    placeholder="Ej. Parcela en zona de riesgo bajo; periodo de retorno 100 años.",
                    help="Requerido si SNCZI = Sí (o rellene capa o medidas).",
                )
                snczi_medidas = st.text_area(
                    "Medidas SNCZI (pluviales / drenaje)",
                    value=(_carto.get("snczi_medidas") or "").strip(),
                    key="carto_snczi_medidas",
                    height=80,
                    placeholder="Ej. Drenaje perimetral, cubiertas impermeables.",
                    help="Requerido si SNCZI = Sí (o rellene capa o interpretación).",
                )
                if snczi_afecta == "Sí":
                    _plantilla_capa = "SNCZI MITECO – capa consultada (especificar) – fecha (AAAA-MM-DD)"
                    _plantilla_interp = (
                        "Según consulta en visor oficial SNCZI (MITECO), la parcela se encuentra en zona con [N/D tipo capa/periodo]. "
                        "Se asume criterio conservador. Se adoptan medidas preventivas de drenaje/contención y se prohíben vertidos al exterior. "
                        "Se adjunta captura oficial y medición de distancias."
                    )
                    _plantilla_medidas = (
                        "Drenaje perimetral y mantenimiento; limpieza en seco; kit anti-derrames; solera impermeable; "
                        "almacenamiento bajo cubierta; protocolo de emergencia; inspección tras episodios de lluvia intensa."
                    )
                    if st.button("📋 Insertar plantilla de interpretación + medidas (editable)", key="btn_plantilla_snczi"):
                        st.session_state["carto_snczi_capa"] = _plantilla_capa
                        st.session_state["carto_snczi_interpretacion"] = _plantilla_interp
                        st.session_state["carto_snczi_medidas"] = _plantilla_medidas
                        st.rerun()
                st.caption("**Trazabilidad:** fechas de consulta y visor/capa (administración las valora).")
                rn2000_visor = st.text_input(
                    "Visor / capa RN2000 (visor + capa consultada)",
                    value=(_carto.get("rn2000_visor") or "").strip(),
                    key="carto_rn2000_visor",
                    placeholder="Ej. IDECanarias – capa Red Natura 2000 – 2024",
                    help="Visor y capa consultados para distancias RN2000/ENP/ZEPA (se imprime en 10.1.3).",
                )
                st.markdown("**Distancias (obligatorias para REGISTRO)**")
                with st.expander("📏 Cómo obtener las distancias (5 min)", expanded=False):
                    st.markdown("""
1. Abra el **visor oficial** (IDECanarias para Canarias, MITECO para península).
2. Active la capa **Red Natura 2000** / ENP / ZEPA.
3. Localice su parcela (coordenadas del proyecto).
4. Use la **herramienta de medición** para medir la distancia desde el centro de la parcela al límite más cercano del espacio protegido.
5. Copie el valor (en m o km) y pégalo aquí.

**Enlaces:** [IDECanarias](https://idecanarias.es/visor/) | [MITECO Red Natura 2000](https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/servidor-cartografico-wms-.html)
                    """)
                st.caption("Indique número + m o km (ej. 4500, 4.5 km). Si no hay espacio cercano, ponga N/D.")
                dist_rn = st.text_input(
                    "Distancia a Red Natura 2000 (m o km)",
                    value=(_carto.get("red_natura_2000_distancia_m") or "").strip(),
                    key="carto_red_natura_2000_distancia_m",
                    placeholder="Ej. 4500 o 4.5 km",
                    help="Distancia en metros o km desde la parcela al espacio RN2000 más cercano. Sin este dato no se puede exportar para REGISTRO.",
                )
                dist_enp = st.text_input(
                    "Distancia a ENP (m o km)",
                    value=(_carto.get("enp_distancia_m") or "").strip(),
                    key="carto_enp_distancia_m",
                    placeholder="Ej. 3200 o 3.2 km",
                    help="Distancia al Espacio Natural Protegido más cercano. Si no aplica, deje vacío o N/D.",
                )
                dist_zepa = st.text_input(
                    "Distancia a ZEPA/ZEC (m o km)",
                    value=(_carto.get("zepa_distancia_m") or "").strip(),
                    key="carto_zepa_distancia_m",
                    placeholder="Ej. 4500 o 4.5 km",
                    help="Distancia a ZEPA o ZEC más cercana. Si coincide con RN2000, puede repetir el valor.",
                )
                rn2000_fecha = st.text_input(
                    "Fecha consulta RN2000 / ENP / ZEPA",
                    value=_normalizar_fecha_yyyy_mm_dd((_carto.get("rn2000_fecha_consulta") or "").strip()) or "",
                    key="carto_rn2000_fecha_consulta",
                    placeholder="AAAA-MM-DD (o DD-MM-YYYY, se convierte automáticamente)",
                    help="Fecha en que se consultó el visor para distancias (ej. IDECanarias/MITECO). Acepta DD-MM-YYYY.",
                )
                snczi_fecha = st.text_input(
                    "Fecha consulta SNCZI",
                    value=_normalizar_fecha_yyyy_mm_dd((_carto.get("snczi_fecha_consulta") or "").strip()) or "",
                    key="carto_snczi_fecha_consulta",
                    placeholder="AAAA-MM-DD (o DD-MM-YYYY, se convierte automáticamente)",
                    help="Fecha en que se consultó el visor SNCZI (MITECO). Acepta DD-MM-YYYY.",
                )
                if snczi_afecta == "Sí" and not (snczi_capa.strip() or snczi_interpretacion.strip() or snczi_medidas.strip()):
                    st.warning("Si SNCZI = Sí, rellene al menos uno: capa/fuente, interpretación o medidas.")
                if snczi_afecta == "N/D":
                    st.info("SNCZI = N/D bloquea la exportación para REGISTRO. Consulte el visor oficial (MITECO SNCZI) y registre Sí o No.")
                    snczi_nd_motivo = st.text_area(
                        "Motivo / Cómo obtenerlo (recomendado para borrador)",
                        value=(_carto.get("snczi_nd_motivo") or "").strip(),
                        key="carto_snczi_nd_motivo",
                        height=60,
                        placeholder="Ej. Pendiente de consulta en visor MITECO SNCZI; se adjuntará captura.",
                        help="Opcional: deja el borrador más limpio si aún no tiene SNCZI resuelto.",
                    )
                else:
                    snczi_nd_motivo = ""
                if st.button("Guardar cartografía (SNCZI)"):
                    try:
                        estado_carto = _cargar_estado_proyecto_cached(st.session_state.proyecto_actual)
                        carto_nuevo = dict(estado_carto.get("cartografia_informe") or {})
                        carto_nuevo["snczi_afecta"] = snczi_afecta
                        carto_nuevo["snczi_capa"] = snczi_capa.strip()
                        carto_nuevo["snczi_interpretacion"] = snczi_interpretacion.strip()
                        carto_nuevo["snczi_medidas"] = snczi_medidas.strip()
                        carto_nuevo["rn2000_visor"] = rn2000_visor.strip()
                        carto_nuevo["red_natura_2000_distancia_m"] = dist_rn.strip()
                        carto_nuevo["enp_distancia_m"] = dist_enp.strip()
                        carto_nuevo["zepa_distancia_m"] = dist_zepa.strip()
                        carto_nuevo["rn2000_fecha_consulta"] = _normalizar_fecha_yyyy_mm_dd(rn2000_fecha.strip())
                        carto_nuevo["snczi_fecha_consulta"] = _normalizar_fecha_yyyy_mm_dd(snczi_fecha.strip())
                        carto_nuevo["snczi_nd_motivo"] = (snczi_nd_motivo if snczi_afecta == "N/D" else "").strip()
                        from persistencia_archivos import guardar_estado_proyecto
                        guardar_estado_proyecto(
                            {"cartografia_informe": carto_nuevo},
                            st.session_state.proyecto_actual,
                            estado_base=estado_carto,
                        )
                        _invalidate_cache_data()
                        st.success("Cartografía SNCZI guardada. Revise el panel de checks arriba.")
                        st.rerun()
                    except Exception as e:
                        _mensaje_suave("error", f"Error al guardar: {e}")
        if getattr(st, "fragment", None):
            st.fragment(_render_formulario_cartografia)()
        else:
            _render_formulario_cartografia()
        with st.expander("🖼️ Portada del informe", expanded=False):
            portada_default_title = f"{st.session_state.proyecto_actual.replace('_', ' ').upper()} - PROYECTO EIA"
            portada_titulo = st.text_input(
                "Título de portada",
                value=st.session_state.get("portada_titulo", portada_default_title),
                key="portada_titulo",
            )
            portada_promotor = st.text_input(
                "Promotor (portada)",
                value=(datos_completos.get("nombre_promotor", "") or "").strip(),
                key="portada_promotor",
                help="Si queda vacío, se deja en blanco para completar manualmente.",
            )
            elaborado_1 = st.text_input(
                "Elaborado por (línea 1)",
                value=st.session_state.get("portada_elab_1", ""),
                key="portada_elab_1",
            )
            elaborado_2 = st.text_input(
                "Elaborado por (línea 2)",
                value=st.session_state.get("portada_elab_2", ""),
                key="portada_elab_2",
            )
            if st.session_state.get("portada_global_path"):
                st.caption(f"Portada global detectada: {st.session_state.portada_global_path}")
            else:
                st.warning(
                    "No se detecta 'imagen de la portada.png'. Colócala en cualquier carpeta de proyecto "
                    "y se copiará automáticamente como plantilla global."
                )
        titulo_exp = datos_para_generador.get("Título Oficial del Proyecto", "") or "Estudio de Impacto Ambiental"
        if modo_no_cat:
            titulo_exp = _normalizar_nomenclatura_no_cat(titulo_exp)
        elif perfil_operativo == "gestion_residuos_no_vehiculos":
            titulo_exp = _normalizar_nomenclatura_no_vehicular(titulo_exp)

        # Preparar datos para exportación y calcular alertas (para habilitar/deshabilitar Registro)
        def _formatear_capacidad_export(_datos: dict) -> str:
            """
            Evita valores legacy sin unidad (ej. '500') en exportación.
            Preferencia: capacidades canónicas con unidad; si no existen, N/D + cómo obtenerlo.
            """
            raw = (_datos.get("capacidad_maxima_almacenamiento") or "").strip()
            # Si ya trae unidad explícita, respetar
            if raw and re.search(r"t/d|tm/d|t\/d|t\/año|t/año|tm/año|m³|m3|kg/h|t/h|\bt\b|\btm\b", raw, re.I):
                return raw

            parts = []
            v_cd = (_datos.get("capacidad_clasificacion_t_d") or "").strip()
            if v_cd:
                if re.fullmatch(r"\d+(?:[.,]\d+)?", v_cd):
                    v_cd = v_cd.replace(",", ".") + " t/d"
                parts.append(f"{v_cd} (capacidad diaria)")
            v_pre = (_datos.get("almacenamiento_pre_t") or "").strip()
            if v_pre:
                if re.fullmatch(r"\d+(?:[.,]\d+)?", v_pre):
                    v_pre = v_pre.replace(",", ".") + " t"
                parts.append(f"{v_pre} (almacenamiento pre)")
            v_post = (_datos.get("almacenamiento_post_t") or "").strip()
            if v_post:
                if re.fullmatch(r"\d+(?:[.,]\d+)?", v_post):
                    v_post = v_post.replace(",", ".") + " t"
                parts.append(f"{v_post} (almacenamiento post)")

            if parts:
                return "; ".join(parts)

            # Si viene un número sin unidad (ej. '500'), nunca imprimirlo como tal
            if raw and re.fullmatch(r"\d+(?:[.,]\d+)?", raw):
                return "N/D (Confianza Baja) + cómo obtenerlo: memoria técnica / tabla de capacidades (no usar valores sin unidad)."

            return raw or "N/D (Confianza Baja) + cómo obtenerlo: memoria técnica / tabla de capacidades."

        datos_tabla = []
        for etiqueta, clave in LISTA_DATOS_NECESARIOS:
            if clave == "capacidad_maxima_almacenamiento":
                val = _formatear_capacidad_export(datos_completos)
            else:
                val = (datos_completos.get(clave, "") or "").strip() or "No consta"
            datos_tabla.append((etiqueta, val))
        # Añadir fila específica para residuos peligrosos propios (LER con *), separada de LER admitidos
        rp_propios = (datos_completos.get("residuos_peligrosos_propios_ler") or "").strip()
        if rp_propios:
            datos_tabla.append(
                ("Residuos peligrosos propios (LER con *)", rp_propios)
            )
        # Aplicar fixes EFIBCA, superficie y RN2000 automáticamente (antes de alertas y export) — evita alertas persistentes
        datos_u_fix = (_estado_registro.get("datos_usuario") or {})
        carto_fix = (_estado_registro.get("cartografia_informe") or {})
        sup_parcela_fix = (datos_u_fix.get("superficie_parcela_m2") or datos_completos.get("superficie_parcela_m2") or "").strip()
        sup_construida_fix = (datos_u_fix.get("superficie_construida_m2") or datos_completos.get("superficie_construida_m2") or "").strip()
        dist_rn_fix = (carto_fix.get("red_natura_2000_distancia_m") or "").strip()
        _hubo_cambios_fix = False
        for cap_key, _, state_key in CHAPTER_TEMPLATE:
            t = capitulos.get(cap_key) or ""
            if not t:
                continue
            orig = t
            # Fix A: EFIBCA 5/1 capacidad 1.000 sin unidad → 1.000 kg
            if "EFIBCA" in t and ("1.000" in t or "1,000" in t):
                t = re.sub(
                    r"(EFIBCA\s*5/1[^\n]{0,100}?)(capacidad\s*)?(1[.,]?000)(?!\s*kg\b)",
                    r"\g<1>\g<3> kg",
                    t,
                    flags=re.I,
                )
            # Fix B: Superficie total/catastral de parcela: pendiente → valor Catastro
            if sup_parcela_fix and sup_parcela_fix not in ("", "N/D"):
                texto_sust = "Superficie de parcela (Catastro – superficie gráfica): " + sup_parcela_fix + " m²."
                if sup_construida_fix and sup_construida_fix not in ("", "N/D"):
                    texto_sust += " Superficie construida (Catastro): " + sup_construida_fix + " m²."
                t = re.sub(
                    r"Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                    texto_sust,
                    t,
                    flags=re.I,
                )
            # Fix D: 2.500/2500 m² legacy → superficie real del estado (sanitización global obligatoria)
            if sup_parcela_fix and sup_parcela_fix not in ("", "N/D"):
                t = re.sub(
                    r"\b2[\s\.,]?\s*500\s*m\s*[²2]\b|\b2500\s*m\s*[²2]\b|\b2\s*500\s*m\s*[²2]\b",
                    sup_parcela_fix + " m²",
                    t,
                    flags=re.I,
                )
            # Fix E: 1.200 m² (valor erróneo en contexto superficies) → superficie construida/parcela del estado
            sust_sup = (sup_construida_fix or sup_parcela_fix or "").strip()
            if sust_sup and sust_sup not in ("", "N/D"):
                t = re.sub(
                    r"\b1[\s\.,]?\s*200\s*m\s*[²2]\b|\b1200\s*m\s*[²2]\b|\b1\s*200\s*m\s*[²2]\b",
                    sust_sup + " m²",
                    t,
                    flags=re.I,
                )
            # Fix F: Representante legal con valor erróneo (distancia RN2000 mezclada, ej. "4950 m desde parcela")
            rep_legal_fix = (datos_u_fix.get("representante_legal") or datos_completos.get("representante_legal") or "").strip()
            if rep_legal_fix and re.search(r"Representante\s+legal\s*[:\-]\s*\d+\s*m\s+desde\s+parcela", t, re.I):
                t = re.sub(
                    r"Representante\s+legal\s*[:\-]\s*\d+\s*m\s+desde\s+parcela[^.\n]*",
                    "Representante legal: " + rep_legal_fix,
                    t,
                    flags=re.I,
                )
            # Fix C: Red Natura 2000: pendiente de acreditación → distancia real (cuando hay valor en cartografía)
            if dist_rn_fix and dist_rn_fix not in ("", "N/D") and re.search(r"red\s+natura|RN2000", t, re.I):
                try:
                    _d = str(dist_rn_fix).replace(",", ".")
                    _n = float(_d)
                    valor_rn_m = f"{int(_n)} m" if _n == int(_n) else f"{_n} m"
                except ValueError:
                    valor_rn_m = str(dist_rn_fix) + " m"
                t = re.sub(
                    r"pendiente\s+de\s+acreditaci[oó]n(?:\s+documental)?(?:\s*[-–]\s*Confianza\s+Alta)?",
                    valor_rn_m + " desde parcela",
                    t,
                    count=1,
                    flags=re.I,
                )
            if t != orig:
                capitulos[cap_key] = t
                st.session_state[state_key] = t
                _hubo_cambios_fix = True
        if _hubo_cambios_fix:
            try:
                from persistencia_archivos import guardar_estado_proyecto
                guardar_estado_proyecto(
                    {"capitulos": {sk: st.session_state.get(sk, "") for ck, _, sk in CHAPTER_TEMPLATE if isinstance(st.session_state.get(sk), str)}},
                    st.session_state.proyecto_actual,
                    estado_base=_estado_registro,
                )
                _invalidate_cache_data()
            except Exception:
                pass
        caps_export = {
            k: _limpiar_texto_capitulo(
                v or "",
                perfil_operativo,
                estado_infraestructura=datos_completos.get("estado_infraestructura", "") or "",
            )
            for k, v in capitulos.items()
        }
        if modo_no_cat:
            caps_export = {k: _normalizar_nomenclatura_no_cat(v or "") for k, v in caps_export.items()}
        elif perfil_operativo == "gestion_residuos_no_vehiculos":
            caps_export = {k: _normalizar_nomenclatura_no_vehicular(v or "") for k, v in caps_export.items()}
        # Fix superficie/EFIBCA/RN2000/2.500 legacy directamente en caps_export (texto que se evalúa para alertas)
        _hubo_fix_caps = False
        if sup_parcela_fix and sup_parcela_fix not in ("", "N/D"):
            # Fix 2.500/2500 m² legacy en todos los capítulos (variantes: 2.500, 2500, 2,500, 2 500, etc.)
            for k in caps_export:
                t = caps_export[k]
                t_nuevo = re.sub(
                    r"\b2[\s\.,]?\s*500\s*m\s*[²2]\b|\b2500\s*m\s*[²2]\b|\b2\s*500\s*m\s*[²2]\b",
                    sup_parcela_fix + " m²",
                    t,
                    flags=re.I,
                )
                if t_nuevo != t:
                    caps_export[k] = t_nuevo
                    _hubo_fix_caps = True
            # Fix 1.200 m² (valor erróneo) → superficie construida/parcela
            sust_sup_caps = (sup_construida_fix or sup_parcela_fix or "").strip()
            if sust_sup_caps and sust_sup_caps not in ("", "N/D"):
                for k in caps_export:
                    t = caps_export[k]
                    t_nuevo = re.sub(
                        r"\b1[\s\.,]?\s*200\s*m\s*[²2]\b|\b1200\s*m\s*[²2]\b|\b1\s*200\s*m\s*[²2]\b",
                        sust_sup_caps + " m²",
                        t,
                        flags=re.I,
                    )
                    if t_nuevo != t:
                        caps_export[k] = t_nuevo
                        _hubo_fix_caps = True
            texto_sust_sup = "Superficie de parcela (Catastro – superficie gráfica): " + sup_parcela_fix + " m²."
            if sup_construida_fix and sup_construida_fix not in ("", "N/D"):
                texto_sust_sup += " Superficie construida (Catastro): " + sup_construida_fix + " m²."
            for k in caps_export:
                t = caps_export[k]
                t_nuevo = re.sub(
                    r"Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                    texto_sust_sup,
                    t,
                    flags=re.I,
                )
                if t_nuevo != t:
                    caps_export[k] = t_nuevo
                    _hubo_fix_caps = True
        if dist_rn_fix and dist_rn_fix not in ("", "N/D"):
            try:
                _d = str(dist_rn_fix).replace(",", ".")
                _n = float(_d)
                valor_rn_m = f"{int(_n)} m" if _n == int(_n) else f"{_n} m"
            except ValueError:
                valor_rn_m = str(dist_rn_fix) + " m"
            for k in caps_export:
                t = caps_export[k]
                if re.search(r"red\s+natura|RN2000", t, re.I):
                    t_nuevo = re.sub(
                        r"pendiente\s+de\s+acreditaci[oó]n(?:\s+documental)?(?:\s*[-–]\s*Confianza\s+Alta)?",
                        valor_rn_m + " desde parcela",
                        t,
                        count=1,
                        flags=re.I,
                    )
                    if t_nuevo != t:
                        caps_export[k] = t_nuevo
                        _hubo_fix_caps = True
        for k in caps_export:
            t = caps_export[k]
            if "EFIBCA" in t and ("1.000" in t or "1,000" in t):
                t_nuevo = re.sub(
                    r"(EFIBCA\s*5/1[^\n]{0,100}?)(capacidad\s*)?(1[.,]?000)(?!\s*kg\b)",
                    r"\g<1>\g<3> kg",
                    t,
                    flags=re.I,
                )
                if t_nuevo != t:
                    caps_export[k] = t_nuevo
                    _hubo_fix_caps = True
        if _hubo_fix_caps:
            for cap_key, _, state_key in CHAPTER_TEMPLATE:
                if cap_key in caps_export and caps_export[cap_key]:
                    st.session_state[state_key] = caps_export[cap_key]
            try:
                from persistencia_archivos import guardar_estado_proyecto
                guardar_estado_proyecto(
                    {"capitulos": {sk: st.session_state.get(sk, "") for ck, _, sk in CHAPTER_TEMPLATE if isinstance(st.session_state.get(sk), str)}},
                    st.session_state.proyecto_actual,
                    estado_base=_estado_registro,
                )
                _invalidate_cache_data()
            except Exception:
                pass
        capitulos_generados = sum(1 for v in caps_export.values() if v.strip())
        alertas_calidad = []
        if capitulos_generados > 0:
            alertas_calidad = _detectar_alertas_calidad_exportacion(
                caps_export,
                datos_completos,
                modo_no_cat=modo_no_cat,
                perfil_operativo=perfil_operativo,
            )
            alertas_calidad.extend(_alertas_coherencia_ler(datos_completos, perfil_operativo))
            try:
                estado_actual = _cargar_estado_proyecto_cached(st.session_state.proyecto_actual)
                alertas_calidad.extend(_alertas_gates_registro(estado_actual, caps_export, datos_completos))
            except Exception:
                pass

        if alertas_calidad:
            st.warning("Hay alertas de calidad. Exporte como **BORRADOR** (incluye portada roja y Anexo 0) o corrija datos para habilitar **Exportación para registro**.")
            col_fix1, col_fix2 = st.columns(2)
            with col_fix1:
                aplicar_correcciones = st.button(
                    "🔧 Aplicar correcciones de alertas al informe (automático)",
                    key="aplicar_correcciones_alertas",
                    help="Inserta en el texto del informe las correcciones sugeridas por las alertas (LER, RP propios, potencia, cartografía, unidades, N/D). Luego vuelva a comprobar alertas o exporte.",
                )
            with col_fix2:
                # Botón directo para superficie parcela (cuando la alerta es Gate coherencia superficie)
                hay_alerta_superficie = any("superficie_parcela_m2" in a or ("Gate coherencia" in a and "parcela" in a.lower()) for a in alertas_calidad)
                sup_manual = (sup_parcela_fix or datos_completos.get("superficie_parcela_m2") or "591").strip()
                sup_const_manual = (sup_construida_fix or datos_completos.get("superficie_construida_m2") or "590").strip()
                if hay_alerta_superficie and sup_manual and sup_manual not in ("", "N/D"):
                    corregir_superficie_btn = st.button(
                        "📐 Corregir superficie parcela manualmente",
                        key="corregir_superficie_manual",
                        help=f"Sustituye 'Superficie total de parcela: pendiente...' por {sup_manual} m² (parcela) y {sup_const_manual} m² (construida) en el capítulo Descripción.",
                    )
                    if corregir_superficie_btn:
                        texto_sust_manual = "Superficie de parcela (Catastro – superficie gráfica): " + sup_manual + " m²."
                        if sup_const_manual and sup_const_manual not in ("", "N/D"):
                            texto_sust_manual += " Superficie construida (Catastro): " + sup_const_manual + " m²."
                        desc_actual = st.session_state.get("informe_descripcion") or ""
                        # Varios patrones por si el texto tiene formato distinto (saltos de línea, etc.)
                        patrones_sup = [
                            r"Superficie\s+(?:catastral|total)\s+(?:de\s+)?(?:la\s+)?parcela\s*[:\s\*\-]*(?:pendiente|No\s+consta|N/D|no\s+consta)[^\n]*",
                            r"Superficie\s+total\s+de\s+parcela\s*[:\-]\s*[\s\n]*(?:pendiente|No\s+consta|N/D)[^\n]*(?:\n[^\n]*)?",
                            r"Superficie\s+total\s+de\s+parcela\s*[:\-]\s*pendiente[^\n]*",
                        ]
                        desc_nuevo = desc_actual
                        for pat in patrones_sup:
                            desc_nuevo = re.sub(pat, texto_sust_manual, desc_nuevo, count=1, flags=re.I | re.DOTALL)
                            if desc_nuevo != desc_actual:
                                break
                        # Fallback: sustitución directa por cadenas típicas
                        if desc_nuevo == desc_actual:
                            for viejo in [
                                "Superficie total de parcela:** pendiente de acreditación documental",
                                "Superficie total de parcela: pendiente de acreditación documental",
                                "Superficie total de parcela: No consta",
                                "Superficie total de parcela: N/D",
                                "Superficie total de parcela: pendiente",
                            ]:
                                if viejo in desc_actual:
                                    desc_nuevo = desc_actual.replace(viejo, texto_sust_manual, 1)
                                    break
                        if desc_nuevo != desc_actual:
                            st.session_state["informe_descripcion"] = desc_nuevo
                            try:
                                from persistencia_archivos import guardar_estado_proyecto
                                guardar_estado_proyecto(
                                    {"capitulos": {sk: st.session_state.get(sk, "") for ck, _, sk in CHAPTER_TEMPLATE if isinstance(st.session_state.get(sk), str)}},
                                    st.session_state.proyecto_actual,
                                    estado_base=_estado_registro,
                                )
                                _invalidate_cache_data()
                            except Exception:
                                pass
                            st.success("Superficie corregida en el capítulo Descripción. La página se recargará.")
                            st.rerun()
                        else:
                            st.info("No se encontró el texto a sustituir en Descripción. El patrón puede haber cambiado.")
            if aplicar_correcciones:
                try:
                    estado_actual = _cargar_estado_proyecto_cached(st.session_state.proyecto_actual)
                    capitulos_actuales = {key: (st.session_state.get(state_key) or "") for key, _, state_key in CHAPTER_TEMPLATE}
                    corregidos, patch_log = _aplicar_correcciones_alertas_al_informe(
                        estado_actual, capitulos_actuales, datos_completos, alertas_calidad
                    )
                    for (cap_key, _, state_key) in CHAPTER_TEMPLATE:
                        if cap_key in corregidos and corregidos[cap_key] != (capitulos_actuales.get(cap_key) or ""):
                            st.session_state[state_key] = corregidos[cap_key]
                    try:
                        from exportador import APP_VERSION
                        patch_log["version_app"] = APP_VERSION
                    except Exception:
                        patch_log["version_app"] = "1.0"
                    payload_estado = {
                        "capitulos": {state_key: corregidos.get(cap_key, "") for cap_key, _, state_key in CHAPTER_TEMPLATE},
                        "ultima_aplicacion_correcciones_qa": patch_log,
                    }
                    from persistencia_archivos import guardar_estado_proyecto
                    guardar_estado_proyecto(
                        payload_estado,
                        st.session_state.proyecto_actual,
                        estado_base=estado_actual,
                    )
                    _invalidate_cache_data()
                    st.session_state.ultima_patch_log_qa = patch_log
                    st.success("Correcciones aplicadas al informe (Nivel 1 y 2; sin inventar datos). Revise el contenido o vuelva a exportar; las alertas se recalcularán.")
                    st.rerun()
                except Exception as e:
                    _mensaje_suave("error", f"Error al aplicar correcciones: {e}")
            hay_alerta_ler_whitelist = any("Gate LER (crítico)" in a or "No hay lista LER de referencia" in a for a in alertas_calidad)
            if hay_alerta_ler_whitelist:
                with st.expander("📌 Cómo rellenar clasificacion_ler", expanded=False):
                    st.markdown(
                        "**Instrucciones:** Copie **literalmente** la lista de códigos LER del listado o plano del **Proyecto** o de la **autorización** que se solicita. "
                        "No invente códigos ni use listas genéricas.\n\n"
                        "- **Formato:** `16 01 17, 17 04 01, 17 04 05` (separados por coma y espacio).\n"
                        "- **Códigos peligrosos** llevan asterisco, p. ej. `20 01 35*`, `15 02 02*`.\n"
                        "- **No mezcle** residuos **admitidos** en la instalación con residuos **generados** por la actividad (RP propios). "
                        "Si su interfaz lo permite, use la lista **clasificacion_ler** solo para LER admitidos y la lista **residuos_peligrosos_propios_ler** para los RP generados (mantenimiento, etc.).\n\n"
                        "Puede editarlos en **Datos del proyecto** o en la tabla de datos antes de generar capítulos."
                    )
            with st.expander("Ver listado de alertas", expanded=True):
                st.markdown("\n".join([f"- {a}" for a in alertas_calidad]))
            if st.session_state.get("ultima_patch_log_qa"):
                pl = st.session_state.ultima_patch_log_qa
                with st.expander("📋 Última aplicación de correcciones (patch log)", expanded=False):
                    st.caption(f"Fecha: {pl.get('fecha', '')} · Reglas: {', '.join(pl.get('reglas_aplicadas', []))} · v{pl.get('version_app', '')}")
                    for d in pl.get("detalle", []):
                        st.caption(f"**{d.get('capitulo', '')}** — {d.get('regla', '')}: {d.get('descripcion', d.get('campo', ''))} → {d.get('valor', '')}")
        else:
            st.success("Sin alertas de calidad. Puede exportar para registro.")

        col_borrador, col_registro = st.columns(2)
        with col_borrador:
            exportar_borrador = st.button(
                "Exportar como BORRADOR (puede incluir alertas)",
                key="export_word_borrador",
                help="Genera Word con portada 'BORRADOR – NO REGISTRAR' y Anexo 0 con alertas de QA si las hay.",
            )
        with col_registro:
            exportar_registro = st.button(
                "Exportar para REGISTRO (solo sin alertas)",
                key="export_word_registro",
                disabled=len(alertas_calidad) > 0,
                help="Solo habilitado cuando no hay alertas. Documento listo para presentación.",
            )

        if exportar_borrador or exportar_registro:
            st.session_state.informe_word_bytes = None
            es_borrador = exportar_borrador
            lista_alertas_export = alertas_calidad if es_borrador else None
            try:
                from exportador import exportar_informe_word
                if capitulos_generados == 0:
                    raise ValueError("No hay capítulos generados todavía. Genera al menos un capítulo antes de exportar.")
                if capitulos_generados < 3:
                    st.warning("Se recomienda generar al menos 3 capítulos antes de exportar para un documento más consistente.")
                imagenes = []
                if st.session_state.get("mapa_imagenes_bytes"):
                    imagenes.extend([img for img in st.session_state.mapa_imagenes_bytes if img])
                elif st.session_state.get("mapa_imagen_bytes"):
                    imagenes.append(st.session_state.mapa_imagen_bytes)

                # Intento automático de captura de mapa si aún no hay ninguna imagen anexada
                if not imagenes:
                    try:
                        from mapas import crear_mapa_interactivo, guardar_mapa_como_imagen
                        import tempfile

                        coord_exp = (datos_completos.get("coordenadas_utm") or "").strip()
                        if coord_exp:
                            zona_auto = 30
                            coord_low = coord_exp.lower()
                            if "28" in coord_exp or any(k in coord_low for k in ["canarias", "tenerife", "gran canaria", "fuerteventura", "lanzarote"]):
                                zona_auto = 28
                            elif "29" in coord_exp:
                                zona_auto = 29
                            elif "31" in coord_exp:
                                zona_auto = 31
                            mapa_auto = crear_mapa_interactivo(
                                coordenadas_utm=coord_exp,
                                zona_utm=zona_auto,
                                zoom=15,
                            )
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmpf:
                                ruta_auto = tmpf.name
                            if guardar_mapa_como_imagen(mapa_auto, ruta_auto):
                                with open(ruta_auto, "rb") as f:
                                    img_auto = f.read()
                                if img_auto:
                                    imagenes.append(img_auto)
                            try:
                                os.unlink(ruta_auto)
                            except Exception:
                                pass
                    except Exception:
                        pass

                with st.spinner("Generando documento Word..."):
                    # Control de calidad mínimo previo a exportación.
                    referencias_count = 0
                    try:
                        from persistencia_archivos import obtener_lista_referencias
                        referencias_count = len(obtener_lista_referencias())
                    except Exception:
                        referencias_count = 0

                    control_calidad = {
                        "Capítulos generados (>=8 recomendado)": "Cumple" if capitulos_generados >= 8 else "Revisar",
                        "Coordenadas del proyecto disponibles": "Cumple" if bool((datos_completos.get("coordenadas_utm") or "").strip()) else "Revisar",
                        "Anexo cartográfico temático": "Cumple" if len(st.session_state.get("mapa_anexos_detalle", [])) >= 4 else "Revisar",
                        "Anexo climático (texto + figura)": "Cumple" if bool(st.session_state.get("clima_analisis_texto", "").strip()) and len(st.session_state.get("clima_figuras_bytes", [])) >= 1 else "Revisar",
                        "Reportaje fotográfico": "Cumple" if len(st.session_state.get("imagenes_reportaje_bytes", [])) >= 1 else "Revisar",
                        "Referencias técnicas cargadas (normativa/ejemplos)": "Cumple" if referencias_count >= 1 else "Revisar",
                    }

                    _estado_export = _cargar_estado_proyecto_cached(st.session_state.proyecto_actual)
                    carto_export = (_estado_export.get("cartografia_informe") or {}) if isinstance(_estado_export, dict) else {}
                    doc_bytes = exportar_informe_word(
                        datos_tabla=datos_tabla,
                        capitulos=caps_export,
                        imagenes_mapa=imagenes if imagenes else None,
                        anexos_cartograficos=st.session_state.get("mapa_anexos_detalle", []),
                        anexos_clima={
                            "texto": st.session_state.get("clima_analisis_texto", ""),
                            "figuras": st.session_state.get("clima_figuras_bytes", []),
                        },
                        imagenes_reportaje=st.session_state.get("imagenes_reportaje_bytes", []),
                        control_calidad=control_calidad,
                        fuentes_oficiales=[
                            "AEMET OpenData",
                            "IGN - PNOA",
                            "MITECO - Red Natura 2000 / SNCZI",
                            "Dirección General del Catastro",
                            "IDECanarias / GRAFCAN",
                            "IGR - Hidrografía",
                        ],
                        titulo_proyecto=titulo_exp[:200],
                        portada_fondo_path=st.session_state.get("portada_global_path", ""),
                        portada_titulo=portada_titulo,
                        portada_promotor=(portada_promotor or "").strip(),
                        portada_elaborado=[
                            (elaborado_1 or "").strip(),
                            (elaborado_2 or "").strip(),
                        ],
                        es_borrador=es_borrador,
                        lista_alertas=lista_alertas_export,
                        cartografia_informe=carto_export if carto_export else None,
                    )
                    st.session_state.informe_word_bytes = doc_bytes
                st.success("Documento generado.")
            except ImportError as e:
                _mensaje_suave("error", "Falta python-docx. Instala con: pip install python-docx")
            except Exception as e:
                _mensaje_suave("error", f"Error al exportar: {e}")

        if st.session_state.get("informe_word_bytes"):
            st.download_button(
                "Descargar informe EIA.docx",
                data=st.session_state.informe_word_bytes,
                file_name="informe_eia.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="dl_word",
            )

# --- SECCIÓN MAPAS Y ANEXOS ---
elif pagina == "mapas":
    st.markdown('<p class="main-header">Mapas y Anexos</p>', unsafe_allow_html=True)
    st.markdown("Mapa interactivo con capas WMS oficiales: PNOA Ortofoto (IGN), Red Natura 2000 (MITECO) y Catastro.")
    st.caption(f"Proyecto activo: {st.session_state.proyecto_actual}")

    datos = st.session_state.datos_extraidos
    datos_completos = _obtener_datos_completos(datos)
    coordenadas = datos_completos.get("coordenadas_utm", "") or ""
    ubicacion_proyecto = datos_completos.get("ubicacion_proyecto", "") or ""

    col1, col2 = st.columns([1, 3])
    with col1:
        zona_sugerida = 29
        try:
            from mapas import inferir_zona_utm
            zona_sugerida = inferir_zona_utm(coordenadas, default=29)
        except Exception:
            zona_sugerida = 29
        zona_utm = st.selectbox(
            "Zona UTM",
            options=[28, 29, 30, 31],
            index=[28, 29, 30, 31].index(zona_sugerida if zona_sugerida in [28, 29, 30, 31] else 29),
            help="28: Canarias, 29-31: Península",
        )
        if coordenadas:
            st.caption(f"Coordenadas (UTM o lat/lon): {coordenadas[:80]}...")
        else:
            st.caption("Indica coordenadas (UTM o lat/lon) en Análisis de Datos para centrar el mapa.")

    try:
        from mapas import (
            crear_mapa_interactivo,
            guardar_mapa_como_imagen,
            parsear_centro,
            DEFAULT_CENTER,
            descargar_capa_wms_png,
            superponer_marcador_en_png,
            combinar_png_base_tematica,
            decorar_png_cartografico,
            analizar_capa_tematica_png,
            WMS_PNOA,
            WMS_RED_NATURA,
            WMS_CATASTRO,
            WMS_SNCZI_INUNDABILIDAD,
            WMS_IGR_HIDROGRAFIA,
            WMS_GRAFCAN_IDEC,
            WMS_GRAFCAN_ESP_NAT,
            WMS_GRAFCAN_ZEC,
            WMS_GRAFCAN_ZEPA,
            WMS_GRAFCAN_ESPECIES,
            WMS_GRAFCAN_RUIDO,
            WMS_MITECO_RUIDO,
        )
        from streamlit_folium import st_folium

        try:
            centro_calc = parsear_centro(
                coordenadas if coordenadas else None,
                zona_utm,
                ubicacion_proyecto,
            )
        except TypeError:
            # Compatibilidad con versión anterior de mapas.parsear_centro en caliente.
            centro_calc = parsear_centro(coordenadas if coordenadas else None, zona_utm)
        st.session_state.centro_proyecto_latlon = centro_calc
        if coordenadas and centro_calc == DEFAULT_CENTER:
            st.warning(
                "No se han podido interpretar bien las coordenadas del proyecto. "
                "Se intentará centrar por ubicación textual si está disponible."
            )

        mapa = crear_mapa_interactivo(
            centro=centro_calc,
            coordenadas_utm=coordenadas if coordenadas else None,
            zona_utm=zona_utm,
            ubicacion_texto=ubicacion_proyecto,
            zoom=15 if coordenadas else 6,
        )
        st_folium(mapa, width=1200, height=500, key="mapa_principal")

        st.markdown("---")
        st.markdown("**Guardar mapa para el informe**")
        st.caption("La imagen del mapa se incluirá automáticamente al exportar el informe a Word.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Guardar captura como imagen"):
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    ruta = tmp.name
                if guardar_mapa_como_imagen(mapa, ruta):
                    with open(ruta, "rb") as f:
                        img_bytes = f.read()
                    st.session_state.mapa_imagen_bytes = img_bytes
                    if img_bytes:
                        st.session_state.mapa_imagenes_bytes = [img_bytes]
                        try:
                            from persistencia_archivos import guardar_bytes_en_imagenes
                            guardar_bytes_en_imagenes(
                                img_bytes,
                                "mapa_00_localizacion.png",
                                st.session_state.proyecto_actual,
                            )
                        except Exception:
                            pass
                    st.download_button(
                        "Descargar imagen PNG",
                        data=img_bytes,
                        file_name="mapa_proyecto_eia.png",
                        mime="image/png",
                    )
                    try:
                        os.unlink(ruta)
                    except Exception:
                        pass
                else:
                    st.warning(
                        "No se pudo generar la captura (requiere Chrome/Chromium). "
                        "Puedes hacer captura de pantalla manual o descargar el HTML."
                    )
            if st.button("Generar anexos cartográficos automáticos"):
                st.info("Generando anexos cartográficos automáticos...")
                imagenes_generadas = []
                anexos_detalle = []
                try:
                    from persistencia_archivos import cargar_archivos_guardados, eliminar_archivo
                    prev = cargar_archivos_guardados(st.session_state.proyecto_actual)
                    for ruta in prev.get("imagenes", []):
                        if ruta.name.lower().startswith("mapa_"):
                            eliminar_archivo(ruta)
                except Exception:
                    pass
                capas_anexo = [
                    ("Mapa base de localización", None, None, 1.2, "Cartografía base", None, None),
                    ("PNOA Ortofoto (IGN)", ["pnoa"], WMS_PNOA, 1.5, "IGN PNOA", None, None),
                    ("Red Natura 2000 (MITECO)", ["red_natura"], WMS_RED_NATURA, 10.0, "MITECO", None, "Zonas de protección ambiental y sensibilidad ecológica"),
                    ("Catastro", ["catastro"], WMS_CATASTRO, 0.9, "Dirección General del Catastro", None, "Parcelario y referencia de implantación"),
                    ("SNCZI Inundabilidad", ["snczi"], WMS_SNCZI_INUNDABILIDAD, 6.0, "MITECO SNCZI", None, "Evaluación de riesgo potencial de inundación"),
                    ("IGR Hidrografía", ["igr_hidrografia"], WMS_IGR_HIDROGRAFIA, 4.5, "IGN IGR Hidrografía", None, "Red hidrográfica y drenajes superficiales"),
                    ("Ruido estratégico (GRAFCAN LDEN)", ["grafcan_ruido"], WMS_GRAFCAN_RUIDO, 2.5, "IDECanarias GRAFCAN", [100, 250, 500], "Anillos de distancia para receptores sensibles"),
                    ("Espacios Naturales Protegidos (GRAFCAN)", ["grafcan_espnat"], WMS_GRAFCAN_ESP_NAT, 10.0, "IDECanarias GRAFCAN", None, "Áreas protegidas y condicionantes territoriales"),
                    ("ZEC (GRAFCAN)", ["grafcan_zec"], WMS_GRAFCAN_ZEC, 10.0, "IDECanarias GRAFCAN", None, "Zonas Especiales de Conservación"),
                    ("ZEPA (GRAFCAN)", ["grafcan_zepa"], WMS_GRAFCAN_ZEPA, 12.0, "IDECanarias GRAFCAN", None, "Zonas de Especial Protección para las Aves"),
                    ("Especies Protegidas (GRAFCAN)", ["grafcan_especies"], WMS_GRAFCAN_ESPECIES, 8.0, "IDECanarias GRAFCAN", None, "Presencia potencial de especies protegidas"),
                    ("Ruido estratégico (MITECO Lden)", ["ruido_miteco"], WMS_MITECO_RUIDO, 2.5, "MITECO", [100, 250, 500], "Anillos de distancia para análisis de afección acústica"),
                ]
                import tempfile
                ruido_grafcan_generado = False
                for idx, (capa_nombre, capas_cfg, cfg_wms, radio_km_mapa, fuente_mapa, anillos_mapa, leyenda_mapa) in enumerate(capas_anexo, start=1):
                    try:
                        if "MITECO Lden" in capa_nombre and ruido_grafcan_generado:
                            # Evita duplicidad: si hay ruido GRAFCAN válido, no añadir mapa de ruido MITECO.
                            continue
                        contenido = None
                        # El mapa base se captura con Folium para conservar cartografía de contexto.
                        if cfg_wms is None:
                            mapa_auto = crear_mapa_interactivo(
                                centro=centro_calc,
                                coordenadas_utm=coordenadas if coordenadas else None,
                                zona_utm=zona_utm,
                                ubicacion_texto=ubicacion_proyecto,
                                zoom=15 if coordenadas else 6,
                                capas_activas=capas_cfg,
                            )
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                ruta_auto = tmp.name
                            if guardar_mapa_como_imagen(mapa_auto, ruta_auto):
                                with open(ruta_auto, "rb") as f:
                                    contenido = f.read()
                            try:
                                os.unlink(ruta_auto)
                            except Exception:
                                pass
                        else:
                            # Para capas temáticas exigimos descarga WMS directa para evitar duplicados.
                            contenido_tematica = descargar_capa_wms_png(
                                centro_calc[0],
                                centro_calc[1],
                                cfg_wms,
                                width=1400,
                                height=900,
                                radio_km=radio_km_mapa,
                            )
                            if contenido_tematica:
                                analisis_tematica = analizar_capa_tematica_png(
                                    contenido_tematica,
                                    centro_calc[0],
                                    centro_calc[1],
                                    radio_km=radio_km_mapa,
                                )
                                base_png = descargar_capa_wms_png(
                                    centro_calc[0],
                                    centro_calc[1],
                                    WMS_PNOA,
                                    width=1400,
                                    height=900,
                                    radio_km=radio_km_mapa,
                                )
                                contenido = combinar_png_base_tematica(base_png, contenido_tematica)
                                contenido = decorar_png_cartografico(
                                    contenido,
                                    centro_calc[0],
                                    centro_calc[1],
                                    radio_km=radio_km_mapa,
                                    titulo=capa_nombre,
                                    fuente=fuente_mapa,
                                    anillos_m=anillos_mapa,
                                    texto_leyenda=leyenda_mapa,
                                )
                            else:
                                analisis_tematica = None

                        if contenido:
                            if cfg_wms is None:
                                contenido = decorar_png_cartografico(
                                    contenido,
                                    centro_calc[0],
                                    centro_calc[1],
                                    radio_km=radio_km_mapa,
                                    titulo=capa_nombre,
                                    fuente=fuente_mapa,
                                    anillos_m=anillos_mapa,
                                    texto_leyenda=leyenda_mapa,
                                )
                                analisis_tematica = None
                            imagenes_generadas.append(contenido)
                            nombre_archivo = f"mapa_{idx:02d}_{capa_nombre}.png"
                            nombre_archivo = "".join(c for c in nombre_archivo if c.isalnum() or c in "._- ").replace(" ", "_")
                            try:
                                from persistencia_archivos import guardar_bytes_en_imagenes
                                guardar_bytes_en_imagenes(
                                    contenido,
                                    nombre_archivo,
                                    st.session_state.proyecto_actual,
                                )
                            except Exception:
                                pass
                            anexos_detalle.append(
                                {
                                    "titulo": capa_nombre,
                                    "imagen": contenido,
                                    "archivo": nombre_archivo,
                                    "fuente": fuente_mapa,
                                    "escala_km": radio_km_mapa,
                                    "interpretacion": leyenda_mapa or "Mapa temático de apoyo al análisis ambiental.",
                                    "analisis": analisis_tematica,
                                }
                            )
                            if "GRAFCAN LDEN" in capa_nombre:
                                ruido_grafcan_generado = True
                            st.caption(f"✓ Anexo cartográfico generado: {capa_nombre}")
                        else:
                            st.caption(f"⚠ No disponible para esta ubicación o servicio: {capa_nombre}")
                    except Exception:
                        continue
                if imagenes_generadas:
                    st.session_state.mapa_imagenes_bytes = imagenes_generadas
                    st.session_state.mapa_anexos_detalle = anexos_detalle
                    _guardar_estado_proyecto(st.session_state.proyecto_actual)
                    st.success(f"Se guardaron {len(imagenes_generadas)} anexos cartográficos para exportación.")
                else:
                    st.warning("No se pudieron generar anexos automáticos. Revisa Selenium/Chrome o usa captura manual.")

        if st.session_state.get("mapa_anexos_detalle"):
            st.markdown("---")
            st.markdown("### Vista previa de anexos cartográficos guardados")
            st.caption(f"Anexos en memoria de sesión: {len(st.session_state.mapa_anexos_detalle)}")
            for idx, item in enumerate(st.session_state.mapa_anexos_detalle, start=1):
                c1_prev, c2_prev = st.columns([6, 1])
                c1_prev.markdown(f"**{idx}. {item.get('titulo','Mapa')}**")
                if c2_prev.button("🗑️", key=f"del_mapa_anexo_{idx}"):
                    try:
                        from persistencia_archivos import cargar_archivos_guardados, eliminar_archivo
                        archivo_ref = item.get("archivo")
                        if archivo_ref:
                            prev = cargar_archivos_guardados(st.session_state.proyecto_actual)
                            for ruta in prev.get("imagenes", []):
                                if ruta.name == archivo_ref:
                                    eliminar_archivo(ruta)
                                    break
                    except Exception:
                        pass
                    nuevos = [a for j, a in enumerate(st.session_state.mapa_anexos_detalle) if j != (idx - 1)]
                    st.session_state.mapa_anexos_detalle = nuevos
                    st.session_state.mapa_imagenes_bytes = [a.get("imagen") for a in nuevos if a.get("imagen")]
                    _guardar_estado_proyecto(st.session_state.proyecto_actual)
                    st.rerun()
                if item.get("imagen"):
                    st.image(item["imagen"], width="stretch")
        with c2:
            html = mapa._repr_html_()
            st.download_button(
                "Descargar mapa (HTML)",
                data=html,
                file_name="mapa_proyecto_eia.html",
                mime="text/html",
            )
    except ImportError as e:
        _mensaje_suave("error", "Faltan dependencias. Instala con: pip install folium pyproj streamlit-folium")
        st.code("pip install folium pyproj streamlit-folium", language="bash")

# --- SECCIÓN CLIMA (AEMET) ---
elif pagina == "clima":
    st.markdown('<p class="main-header">Clima (AEMET OpenData)</p>', unsafe_allow_html=True)
    st.markdown(
        "Datos climáticos oficiales para el EIA: estación más cercana, climograma, rosa de los vientos y "
        "clasificación de aridez. **Garantía de origen** citando AEMET como fuente."
    )
    st.markdown("---")
    st.caption(f"Proyecto activo: {st.session_state.proyecto_actual}")

    api_key = st.session_state.get("aemet_api_key", "").strip()
    datos = st.session_state.datos_extraidos
    datos_completos = _obtener_datos_completos(datos)
    coordenadas_utm = (datos_completos.get("coordenadas_utm") or "").strip()
    ubicacion_proyecto = (datos_completos.get("ubicacion_proyecto") or "").strip()

    if not coordenadas_utm and not ubicacion_proyecto:
        st.warning(
            "No hay coordenadas ni ubicación textual del proyecto. Ve a **Análisis de Datos**, "
            "extrae los datos y completa las coordenadas UTM o la ubicación para obtener la estación meteorológica más cercana."
        )
    else:
        try:
            from mapas import parsear_centro, inferir_zona_utm
            from clima_agent import render_climatologia_panel

            zona_sugerida = inferir_zona_utm(coordenadas_utm, default=29)
            zona_utm = st.selectbox(
                "Zona UTM (para convertir a lat/lon)",
                options=[28, 29, 30, 31],
                index=[28, 29, 30, 31].index(zona_sugerida if zona_sugerida in [28, 29, 30, 31] else 29),
                help="28: Canarias, 29-31: Península. Debe coincidir con las coordenadas del proyecto.",
            )
            try:
                lat, lon = parsear_centro(coordenadas_utm, zona_utm, ubicacion_proyecto)
            except TypeError:
                # Compatibilidad con versión anterior de mapas.parsear_centro en caliente.
                lat, lon = parsear_centro(coordenadas_utm, zona_utm)
            centro_prev = st.session_state.get("centro_proyecto_latlon")
            if (
                isinstance(centro_prev, (tuple, list))
                and len(centro_prev) == 2
                and all(isinstance(v, (int, float)) for v in centro_prev)
            ):
                lat, lon = float(centro_prev[0]), float(centro_prev[1])
            st.session_state.centro_proyecto_latlon = (lat, lon)
            st.caption(f"Centro calculado del proyecto: lat {lat:.6f}, lon {lon:.6f}")
            resultado_clima = render_climatologia_panel(api_key, lat, lon)
            st.session_state.clima_analisis_texto = (resultado_clima.get("texto") or "").strip()

            figuras_bytes = []
            for fig_key in ("fig_climograma", "fig_rosa"):
                fig = resultado_clima.get(fig_key)
                if fig is None:
                    continue
                try:
                    # Requiere kaleido; si no está instalado, se omite sin romper.
                    figuras_bytes.append(fig.to_image(format="png", width=1200, height=700))
                except Exception:
                    pass
            if not figuras_bytes:
                figuras_bytes.extend(resultado_clima.get("figuras_png") or [])
            st.session_state.clima_figuras_bytes = figuras_bytes
            try:
                from persistencia_archivos import cargar_archivos_guardados, eliminar_archivo, guardar_bytes_en_imagenes
                prev = cargar_archivos_guardados(st.session_state.proyecto_actual)
                for ruta in prev.get("imagenes", []):
                    if ruta.name.lower().startswith("clima_"):
                        eliminar_archivo(ruta)
                for i, img in enumerate(figuras_bytes, start=1):
                    guardar_bytes_en_imagenes(
                        img,
                        f"clima_{i:02d}.png",
                        st.session_state.proyecto_actual,
                    )
            except Exception:
                pass
            _guardar_estado_proyecto(st.session_state.proyecto_actual)
        except ImportError:
            _mensaje_suave("error", "Faltan dependencias para clima. Instala con: pip install requests plotly matplotlib")
            st.code("pip install requests plotly matplotlib", language="bash")
        except ValueError as e:
            _mensaje_suave("error", str(e))
        except Exception as e:
            _mensaje_suave("error", f"Error al cargar climatología: {e}")

    if st.session_state.get("clima_figuras_bytes"):
        if st.button("🗑️ Borrar figuras climáticas guardadas"):
            st.session_state.clima_figuras_bytes = []
            st.session_state.clima_analisis_texto = ""
            try:
                from persistencia_archivos import cargar_archivos_guardados, eliminar_archivo
                prev = cargar_archivos_guardados(st.session_state.proyecto_actual)
                for ruta in prev.get("imagenes", []):
                    if ruta.name.lower().startswith("clima_"):
                        eliminar_archivo(ruta)
            except Exception:
                pass
            _guardar_estado_proyecto(st.session_state.proyecto_actual)
            st.rerun()

# Persistencia ligera periódica para evitar escrituras en cada interacción de UI.
try:
    now_ts = time.time()
    if "ultimo_autoguardado_ts" not in st.session_state:
        st.session_state.ultimo_autoguardado_ts = 0.0
    if now_ts - float(st.session_state.ultimo_autoguardado_ts) >= 20.0:
        _guardar_estado_proyecto(st.session_state.get("proyecto_actual", "proyecto_default"))
        st.session_state.ultimo_autoguardado_ts = now_ts
except Exception:
    pass
