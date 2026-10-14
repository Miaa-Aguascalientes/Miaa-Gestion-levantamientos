# Levantamientos - Gestión de Predios (MIAA)
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
    page_title="Gestión Levantamientos de Predios - MIAA",
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

COLUMNAS_FECHA = ["fechaRegistro", "fechaModificacion", "_Ult_actualizacion"]

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

# 02 SECCION -------------------------------------------------------------------------- CONEXIÓN A BASE DE DATOS POSTGRESQL (Esquema Usuarios, Tabla levantamientos) --------------------------------------------------------------------------------------

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
  mysql_sec = st.secrets["mysql_usuarios_levantamientos"]
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
  _, col_centro, _ = st.columns([1, 1.4, 1])

  with col_centro:
    st.markdown(
        """
        <div class="login-container-animated">
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; width: 100%; margin-bottom: 25px;">
                <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" class="login-logo-animated" style="width: 200px; height: auto; margin-bottom: 15px;" />
                <h3 style="color: #00E5FF; font-size: 1.5rem; font-weight: 800; margin: 0 0 8px 0; letter-spacing: -0.5px;">Acceso al Sistema</h3>
                <p style="color: #94A3B8; font-size: 0.9rem; margin: 0;">Gestión de Levantamientos de Predios</p>
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
                        FROM usuarios_miaa 
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
    opciones_menu = ["📍 Registros", "🗺️ Mapa", "⚙ Editar"]
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

  df_sidebar_levantamientos, _ = obtener_datos(
      'SELECT fid, medidorId, serie, domicilio, colonia, activo FROM "Usuarios"."levantamientos"'
  )

  if not df_sidebar_levantamientos.empty:
    st.markdown(
        "<p style='color: #00E5FF; font-size: 0.85rem; font-weight: 700;"
        " margin-bottom: 16px; margin-top: 8px;'>📊 Resumen Predios</p>",
        unsafe_allow_html=True,
    )

    total_predios = len(df_sidebar_levantamientos)
    activos_count = len(df_sidebar_levantamientos[df_sidebar_levantamientos["activo"] == True])
    inactivos_count = total_predios - activos_count

    st.markdown(
        f"""
        <div style="font-size: 0.8rem; color: #94A3B8; line-height: 1.6;">
            <b>Total Registrados:</b> <span style="color: #00E5FF;">{total_predios}</span><br>
            <b>Activos:</b> <span style="color: #2ECC71;">{activos_count}</span><br>
            <b>Inactivos:</b> <span style="color: #E74C3C;">{inactivos_count}</span>
        </div>
        """,
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
        <h1 style="color: #00E5FF; font-size: 1.8rem; font-weight: 800; margin: 0; letter-spacing: -0.5px;">Gestión de Levantamientos de Predios</h1>
    </div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<hr style='border: 0.5px solid rgba(0,229,255,0.2); margin: 10px 0;'>",
    unsafe_allow_html=True,
)

COLUMNAS_LEV = """
    fid, medidorId, serie, toma, domicilio, colonia, latitud, longitud, precisionGps, 
    ajusteManual, observaciones, usuarioNombre, fechaRegistro, fechaModificacion, 
    activo, "Predio_Viv", "Latitud", "Longitud", _Ult_actualizacion,
    ST_X(geom) as coord_x, ST_Y(geom) as coord_y
"""

# 08 SECCION ---------------------------------------------------------------------------- VER REGISTROS (levantamientos) ------------------------------------------------------------------------------------------------

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

  tab_registros, tab_bd_completa, tab_gestor_bd = st.tabs([
      "📍 Registros",
      "🗄️ Tabla Base de Datos Completa",
      "🛠 Gestión BD",
  ])

  with tab_registros:
    busqueda = st.text_input(
        "🔍 Buscar predio (Medidor ID, Serie, Toma, Domicilio, Colonia):",
        placeholder="Ej. MED-001, Centro...",
    )

    if busqueda and busqueda.strip() != "":
      filtro = f"%{busqueda.strip()}%"
      query = f"""
                SELECT {COLUMNAS_LEV} 
                FROM "Usuarios"."levantamientos" 
                WHERE medidorId ILIKE :filtro 
                   OR serie ILIKE :filtro 
                   OR CAST(toma AS TEXT) ILIKE :filtro
                   OR domicilio ILIKE :filtro 
                   OR colonia ILIKE :filtro 
                ORDER BY fid
            """
      df_lev, error_db = obtener_datos(query, {"filtro": filtro})
    else:
      query = (
          f'SELECT {COLUMNAS_LEV} FROM "Usuarios"."levantamientos" ORDER BY fid'
          " LIMIT 15"
      )
      df_lev, error_db = obtener_datos(query)

    if error_db:
      st.error(f"❌ Error al consultar PostgreSQL: {error_db}")
    elif not df_lev.empty:
      if not busqueda or busqueda.strip() == "":
        st.markdown(
            "<p style='color: #94A3B8; font-size: 0.85rem; margin-bottom:"
            " 10px;'>Mostrando primeros 15 registros.</p>",
            unsafe_allow_html=True,
        )
      else:
        st.markdown(
            f"<p style='color: #94A3B8; font-size: 0.85rem; margin-bottom:"
            f" 10px;'>Se encontraron {len(df_lev)} registros.</p>",
            unsafe_allow_html=True,
        )

      for idx, row in df_lev.iterrows():
        serie_val = row["serie"]
        serie_texto = (
            ""
            if (
                pd.isna(serie_val)
                or str(serie_val).strip().lower() in ["nan", "none", ""]
            )
            else f" | Serie: {serie_val}"
        )
        toma_texto = f" | Toma: {row['toma']}" if pd.notna(row["toma"]) else ""

        card_html = f"""
                    <div class="user-card">
                        <span style="font-size: 0.95rem; font-weight: bold; color: #F8FAFC;">Medidor ID: {row['medidorId']}{serie_texto}{toma_texto}</span><br>
                        <span style="color: #00E5FF; font-size: 0.85rem;">📍 {row['domicilio'] or 'Sin domicilio'}, Col. {row['colonia'] or 'Sin colonia'}</span>
                    </div>
                """
        st.markdown(card_html, unsafe_allow_html=True)

        with st.expander("🔍 Ver detalles completos del levantamiento"):
          geom_str = (
              f"POINT ({row['coord_x']} {row['coord_y'])})"
              if pd.notna(row["coord_x"]) and pd.notna(row["coord_y"])
              else "Sin geometría"
          )
          detalle_html = f"""
                        <span style="color: #94A3B8; font-size: 0.8rem; line-height: 1.6;">
                            <b>FID:</b> {row['fid']} &nbsp;|&nbsp; <b>Predio Viv:</b> {row['Predio_Viv']} &nbsp;|&nbsp; <b>Activo:</b> {row['activo']}<br>
                            <b>Lat/Lon:</b> {row['latitud']}, {row['longitud']} &nbsp;|&nbsp; <b>Precisión GPS:</b> {row['precisionGps']} m<br>
                            <b>Ajuste Manual:</b> {row['ajusteManual']} &nbsp;|&nbsp; <b>Usuario Levantamiento:</b> {row['usuarioNombre']}<br>
                            <b>Fecha Registro:</b> {formatear_fecha_str(row['fechaRegistro'])} &nbsp;|&nbsp; <b>Modificación:</b> {formatear_fecha_str(row['fechaModificacion'])}<br>
                            <b>Geometría (geom):</b> {geom_str}<br>
                            <b>Observaciones:</b> {row['observaciones']}
                        </span>
                    """
          st.markdown(detalle_html, unsafe_allow_html=True)
    else:
      st.info("No se encontraron registros de levantamientos.")

  with tab_bd_completa:
    st.markdown("### Tabla Completa de Levantamientos (Base de Datos)")

    query_completa = (
        f'SELECT {COLUMNAS_LEV} FROM "Usuarios"."levantamientos" ORDER BY fid ASC;'
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
            "📌 Administra el vaciado masivo, actualizaciones e inserciones masivas por CSV usando `fid` como identificador principal."
        )

        st.markdown("---")
        st.markdown("#### 1️⃣ Zona de Peligro: Vaciar Tabla de Base de Datos")
        st.warning(
            "⚠️ Esta acción eliminará **todos** los registros de la tabla"
            ' `"Usuarios"."levantamientos"`. Utilízala con extrema precaución.'
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
                ejecutar_sql('DELETE FROM "Usuarios"."levantamientos";')
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
            "Sube un archivo CSV que contenga obligatoriamente la columna identificadora `fid` para actualizar registros existentes o insertar nuevos automáticamente."
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

            if "fid" not in df_csv_input.columns and "FID" not in df_csv_input.columns:
              st.error("❌ El archivo CSV debe contener obligatoriamente una columna llamada `fid` como identificador.")
            else:
              col_id_csv = "fid" if "fid" in df_csv_input.columns else "FID"
              st.success(
                  f"CSV cargado correctamente ({len(df_csv_input)} filas detectadas). Identificador principal: `fid`."
              )
              st.dataframe(df_csv_input.head(5), use_container_width=True)

              cols_csv = list(df_csv_input.columns)
              columnas_a_procesar = st.multiselect(
                  "Selecciona qué columnas deseas actualizar/insertar en la BD:",
                  options=[c for c in cols_csv if c.lower() != "fid"],
                  default=[
                      c for c in cols_csv 
                      if c.lower() != "fid" and c.lower() in [
                          "medidorid", "serie", "toma", "domicilio", "colonia", "latitud", 
                          "longitud", "precisiongps", "ajustemanual", "observaciones", 
                          "usuarionombre", "activo", "predio_viv"
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
                            val_fid = row_c[col_id_csv]
                            if pd.isna(val_fid):
                              continue
                            try:
                              val_fid_int = int(val_fid)
                            except:
                              continue

                            check_query = text('SELECT fid FROM "Usuarios"."levantamientos" WHERE fid = :f')
                            res_chk = conn.execute(check_query, {"f": val_fid_int}).fetchone()

                            params_dict = {"fid": val_fid_int}
                            set_clauses = []
                            insert_cols = ["fid"]
                            insert_vals = [":fid"]

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
                                        UPDATE "Usuarios"."levantamientos" 
                                        SET {", ".join(set_clauses)}
                                        WHERE fid = :fid;
                                    """)
                                    conn.execute(sql_update_csv, params_dict)
                                    actualizados_count += 1
                                else:
                                  sql_insert_csv = text(f"""
                                        INSERT INTO "Usuarios"."levantamientos" ({", ".join(insert_cols)})
                                        VALUES ({", ".join(insert_vals)});
                                    """)
                                  conn.execute(sql_insert_csv, params_dict)
                                  insertados_count += 1
                            except Exception as ex_fila:
                              errores_count += 1
                              if len(lista_errores_detalle) < 5:
                                lista_errores_detalle.append(f"FID {val_fid_int}: {str(ex_fila)}")
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

# 09 SECCION ------------------------------------------------------------ MAPA DE LEVANTAMIENTOS DE PREDIOS (POSTGIS) -----------------------------------------------------------------------------------------

elif st.session_state.active_tab == "🗺️ Mapa":
  query_mapa = """
        SELECT 
            fid,
            medidorId,
            serie,
            toma,
            domicilio,
            colonia,
            activo,
            ST_X(geom) as x,
            ST_Y(geom) as y
        FROM "Usuarios"."levantamientos"
        WHERE geom IS NOT NULL;
    """
  df_mapa, err_mapa = obtener_datos(query_mapa)

  if err_mapa:
    st.error(f"❌ Error al cargar datos espaciales de levantamientos: {err_mapa}")
  else:
    m = folium.Map(
        location=[21.8853, -102.2916], zoom_start=13, control_scale=True
    )

    agregar_capas_base_mapa(m)
    Fullscreen().add_to(m)

    fg_activos = folium.FeatureGroup(name="🟢 Predios Activos", show=True)
    fg_inactivos = folium.FeatureGroup(name="🔴 Predios Inactivos", show=True)
    fg_activos.add_to(m)
    fg_inactivos.add_to(m)

    success_count = 0

    if not df_mapa.empty:
      for _, row in df_mapa.iterrows():
        try:
          lon, lat = transformer_to_latlon.transform(row["x"], row["y"])
          is_activo = bool(row["activo"]) if pd.notna(row["activo"]) else True
          color_hex = "#2ECC71" if is_activo else "#E74C3C"
          grupo_destino = fg_activos if is_activo else fg_inactivos

          id_predio = str(row["medidorId"] or row["serie"] or row["fid"])

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
                        <b>Medidor ID:</b> {row['medidorId']}<br>
                        <b>Serie:</b> {row['serie']}<br>
                        <b>Toma:</b> {row['toma']}<br>
                        <b>Activo:</b> {'Sí' if is_activo else 'No'}<br>
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
                        ">{id_predio}</span>
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

    st.markdown(
        f"<p style='color: #94A3B8; font-size: 0.85rem; margin-top: 10px;'>Se renderizaron {success_count} predios georreferenciados en el mapa.</p>",
        unsafe_allow_html=True,
    )

# 10 SECCION --------------------------------------------------------------------- AÑADIR NUEVO LEVANTAMIENTO DE PREDIO ---------------------------------------------------------------------------------------------

elif st.session_state.active_tab == "➕ Añadir":
  if es_operador:
    st.error(
        "⛔ El perfil de operador no tiene permisos para dar de alta nuevos levantamientos."
    )
    st.stop()

  if "add_coord_x_input" not in st.session_state:
    st.session_state["add_coord_x_input"] = 0.0
  if "add_coord_y_input" not in st.session_state:
    st.session_state["add_coord_y_input"] = 0.0

  a_c1, a_c2, a_c3, a_c4 = st.columns(4)
  with a_c1:
    val_medidor_id = st.text_input("Medidor ID *Obligatorio", key="add_medidorId")
  with a_c2:
    val_serie = st.text_input("Serie", key="add_serie")
  with a_c3:
    val_toma = st.number_input("Toma", min_value=0, value=0, key="add_toma")
  with a_c4:
    val_predio_viv = st.text_input("Predio_Viv", key="add_predio_viv")

  a_c5, a_c6, a_c7, a_c8 = st.columns(4)
  with a_c5:
    val_domicilio = st.text_input("Domicilio", key="add_domicilio")
  with a_c6:
    val_colonia = st.text_input("Colonia", key="add_colonia")
  with a_c7:
    val_latitud = st.number_input("Latitud", format="%.6f", value=21.8853, key="add_latitud")
  with a_c8:
    val_longitud = st.number_input("Longitud", format="%.6f", value=-102.2916, key="add_longitud")

  a_c9, a_c10, a_c11, a_c12 = st.columns(4)
  with a_c9:
    val_precision_gps = st.number_input("Precisión GPS (m)", value=0.0, key="add_precisionGps")
  with a_c10:
    val_ajuste_manual = st.checkbox("Ajuste Manual", key="add_ajusteManual")
  with a_c11:
    val_activo = st.checkbox("Activo", value=True, key="add_activo")
  with a_c12:
    val_usuario_nombre = st.text_input("Usuario Nombre", value=st.session_state.get("usuario_actual", ""), key="add_usuarioNombre")

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
            popup="Nuevo Predio",
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
          "Coordenada X (UTM)",
          format="%.2f",
          key="add_coord_x_input",
      )
    with cx2:
      val_coord_y = st.number_input(
          "Coordenada Y (UTM)",
          format="%.3f",
          key="add_coord_y_input",
      )

  val_observaciones = st.text_area("Observaciones", key="add_observaciones")

  st.markdown("<br>", unsafe_allow_html=True)
  if st.button(
      "💾 Guardar Nuevo Levantamiento",
      key="btn_guardar_nuevo",
      use_container_width=True,
  ):
    if val_medidor_id:
      try:
        fecha_actual_str = datetime.datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

        sql_insert = """
                    INSERT INTO "Usuarios"."levantamientos" (
                        medidorId, serie, toma, domicilio, colonia, latitud, longitud, 
                        precisionGps, ajusteManual, observaciones, usuarioNombre, 
                        fechaRegistro, fechaModificacion, activo, "Predio_Viv", "Latitud", "Longitud", geom
                    ) VALUES (
                        :medidorId, :serie, :toma, :domicilio, :colonia, :latitud, :longitud, 
                        :precisionGps, :ajusteManual, :observaciones, :usuarioNombre, 
                        :fechaRegistro, :fechaModificacion, :activo, :Predio_Viv, :Latitud, :Longitud, 
                        ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                    )
                """
        ejecutar_sql(
            sql_insert,
            {
                "medidorId": val_medidor_id.strip(),
                "serie": val_serie if val_serie.strip() != "" else None,
                "toma": val_toma,
                "domicilio": val_domicilio if val_domicilio.strip() != "" else None,
                "colonia": val_colonia if val_colonia.strip() != "" else None,
                "latitud": val_latitud,
                "longitud": val_longitud,
                "precisionGps": val_precision_gps,
                "ajusteManual": val_ajuste_manual,
                "observaciones": val_observaciones if val_observaciones.strip() != "" else None,
                "usuarioNombre": val_usuario_nombre if val_usuario_nombre.strip() != "" else None,
                "fechaRegistro": fecha_actual_str,
                "fechaModificacion": fecha_actual_str,
                "activo": val_activo,
                "Predio_Viv": val_predio_viv if val_predio_viv.strip() != "" else None,
                "Latitud": val_latitud,
                "Longitud": val_longitud,
                "coord_x": val_coord_x,
                "coord_y": val_coord_y,
            },
        )
        st.success("¡Predio registrado con éxito!")
        t.sleep(1)
        st.rerun()
      except Exception as ex:
        st.error(f"Error al insertar: {ex}")
    else:
      st.warning("El campo Medidor ID es obligatorio.")

# 11 ----------------------------------------------------------------- EDITAR Y ELIMINAR ----------------------------------------------------------------------------------------------

elif st.session_state.active_tab == "⚙️ Editar":
  busqueda_edit = st.session_state.get("busqueda_edit_val", "")

  if busqueda_edit and busqueda_edit.strip() != "":
    filtro_ed = f"%{busqueda_edit.strip()}%"
    query_edit = f"""
            SELECT {COLUMNAS_LEV} 
            FROM "Usuarios"."levantamientos" 
            WHERE medidorId ILIKE :filtro 
               OR serie ILIKE :filtro 
               OR CAST(toma AS TEXT) ILIKE :filtro
               OR domicilio ILIKE :filtro 
               OR colonia ILIKE :filtro 
            ORDER BY fid
            LIMIT 1
        """
    df_lev, error_db = obtener_datos(query_edit, {"filtro": filtro_ed})
  else:
    query = (
        f'SELECT {COLUMNAS_LEV} FROM "Usuarios"."levantamientos" ORDER BY fid LIMIT 1'
    )
    df_lev, error_db = obtener_datos(query)

  col_search, col_info, col_msg = st.columns([2.5, 1.5, 2], vertical_alignment="center")

  with col_search:
    st.text_input(
        "🔍 Buscar predio a editar (Medidor ID, Serie, Toma, Domicilio, Colonia):",
        placeholder="Ej. MED-001, Centro...",
        key="busqueda_edit_val",
    )

  if error_db:
    st.error(f"Error: {error_db}")
  elif not df_lev.empty:
    row_first = df_lev.iloc[0]

    with col_info:
      st.markdown(
          f"<div style='margin-top: 15px;'><span style='color: #00E5FF; font-weight: bold;'>FID: {row_first['fid']}</span> | "
          f"<span style='color: #F8FAFC; font-weight: bold;'>Medidor ID: {row_first['medidorId']}</span></div>",
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

    for idx, row in df_lev.iterrows():
      e_fid = row["fid"]
      default_x = float(row["coord_x"]) if pd.notna(row["coord_x"]) else 0.0
      default_y = float(row["coord_y"]) if pd.notna(row["coord_y"]) else 0.0

      x_key = f"coord_x_input_{row['fid']}"
      y_key = f"coord_y_input_{row['fid']}"
      if x_key not in st.session_state:
        st.session_state[x_key] = default_x
      if y_key not in st.session_state:
        st.session_state[y_key] = default_y

      e_c1, e_c2, e_c3, e_c4 = st.columns(4)
      with e_c1:
        st.text_input(
            "FID",
            value=str(row["fid"] or 0),
            disabled=True,
            key=f"fid_bloq_{row['fid']}",
        )
      with e_c2:
        e_medidor_id = st.text_input(
            "Medidor ID", value=str(row["medidorId"] or ""), key=f"medid_{row['fid']}"
        )
      with e_c3:
        e_serie = st.text_input(
            "Serie",
            value=str(row["serie"] or ""),
            key=f"ser_{row['fid']}",
        )
      with e_c4:
        e_toma = st.number_input(
            "Toma",
            value=int(row["toma"] or 0),
            key=f"tom_{row['fid']}",
        )

      e_c5, e_c6, e_c7, e_c8 = st.columns(4)
      with e_c5:
        e_domicilio = st.text_input(
            "Domicilio", value=str(row["domicilio"] or ""), key=f"dom_{row['fid']}"
        )
      with e_c6:
        e_colonia = st.text_input(
            "Colonia",
            value=str(row["colonia"] or ""),
            key=f"col_{row['fid']}",
        )
      with e_c7:
        e_latitud = st.number_input(
            "Latitud",
            format="%.6f",
            value=float(row["latitud"] or 21.8853),
            key=f"lat_{row['fid']}",
        )
      with e_c8:
        e_longitud = st.number_input(
            "Longitud",
            format="%.6f",
            value=float(row["longitud"] or -102.2916),
            key=f"lon_{row['fid']}",
        )

      e_c9, e_c10, e_c11, e_c12 = st.columns(4)
      with e_c9:
        e_precision = st.number_input(
            "Precisión GPS",
            value=float(row["precisionGps"] or 0.0),
            key=f"prec_{row['fid']}",
        )
      with e_c10:
        e_ajuste = st.checkbox(
            "Ajuste Manual",
            value=bool(row["ajusteManual"]),
            key=f"ajust_{row['fid']}",
        )
      with e_c11:
        e_activo = st.checkbox(
            "Activo",
            value=bool(row["activo"]),
            key=f"act_{row['fid']}",
        )
      with e_c12:
        e_predio_viv = st.text_input(
            "Predio_Viv",
            value=str(row["Predio_Viv"] or ""),
            key=f"pviv_{row['fid']}",
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
                popup=f"Predio: {row['medidorId']}",
                icon=folium.Icon(color="cyan", icon="info-sign"),
            ).add_to(m_ed)

          folium.LayerControl(collapsed=False).add_to(m_ed)
          map_data_ed = st_folium(
              m_ed,
              width="100%",
              height=325,
              key=f"map_edit_preview_{row['fid']}",
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

      e_observaciones = st.text_area(
          "Observaciones",
          value=str(row["observaciones"] or ""),
          key=f"obs_{row['fid']}",
      )

      st.markdown("<br>", unsafe_allow_html=True)
      actualizar_click = st.button(
          "💾 Actualizar Registro en Base de Datos",
          key=f"btn_act_{row['fid']}",
          use_container_width=True,
      )

      if actualizar_click:
        try:
          fecha_mod_str = datetime.datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")

          sql_update = """
                        UPDATE "Usuarios"."levantamientos" 
                        SET medidorId = :medidorId, serie = :serie, toma = :toma, 
                            domicilio = :domicilio, colonia = :colonia, latitud = :latitud, 
                            longitud = :longitud, precisionGps = :precisionGps, 
                            ajusteManual = :ajusteManual, observaciones = :observaciones, 
                            activo = :activo, "Predio_Viv" = :Predio_Viv, 
                            "Latitud" = :Latitud, "Longitud" = :Longitud, 
                            fechaModificacion = :fechaModificacion, 
                            geom = ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                        WHERE fid = :fid
                    """
          ejecutar_sql(
              sql_update,
              {
                  "fid": e_fid,
                  "medidorId": e_medidor_id.strip(),
                  "serie": e_serie if e_serie.strip() != "" else None,
                  "toma": e_toma,
                  "domicilio": e_domicilio if e_domicilio.strip() != "" else None,
                  "colonia": e_colonia if e_colonia.strip() != "" else None,
                  "latitud": e_latitud,
                  "longitud": e_longitud,
                  "precisionGps": e_precision,
                  "ajusteManual": e_ajuste,
                  "observaciones": e_observaciones if e_observaciones.strip() != "" else None,
                  "activo": e_activo,
                  "Predio_Viv": e_predio_viv if e_predio_viv.strip() != "" else None,
                  "Latitud": e_latitud,
                  "Longitud": e_longitud,
                  "fechaModificacion": fecha_mod_str,
                  "coord_x": st.session_state[x_key],
                  "coord_y": st.session_state[y_key],
              },
          )

          st.success(f"¡Predio FID {row['fid']} actualizado con éxito!")
          t.sleep(1)
          st.rerun()
        except Exception as ex:
          st.error(f"Error al actualizar: {ex}")

      if not es_operador:
        st.markdown(
            "<hr style='border: 0.5px solid rgba(255,0,0,0.2); margin: 20px 0;'>",
            unsafe_allow_html=True,
        )

        if st.session_state.registro_to_delete == row["fid"]:
          st.markdown(
              f"<p style='color: #ff4d4d; font-size: 0.9rem; font-weight:"
              f" bold;'>Para eliminar el registro FID {row['fid']} (Medidor ID:"
              f" {row['medidorId']}), escribe la palabra 'delete':</p>",
              unsafe_allow_html=True,
          )
          confirm_text = st.text_input(
              "Confirmación de eliminación", key=f"input_del_text_{row['fid']}"
          )

          col_y, col_n = st.columns(2)
          with col_y:
            if st.button(
                "Sí, eliminar definitivamente",
                key=f"confirm_del_{row['fid']}",
                use_container_width=True,
            ):
              if confirm_text.strip() == "delete":
                try:
                  ejecutar_sql(
                      'DELETE FROM "Usuarios"."levantamientos" WHERE fid = :fid',
                      {"fid": row["fid"]},
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
                key=f"cancel_del_{row['fid']}",
                use_container_width=True,
            ):
              st.session_state.registro_to_delete = None
              st.rerun()
        else:
          if st.button(
              "🗑️ Eliminar este registro",
              key=f"btn_del_{row['fid']}",
              use_container_width=True,
          ):
            st.session_state.registro_to_delete = row["fid"]
            st.rerun()
  else:
    st.info("No se encontró ningún registro para editar.")

# 12 -------------------------------------------------------------------------------------- PIE DE PÁGINA --------------------------------------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align: center; color: #94A3B8; font-size: 0.8rem; margin-top: 30px;">
        MIAA - Sistema de Gestión de Levantamientos de Predios © 2026
    </div>
    """,
    unsafe_allow_html=True,
)
