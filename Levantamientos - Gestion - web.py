# VRP - Registros.py
import base64
import datetime
import time as t
from zoneinfo import ZoneInfo
import folium
from folium.plugins import Fullscreen, MarkerCluster
import pandas as pd
from pyproj import Transformer
from sqlalchemy import create_engine, text
import streamlit as st
from streamlit_folium import st_folium

# Configuración de página
st.set_page_config(
    layout="wide",
    page_title="Gestión Válvulas Reductoras de Presión - MIAA",
    page_icon="https://www.miaa.mx/favicon.ico",
)

# 01 SECCION ----------------------------------------------------------------------------------------------- ESTADO DE SESIÓN ----------------------------------------------------------------------------------------
if "registro_to_delete" not in st.session_state:
  st.session_state.registro_to_delete = None
if "active_tab" not in st.session_state:
  st.session_state.active_tab = "📍 Registros"
if "autenticado" not in st.session_state:
  st.session_state.autenticado = False
if "gestor_bd_autenticado" not in st.session_state:
  st.session_state.gestor_bd_autenticado = False

zona_mx = ZoneInfo("America/Mexico_City")
API_KEY_CARTO = "cb1_26ji_1_864817f3cb73c0bdbe0daccd"

# Transformadores de coordenadas (UTM Zona 13N <-> Lat/Lon WGS84)
transformer_to_latlon = Transformer.from_crs(
    "EPSG:32613", "EPSG:4326", always_xy=True
)
transformer_to_utm = Transformer.from_crs(
    "EPSG:4326", "EPSG:32613", always_xy=True
)

OPCIONES_ESTADO_VALVULA = [
    "Abierta",
    "Calibrada",
    "Cerrada",
    "Dañada",
    "Descalibrada",
    "Habilitada",
    "No opera",
    "Pendiente",
]

COLUMNAS_FECHA = ["fecha_inst", "fecha_vis", "fecha_mtto", "fecha_tim", "_ult_visita"]

def parsear_fecha_segura(val_fecha):
  if (
      pd.isna(val_fecha)
      or val_fecha is None
      or str(val_fecha).strip() in ["", "nan", "None", "NaT"]
  ):
    return datetime.date.today()
  if isinstance(val_fecha, (datetime.date, datetime.datetime)):
    return val_fecha if isinstance(val_fecha, datetime.date) else val_fecha.date()
  try:
    dt = pd.to_datetime(val_fecha, dayfirst=True, errors="coerce")
    if pd.isna(dt):
      dt = pd.to_datetime(val_fecha, errors="coerce")
    if pd.isna(dt):
      return datetime.date.today()
    return dt.date()
  except Exception:
    return datetime.date.today()

def formatear_fecha_str(val_fecha):
  if (
      pd.isna(val_fecha)
      or val_fecha is None
      or str(val_fecha).strip() in ["", "nan", "None", "NaT"]
  ):
    return ""
  if isinstance(val_fecha, (datetime.date, datetime.datetime)):
    d = val_fecha if isinstance(val_fecha, datetime.date) else val_fecha.date()
    return d.strftime("%d/%m/%Y")
  try:
    dt = pd.to_datetime(val_fecha, dayfirst=True, errors="coerce")
    if pd.isna(dt):
      dt = pd.to_datetime(val_fecha, errors="coerce")
    if pd.isna(dt):
      return str(val_fecha)
    return dt.strftime("%d/%m/%Y")
  except Exception:
    return str(val_fecha)

def formatear_columnas_fecha(df):
  if df is None or df.empty:
    return df
  df_copia = df.copy()
  for col in COLUMNAS_FECHA:
    if col in df_copia.columns:
      df_copia[col] = df_copia[col].apply(formatear_fecha_str)
  return df_copia

# 02 SECCION -------------------------------------------------------------------------- CONEXIÓN A BASE DE DATOS POSTGRESQL (VRP_Oficial) --------------------------------------------------------------------------------------

def crear_nuevo_engine():
  pg = st.secrets["postgres"]
  db_url = f"postgresql+psycopg2://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{pg['database']}"
  return create_engine(
      db_url,
      pool_pre_ping=True,
      pool_recycle=1800,
      pool_timeout=60,
      connect_args={"connect_timeout": 60},
  )

if "db_engine" not in st.session_state:
  st.session_state.db_engine = crear_nuevo_engine()

def obtener_datos(query, params=None):
  for intento in range(2):
    try:
      with st.session_state.db_engine.connect() as conn:
        df = pd.read_sql(
            text(query) if isinstance(query, str) else query,
            conn,
            params=params or {},
        )
        return df, None
    except Exception:
      try:
        st.session_state.db_engine.dispose()
        st.session_state.db_engine = crear_nuevo_engine()
        with st.session_state.db_engine.connect() as conn:
          df = pd.read_sql(
              text(query) if isinstance(query, str) else query,
              conn,
              params=params or {},
          )
          return df, None
      except Exception as e2:
        if intento == 1:
          return pd.DataFrame(), str(e2)
  return pd.DataFrame(), "Error de conexión persistente."

def ejecutar_sql(query, params=None):
  with st.session_state.db_engine.connect() as conn:
    with conn.begin():
      conn.execute(
          text(query) if isinstance(query, str) else query, params or {}
      )
  return True

# 03 SECCION ------------------------------------------------------------------- CONEXIÓN A MYSQL (USUARIOS / LOGIN) --------------------------------------------------------------------------------------------------
def crear_engine_mysql():
  mysql_sec = st.secrets["mysql_usuarios_vrp"]
  db_url = f"mysql+pymysql://{mysql_sec['user']}:{mysql_sec['password']}@{mysql_sec['host']}:{mysql_sec['port']}/{mysql_sec['database']}"
  return create_engine(
      db_url,
      pool_pre_ping=True,
      pool_recycle=1800,
      pool_timeout=60,
      connect_args={"connect_timeout": 60},
  )

if "db_mysql_engine" not in st.session_state:
  st.session_state.db_mysql_engine = crear_engine_mysql()

def obtener_datos_mysql(query, params=None):
  for intento in range(2):
    try:
      with st.session_state.db_mysql_engine.connect() as conn:
        df = pd.read_sql(
            text(query) if isinstance(query, str) else query,
            conn,
            params=params or {},
        )
        return df, None
    except Exception:
      try:
        st.session_state.db_mysql_engine.dispose()
        st.session_state.db_mysql_engine = crear_engine_mysql()
        with st.session_state.db_mysql_engine.connect() as conn:
          df = pd.read_sql(
              text(query) if isinstance(query, str) else query,
              conn,
              params=params or {},
          )
          return df, None
      except Exception as e2:
        if intento == 1:
          return pd.DataFrame(), str(e2)
  return pd.DataFrame(), "Error de conexión persistente a MySQL."

def procesar_bytes_foto(foto_data):
  if foto_data is None:
    return None
  if isinstance(foto_data, memoryview):
    return bytes(foto_data)
  if isinstance(foto_data, bytes):
    return foto_data
  if isinstance(foto_data, str) and len(foto_data) > 10:
    try:
      return base64.b64decode(foto_data)
    except:
      return None
  return None

def agregar_capas_base_mapa(m):
  folium.TileLayer(
      tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
      name="Vista Satélite",
      attr="Google",
      max_zoom=20,
      overlay=False,
      control=True,
  ).add_to(m)

  folium.TileLayer(
      tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      name="Satélite (Esri)",
      attr="Esri",
      max_zoom=20,
      overlay=False,
      control=True,
  ).add_to(m)

  folium.TileLayer(
      tiles=f"https://{{s}}.basemaps.cartocdn.com/rastertiles/dark_all/{{z}}/{{x}}/{{y}}.png?key={API_KEY_CARTO}",
      name="Vista Nocturna",
      attr=(
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          ' contributors &copy; <a'
          ' href="https://carto.com/attributions">CARTO</a>'
      ),
      subdomains="abcd",
      max_zoom=20,
      overlay=False,
      control=True,
  ).add_to(m)

# 04 SECCION ------------------------------------------------------------- ESTILOS CSS CON BARRA LATERAL FIJA Y LOGOTIPO MÁS ARRIBA --------------------------------------------------------------------------------
st.write(
    """<style>
    #MainMenu, [data-testid="stHeader"] {visibility: hidden !important; display: none !important;} 
    
    div[data-baseweb="calendar"] header,
    div[data-baseweb="popover"] header {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        background-color: #0D1424 !important;
        color: #00E5FF !important;
    }
    div[data-baseweb="calendar"] header button,
    div[data-baseweb="calendar"] header div,
    div[data-baseweb="calendar"] header svg {
        color: #00E5FF !important;
        fill: #00E5FF !important;
    }

    .block-container {
        padding-top: 0.5rem !important; 
        padding-bottom: 3rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        background: #080C14;
        color: #F8FAFC;
        max-width: 1650px !important;
    }
    body, [data-testid="stAppViewContainer"] {
        background: #080C14;
        color: #F8FAFC;
    }

    [data-testid="stSidebar"] {
        background-color: #0A0F1D !important;
        border-right: 1px solid rgba(0, 229, 255, 0.15) !important;
        padding-top: 0rem !important;
        min-width: 280px !important;
        max-width: 320px !important;
        transform: none !important;
        visibility: visible !important;
        display: block !important;
    }
    
    [data-testid="stSidebarNavSeparator"], button[kind="header"], [data-testid="collapsedControl"] {
        display: none !important;
        visibility: hidden !important;
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    div.row-widget.stRadio > div {
        display: flex;
        flex-direction: column;
        gap: 8px !important;
    }

    div.row-widget.stRadio input[type="radio"],
    div.row-widget.stRadio div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }

    div.row-widget.stRadio div[role="radiogroup"] > label {
        background: #0D1424 !important;
        border: 1px solid rgba(0, 229, 255, 0.15) !important;
        border-radius: 8px !important;
        padding: 10px 14px !important;
        margin: 0 !important;
        cursor: pointer !important;
        transition: all 0.2s ease-in-out !important;
        width: 100% !important;
    }

    div.row-widget.stRadio div[role="radiogroup"] label p,
    div.row-widget.stRadio div[role="radiogroup"] label span {
        color: #94A3B8 !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
    }

    div.row-widget.stRadio div[role="radiogroup"] > label:hover {
        background: #152035 !important;
        border-color: rgba(0, 229, 255, 0.4) !important;
        transform: translateX(4px) !important;
    }

    div.row-widget.stRadio div[role="radiogroup"] > label[data-checked="true"] {
        background: linear-gradient(90deg, #0A2540 0%, #0D1424 100%) !important;
        border-left: 4px solid #00E5FF !important;
        border-color: rgba(0, 229, 255, 0.5) !important;
        box-shadow: 0 2px 10px rgba(0, 229, 255, 0.15) !important;
    }

    div.row-widget.stRadio div[role="radiogroup"] > label[data-checked="true"] p,
    div.row-widget.stRadio div[role="radiogroup"] > label[data-checked="true"] span {
        color: #00E5FF !important;
        font-weight: 700 !important;
    }

    .user-card {
        background: #0D1424;
        border: 1px solid rgba(0, 229, 255, 0.15);
        border-left: 4px solid #00E5FF;
        border-radius: 6px;
        padding: 12px 16px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        margin-bottom: 10px;
    }

    .stTextInput label, .stSelectbox label, .stNumberInput label, .stDateInput label, [data-testid="stWidgetLabel"] p {
        color: #E2E8F0 !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
    }

    .stButton>button {
        background: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid rgba(0, 229, 255, 0.25) !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.55rem 1.2rem !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    .stButton>button:hover {
        background: #334155 !important;
        border-color: #00E5FF !important;
        color: #00E5FF !important;
        box-shadow: 0 0 12px rgba(0, 229, 255, 0.3) !important;
        transform: translateY(-1px) !important;
    }

    .stButton>button:has(p:contains("Actualizar")), 
    .stButton>button:has(span:contains("Actualizar")),
    .stButton>button:has(p:contains("Guardar")), 
    .stButton>button:has(span:contains("Guardar")),
    div[data-testid="stFormSubmitButton"]>button {
        background: linear-gradient(135deg, #0284C7 0%, #00B4D8 100%) !important;
        color: #FFFFFF !important;
        border: 1px solid #00E5FF !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 15px rgba(0, 180, 216, 0.35) !important;
    }
    .stButton>button:has(p:contains("Actualizar")):hover,
    .stButton>button:has(span:contains("Actualizar")):hover,
    .stButton>button:has(p:contains("Guardar")):hover,
    .stButton>button:has(span:contains("Guardar")):hover {
        background: linear-gradient(135deg, #0369A1 0%, #0096C7 100%) !important;
        box-shadow: 0 0 20px rgba(0, 229, 255, 0.6) !important;
        color: #FFFFFF !important;
    }

    .stButton>button:has(p:contains("Eliminar")), 
    .stButton>button:has(span:contains("Eliminar")) {
        background: rgba(153, 27, 27, 0.25) !important;
        color: #FCA5A5 !important;
        border: 1px solid rgba(239, 68, 68, 0.5) !important;
    }
    .stButton>button:has(p:contains("Eliminar")):hover,
    .stButton>button:has(span:contains("Eliminar")):hover {
        background: #991B1B !important;
        color: #FFFFFF !important;
        border-color: #EF4444 !important;
        box-shadow: 0 0 15px rgba(239, 68, 68, 0.5) !important;
    }
    div[data-baseweb="input"] input, div[data-baseweb="base-input"] input, div[data-baseweb="textarea"] textarea {
        background-color: #080C14 !important;
        color: #F8FAFC !important;
        border-color: rgba(0, 229, 255, 0.25) !important;
        border-radius: 6px !important;
        font-size: 0.9rem !important;
    } 
    
    [data-testid="stExpander"] {
        background-color: #080C14 !important;
        border: 1px solid rgba(0, 229, 255, 0.15) !important;
        border-radius: 6px !important;
        margin-top: 3px !important;
        margin-bottom: 3px !important;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.2rem !important;
    }

    [data-testid="stExpander"] summary {
        color: #00E5FF !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        padding-top: 6px !important;
        padding-bottom: 6px !important;
    }

    [data-testid="stCameraInput"] video, 
    [data-testid="stCameraInput"] img {
        width: 100% !important;
        max-width: 640px !important;
        height: auto !important;
        border-radius: 8px !important;
    }

    /* Animaciones y Estilos Dinámicos para el Login */
    @keyframes fadeInSlide {
        0% {
            opacity: 0;
            transform: translateY(25px) scale(0.98);
        }
        100% {
            opacity: 1;
            transform: translateY(0) scale(1);
        }
    }

    @keyframes pulseGlow {
        0% {
            box-shadow: 0 0 15px rgba(0, 229, 255, 0.1);
        }
        50% {
            box-shadow: 0 0 30px rgba(0, 229, 255, 0.35);
        }
        100% {
            box-shadow: 0 0 15px rgba(0, 229, 255, 0.1);
        }
    }

    @keyframes floatLogo {
        0%, 100% {
            transform: translateY(0px);
        }
        50% {
            transform: translateY(-6px);
        }
    }

    .login-container-animated {
        animation: fadeInSlide 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        background: linear-gradient(145deg, #0D1424 0%, #0A0F1D 100%);
        border: 1px solid rgba(0, 229, 255, 0.25);
        border-radius: 14px;
        padding: 35px 40px;
        box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5);
        animation: fadeInSlide 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards, pulseGlow 4s infinite ease-in-out;
        margin-top: 4vh;
    }

    .login-logo-animated {
        animation: floatLogo 3s infinite ease-in-out;
    }
</style>""",
    unsafe_allow_html=True,
)

# 05 SECCION ------------------------------------------------------------------- SISTEMA DE LOGIN CONECTADO A MYSQL -----------------------------------------------------------------------------------------------
if not st.session_state.autenticado:
  # Contenedor principal centrado mediante columnas de Streamlit
  _, col_centro, _ = st.columns([1, 1.4, 1])

  with col_centro:
    st.markdown(
        """
        <div class="login-container-animated">
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; width: 100%; margin-bottom: 25px;">
                <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" class="login-logo-animated" style="width: 200px; height: auto; margin-bottom: 15px;" />
                <h3 style="color: #00E5FF; font-size: 1.5rem; font-weight: 800; margin: 0 0 8px 0; letter-spacing: -0.5px;">Acceso al Sistema</h3>
                <p style="color: #94A3B8; font-size: 0.9rem; margin: 0;">Gestión de Válvulas Reductoras de Presión</p>
            </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
      usuario_input = st.text_input("Usuario")
      password_input = st.text_input("Contraseña", type="password")
      
      st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
      submit_login = st.form_submit_button(
          "Iniciar Sesión", use_container_width=True
      )

      if submit_login:
        if usuario_input and password_input:
          query_login = """
                        SELECT id, usuario, tipo_usuario, departamento 
                        FROM usuarios_vrp 
                        WHERE usuario = :usu AND password = :pas
                    """
          df_user, err_login = obtener_datos_mysql(
              query_login,
              {"usu": usuario_input.strip(), "pas": password_input.strip()},
          )

          if not err_login and not df_user.empty:
            st.session_state.autenticado = True
            st.session_state.usuario_actual = df_user.iloc[0]["usuario"]
            st.session_state.tipo_usuario = (
                str(df_user.iloc[0]["tipo_usuario"]).strip().lower()
            )
            st.session_state.departamento = df_user.iloc[0]["departamento"]
            st.success("¡Acceso concedido!")
            t.sleep(0.5)
            st.rerun()
          else:
            st.error("Usuario o contraseña incorrectos.")
        else:
          st.warning("Por favor, ingrese usuario y contraseña.")

    st.markdown("</div>", unsafe_allow_html=True)
  st.stop()

# 05.1. SECCION ------------------------------------------------------------- DETERMINAR ROL DEL USUARIO -----------------------------------------------------------------------------------------------------------
es_operador = st.session_state.get("tipo_usuario", "") == "operador"

# 06 SECCION ------------------------------------------------------------ BARRA LATERAL IZQUIERDA (SIDEBAR) --------------------------------------------------------------------------------------------------------
with st.sidebar:

  st.markdown(
      """
        <div style="text-align: center; margin-top: -35px; padding-top: 0px; padding-bottom: 8px; border-bottom: 1px solid rgba(0, 229, 255, 0.15); margin-bottom: 12px;">
            <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" style="width: 140px; margin-bottom: 0px;" />
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      f"""
        <div style="background: #111A30; border: 1px solid rgba(0, 229, 255, 0.15); border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 15px;">
            <div style="color: #00E5FF; font-weight: 700; font-size: 0.9rem; margin-bottom: 4px;">👤 {st.session_state.usuario_actual}</div>
            <div style="color: #94A3B8; font-size: 0.75rem; text-transform: uppercase;">{st.session_state.get('tipo_usuario', 'usuario')}</div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  if es_operador:
    opciones_menu = ["📍 Registros", "🗺️ Mapa", "⚙️️ Editar"]
  else:
    opciones_menu = ["📍 Registros", "🗺️ Mapa", "➕ Añadir", "⚙️ Editar"]

  if (
      "active_tab" not in st.session_state
      or st.session_state.active_tab not in opciones_menu
  ):
    st.session_state.active_tab = opciones_menu[0]

  st.markdown(
      "<p style='color: #64748B; font-size: 0.75rem; font-weight: 700;"
      " text-transform: uppercase; margin-bottom: 8px;'>Navegación</p>",
      unsafe_allow_html=True,
  )

  for opcion in opciones_menu:
    es_activa = st.session_state.active_tab == opcion
    tipo_btn = "primary" if es_activa else "secondary"

    if st.button(
        opcion,
        key=f"nav_{opcion}",
        use_container_width=True,
        type=tipo_btn,
    ):
      if st.session_state.active_tab != opcion:
        st.session_state.active_tab = opcion
        st.rerun()

  st.markdown(
      "<hr style='border: 0.5px solid rgba(0,229,255,0.2); margin: 15px 0;'>",
      unsafe_allow_html=True,
  )

  df_sidebar_valvulas, _ = obtener_datos(
      'SELECT id_0, id, estatus, domicilio, colonia FROM "Agua_potable"."VRP_Oficial"'
  )

  if not df_sidebar_valvulas.empty:
    st.markdown(
        "<p style='color: #00E5FF; font-size: 0.85rem; font-weight: 700;"
        " margin-bottom: 16px; margin-top: 8px;'>📊 Estado de Válvulas</p>",
        unsafe_allow_html=True,
    )

    ICONOS_ESTADO = {
        "Calibrada": "🟢",
        "Abierta": "🔵",
        "Cerrada": "🔴",
        "Dañada": "⛔",
        "Descalibrada": "🟠",
        "Habilitada": "🔷",
        "No opera": "⚫",
        "Pendiente": "⚠️",
    }

    for estado in OPCIONES_ESTADO_VALVULA:
      df_filtro = df_sidebar_valvulas[
          df_sidebar_valvulas["estatus"].str.strip().str.lower()
          == estado.lower()
      ]
      conteo = len(df_filtro)
      icono = ICONOS_ESTADO.get(estado, "⚪")

      with st.expander(f"{icono} {estado} ({conteo})"):
        if conteo > 0:
          for _, v_row in df_filtro.iterrows():
            st.markdown(
                f"""
                            <div style="padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.78rem;">
                                <strong style="color: #00E5FF;">{v_row['id']}</strong><br>
                                <span style="color: #94A3B8;">📍 {v_row['domicilio'] or 'Sin dom.'}</span>
                            </div>
                            """,
                unsafe_allow_html=True,
            )
        else:
          st.markdown(
              "<span style='color: #64748B; font-size: 0.75rem;'>Sin"
              " registros</span>",
              unsafe_allow_html=True,
          )

  st.markdown("<br>", unsafe_allow_html=True)

  if st.button("Cerrar Sesión", key="btn_logout", use_container_width=True):
    st.session_state.autenticado = False
    st.session_state.gestor_bd_autenticado = False
    st.rerun()

# 07 SECCION ------------------------------------------------------------------------ CABECERA PRINCIPAL ---------------------------------------------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align: center; margin-bottom: 10px; margin-top: 0px;">
        <h1 style="color: #00E5FF; font-size: 1.8rem; font-weight: 800; margin: 0; letter-spacing: -0.5px;">Gestión Válvulas Reductoras de Presión</h1>
    </div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<hr style='border: 0.5px solid rgba(0,229,255,0.2); margin: 10px 0;'>",
    unsafe_allow_html=True,
)

COLUMNAS_VPRS = """
    id_0, id, num_serie, fecha_inst, tipo_valv, diametro, marca, modelo, trim, 
    control_au, domicilio, colonia, sect_hidr, distrito, cota_terr, estatus, condicion, 
    cal_antd, cal_antn, fecha_vis, p_ab, p_arr, cal_postd, cal_postn, prog_hor, 
    fecha_mtto, tim_cambio, fecha_tim, obs, _ult_visita, _p_ab, _p_arr, fotos, fotos_2,
    ST_X(geom) as coord_x, ST_Y(geom) as coord_y
"""

# 08 SECCION ---------------------------------------------------------------------------- VER REGISTROS (VRP_Oficial) ------------------------------------------------------------------------------------------------

if st.session_state.active_tab == "📍 Registros":

  st.markdown(
      """
        <style>
        div[data-baseweb="tab-list"] {
            gap: 2px;
            background-color: #5B63B7;
            padding: 4px 4px 0px 4px;
            border-radius: 6px 6px 0px 0px;
        }

        div[data-baseweb="tab-list"] button {
            background-color: #8C93D3 !important;
            color: #FFFFFF !important;
            font-weight: bold !important;
            border-radius: 6px 6px 0px 0px !important;
            padding: 10px 20px !important;
            border: none !important;
            margin-right: 2px !important;
        }

        div[data-baseweb="tab-list"] button[aria-selected="true"] {
            background-color: #FFFFFF !important;
            color: #4A52A0 !important;
            border-top: 3px solid #3F468F !important;
        }

        div[data-baseweb="tab-highlight"] {
            background-color: transparent !important;
        }
        </style>
        """,
      unsafe_allow_html=True,
  )

  tab_registros, tab_bd_completa, tab_sheets, tab_comparativa, tab_gestor_bd = (
      st.tabs([
          "📍 Registros",
          "🗄️ Tabla Base de Datos Completa",
          "📊 2.Informe visitas a VRP´s (Sheets)",
          "🔍 Comparativa (BD vs Sheets)",
          "🛠️️ Gestión BD",
      ])
  )

  with tab_registros:
    busqueda = st.text_input(
        "🔍 Buscar válvula (ID, Num. Serie, Domicilio, Col.):",
        placeholder="Ej. VF01, Centro...",
    )

    if busqueda and busqueda.strip() != "":
      filtro = f"%{busqueda.strip()}%"
      query = f"""
                SELECT {COLUMNAS_VPRS} 
                FROM "Agua_potable"."VRP_Oficial" 
                WHERE id ILIKE :filtro 
                   OR num_serie ILIKE :filtro 
                   OR domicilio ILIKE :filtro 
                   OR colonia ILIKE :filtro 
                ORDER BY id_0
            """
      df_vprs, error_db = obtener_datos(query, {"filtro": filtro})
    else:
      query = (
          f'SELECT {COLUMNAS_VPRS} FROM "Agua_potable"."VRP_Oficial" ORDER BY id_0'
          " LIMIT 15"
      )
      df_vprs, error_db = obtener_datos(query)

    if error_db:
      st.error(f"❌ Error al consultar PostgreSQL: {error_db}")
    elif not df_vprs.empty:
      if not busqueda or busqueda.strip() == "":
        st.markdown(
            "<p style='color: #94A3B8; font-size: 0.85rem; margin-bottom:"
            " 10px;'>Mostrando primeros 15 registros.</p>",
            unsafe_allow_html=True,
        )
      else:
        st.markdown(
            f"<p style='color: #94A3B8; font-size: 0.85rem; margin-bottom:"
            f" 10px;'>Se encontraron {len(df_vprs)} registros.</p>",
            unsafe_allow_html=True,
        )

      for idx, row in df_vprs.iterrows():
        serie_val = row["num_serie"]
        serie_texto = (
            ""
            if (
                pd.isna(serie_val)
                or str(serie_val).strip().lower() in ["nan", "none", ""]
            )
            else f" | Num. Serie: {serie_val}"
        )

        card_html = f"""
                    <div class="user-card">
                        <span style="font-size: 0.95rem; font-weight: bold; color: #F8FAFC;">ID: {row['id']}{serie_texto}</span><br>
                        <span style="color: #00E5FF; font-size: 0.85rem;">📍 {row['domicilio'] or 'Sin domicilio'}, Col. {row['colonia'] or 'Sin colonia'}</span>
                    </div>
                """
        st.markdown(card_html, unsafe_allow_html=True)

        with st.expander("🔍 Ver detalles completos y fotografías"):
          geom_str = (
              f"POINT ({row['coord_x']} {row['coord_y']})"
              if pd.notna(row["coord_x"]) and pd.notna(row["coord_y"])
              else "Sin geometría"
          )
          detalle_html = f"""
                        <span style="color: #94A3B8; font-size: 0.8rem; line-height: 1.6;">
                            <b>Diámetro:</b> {row['diametro']} pulgadas &nbsp;|&nbsp; <b>Marca:</b> {row['marca']} &nbsp;|&nbsp; <b>Modelo:</b> {row['modelo']} &nbsp;|&nbsp; <b>Trim:</b> {row['trim']} &nbsp;|&nbsp; <b>Cota:</b> {row['cota_terr']}<br>
                            <b>Sector:</b> {row['sect_hidr']} &nbsp;|&nbsp; <b>Estado:</b> {row['estatus']} &nbsp;|&nbsp; <b>Última Visita:</b> {formatear_fecha_str(row['fecha_vis'])}<br>
                            <b>Fecha Inst.:</b> {formatear_fecha_str(row['fecha_inst'])} &nbsp;|&nbsp; <b>Fecha Mtto:</b> {formatear_fecha_str(row['fecha_mtto'])}<br>
                            <b>Geom:</b> {geom_str}<br>
                            <b>Cal Ant Día:</b> {row['cal_antd']} &nbsp;|&nbsp; <b>Cal Ant Noche:</b> {row['cal_antn']}<br>
                            <b>Cal Post Día:</b> {row['cal_postd']} &nbsp;|&nbsp; <b>Cal Post Noche:</b> {row['cal_postn']}<br>
                            <b>Programación Horaria (prog_hor):</b> {row['prog_hor']}<br>
                            <b>Observaciones:</b> {row['obs']}
                        </span>
                    """
          st.markdown(detalle_html, unsafe_allow_html=True)

          col_img1, col_img2 = st.columns(2)
          with col_img1:
            img_bytes = procesar_bytes_foto(row["fotos"])
            if img_bytes is not None and len(img_bytes) > 0:
              st.markdown(
                  "<p style='color: #00E5FF; font-size: 0.85rem; margin-top:"
                  " 10px; margin-bottom: 5px;'>📸 Fotografía 1:</p>",
                  unsafe_allow_html=True,
              )
              st.image(
                  img_bytes,
                  caption=f"ID: {row['id']} (Foto 1)",
                  use_container_width=True,
              )

          with col_img2:
            img_bytes_2 = procesar_bytes_foto(row["fotos_2"])
            if img_bytes_2 is not None and len(img_bytes_2) > 0:
              st.markdown(
                  "<p style='color: #00E5FF; font-size: 0.85rem; margin-top:"
                  " 10px; margin-bottom: 5px;'>📸 Fotografía 2:</p>",
                  unsafe_allow_html=True,
              )
              st.image(
                  img_bytes_2,
                  caption=f"ID: {row['id']} (Foto 2)",
                  use_container_width=True,
              )
    else:
      st.info("No se encontraron registros.")

  with tab_bd_completa:
    st.markdown("### Tabla Completa de VRP_Oficial (Base de Datos)")

    query_completa = (
        f'SELECT {COLUMNAS_VPRS} FROM "Agua_potable"."VRP_Oficial" ORDER BY id_0 ASC;'
    )
    df_completo, err_bd_comp = obtener_datos(query_completa)

    if err_bd_comp:
      st.error(f"❌ Error al consultar la base de datos: {err_bd_comp}")
    elif not df_completo.empty:
      df_completo_fmt = formatear_columnas_fecha(df_completo)
      st.dataframe(
          df_completo_fmt, use_container_width=True, hide_index=True, height=650
      )
      st.caption(f"Total de registros en base de datos: {len(df_completo)}")
    else:
      st.warning("⚠️ No se encontraron registros en la base de datos.")

  with tab_sheets:
    st.markdown("### Hoja de Cálculo: 2.Informe visitas a VRP´s")

    sheet_url_editable = "https://docs.google.com/spreadsheets/d/1am_DvVrUYPYqXnH8Pt3xoeMuG6BFr4z2x8PBRNskB-M/edit?rm=embedded&gid=769091515#gid=769091515"

    st.markdown(
        f"""
        <iframe 
            src="{sheet_url_editable}" 
            style="width: 100%; height: 80vh; border: 1px solid #334155; border-radius: 0px 0px 8px 8px;" 
            allowfullscreen>
        </iframe>
        """,
        unsafe_allow_html=True,
    )

    st.link_button(
        "🔗 Abrir hoja directamente en pestaña de Google Sheets",
        "https://docs.google.com/spreadsheets/d/1am_DvVrUYPYqXnH8Pt3xoeMuG6BFr4z2x8PBRNskB-M/edit#gid=769091515",
    )

  with tab_comparativa:
    st.markdown(
        "### 🔍 Auditoría y Comparativa: BD vs Hoja '2.Informe visitas a VRP´s'"
    )
    st.info(
        "📌 **Prioridad:** Base de Datos. Esta herramienta evalúa la pestaña"
        " específica de Sheets frente a PostgreSQL independientemente de"
        " mayúsculas o minúsculas en 'ID'."
    )

    if st.button("🔄 Ejecutar Comparación de Datos"):
      with st.spinner("Procesando datos de la pestaña especificada..."):
        query_audit = f'SELECT {COLUMNAS_VPRS} FROM "Agua_potable"."VRP_Oficial";'
        df_bd, err_audit_bd = obtener_datos(query_audit)

        csv_sheets_url = "https://docs.google.com/spreadsheets/d/1am_DvVrUYPYqXnH8Pt3xoeMuG6BFr4z2x8PBRNskB-M/gviz/tq?tqx=out:csv&gid=769091515"

        try:
          df_sheets = pd.read_csv(csv_sheets_url)
          err_sheets = None
        except Exception as e:
          err_sheets = str(e)
          df_sheets = pd.DataFrame()

        if err_audit_bd:
          st.error(f"❌ Error al consultar la Base de Datos: {err_audit_bd}")
        elif err_sheets:
          st.error(
              f"❌ Error al descargar datos de la pestaña de Sheets:"
              f" {err_sheets}."
          )
        else:
          col_id_sheets = [
              c for c in df_sheets.columns if str(c).strip().lower() == "id"
          ]
          col_id_bd = [
              c for c in df_bd.columns if str(c).strip().lower() == "id"
          ]

          if not col_id_sheets:
            st.error(
                "❌ No se encontró la columna 'ID' o 'id' en la pestaña de"
                " Sheets."
                f" Columnas detectadas: {list(df_sheets.columns)}"
            )
          elif not col_id_bd:
            st.error(
                "❌ No se encontró la columna 'id' en la consulta de la Base de"
                " Datos."
            )
          else:
            name_id_sheets = col_id_sheets[0]
            name_id_bd = col_id_bd[0]

            df_bd["id_clean"] = (
                df_bd[name_id_bd].astype(str).str.strip().str.upper()
            )
            df_sheets["id_clean"] = (
                df_sheets[name_id_sheets].astype(str).str.strip().str.upper()
            )

            df_bd = df_bd[~df_bd["id_clean"].isin(["NAN", "NONE", ""])]
            df_sheets = df_sheets[~df_sheets["id_clean"].isin(["NAN", "NONE", ""])]

            ids_bd = set(df_bd["id_clean"].unique())
            ids_sheets = set(df_sheets["id_clean"].unique())

            ids_solo_sheets = ids_sheets - ids_bd
            df_solo_sheets = df_sheets[
                df_sheets["id_clean"].isin(ids_solo_sheets)
            ]

            ids_solo_bd = ids_bd - ids_sheets
            df_solo_bd = df_bd[df_bd["id_clean"].isin(ids_solo_bd)]

            ids_comunes = ids_bd.intersection(ids_sheets)

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Registros BD", len(ids_bd))
            col_m2.metric("Registros en Pestaña Sheets", len(ids_sheets))
            col_m3.metric(
                "⚠️ En Sheets y NO en BD",
                len(ids_solo_sheets),
                delta_color="inverse",
            )
            col_m4.metric("Coinciden en ID", len(ids_comunes))

            st.markdown("---")

            st.markdown(
                "#### 🚨 1. Registros presentes en '2.Informe visitas a VRP´s'"
                " que NO existen en la Base de Datos"
            )
            if not df_solo_sheets.empty:
              st.warning(
                  f"Se encontraron **{len(df_solo_sheets)}** registros en la"
                  " pestaña de Sheets que no están registrados en PostgreSQL:"
              )
              cols_mostrar_sheets = [
                  c for c in df_solo_sheets.columns if c != "id_clean"
              ]
              st.dataframe(
                  df_solo_sheets[cols_mostrar_sheets],
                  use_container_width=True,
                  hide_index=True,
              )
            else:
              st.success(
                  "✅ Todos los registros de la pestaña de Sheets existen en la"
                  " Base de Datos."
              )

            with st.expander("ℹ️ 2. Registros en Base de Datos que FALTAN en Sheets"):
              if not df_solo_bd.empty:
                st.info(
                    f"Hay **{len(df_solo_bd)}** registros de PostgreSQL que no"
                    " se encuentran en la pestaña de Sheets:"
                )
                cols_mostrar_bd = [
                    c for c in df_bd.columns if c != "id_clean"
                ]
                st.dataframe(
                    df_solo_bd[cols_mostrar_bd],
                    use_container_width=True,
                    hide_index=True,
                )
              else:
                st.success(
                    "✅ Todos los registros de la Base de Datos están"
                    " presentes en la pestaña de Sheets."
                )

            with st.expander("🔍 3. Diferencias de atributos en IDs comunes"):
              cols_map_bd = {
                  str(c).strip().lower(): c
                  for c in df_bd.columns
                  if c not in ["id_clean", name_id_bd]
              }
              cols_map_sh = {
                  str(c).strip().lower(): c
                  for c in df_sheets.columns
                  if c not in ["id_clean", name_id_sheets]
              }

              columnas_comunes_keys = list(
                  set(cols_map_bd.keys()).intersection(set(cols_map_sh.keys()))
              )

              if not columnas_comunes_keys:
                st.caption(
                    "No se detectaron nombres de columnas adicionales coincidentes"
                    " entre ambas fuentes para comparar contenido campo a"
                    " campo."
                )
              else:
                df_merged = pd.merge(
                    df_bd,
                    df_sheets,
                    on="id_clean",
                    suffixes=("_BD", "_Sheets"),
                )
                diferencias_list = []

                def son_valores_equivalentes(val1, val2, es_fecha=False):
                  s1 = (
                      str(val1).strip().lower()
                      if pd.notna(val1)
                      else ""
                  )
                  s2 = (
                      str(val2).strip().lower()
                      if pd.notna(val2)
                      else ""
                  )

                  s1 = "" if s1 in ["nan", "none", "nat", ""] else s1
                  s2 = "" if s2 in ["nan", "none", "nat", ""] else s2

                  if s1 == s2:
                    return True

                  if es_fecha:
                    try:
                      dt1 = pd.to_datetime(val1, dayfirst=True, errors="coerce")
                      if pd.isna(dt1):
                        dt1 = pd.to_datetime(val1, errors="coerce")
                      dt2 = pd.to_datetime(val2, dayfirst=True, errors="coerce")
                      if pd.isna(dt2):
                        dt2 = pd.to_datetime(val2, errors="coerce")
                      if pd.notna(dt1) and pd.notna(dt2):
                        return dt1.date() == dt2.date()
                    except Exception:
                      pass

                  try:
                    f1 = float(s1)
                    f2 = float(s2)
                    return f1 == f2
                  except ValueError:
                    pass

                  return False

                for key_col in columnas_comunes_keys:
                  col_bd_real = cols_map_bd[key_col]
                  col_sh_real = cols_map_sh[key_col]

                  col_bd_name = (
                      f"{col_bd_real}_BD"
                      if col_bd_real in df_sheets.columns
                      else col_bd_real
                  )
                  col_sh_name = (
                      f"{col_sh_real}_Sheets"
                      if col_sh_real in df_bd.columns
                      else col_sh_real
                  )

                  if (
                      col_bd_name in df_merged.columns
                      and col_sh_name in df_merged.columns
                  ):
                    es_col_fecha = col_bd_real in COLUMNAS_FECHA

                    for _, row_d in df_merged.iterrows():
                      v_bd = row_d[col_bd_name]
                      v_sh = row_d[col_sh_name]

                      if not son_valores_equivalentes(v_bd, v_sh, es_fecha=es_col_fecha):
                        v_bd_mostrar = (
                            formatear_fecha_str(v_bd)
                            if es_col_fecha
                            else v_bd
                        )
                        diferencias_list.append({
                            "ID Válvula": row_d["id_clean"],
                            "Campo": col_bd_real,
                            "Valor en BD (Prioritario)": v_bd_mostrar,
                            "Valor en Sheets": v_sh,
                        })

                if diferencias_list:
                  df_diff_final = pd.DataFrame(diferencias_list)
                  st.warning(
                      f"Se detectaron **{len(df_diff_final)}** diferencias en"
                      " campos para registros con el mismo ID:"
                  )
                  st.dataframe(
                      df_diff_final,
                      use_container_width=True,
                      hide_index=True,
                  )
                else:
                  st.success(
                      "✅ Los valores en las columnas coincidentes son"
                      " idénticos para todos los IDs en común."
                  )

  with tab_gestor_bd:
    usuario_actual_sesion = str(st.session_state.get("usuario_actual", "")).strip().lower()

    if usuario_actual_sesion != "pedro.templos@miaa.mx":
      st.error("⛔ Acceso denegado. Esta sección está protegida y es exclusiva para el usuario pedro.templos@miaa.mx.")
    else:
      if not st.session_state.get("gestor_bd_autenticado", False):
        st.markdown("### 🔐 Sección Protegida - Gestión BD")
        pass_gestor = st.text_input("Ingrese la contraseña de seguridad para acceder a Gestión BD:", type="password", key="pass_gestor_input")
        if st.button("Desbloquear Gestión BD"):
          if pass_gestor == "MIAA2026":
            st.session_state.gestor_bd_autenticado = True
            st.success("¡Acceso concedido!")
            t.sleep(0.5)
            st.rerun()
          else:
            st.error("Contraseña incorrecta.")
      else:
        col_t_title, col_t_btn = st.columns([4, 1])
        with col_t_title:
          st.markdown("### 🛠️ Herramientas de Gestión y Mantenimiento de la BD")
        with col_t_btn:
          if st.button("🔒 Bloquear"):
            st.session_state.gestor_bd_autenticado = False
            st.rerun()

        st.info(
            "📌 Administra el vaciado masivo, actualizaciones e inserciones masivas por CSV usando `id_0` como identificador, y traspasos de información."
        )

        st.markdown("---")
        st.markdown("#### 1️⃣ Zona de Peligro: Vaciar Tabla de Base de Datos")
        st.warning(
            "⚠️ Esta acción eliminará **todos** los registros de la tabla"
            ' `"Agua_potable"."VRP_Oficial"`. Utilízala con extrema precaución.'
        )

        if "confirmar_borrado_total" not in st.session_state:
          st.session_state.confirmar_borrado_total = False

        if not st.session_state.confirmar_borrado_total:
          if st.button("🗑️ Eliminar TODOS los registros de la BD"):
            st.session_state.confirmar_borrado_total = True
            st.rerun()
        else:
          st.error(
              "🚨 ¿Estás completamente seguro? Esta acción no se puede deshacer."
          )
          col_bt_del1, col_bt_del2 = st.columns(2)
          with col_bt_del1:
            if st.button("⚠️ Sí, borrar absolutamente todo"):
              try:
                ejecutar_sql('DELETE FROM "Agua_potable"."VRP_Oficial";')
                st.session_state.confirmar_borrado_total = False
                st.success("¡Todos los registros han sido eliminados de la BD!")
                t.sleep(1)
                st.rerun()
              except Exception as ex_all:
                st.error(f"Error al vaciar la tabla: {ex_all}")
          with col_bt_del2:
            if st.button("❌ Cancelar borrado masivo"):
              st.session_state.confirmar_borrado_total = False
              st.rerun()

        st.markdown("---")
        st.markdown("#### 2️⃣ Actualización e Inserción Masiva (CSV)")
        st.write(
            "Sube un archivo CSV que contenga obligatoriamente la columna identificadora `id_0` para actualizar registros existentes o insertar nuevos automáticamente."
        )

        archivo_csv_subido = st.file_uploader(
            "Cargar archivo CSV",
            type=["csv"],
            key="csv_gestor_uploader",
        )

        if archivo_csv_subido is not None:
          try:
            df_csv_input = pd.read_csv(archivo_csv_subido)
            df_csv_input.columns = [str(c).strip() for c in df_csv_input.columns]

            if "id_0" not in df_csv_input.columns and "ID_0" not in df_csv_input.columns:
              st.error("❌ El archivo CSV debe contener obligatoriamente una columna llamada `id_0` como identificador.")
            else:
              col_id_csv = "id_0" if "id_0" in df_csv_input.columns else "ID_0"
              st.success(
                  f"CSV cargado correctamente ({len(df_csv_input)} filas detectadas). Identificador principal: `id_0`."
              )
              st.dataframe(df_csv_input.head(5), use_container_width=True)

              cols_csv = list(df_csv_input.columns)
              columnas_a_procesar = st.multiselect(
                  "Selecciona qué columnas deseas actualizar/insertar en la BD:",
                  options=[c for c in cols_csv if c.lower() != "id_0"],
                  default=[
                      c for c in cols_csv 
                      if c.lower() != "id_0" and c.lower() in [
                          "id", "estatus", "domicilio", "colonia", "obs", "observaciones", 
                          "diametro", "marca", "modelo", "trim", "sect_hidr", "cota_terr",
                          "cal_antd", "cal_antn", "cal_postd", "cal_postn", "prog_hor", "tipo_valv", "num_serie"
                      ]
                  ],
              )

              if st.button("🚀 Ejecutar Inserción/Actualización en Lotes de 50 en 50"):
                if not columnas_a_procesar:
                  st.warning("Debes seleccionar al menos una columna para procesar.")
                else:
                  actualizados_count = 0
                  insertados_count = 0
                  errores_count = 0
                  lista_errores_detalle = []
                  
                  total_filas = len(df_csv_input)
                  tamano_lote = 50
                  
                  progress_bar = st.progress(0)
                  status_text = st.empty()

                  for i in range(0, total_filas, tamano_lote):
                    lote_df = df_csv_input.iloc[i:i + tamano_lote]
                    
                    try:
                      with st.session_state.db_engine.connect() as conn:
                        with conn.begin():
                          for _, row_c in lote_df.iterrows():
                            val_id_0 = row_c[col_id_csv]
                            if pd.isna(val_id_0):
                              continue
                            try:
                              val_id_0_int = int(val_id_0)
                            except:
                              continue

                            check_query = text('SELECT id_0 FROM "Agua_potable"."VRP_Oficial" WHERE id_0 = :id0')
                            res_chk = conn.execute(check_query, {"id0": val_id_0_int}).fetchone()

                            params_dict = {"id_0": val_id_0_int}
                            set_clauses = []
                            insert_cols = ["id_0"]
                            insert_vals = [":id_0"]

                            for col_p in columnas_a_procesar:
                              val_val = row_c[col_p]
                              if pd.isna(val_val):
                                val_val = None
                              set_clauses.append(f'"{col_p}" = :{col_p}')
                              insert_cols.append(f'"{col_p}"')
                              insert_vals.append(f':{col_p}')
                              params_dict[col_p] = val_val

                            try:
                              with conn.begin_nested():
                                if res_chk:
                                  if set_clauses:
                                    sql_update_csv = text(f"""
                                        UPDATE "Agua_potable"."VRP_Oficial" 
                                        SET {", ".join(set_clauses)}
                                        WHERE id_0 = :id_0;
                                    """)
                                    conn.execute(sql_update_csv, params_dict)
                                    actualizados_count += 1
                                else:
                                  sql_insert_csv = text(f"""
                                        INSERT INTO "Agua_potable"."VRP_Oficial" ({", ".join(insert_cols)})
                                        VALUES ({", ".join(insert_vals)});
                                    """)
                                  conn.execute(sql_insert_csv, params_dict)
                                  insertados_count += 1
                            except Exception as ex_fila:
                              errores_count += 1
                              if len(lista_errores_detalle) < 5:
                                lista_errores_detalle.append(f"ID_0 {val_id_0_int}: {str(ex_fila)}")
                              continue

                    except Exception as e_lote:
                      st.error(f"Error crítico en el lote {i}: {e_lote}")

                    porcentaje = min(1.0, (i + tamano_lote) / total_filas)
                    progress_bar.progress(porcentaje)
                    status_text.text(f"Procesando registros... {min(i + tamano_lote, total_filas)} de {total_filas}")

                  st.success(
                      f"¡Proceso por lotes finalizado! Actualizados: {actualizados_count} | Insertados: {insertados_count} | Errores omitidos: {errores_count}."
                  )
                  if lista_errores_detalle:
                    st.warning("⚠️ Primeros errores detallados detectados en las filas:")
                    for err_det in lista_errores_detalle:
                      st.code(err_det)

                  t.sleep(1.5)
                  st.rerun()

          except Exception as e_csv:
            st.error(f"Error al leer el archivo CSV: {e_csv}")

        st.markdown("---")
        st.markdown(
            "#### 3️⃣ Traspaso Bidireccional Selectivo (Sheets ⇄ Base de Datos)"
        )
        traspaso_dir = st.radio(
            "Dirección del Traspaso:",
            [
                "📤 De Google Sheets hacia Base de Datos",
                "📥 De Base de Datos hacia Google Sheets (Exportación)",
            ],
            horizontal=True,
        )

        query_bd_traspaso = f'SELECT {COLUMNAS_VPRS} FROM "Agua_potable"."VRP_Oficial";'
        df_bd_t, err_t_bd = obtener_datos(query_bd_traspaso)

        csv_sheets_traspaso_url = "https://docs.google.com/spreadsheets/d/1am_DvVrUYPYqXnH8Pt3xoeMuG6BFr4z2x8PBRNskB-M/gviz/tq?tqx=out:csv&gid=769091515"
        try:
          df_sh_t = pd.read_csv(csv_sheets_traspaso_url)
          err_t_sh = None
        except Exception as e_sh_t:
          df_sh_t = pd.DataFrame()
          err_t_sh = str(e_sh_t)

        if err_t_bd or err_t_sh:
          st.error("❌ No se pudieron cargar los datos de ambas fuentes para realizar el traspaso.")
        elif not df_bd_t.empty and not df_sh_t.empty:
          if "De Google Sheets hacia Base de Datos" in traspaso_dir:
            st.info("Se sincronizarán los campos seleccionados tomando como fuente Google Sheets y emparejándolos por el campo ID.")
            cols_sh_disp = [c for c in df_sh_t.columns if str(c).strip().lower() not in ["id_clean"]]
            campos_a_pasar_sh = st.multiselect(
                "Selecciona los campos de Sheets que quieres pasar a la BD:",
                options=cols_sh_disp,
            )

            if st.button("🔄 Importar Campos Seleccionados desde Sheets"):
              if not campos_a_pasar_sh:
                st.warning("Selecciona al menos un campo para traspasar.")
              else:
                actualizados_sh_db = 0
                with st.spinner("Traspasando información..."):
                  for _, row_sh in df_sh_t.iterrows():
                    id_sh_val = str(row_sh.get("id", "")).strip()
                    if not id_sh_val or id_sh_val.lower() in ["nan", "none", ""]:
                      continue

                    set_parts = []
                    params_sh = {"id_val": id_sh_val}
                    for c_sh in campos_a_pasar_sh:
                      val_cell = row_sh[c_sh]
                      if pd.isna(val_cell):
                        val_cell = None
                      if c_sh in df_bd_t.columns:
                        set_parts.append(f'"{c_sh}" = :{c_sh}')
                        params_sh[c_sh] = val_cell

                    if set_parts:
                      sql_trasp_sh = f"""
                                        UPDATE "Agua_potable"."VRP_Oficial" 
                                        SET {", ".join(set_parts)}
                                        WHERE TRIM(id) ILIKE :id_val;
                                    """
                      try:
                        ejecutar_sql(sql_trasp_sh, params_sh)
                        actualizados_sh_db += 1
                      except Exception:
                        pass

                st.success(f"¡Traspaso completado! Se actualizaron {actualizados_sh_db} registros en la BD desde Sheets.")
                t.sleep(1)
                st.rerun()
          else:
            cols_bd_disp = [c for c in df_bd_t.columns if c not in ["geom", "coord_x", "coord_y", "id_clean"]]
            campos_a_pasar_bd = st.multiselect(
                "Selecciona los campos de la BD que deseas exportar:",
                options=cols_bd_disp,
            )

            if campos_a_pasar_bd:
              df_exportable = df_bd_t[["id"] + campos_a_pasar_bd].copy()
              csv_export = df_exportable.to_csv(index=False).encode("utf-8")
              st.download_button(
                  label="📥 Descargar CSV con Campos Seleccionados de la BD",
                  data=csv_export,
                  file_name="traspaso_bd_a_sheets.csv",
                  mime="text/csv",
              )

# 09 SECCION ------------------------------------------------------------ MAPA DE VRPs Y SECTORES HIDRÁULICOS (POSTGIS) -----------------------------------------------------------------------------------------

elif st.session_state.active_tab == "🗺️ Mapa":
  query_mapa = """
        SELECT 
            id_0,
            id,
            estatus,
            domicilio,
            colonia,
            ST_X(geom) as x,
            ST_Y(geom) as y
        FROM "Agua_potable"."VRP_Oficial"
        WHERE geom IS NOT NULL;
    """
  df_mapa, err_mapa = obtener_datos(query_mapa)

  query_sectores = """
        SELECT 
            objectid as fid,
            sector,
            ST_AsGeoJSON(ST_MakeValid(ST_Force2D(ST_Transform(geom, 4326)))) as geojson
        FROM "Sectorizacion"."Sectores_hidr"
        WHERE geom IS NOT NULL;
    """
  df_sectores, err_sectores = obtener_datos(query_sectores)

  if err_mapa:
    st.error(f"❌ Error al cargar datos espaciales de VPRs: {err_mapa}")
  else:
    CONFIG_ESTADOS = {
        "calibrada": {"color": "#2ECC71", "emoji": "🟢", "forma": "circulo"},
        "abierta": {"color": "#3498DB", "emoji": "🔵", "forma": "circulo"},
        "cerrada": {"color": "#E74C3C", "emoji": "🔴", "forma": "circulo"},
        "dañada": {"color": "#E84393", "emoji": "⛔", "forma": "circulo"},
        "descalibrada": {"color": "#F1C40F", "emoji": "⚠️", "forma": "triangulo"},
        "habilitada": {"color": "#38B6FF", "emoji": "🔷", "forma": "rombo"},
        "no opera": {"color": "#A0A0A0", "emoji": "⚫", "forma": "circulo"},
        "pendiente": {"color": "#F1C40F", "emoji": "⚠️", "forma": "triangulo"},
        "amarillo": {"color": "#F1C40F", "emoji": "🟡", "forma": "circulo"},
    }

    m = folium.Map(
        location=[21.8853, -102.2916], zoom_start=13, control_scale=True
    )

    agregar_capas_base_mapa(m)
    Fullscreen().add_to(m)

    fg_sectores = folium.FeatureGroup(
        name="📐 Sectores Hidráulicos", show=True
    )

    if not err_sectores and not df_sectores.empty:
      import json

      def estilo_final_sector(feature):
        props = feature.get("properties", {})
        nombre_actual = props.get("sector")
        sec_sel = st.session_state.get("sector_resaltado")

        es_match = (
            sec_sel is not None and nombre_actual == sec_sel.get("sector")
        )
        afectacion_val = props.get("afectacion", 0)
        color_dinamico = props.get("color_dinamico", "#2980B9")

        fill_color_final = "#F1C40F" if es_match else color_dinamico

        if es_match:
          border_color_final = "#F39C12"
          weight_final = 3
          opacity_final = 0.5
        elif afectacion_val > 0:
          border_color_final = color_dinamico
          weight_final = 2.5
          opacity_final = 0.25
        else:
          border_color_final = "#2980B9"
          weight_final = 1
          opacity_final = 0.08

        return {
            "fillColor": fill_color_final,
            "color": border_color_final,
            "weight": weight_final,
            "fillOpacity": opacity_final,
        }

      def estilo_hover_sector(feature):
        return {"fillOpacity": 0.12, "weight": 2, "color": "#FFFFFF"}

      for _, sec_row in df_sectores.iterrows():
        try:
          raw_json = sec_row["geojson"]
          if pd.isna(raw_json) or not raw_json:
            continue
          
          geom_json = json.loads(raw_json)

          feature_estructurado = {
              "type": "Feature",
              "geometry": geom_json,
              "properties": {
                  "sector": str(sec_row.get("sector", "Sin Nombre")),
                  "fid": sec_row.get("fid"),
                  "afectacion": 0,
                  "color_dinamico": "#2980B9",
              },
          }

          folium.GeoJson(
              feature_estructurado,
              style_function=estilo_final_sector,
              highlight_function=estilo_hover_sector,
              tooltip=folium.GeoJsonTooltip(
                  fields=["sector"],
                  aliases=["Sector:"],
                  localize=True,
                  sticky=True,
              ),
          ).add_to(fg_sectores)
        except Exception as e:
          continue

    fg_sectores.add_to(m)

    grupos_capas = {}
    success_count = 0

    if not df_mapa.empty:
      for estado_opc in OPCIONES_ESTADO_VALVULA:
        count_est = len(
            df_mapa[
                df_mapa["estatus"].str.strip().str.lower()
                == estado_opc.lower()
            ]
        )
        conf = CONFIG_ESTADOS.get(
            estado_opc.lower(),
            {"color": "#95A5A6", "emoji": "⚪", "forma": "circulo"},
        )

        fg = folium.FeatureGroup(
            name=f"{conf['emoji']} {estado_opc} ({count_est})", show=True
        )
        fg.add_to(m)
        grupos_capas[estado_opc.lower()] = fg

      fg_otros = folium.FeatureGroup(name="⚪ Otros / Sin Estado", show=True)
      fg_otros.add_to(m)

      for _, row in df_mapa.iterrows():
        try:
          lon, lat = transformer_to_latlon.transform(row["x"], row["y"])
          estado_raw = str(row["estatus"] or "Desconocido").strip()
          estado_key = estado_raw.lower()
          id_vrp = str(row["id"] or row["id_0"])

          conf_punto = CONFIG_ESTADOS.get(
              estado_key, {"color": "#95A5A6", "emoji": "⚪", "forma": "circulo"}
          )
          color_hex = conf_punto["color"]
          emoji_punto = conf_punto["emoji"]
          tipo_forma = conf_punto["forma"]

          grupo_destino = grupos_capas.get(estado_key, fg_otros)

          if tipo_forma == "triangulo":
            simbolo_html = f'<span style="font-size: 13px; line-height: 1; filter: drop-shadow(0 0 3px {color_hex});">⚠️</span>'
          elif tipo_forma == "rombo":
            simbolo_html = f"""
                        <span style="
                            height: 10px; 
                            width: 10px; 
                            background-color: {color_hex}; 
                            transform: rotate(45deg); 
                            display: inline-block;
                            box-shadow: 0 0 5px {color_hex};
                        "></span>"""
          else:
            simbolo_html = f"""
                        <span style="
                            height: 10px; 
                            width: 10px; 
                            background-color: {color_hex}; 
                            border-radius: 50%; 
                            display: inline-block;
                            box-shadow: 0 0 5px {color_hex};
                        "></span>"""

          popup_html = f"""
                    <div style="font-size: 0.85rem; color: #000; font-family: sans-serif;">
                        <b>ID:</b> {id_vrp}<br>
                        <b>Estado:</b> {emoji_punto} {estado_raw}<br>
                        <b>Ubicación:</b> {row['domicilio'] or 'Sin domicilio'}, Col. {row['colonia'] or 'Sin colonia'}
                    </div>
                    """

          icon_html = f"""
                    <div style="display: flex; align-items: center; white-space: nowrap;">
                        {simbolo_html}
                        <span style="
                            color: {color_hex}; 
                            font-size: 11px; 
                            font-weight: bold; 
                            font-family: monospace, sans-serif;
                            margin-left: 6px; 
                            text-shadow: 1px 1px 2px #000, -1px -1px 2px #000, 1px -1px 2px #000, -1px 1px 2px #000;
                        ">{id_vrp}</span>
                    </div>
                    """

          folium.Marker(
              location=[lat, lon],
              icon=folium.DivIcon(
                  html=icon_html, icon_size=(150, 16), icon_anchor=(5, 8)
              ),
              popup=folium.Popup(popup_html, max_width=300),
          ).add_to(grupo_destino)

          success_count += 1
        except Exception:
          continue

    folium.LayerControl(collapsed=False).add_to(m)

    st.markdown(
        """
        <style>
        iframe[title="streamlit_folium.st_folium"] {
            height: 85vh !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st_folium(m, width="100%", height=800, returned_objects=[])

    total_sectores = len(df_sectores) if not df_sectores.empty else 0
    st.markdown(
        f"<p style='color: #94A3B8; font-size: 0.85rem; margin-top: 10px;'>Se"
        f" renderizaron {total_sectores} sectores hidráulicos y"
        f" {success_count} VRPs georreferenciadas.</p>",
        unsafe_allow_html=True,
    )

# 10 SECCION --------------------------------------------------------------------- AÑADIR NUEVA VÁLVULA ---------------------------------------------------------------------------------------------

elif st.session_state.active_tab == "➕ Añadir":
  if es_operador:
    st.error(
        "⛔ El perfil de operador no tiene permisos para dar de alta nueva"
        " infraestructura."
    )
    st.stop()

  df_max_id0, err_max = obtener_datos(
      'SELECT MAX(id_0) as max_id FROM "Agua_potable"."VRP_Oficial"'
  )
  siguiente_id_0 = 1
  if (
      not err_max
      and not df_max_id0.empty
      and df_max_id0["max_id"].iloc[0] is not None
  ):
    try:
      siguiente_id_0 = int(df_max_id0["max_id"].iloc[0]) + 1
    except Exception:
      siguiente_id_0 = 1

  if "add_coord_x_input" not in st.session_state:
    st.session_state["add_coord_x_input"] = 0.0
  if "add_coord_y_input" not in st.session_state:
    st.session_state["add_coord_y_input"] = 0.0

  a_c1, a_c2, a_c3, a_c4 = st.columns(4)
  with a_c1:
    st.text_input(
        "ID_0 (Registro)",
        value=str(siguiente_id_0),
        disabled=True,
        key="add_id_0_bloq",
    )
    val_id_0 = siguiente_id_0
  with a_c2:
    val_id = st.text_input("ID *Obligatorio", key="add_id")
  with a_c3:
    val_cota = st.number_input("Cota Terreno", value=0.0, key="add_cota")
  with a_c4:
    val_marca = st.text_input("Marca", key="add_marca")

  a_c5, a_c6, a_c7, a_c8 = st.columns(4)
  with a_c5:
    val_num_serie = st.text_input("Num. Serie", key="add_num_serie")
  with a_c6:
    val_diametro = st.number_input(
        "Diámetro", min_value=0, value=0, key="add_diam"
    )
  with a_c7:
    val_modelo = st.text_input("Modelo", key="add_modelo")
  with a_c8:
    val_trim = st.text_input("Trim", key="add_trim")

  a_c9, a_c10, a_c11, a_c12 = st.columns(4)
  with a_c9:
    val_domicilio = st.text_input("Domicilio", key="add_dom")
  with a_c10:
    val_colonia = st.text_input("Colonia", key="add_col")
  with a_c11:
    val_estat = st.selectbox(
        "Estatus",
        options=OPCIONES_ESTADO_VALVULA,
        index=0,
        key="add_estat",
    )
  with a_c12:
    val_sect_hidr = st.text_input("Sector Hidráulico (sect_hidr)", key="add_sect_hidr")

  col_coord_left, col_map_right = st.columns([1, 1])

  with col_map_right:
    st.markdown(
        "<p style='color: #00E5FF; font-size: 0.8rem; font-weight: 700;"
        " margin-top: 0px;'>🗺️ Ubicación Geográfica (geom) - Haga clic en el"
        " mapa para establecer coordenadas automáticamente</p>",
        unsafe_allow_html=True,
    )
    try:
      if (
          st.session_state["add_coord_x_input"] != 0.0
          and st.session_state["add_coord_y_input"] != 0.0
      ):
        lon_add, lat_add = transformer_to_latlon.transform(
            st.session_state["add_coord_x_input"],
            st.session_state["add_coord_y_input"],
        )
        m_add = folium.Map(
            location=[lat_add, lon_add], zoom_start=16, control_scale=True
        )
      else:
        m_add = folium.Map(
            location=[21.8853, -102.2916], zoom_start=12, control_scale=True
        )

      agregar_capas_base_mapa(m_add)
      Fullscreen().add_to(m_add)

      if (
          st.session_state["add_coord_x_input"] != 0.0
          and st.session_state["add_coord_y_input"] != 0.0
      ):
        folium.Marker(
            location=[lat_add, lon_add],
            popup="Nueva VRP",
            icon=folium.Icon(color="cyan", icon="info-sign"),
        ).add_to(m_add)

      folium.LayerControl(collapsed=False).add_to(m_add)
      map_data_add = st_folium(
          m_add,
          width="100%",
          height=325,
          key="map_add_preview",
          returned_objects=["last_clicked"],
      )

      if map_data_add and map_data_add.get("last_clicked"):
        lat_c = map_data_add["last_clicked"]["lat"]
        lon_c = map_data_add["last_clicked"]["lng"]
        utm_x, utm_y = transformer_to_utm.transform(lon_c, lat_c)
        new_x = round(utm_x, 2)
        new_y = round(utm_y, 3)
        if (
            st.session_state["add_coord_x_input"] != new_x
            or st.session_state["add_coord_y_input"] != new_y
        ):
          st.session_state["add_coord_x_input"] = new_x
          st.session_state["add_coord_y_input"] = new_y
          st.rerun()

    except Exception as e_map_add:
      st.info(
          "Haga clic en el mapa para establecer la posición geográfica."
          f" ({e_map_add})"
      )

  with col_coord_left:
    cx1, cx2 = st.columns(2)
    with cx1:
      val_coord_x = st.number_input(
          "Coordenada X",
          format="%.2f",
          key="add_coord_x_input",
      )
    with cx2:
      val_coord_y = st.number_input(
          "Coordenada Y",
          format="%.3f",
          key="add_coord_y_input",
      )

    cc1, cc2 = st.columns(2)
    with cc1:
      val_cal_antd = st.text_input("Calibración Ant. Día (cal_antd)", value="0.0", key="add_cand")
    with cc2:
      val_cal_antn = st.text_input("Calibración Ant. Noche (cal_antn)", value="0.0", key="add_cann")

    cc3, cc4 = st.columns(2)
    with cc3:
      val_cal_postd = st.text_input("Calibración Post. Día (cal_postd)", value="0.0", key="add_cpostd")
    with cc4:
      val_cal_postn = st.text_input("Calibración Post. Noche (cal_postn)", value="0.0", key="add_cpostn")

    cc5, cc6 = st.columns(2)
    with cc5:
      val_prog_hor = st.text_input("Programación Horaria (prog_hor)", key="add_prog_hor")
    with cc6:
      val_tipo_valv = st.text_input("Tipo Válvula (tipo_valv)", key="add_tipovalv")

    val_fecha_obj = st.date_input(
        "Fecha Visita (fecha_vis)",
        value=datetime.date.today(),
        format="DD/MM/YYYY",
        key="add_fecha",
    )
    val_fecha_vis = val_fecha_obj.strftime("%d/%m/%Y")

  val_obs = st.text_area("Observaciones (obs)", key="add_obs")

  st.markdown(
      "<hr style='border: 0.3px solid rgba(0,229,255,0.2); margin: 15px 0;'>",
      unsafe_allow_html=True,
  )
  st.markdown(
      '<h4 style="color: #00E5FF; font-size: 1rem; font-weight: 700;">📸'
      " Registro de Fotografías</h4>",
      unsafe_allow_html=True,
  )

  col_foto1, col_foto2 = st.columns(2)

  with col_foto1:
    st.markdown(
        "<p style='font-weight: 600; font-size: 0.85rem;'>Fotografía 1</p>",
        unsafe_allow_html=True,
    )
    origen_foto_1 = st.radio(
        "Origen Foto 1",
        ["📁 Seleccionar Archivo", "📷 Usar Cámara"],
        key="origen_foto_1",
        horizontal=True,
        label_visibility="collapsed",
    )
    foto_input_1 = None
    if origen_foto_1 == "📁 Seleccionar Archivo":
      foto_input_1 = st.file_uploader(
          "Subir Fotografía 1",
          type=["png", "jpg", "jpeg"],
          key="file_uploader_1",
      )
    else:
      foto_input_1 = st.camera_input(
          "Capturar Fotografía 1",
          key="camara_nuevo_1",
          label_visibility="collapsed",
      )

  with col_foto2:
    st.markdown(
        "<p style='font-weight: 600; font-size: 0.85rem;'>Fotografía 2</p>",
        unsafe_allow_html=True,
    )
    origen_foto_2 = st.radio(
        "Origen Foto 2",
        ["📁 Seleccionar Archivo", "📷 Usar Cámara"],
        key="origen_foto_2",
        horizontal=True,
        label_visibility="collapsed",
    )
    foto_input_2 = None
    if origen_foto_2 == "📁 Seleccionar Archivo":
      foto_input_2 = st.file_uploader(
          "Subir Fotografía 2",
          type=["png", "jpg", "jpeg"],
          key="file_uploader_2",
      )
    else:
      foto_input_2 = st.camera_input(
          "Capturar Fotografía 2",
          key="camara_nuevo_2",
          label_visibility="collapsed",
      )

  st.markdown("<br>", unsafe_allow_html=True)
  if st.button(
      "💾 Guardar Nuevo Registro VRP",
      key="btn_guardar_nuevo",
      use_container_width=True,
  ):
    if val_id:
      try:
        foto_bytes = (
            foto_input_1.getvalue() if foto_input_1 is not None else None
        )
        foto_bytes_2 = (
            foto_input_2.getvalue() if foto_input_2 is not None else None
        )

        sql_insert = """
                    INSERT INTO "Agua_potable"."VRP_Oficial" (
                        id_0, id, num_serie, fecha_inst, tipo_valv, diametro, marca, modelo, trim, 
                        control_au, domicilio, colonia, sect_hidr, distrito, cota_terr, estatus, 
                        condicion, cal_antd, cal_antn, fecha_vis, p_ab, p_arr, cal_postd, cal_postn, 
                        prog_hor, fecha_mtto, tim_cambio, fecha_tim, obs, _ult_visita, _p_ab, _p_arr, 
                        fotos, fotos_2, geom
                    ) VALUES (
                        :id_0, :id, :num_serie, NULL, :tipo_valv, :diametro, :marca, :modelo, :trim, 
                        NULL, :domicilio, :colonia, :sect_hidr, NULL, :cota_terr, :estatus, 
                        NULL, :cal_antd, :cal_antn, :fecha_vis, NULL, NULL, :cal_postd, :cal_postn, 
                        :prog_hor, NULL, NULL, NULL, :obs, NULL, NULL, NULL, 
                        :fotos, :fotos_2, ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                    )
                """
        ejecutar_sql(
            sql_insert,
            {
                "id_0": val_id_0,
                "id": val_id,
                "num_serie": val_num_serie if val_num_serie.strip() != "" else None,
                "tipo_valv": val_tipo_valv if val_tipo_valv.strip() != "" else None,
                "diametro": val_diametro,
                "marca": val_marca,
                "modelo": val_modelo,
                "trim": val_trim,
                "domicilio": val_domicilio,
                "colonia": val_colonia,
                "sect_hidr": val_sect_hidr,
                "cota_terr": val_cota,
                "estatus": val_estat,
                "cal_antd": val_cal_antd if val_cal_antd.strip() != "" else None,
                "cal_antn": val_cal_antn if val_cal_antn.strip() != "" else None,
                "cal_postd": val_cal_postd if val_cal_postd.strip() != "" else None,
                "cal_postn": val_cal_postn if val_cal_postn.strip() != "" else None,
                "prog_hor": val_prog_hor if val_prog_hor.strip() != "" else None,
                "fecha_vis": val_fecha_vis,
                "obs": val_obs,
                "fotos": foto_bytes,
                "fotos_2": foto_bytes_2,
                "coord_x": val_coord_x,
                "coord_y": val_coord_y,
            },
        )
        st.success("¡Válvula registrada con éxito!")
        t.sleep(1)
        st.rerun()
      except Exception as ex:
        st.error(f"Error al insertar: {ex}")
    else:
      st.warning("El campo ID es obligatorio.")

# 11 ----------------------------------------------------------------- EDITAR Y ELIMINAR ----------------------------------------------------------------------------------------------

elif st.session_state.active_tab == "⚙️ Editar":
  busqueda_edit = st.session_state.get("busqueda_edit_val", "")

  if busqueda_edit and busqueda_edit.strip() != "":
    filtro_ed = f"%{busqueda_edit.strip()}%"
    query_edit = f"""
            SELECT {COLUMNAS_VPRS} 
            FROM "Agua_potable"."VRP_Oficial" 
            WHERE id ILIKE :filtro 
               OR num_serie ILIKE :filtro 
               OR domicilio ILIKE :filtro 
               OR colonia ILIKE :filtro 
            ORDER BY id_0
            LIMIT 1
        """
    df_vprs, error_db = obtener_datos(query_edit, {"filtro": filtro_ed})
  else:
    query = (
        f'SELECT {COLUMNAS_VPRS} FROM "Agua_potable"."VRP_Oficial" ORDER BY id_0 LIMIT 1'
    )
    df_vprs, error_db = obtener_datos(query)

  col_search, col_info, col_msg = st.columns([2.5, 1.5, 2], vertical_alignment="center")

  with col_search:
    st.text_input(
        "🔍 Buscar válvula a editar (ID, Num. Serie, Domicilio, Colonia):",
        placeholder="Ej. VRP-01, Centro...",
        key="busqueda_edit_val",
    )

  if error_db:
    st.error(f"Error: {error_db}")
  elif not df_vprs.empty:
    row_first = df_vprs.iloc[0]

    with col_info:
      st.markdown(
          f"<div style='margin-top: 15px;'><span style='color: #00E5FF; font-weight: bold;'>ID_0: {row_first['id_0']}</span> | "
          f"<span style='color: #F8FAFC; font-weight: bold;'>ID: {row_first['id']}</span></div>",
          unsafe_allow_html=True,
      )

    with col_msg:
      msg_texto = (
          "Mostrando la primera coincidencia encontrada."
          if (busqueda_edit and busqueda_edit.strip() != "")
          else "Mostrando el primer registro de la base de datos."
      )
      st.markdown(
          f"<p style='color: #94A3B8; font-size: 0.85rem; margin-top: 20px; margin-bottom: 0px;'>{msg_texto}</p>",
          unsafe_allow_html=True,
      )

    for idx, row in df_vprs.iterrows():
      e_id_0 = row["id_0"]
      default_x = float(row["coord_x"]) if pd.notna(row["coord_x"]) else 0.0
      default_y = float(row["coord_y"]) if pd.notna(row["coord_y"]) else 0.0

      x_key = f"coord_x_input_{row['id_0']}"
      y_key = f"coord_y_input_{row['id_0']}"
      if x_key not in st.session_state:
        st.session_state[x_key] = default_x
      if y_key not in st.session_state:
        st.session_state[y_key] = default_y

      estado_actual = str(row["estatus"] or "").strip()
      idx_estado = 0
      if estado_actual in OPCIONES_ESTADO_VALVULA:
        idx_estado = OPCIONES_ESTADO_VALVULA.index(estado_actual)

      e_num_serie_val = (
          ""
          if (
              pd.isna(row["num_serie"])
              or str(row["num_serie"]).strip().lower() in ["nan", "none"]
          )
          else str(row["num_serie"])
      )

      e_c1, e_c2, e_c3, e_c4 = st.columns(4)
      with e_c1:
        st.text_input(
            "ID_0",
            value=str(row["id_0"] or 0),
            disabled=True,
            key=f"id0_bloq_{row['id_0']}",
        )
      with e_c2:
        e_id = st.text_input(
            "ID", value=str(row["id"] or ""), key=f"id_{row['id_0']}"
        )
      with e_c3:
        e_cota = st.number_input(
            "Cota Terreno",
            value=float(row["cota_terr"] or 0.0),
            key=f"cota_{row['id_0']}",
        )
      with e_c4:
        e_marca = st.text_input(
            "Marca",
            value=str(row["marca"] or ""),
            key=f"mar_{row['id_0']}",
        )

      e_c5, e_c6, e_c7, e_c8 = st.columns(4)
      with e_c5:
        e_num_serie = st.text_input(
            "Num. Serie", value=e_num_serie_val, key=f"num_serie_{row['id_0']}"
        )
      with e_c6:
        e_diametro = st.number_input(
            "Diámetro",
            value=int(row["diametro"] or 0),
            key=f"diam_{row['id_0']}",
        )
      with e_c7:
        e_modelo = st.text_input(
            "Modelo",
            value=str(row["modelo"] or ""),
            key=f"mod_{row['id_0']}",
        )
      with e_c8:
        e_trim = st.text_input(
            "Trim",
            value=str(row["trim"] or ""),
            key=f"trim_{row['id_0']}",
        )

      e_c9, e_c10, e_c11, e_c12 = st.columns(4)
      with e_c9:
        e_domicilio = st.text_input(
            "Domicilio",
            value=str(row["domicilio"] or ""),
            key=f"dom_{row['id_0']}",
        )
      with e_c10:
        e_colonia = st.text_input(
            "Colonia",
            value=str(row["colonia"] or ""),
            key=f"col_{row['id_0']}",
        )
      with e_c11:
        e_estat = st.selectbox(
            "Estatus",
            options=OPCIONES_ESTADO_VALVULA,
            index=idx_estado,
            key=f"est_{row['id_0']}",
        )
      with e_c12:
        e_sect_hidr = st.text_input(
            "Sector Hidráulico (sect_hidr)",
            value=str(row["sect_hidr"] or ""),
            key=f"sec_{row['id_0']}",
        )

      col_coord_left, col_map_right = st.columns([1, 1])

      with col_map_right:
        st.markdown(
            "<p style='color: #00E5FF; font-size: 0.8rem; font-weight: 700;"
            " margin-top: 0px;'>🗺️ Ubicación Geográfica (geom) - Haga clic en el"
            " mapa para actualizar coordenadas automáticamente</p>",
            unsafe_allow_html=True,
        )
        try:
          if (
              st.session_state[x_key] != 0.0
              and st.session_state[y_key] != 0.0
          ):
            lon_ed, lat_ed = transformer_to_latlon.transform(
                st.session_state[x_key], st.session_state[y_key]
            )
            m_ed = folium.Map(
                location=[lat_ed, lon_ed], zoom_start=16, control_scale=True
            )
          else:
            m_ed = folium.Map(
                location=[21.8853, -102.2916], zoom_start=12, control_scale=True
            )

          agregar_capas_base_mapa(m_ed)
          Fullscreen().add_to(m_ed)

          if (
              st.session_state[x_key] != 0.0
              and st.session_state[y_key] != 0.0
          ):
            folium.Marker(
                location=[lat_ed, lon_ed],
                popup=f"VRP: {row['id']}",
                icon=folium.Icon(color="cyan", icon="info-sign"),
            ).add_to(m_ed)

          folium.LayerControl(collapsed=False).add_to(m_ed)
          map_data_ed = st_folium(
              m_ed,
              width="100%",
              height=325,
              key=f"map_edit_preview_{row['id_0']}",
              returned_objects=["last_clicked"],
          )

          if map_data_ed and map_data_ed.get("last_clicked"):
            lat_c = map_data_ed["last_clicked"]["lat"]
            lon_c = map_data_ed["last_clicked"]["lng"]
            utm_x, utm_y = transformer_to_utm.transform(lon_c, lat_c)
            new_x = round(utm_x, 2)
            new_y = round(utm_y, 3)
            if (
                st.session_state[x_key] != new_x
                or st.session_state[y_key] != new_y
            ):
              st.session_state[x_key] = new_x
              st.session_state[y_key] = new_y
              st.rerun()

        except Exception as e_map_ed:
          st.info(
              "Haga clic en el mapa para actualizar la posición geográfica."
              f" ({e_map_ed})"
          )

      with col_coord_left:
        cx1, cx2 = st.columns(2)
        with cx1:
          e_coord_x = st.number_input(
              "Coordenada X",
              format="%.2f",
              key=x_key,
          )
        with cx2:
          e_coord_y = st.number_input(
              "Coordenada Y",
              format="%.3f",
              key=y_key,
          )

        cc1, cc2 = st.columns(2)
        with cc1:
          val_cantd_str = str(row["cal_antd"]) if pd.notna(row["cal_antd"]) and str(row["cal_antd"]).strip().lower() not in ["nan", "none"] else "0.0"
          e_cal_antd = st.text_input(
              "Calibración Ant. Día (cal_antd)",
              value=val_cantd_str,
              key=f"cand_{row['id_0']}",
          )
        with cc2:
          val_cantn_str = str(row["cal_antn"]) if pd.notna(row["cal_antn"]) and str(row["cal_antn"]).strip().lower() not in ["nan", "none"] else "0.0"
          e_cal_antn = st.text_input(
              "Calibración Ant. Noche (cal_antn)",
              value=val_cantn_str,
              key=f"cann_{row['id_0']}",
          )

        cc3, cc4 = st.columns(2)
        with cc3:
          val_cpostd_str = str(row["cal_postd"]) if pd.notna(row["cal_postd"]) and str(row["cal_postd"]).strip().lower() not in ["nan", "none"] else "0.0"
          e_cal_postd = st.text_input(
              "Calibración Post. Día (cal_postd)",
              value=val_cpostd_str,
              key=f"cpostd_{row['id_0']}",
          )
        with cc4:
          val_cpostn_str = str(row["cal_postn"]) if pd.notna(row["cal_postn"]) and str(row["cal_postn"]).strip().lower() not in ["nan", "none"] else "0.0"
          e_cal_postn = st.text_input(
              "Calibración Post. Noche (cal_postn)",
              value=val_cpostn_str,
              key=f"cpostn_{row['id_0']}",
          )

        cc5, cc6 = st.columns(2)
        with cc5:
          val_prog_hor_str = str(row["prog_hor"]) if pd.notna(row["prog_hor"]) and str(row["prog_hor"]).strip().lower() not in ["nan", "none"] else ""
          e_prog_hor = st.text_input(
              "Programación Horaria (prog_hor)",
              value=val_prog_hor_str,
              key=f"prog_hor_{row['id_0']}",
          )
        with cc6:
          e_tipo_valv = st.text_input(
              "Tipo Válvula (tipo_valv)",
              value=str(row["tipo_valv"] or ""),
              key=f"tipval_{row['id_0']}",
          )

        fecha_def = parsear_fecha_segura(row["fecha_vis"])
        e_fecha_obj = st.date_input(
            "Fecha Visita (fecha_vis)",
            value=fecha_def,
            format="DD/MM/YYYY",
            key=f"fec_{row['id_0']}",
        )
        e_fecha_vis = e_fecha_obj.strftime("%d/%m/%Y")

      e_obs = st.text_area(
          "Observaciones (obs)",
          value=str(row["obs"] or ""),
          key=f"obs_{row['id_0']}",
      )

      st.markdown(
          "<hr style='border: 0.3px solid rgba(0,229,255,0.2); margin: 15px 0;'>",
          unsafe_allow_html=True,
      )
      st.markdown(
          '<h4 style="color: #00E5FF; font-size: 1rem; font-weight: 700;">📸'
          " Gestión de Fotografías</h4>",
          unsafe_allow_html=True,
      )

      key_ver_1 = f"uploader_ver_1_{row['id_0']}"
      key_ver_2 = f"uploader_ver_2_{row['id_0']}"

      if key_ver_1 not in st.session_state:
        st.session_state[key_ver_1] = 0
      if key_ver_2 not in st.session_state:
        st.session_state[key_ver_2] = 0

      col_edit_f1, col_edit_f2 = st.columns(2)

      with col_edit_f1:
        foto_actual_bytes = procesar_bytes_foto(row["fotos"])
        eliminar_foto = False

        if foto_actual_bytes is not None and len(foto_actual_bytes) > 0:
          st.image(
              foto_actual_bytes,
              caption=f"ID: {row['id']} (Foto 1 Actual)",
              use_container_width=True,
          )
          eliminar_foto = st.checkbox(
              "🗑️ Eliminar fotografía 1", key=f"del_foto_{row['id_0']}"
          )

        nueva_foto_archivo = st.file_uploader(
            "📁 Cargar/Reemplazar Foto 1 desde PC",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"file_edit_1_{row['id_0']}_{st.session_state[key_ver_1]}",
        )

      with col_edit_f2:
        foto_actual_bytes_2 = procesar_bytes_foto(row["fotos_2"])
        eliminar_foto_2 = False

        if foto_actual_bytes_2 is not None and len(foto_actual_bytes_2) > 0:
          st.image(
              foto_actual_bytes_2,
              caption=f"ID: {row['id']} (Foto 2 Actual)",
              use_container_width=True,
          )
          eliminar_foto_2 = st.checkbox(
              "🗑️ Eliminar fotografía 2", key=f"del_foto_2_{row['id_0']}"
          )

        nueva_foto_archivo_2 = st.file_uploader(
            "📁 Cargar/Reemplazar Foto 2 desde PC",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"file_edit_2_{row['id_0']}_{st.session_state[key_ver_2]}",
        )

      st.markdown("<br>", unsafe_allow_html=True)
      actualizar_click = st.button(
          "💾 Actualizar Registro en Base de Datos",
          key=f"btn_act_{row['id_0']}",
          use_container_width=True,
      )

      if actualizar_click:
        try:
          if eliminar_foto:
            foto_bytes_final = None
          else:
            foto_bytes_final = foto_actual_bytes
            if nueva_foto_archivo is not None:
              foto_bytes_final = nueva_foto_archivo.getvalue()

          if eliminar_foto_2:
            foto_bytes_final_2 = None
          else:
            foto_bytes_final_2 = foto_actual_bytes_2
            if nueva_foto_archivo_2 is not None:
              foto_bytes_final_2 = nueva_foto_archivo_2.getvalue()

          sql_update = """
                        UPDATE "Agua_potable"."VRP_Oficial" 
                        SET id = :id, num_serie = :num_serie, tipo_valv = :tipo_valv, 
                            diametro = :diametro, marca = :marca, modelo = :modelo, trim = :trim, 
                            domicilio = :domicilio, colonia = :colonia, sect_hidr = :sect_hidr, 
                            cota_terr = :cota_terr, estatus = :estatus, cal_antd = :cal_antd, 
                            cal_antn = :cal_antn, fecha_vis = :fecha_vis, cal_postd = :cal_postd, 
                            cal_postn = :cal_postn, prog_hor = :prog_hor, obs = :obs, fotos = :fotos, fotos_2 = :fotos_2,
                            geom = ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                        WHERE id_0 = :id_0
                    """
          ejecutar_sql(
              sql_update,
              {
                  "id_0": e_id_0,
                  "id": e_id,
                  "num_serie": e_num_serie if e_num_serie.strip() != "" else None,
                  "tipo_valv": e_tipo_valv if e_tipo_valv.strip() != "" else None,
                  "diametro": e_diametro,
                  "marca": e_marca,
                  "modelo": e_modelo,
                  "trim": e_trim,
                  "domicilio": e_domicilio,
                  "colonia": e_colonia,
                  "sect_hidr": e_sect_hidr,
                  "cota_terr": e_cota,
                  "estatus": e_estat,
                  "cal_antd": e_cal_antd if e_cal_antd.strip() != "" else None,
                  "cal_antn": e_cal_antn if e_cal_antn.strip() != "" else None,
                  "cal_postd": e_cal_postd if e_cal_postd.strip() != "" else None,
                  "cal_postn": e_cal_postn if e_cal_postn.strip() != "" else None,
                  "prog_hor": e_prog_hor if e_prog_hor.strip() != "" else None,
                  "fecha_vis": e_fecha_vis,
                  "obs": e_obs,
                  "fotos": foto_bytes_final,
                  "fotos_2": foto_bytes_final_2,
                  "coord_x": st.session_state[x_key],
                  "coord_y": st.session_state[y_key],
              },
          )

          st.session_state[key_ver_1] += 1
          st.session_state[key_ver_2] += 1

          st.success(f"¡Registro ID_0 {row['id_0']} actualizado con éxito!")
          t.sleep(1)
          st.rerun()
        except Exception as ex:
          st.error(f"Error al actualizar: {ex}")

      if not es_operador:
        st.markdown(
            "<hr style='border: 0.5px solid rgba(255,0,0,0.2); margin: 20px 0;'>",
            unsafe_allow_html=True,
        )

        if st.session_state.registro_to_delete == row["id_0"]:
          st.markdown(
              f"<p style='color: #ff4d4d; font-size: 0.9rem; font-weight:"
              f" bold;'>Para eliminar el registro ID_0 {row['id_0']} (ID:"
              f" {row['id']}), escribe la palabra 'delete':</p>",
              unsafe_allow_html=True,
          )
          confirm_text = st.text_input(
              "Confirmación de eliminación", key=f"input_del_text_{row['id_0']}"
          )

          col_y, col_n = st.columns(2)
          with col_y:
            if st.button(
                "Sí, eliminar definitivamente",
                key=f"confirm_del_{row['id_0']}",
                use_container_width=True,
            ):
              if confirm_text.strip() == "delete":
                try:
                  ejecutar_sql(
                      'DELETE FROM "Agua_potable"."VRP_Oficial" WHERE id_0 = :id_0',
                      {"id_0": row["id_0"]},
                  )
                  st.session_state.registro_to_delete = None
                  st.success("Registro eliminado correctamente.")
                  t.sleep(1)
                  st.rerun()
                except Exception as ex_del:
                  st.error(f"Error al eliminar: {ex_del}")
              else:
                st.error(
                    "Debes escribir exactamente la palabra 'delete' para"
                    " confirmar."
                )
          with col_n:
            if st.button(
                "Cancelar",
                key=f"cancel_del_{row['id_0']}",
                use_container_width=True,
            ):
              st.session_state.registro_to_delete = None
              st.rerun()
        else:
          if st.button(
              "🗑️ Eliminar este registro",
              key=f"btn_del_{row['id_0']}",
              use_container_width=True,
          ):
            st.session_state.registro_to_delete = row["id_0"]
            st.rerun()
  else:
    st.info("No se encontró ningún registro para editar.")

# 12 -------------------------------------------------------------------------------------- PIE DE PÁGINA --------------------------------------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align: center; color: #94A3B8; font-size: 0.8rem; margin-top: 30px;">
        MIAA - Sistema de Gestión de Válvulas Reductoras de Presión © 2026
    </div>
    """,
    unsafe_allow_html=True,
)
