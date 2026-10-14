# Levantamientos - Gestión de Predios (MIAA)
import base64
import datetime
import time as t
from zoneinfo import ZoneInfo
import folium
from folium.plugins import Fullscreen, MarkerCluster
import pandas as pd
import pydeck as pdk
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
  st.session_state.active_tab = "📊 Dashboard General"
if "autenticado" not in st.session_state:
  st.session_state.autenticado = False
if "gestor_bd_autenticado" not in st.session_state:
  st.session_state.gestor_bd_autenticado = False
if "tipo_vista_grafico" not in st.session_state:
  st.session_state.tipo_vista_grafico = "Diaria"

zona_mx = ZoneInfo("America/Mexico_City")

# Transformadores de coordenadas (UTM Zona 13N <-> Lat/Lon WGS84)
transformer_to_latlon = Transformer.from_crs(
    "EPSG:32613", "EPSG:4326", always_xy=True
)
transformer_to_utm = Transformer.from_crs(
    "EPSG:4326", "EPSG:32613", always_xy=True
)

COLUMNAS_FECHA = ["fechaRegistro", "fechaModificacion", "_Ultima_actualizacion"]

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
      checked=True,
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

    @keyframes fadeInSlide {
        0% { opacity: 0; transform: translateY(25px) scale(0.98); }
        100% { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes pulseGlow {
        0% { box-shadow: 0 0 15px rgba(0, 229, 255, 0.1); }
        50% { box-shadow: 0 0 30px rgba(0, 229, 255, 0.35); }
        100% { box-shadow: 0 0 15px rgba(0, 229, 255, 0.1); }
    }

    @keyframes floatLogo {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-6px); }
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
                        SELECT id, usuario, password, tipo_usuario, departamento 
                        FROM usuarios_levantamientos 
                        WHERE TRIM(usuario) = :usu AND TRIM(CAST(password AS CHAR)) = :pas
                    """
          df_user, err_login = obtener_datos_mysql(
              query_login,
              {"usu": usuario_input.strip(), "pas": str(password_input).strip()},
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

es_operador = st.session_state.get("tipo_usuario", "") == "operador"

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
    fid, "medidorId", serie, toma, domicilio, colonia, latitud, longitud, "precisionGps", 
    "ajusteManual", observaciones, "usuarioNombre", "fechaRegistro", "fechaModificacion", 
    activo, "Predio_Viv", "Latitud", "Longitud", "_Ultima_actualizacion",
    ST_X(geom) as coord_x, ST_Y(geom) as coord_y,
    ST_X(geom_ant) as coord_ant_x, ST_Y(geom_ant) as coord_ant_y
"""

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

  opciones_menu = ["📊 Dashboard General", "⚙️ Editar", "🛠️ Ajustes Manuales", "⚠️ Series Duplicadas"]

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

  # Variable global temporal para el row_first si estamos en Editar
  # (Se evalúa abajo al cargar la pestaña Editar)

  df_sidebar_levantamientos, _ = obtener_datos(
      'SELECT fid, "medidorId", serie, domicilio, colonia, activo FROM "Usuarios"."levantamientos"'
  )

  if not df_sidebar_levantamientos.empty:
    st.markdown(
        "<hr style='border: 0.5px solid rgba(0,229,255,0.2); margin: 15px 0;'>",
        unsafe_allow_html=True,
    )
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
        <div style="font-size: 0.80rem; color: #94A3B8; line-height: 1.6;">
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


# 08 -------------------------------------------------------------------------------------- EDITAR Y ELIMINAR ----------------------------------------------------------------------------------------------

df_lev = pd.DataFrame()
row_first = None

if st.session_state.active_tab == "⚙️ Editar":
  busqueda_edit = st.session_state.get("busqueda_edit_val", "")

  if busqueda_edit and busqueda_edit.strip() != "":
    filtro_ed = f"%{busqueda_edit.strip()}%"
    query_edit = f"""
            SELECT {COLUMNAS_LEV} 
            FROM "Usuarios"."levantamientos" 
            WHERE "medidorId" ILIKE :filtro 
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
      default_x = float(row["coord_x"]) if pd.notna(row["coord_x"]) else 0.0
      default_y = float(row["coord_y"]) if pd.notna(row["coord_y"]) else 0.0

      default_ant_x = float(row["coord_ant_x"]) if pd.notna(row["coord_ant_x"]) else 0.0
      default_ant_y = float(row["coord_ant_y"]) if pd.notna(row["coord_ant_y"]) else 0.0

      x_key = f"coord_x_input_{row['fid']}"
      y_key = f"coord_y_input_{row['fid']}"
      ant_x_key = f"coord_ant_x_input_{row['fid']}"
      ant_y_key = f"coord_ant_y_input_{row['fid']}"
      ajust_key = f"ajust_{row['fid']}"

      if x_key not in st.session_state:
        st.session_state[x_key] = default_x
      if y_key not in st.session_state:
        st.session_state[y_key] = default_y
      if ant_x_key not in st.session_state:
        st.session_state[ant_x_key] = default_ant_x
      if ant_y_key not in st.session_state:
        st.session_state[ant_y_key] = default_ant_y
      if ajust_key not in st.session_state:
        st.session_state[ajust_key] = bool(row["ajusteManual"])

      map_key = f"map_edit_preview_{row['fid']}"
      if map_key in st.session_state and st.session_state[map_key] and st.session_state[map_key].get("last_clicked"):
        clicked_data = st.session_state[map_key]["last_clicked"]
        lat_c = clicked_data["lat"]
        lon_c = clicked_data["lng"]
        utm_x, utm_y = transformer_to_utm.transform(lon_c, lat_c)
        new_x = round(utm_x, 2)
        new_y = round(utm_y, 3)
        if st.session_state[x_key] != new_x or st.session_state[y_key] != new_y:
          st.session_state[ant_x_key] = st.session_state[x_key]
          st.session_state[ant_y_key] = st.session_state[y_key]
          st.session_state[x_key] = new_x
          st.session_state[y_key] = new_y
          st.session_state[ajust_key] = True

      col_inputs_left, col_map_right = st.columns([1.1, 1.2], gap="large")

      with col_inputs_left:
        ic1, ic2 = st.columns(2)
        with ic1:
          st.text_input(
              "FID",
              value=str(row["fid"] or 0),
              disabled=True,
              key=f"fid_bloq_{row['fid']}",
          )
          st.text_input(
              "Serie",
              value=str(row["serie"] or ""),
              key=f"ser_{row['fid']}",
          )
          st.text_input(
              "Domicilio", value=str(row["domicilio"] or ""), key=f"dom_{row['fid']}"
          )
          st.number_input(
              "Latitud",
              format="%.6f",
              value=float(row["latitud"] or 21.8853),
              key=f"lat_{row['fid']}",
          )
          st.number_input(
              "Precisión GPS",
              value=float(row["precisionGps"] or 0.0),
              key=f"prec_{row['fid']}",
          )
          st.checkbox(
              "Activo",
              value=bool(row["activo"]),
              key=f"act_{row['fid']}",
          )
          st.number_input(
              "Coordenada X",
              format="%.2f",
              key=x_key,
          )
          st.number_input(
              "Coordenada X Anterior",
              format="%.2f",
              key=ant_x_key,
          )

        with ic2:
          st.text_input(
              "Medidor ID", value=str(row["medidorId"] or ""), key=f"medid_{row['fid']}"
          )
          st.number_input(
              "Toma",
              value=int(row["toma"] or 0),
              key=f"tom_{row['fid']}",
          )
          st.text_input(
              "Colonia",
              value=str(row["colonia"] or ""),
              key=f"col_{row['fid']}",
          )
          st.number_input(
              "Longitud",
              format="%.6f",
              value=float(row["longitud"] or -102.2916),
              key=f"lon_{row['fid']}",
          )
          st.checkbox(
              "Ajuste Manual",
              key=ajust_key,
          )
          st.text_input(
              "Predio_Viv",
              value=str(row["Predio_Viv"] or ""),
              key=f"pviv_{row['fid']}",
          )
          st.number_input(
              "Coordenada Y",
              format="%.3f",
              key=y_key,
          )
          st.number_input(
              "Coordenada Y Anterior",
              format="%.3f",
              key=ant_y_key,
          )

        st.text_area(
            "Observaciones",
            value=str(row["observaciones"] or ""),
            key=f"obs_{row['fid']}",
        )

      with col_map_right:
        st.markdown(
            "<p style='color: #00E5FF; font-size: 0.85rem; font-weight: 700;"
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
                location=[lat_ed, lon_ed], zoom_start=17, control_scale=True
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

          st_folium(
              m_ed,
              width="100%",
              height=540,
              key=map_key,
              returned_objects=["last_clicked"],
          )

        except Exception as e_map_ed:
          st.info(
              "Haga clic en el mapa para actualizar la posición geográfica."
              f" ({e_map_ed})"
          )
  else:
    st.info("No se encontró ningún registro para editar.")

# Renderizar botones de acción en la barra lateral si estamos en la pestaña Editar
if st.session_state.active_tab == "⚙️ Editar" and not df_lev.empty and row_first is not None:
  with st.sidebar:
    st.markdown(
        "<hr style='border: 0.5px solid rgba(0,229,255,0.2); margin: 15px 0;'>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #00E5FF; font-size: 0.85rem; font-weight: 700;"
        " margin-bottom: 10px;'>💾 Acciones de Registro</p>",
        unsafe_allow_html=True,
    )

    if st.button("🔄 Restablecer Originales", key="btn_reset_sidebar", use_container_width=True):
      e_fid = int(row_first["fid"])
      x_key = f"coord_x_input_{e_fid}"
      y_key = f"coord_y_input_{e_fid}"
      ant_x_key = f"coord_ant_x_input_{e_fid}"
      ant_y_key = f"coord_ant_y_input_{e_fid}"
      ajust_key = f"ajust_{e_fid}"
      map_key = f"map_edit_preview_{e_fid}"

      for k in [x_key, y_key, ant_x_key, ant_y_key, ajust_key, map_key]:
        if k in st.session_state:
          del st.session_state[k]

      st.success("¡Datos restablecidos a sus valores originales!")
      t.sleep(0.8)
      st.rerun()

    if st.button("💾 Actualizar Registro", key="btn_act_sidebar", use_container_width=True):
      try:
        e_fid = int(row_first["fid"])
        default_x = float(row_first["coord_x"]) if pd.notna(row_first["coord_x"]) else 0.0
        default_y = float(row_first["coord_y"]) if pd.notna(row_first["coord_y"]) else 0.0

        x_key = f"coord_x_input_{e_fid}"
        y_key = f"coord_y_input_{e_fid}"
        ant_x_key = f"coord_ant_x_input_{e_fid}"
        ant_y_key = f"coord_ant_y_input_{e_fid}"
        ajust_key = f"ajust_{e_fid}"

        fecha_mod_str = datetime.datetime.now(zona_mx).strftime("%Y-%m-%d %H:%M:%S")
        
        nuevo_x = float(st.session_state.get(x_key, default_x))
        nuevo_y = float(st.session_state.get(y_key, default_y))
        nuevo_ant_x = float(st.session_state.get(ant_x_key, 0.0))
        nuevo_ant_y = float(st.session_state.get(ant_y_key, 0.0))
        
        hubo_cambio_coord = (nuevo_x != default_x) or (nuevo_y != default_y)
        
        sql_update = """
                      UPDATE "Usuarios"."levantamientos" 
                      SET "medidorId" = :medidorId, serie = :serie, toma = :toma, 
                          domicilio = :domicilio, colonia = :colonia, latitud = :latitud, 
                          longitud = :longitud, "precisionGps" = :precisionGps, 
                          "ajusteManual" = :ajusteManual, observaciones = :observaciones, 
                          activo = :activo, "Predio_Viv" = :Predio_Viv, 
                          "Latitud" = :Latitud, "Longitud" = :Longitud, 
                          "fechaModificacion" = :fechaModificacion, 
                          {geom_ant_sql}
                          geom = ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                      WHERE fid = :fid
                  """.format(
                      geom_ant_sql='geom_ant = ST_SetSRID(ST_MakePoint(:coord_ant_x, :coord_ant_y), 32613),' if hubo_cambio_coord else ''
                  )

        params_sql = {
            "fid": e_fid,
            "medidorId": st.session_state.get(f"medid_{e_fid}", str(row_first["medidorId"] or "")).strip(),
            "serie": st.session_state.get(f"ser_{e_fid}", str(row_first["serie"] or "")) or None,
            "toma": int(st.session_state.get(f"tom_{e_fid}", int(row_first["toma"] or 0))),
            "domicilio": st.session_state.get(f"dom_{e_fid}", str(row_first["domicilio"] or "")) or None,
            "colonia": st.session_state.get(f"col_{e_fid}", str(row_first["colonia"] or "")) or None,
            "latitud": float(st.session_state.get(f"lat_{e_fid}", float(row_first["latitud"] or 21.8853))),
            "longitud": float(st.session_state.get(f"lon_{e_fid}", float(row_first["longitud"] or -102.2916))),
            "precisionGps": float(st.session_state.get(f"prec_{e_fid}", float(row_first["precisionGps"] or 0.0))),
            "ajusteManual": bool(st.session_state.get(ajust_key, bool(row_first["ajusteManual"]))),
            "observaciones": st.session_state.get(f"obs_{e_fid}", str(row_first["observaciones"] or "")) or None,
            "activo": bool(st.session_state.get(f"act_{e_fid}", bool(row_first["activo"]))),
            "Predio_Viv": st.session_state.get(f"pviv_{e_fid}", str(row_first["Predio_Viv"] or "")) or None,
            "Latitud": float(st.session_state.get(f"lat_{e_fid}", float(row_first["latitud"] or 21.8853))),
            "Longitud": float(st.session_state.get(f"lon_{e_fid}", float(row_first["longitud"] or -102.2916))),
            "fechaModificacion": fecha_mod_str,
            "coord_x": nuevo_x,
            "coord_y": nuevo_y,
        }
        if hubo_cambio_coord:
          params_sql["coord_ant_x"] = nuevo_ant_x
          params_sql["coord_ant_y"] = nuevo_ant_y

        ejecutar_sql(sql_update, params_sql)

        for k in [x_key, y_key, ant_x_key, ant_y_key, ajust_key, f"map_edit_preview_{e_fid}"]:
          if k in st.session_state:
            del st.session_state[k]

        st.success(f"¡Predio FID {e_fid} actualizado con éxito!")
        t.sleep(1)
        st.rerun()
      except Exception as ex:
        st.error(f"Error al actualizar: {ex}")

    if not es_operador:
      if st.session_state.registro_to_delete == row_first["fid"]:
        st.markdown(
            f"<p style='color: #ff4d4d; font-size: 0.8rem; font-weight: bold; margin-top: 8px;'>Escribe 'delete' para confirmar:</p>",
            unsafe_allow_html=True,
        )
        confirm_text = st.text_input("Confirmación", key=f"input_del_sidebar_{row_first['fid']}")
        c_y, c_n = st.columns(2)
        with c_y:
          if st.button("Sí, borrar", key="btn_yes_del", use_container_width=True):
            if confirm_text.strip() == "delete":
              try:
                ejecutar_sql('DELETE FROM "Usuarios"."levantamientos" WHERE fid = :fid', {"fid": int(row_first["fid"])})
                st.session_state.registro_to_delete = None
                st.success("Registro eliminado.")
                t.sleep(1)
                st.rerun()
              except Exception as ex_del:
                st.error(f"Error: {ex_del}")
            else:
              st.error("Escribe 'delete'.")
        with c_n:
          if st.button("Cancelar", key="btn_cancel_del", use_container_width=True):
            st.session_state.registro_to_delete = None
            st.rerun()
      else:
        if st.button("🗑️ Eliminar Registro", key="btn_del_sidebar", use_container_width=True):
          st.session_state.registro_to_delete = row_first["fid"]
          st.rerun()


# 08B ---------------------------------------------------------------------------------- SECCIÓN: DASHBOARD GENERAL ---------------------------------------------------------------------------------------
if st.session_state.active_tab == "📊 Dashboard General":
  st.markdown(
      """
      <div style="margin-bottom: 12px;">
          <h2 style="color: #00E5FF; font-size: 1.3rem; font-weight: 800; margin-bottom: 2px;">📊 Dashboard General de Levantamientos</h2>
          <p style="color: #94A3B8; font-size: 0.85rem;">Resumen estadístico, gráficos de instalaciones y mapa 3D de ubicación.</p>
      </div>
      """,
      unsafe_allow_html=True,
  )

  df_dash, err_dash = obtener_datos(
      'SELECT fid, "fechaRegistro", "ajusteManual" FROM "Usuarios"."levantamientos"'
  )

  total_reg = len(df_dash) if not err_dash and not df_dash.empty else 0
  ajuste_manual_count = (
      len(df_dash[df_dash["ajusteManual"] == True])
      if not err_dash and not df_dash.empty
      else 0
  )

  # Tarjetas superiores compactas
  c_m1, c_m2 = st.columns(2)
  with c_m1:
    st.markdown(
        f"""
        <div style="background: #0D1424; border: 1px solid rgba(0, 229, 255, 0.2); border-left: 4px solid #00E5FF; border-radius: 6px; padding: 12px 16px; box-shadow: 0 2px 10px rgba(0,0,0,0.2);">
            <div style="color: #94A3B8; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Levantamientos</div>
            <div style="display: flex; align-items: baseline; justify-content: space-between;">
                <div style="color: #00E5FF; font-size: 1.6rem; font-weight: 800;">{total_reg:,}</div>
                <div style="color: #94A3B8; font-size: 0.75rem;">Total</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  with c_m2:
    st.markdown(
        f"""
        <div style="background: #0D1424; border: 1px solid rgba(0, 229, 255, 0.2); border-left: 4px solid #3B82F6; border-radius: 6px; padding: 12px 16px; box-shadow: 0 2px 10px rgba(0,0,0,0.2);">
            <div style="color: #94A3B8; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Levantamientos con Ajuste Manual</div>
            <div style="display: flex; align-items: baseline; justify-content: space-between;">
                <div style="color: #00E5FF; font-size: 1.6rem; font-weight: 800;">{ajuste_manual_count:,} con ajuste</div>
                <div style="color: #94A3B8; font-size: 0.75rem;">Ajuste manual: <b>{ajuste_manual_count:,}</b></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

  # Gráfica superior con selector de tipo de vista (Diaria / Mensual)
  col_titulo_g, col_botones_g = st.columns([3, 1])
  with col_titulo_g:
    st.markdown(
        "<h4 style='color: #00E5FF; font-size: 1.05rem; font-weight: 700; margin-bottom: 0px;'>Instalaciones de Medidores</h4>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #94A3B8; font-size: 0.8rem; margin-top: 0px;'>Todos los registros</p>",
        unsafe_allow_html=True,
    )
  with col_botones_g:
    tipo_vista = st.radio(
        "Vista Gráfico",
        ["Mensual", "Diaria"],
        index=1 if st.session_state.tipo_vista_grafico == "Diaria" else 0,
        horizontal=True,
        label_visibility="collapsed",
        key="selector_vista_grafico",
    )
    st.session_state.tipo_vista_grafico = tipo_vista

  if not err_dash and not df_dash.empty:
    df_dash["fecha_dt"] = pd.to_datetime(
        df_dash["fechaRegistro"], errors="coerce"
    )
    
    if st.session_state.tipo_vista_grafico == "Diaria":
      df_dias = (
          df_dash.groupby(df_dash["fecha_dt"].dt.date)
          .size()
          .reset_index(name="count")
      )
      df_dias = df_dias.dropna().sort_values("fecha_dt")
      df_dias["fecha_str"] = pd.to_datetime(df_dias["fecha_dt"]).dt.strftime(
          "%d-%b"
      ).str.lower()

      chart_data = pd.DataFrame(
          {"Instalaciones": df_dias["count"].values},
          index=df_dias["fecha_str"].values,
      )
      st.bar_chart(chart_data, color="#2B7DE9", height=280)
    else:
      df_dash["mes_anio"] = df_dash["fecha_dt"].dt.to_period("M")
      df_meses = (
          df_dash.groupby("mes_anio").size().reset_index(name="count")
      )
      df_meses = df_meses.dropna().sort_values("mes_anio")
      df_meses["mes_str"] = df_meses["mes_anio"].dt.strftime("%b %Y")

      chart_data = pd.DataFrame(
          {"Instalaciones": df_meses["count"].values},
          index=df_meses["mes_str"].values,
      )
      st.bar_chart(chart_data, color="#2B7DE9", height=280)
  else:
    st.info("No hay datos suficientes para mostrar la gráfica.")

  st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

  # Mapa 3D de Ubicación de Medidores
  st.markdown(
      "<h4 style='color: #00E5FF; font-size: 1.05rem; font-weight: 700; margin-bottom: 5px;'>Mapa de Ubicación de Medidores</h4>",
      unsafe_allow_html=True,
  )

  df_map_3d, err_map_3d = obtener_datos("""
        SELECT fid, "medidorId", ST_X(geom) as lon, ST_Y(geom) as lat 
        FROM "Usuarios"."levantamientos" 
        WHERE geom IS NOT NULL 
        LIMIT 1000
    """)

  if not err_map_3d and not df_map_3d.empty:
    puntos_3d = []
    for _, r in df_map_3d.iterrows():
      if pd.notna(r["lon"]) and pd.notna(r["lat"]):
        lon_wgs, lat_wgs = transformer_to_latlon.transform(r["lon"], r["lat"])
        puntos_3d.append({
            "position": [lon_wgs, lat_wgs],
            "elevation": 30,
            "color": [0, 229, 255, 200],
        })

    view_state = pdk.ViewState(
        latitude=21.8853, longitude=-102.2916, zoom=14, pitch=45, bearing=0
    )

    layer = pdk.Layer(
        "ColumnLayer",
        data=puntos_3d,
        get_position="position",
        get_elevation="elevation",
        elevation_scale=1,
        radius=3,
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
    )

    r_deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip={"text": "Medidor ID: {medidorId}"},
        map_style=pdk.map_styles.DARK,
    )
    st.pydeck_chart(r_deck)
  else:
    st.info("No hay geometrías disponibles para renderizar el mapa 3D.")


# 09 ----------------------------------------------------------------------------------- ZONA: AJUSTES MANUALES ---------------------------------------------------------------------------------------------
if st.session_state.active_tab == "🛠️ Ajustes Manuales":
  st.markdown(
      """
      <div style="margin-bottom: 20px;">
          <h2 style="color: #00E5FF; font-size: 1.4rem; font-weight: 700; margin-bottom: 5px;">🛠️ Registros con Ajuste Manual</h2>
          <p style="color: #94A3B8; font-size: 0.9rem;">Listado completo de predios que han sido modificados o ajustados manualmente.</p>
      </div>
      """,
      unsafe_allow_html=True,
  )

  query_manuales = f"""
        SELECT {COLUMNAS_LEV} 
        FROM "Usuarios"."levantamientos" 
        WHERE "ajusteManual" = TRUE 
        ORDER BY fid
    """
  df_manuales, err_man = obtener_datos(query_manuales)

  if err_man:
    st.error(f"Error al obtener los registros: {err_man}")
  elif df_manuales.empty:
    st.info("No se encontró ningún registro con ajuste manual activo.")
  else:
    st.success(f"Se encontraron {len(df_manuales)} registros con ajuste manual.")
    
    df_mostrar = df_manuales[[
        "fid", "medidorId", "serie", "toma", "domicilio", "colonia", 
        "coord_x", "coord_y", "coord_ant_x", "coord_ant_y", "fechaModificacion"
    ]].copy()
    
    df_mostrar = formatear_columnas_fecha(df_mostrar)
    st.dataframe(df_mostrar, use_container_width=True, hide_index=True)


# 10 ----------------------------------------------------------------------------------- ZONA: SERIES DUPLICADAS ---------------------------------------------------------------------------------------------
elif st.session_state.active_tab == "⚠️ Series Duplicadas":
  st.markdown(
      """
      <div style="margin-bottom: 20px;">
          <h2 style="color: #00E5FF; font-size: 1.4rem; font-weight: 700; margin-bottom: 5px;">⚠️ Control de Series Duplicadas</h2>
          <p style="color: #94A3B8; font-size: 0.9rem;">Detección de números de serie repetidos y herramienta para eliminar duplicados dejando solo un registro.</p>
      </div>
      """,
      unsafe_allow_html=True,
  )

  query_duplicados = """
        SELECT {cols} 
        FROM "Usuarios"."levantamientos" 
        WHERE serie IS NOT NULL AND TRIM(serie) != '' AND serie IN (
            SELECT serie 
            FROM "Usuarios"."levantamientos" 
            WHERE serie IS NOT NULL AND TRIM(serie) != '' 
            GROUP BY serie 
            HAVING COUNT(*) > 1
        )
        ORDER BY serie, fid
    """.format(cols=COLUMNAS_LEV)

  df_dups, err_dup = obtener_datos(query_duplicados)

  if err_dup:
    st.error(f"Error al consultar duplicados: {err_dup}")
  elif df_dups.empty:
    st.success("¡Excelente! No hay números de serie duplicados en la base de datos.")
  else:
    total_duplicados = len(df_dups)
    series_unicas = df_dups["serie"].nunique()
    
    st.warning(f"Se encontraron **{total_duplicados} registros** distribuidos en **{series_unicas} números de serie** repetidos.")

    col_btn_limpiar, col_info_limp = st.columns([1.5, 3])
    with col_btn_limpiar:
      if st.button("🧹 Eliminar Duplicados (Conservar el menor FID)", use_container_width=True):
        try:
          sql_delete_dups = """
                        DELETE FROM "Usuarios"."levantamientos" 
                        WHERE fid NOT IN (
                            SELECT MIN(fid) 
                            FROM "Usuarios"."levantamientos" 
                            WHERE serie IS NOT NULL AND TRIM(serie) != '' 
                            GROUP BY serie
                        ) AND serie IN (
                            SELECT serie 
                            FROM "Usuarios"."levantamientos" 
                            WHERE serie IS NOT NULL AND TRIM(serie) != '' 
                            GROUP BY serie 
                            HAVING COUNT(*) > 1
                        )
                    """
          ejecutar_sql(sql_delete_dups)
          st.success("¡Duplicados eliminados correctamente! Se ha conservado únicamente el registro original (menor FID) por cada serie.")
          t.sleep(1.5)
          st.rerun()
        except Exception as e_del_dup:
          st.error(f"Error al eliminar duplicados: {e_del_dup}")

    with col_info_limp:
      st.markdown(
          "<p style='color: #94A3B8; font-size: 0.85rem; margin-top: 10px;'>"
          "Nota: Al hacer clic en limpiar, el sistema mantendrá el registro con el <b>FID más bajo</b> de cada serie repetida y borrará los demás."
          "</p>",
          unsafe_allow_html=True,
      )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #00E5FF; font-size: 1.1rem;'>Detalle de Registros Duplicados:</h4>", unsafe_allow_html=True)
    
    df_mostrar_dup = df_dups[[
        "fid", "medidorId", "serie", "toma", "domicilio", "colonia", 
        "fechaRegistro", "activo"
    ]].copy()
    
    df_mostrar_dup = formatear_columnas_fecha(df_mostrar_dup)
    st.dataframe(df_mostrar_dup, use_container_width=True, hide_index=True)


# 11 -------------------------------------------------------------------------------------- PIE DE PÁGINA --------------------------------------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align: center; color: #94A3B8; font-size: 0.8rem; margin-top: 30px;">
        MIAA - Sistema de Gestión de Levantamientos de Predios © 2026
    </div>
    """,
    unsafe_allow_html=True,
)
