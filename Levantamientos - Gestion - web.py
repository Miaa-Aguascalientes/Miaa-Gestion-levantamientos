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
  st.session_state.active_tab = "⚙️ Editar"
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
                        SELECT id, usuario, password, tipo_usuario, departamento 
                        FROM usuarios_levantamientos 
                        WHERE TRIM(usuario) = :usu AND TRIM(password) = :pas
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

  opciones_menu = ["⚙️ Editar"]

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
      'SELECT fid, "medidorId", serie, domicilio, colonia, activo FROM "Usuarios"."levantamientos"'
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
    fid, "medidorId", serie, toma, domicilio, colonia, latitud, longitud, "precisionGps", 
    "ajusteManual", observaciones, "usuarioNombre", "fechaRegistro", "fechaModificacion", 
    activo, "Predio_Viv", "Latitud", "Longitud", "_Ultima_actualizacion",
    ST_X(geom) as coord_x, ST_Y(geom) as coord_y,
    ST_X(geom_ant) as coord_ant_x, ST_Y(geom_ant) as coord_ant_y
"""

# 08 -------------------------------------------------------------------------------------- EDITAR Y ELIMINAR ----------------------------------------------------------------------------------------------

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
      e_fid = row["fid"]
      default_x = float(row["coord_x"]) if pd.notna(row["coord_x"]) else 0.0
      default_y = float(row["coord_y"]) if pd.notna(row["coord_y"]) else 0.0

      db_original_x = default_x
      db_original_y = default_y

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
          
          nuevo_x = st.session_state[x_key]
          nuevo_y = st.session_state[y_key]
          
          hubo_cambio_coord = (nuevo_x != db_original_x) or (nuevo_y != db_original_y)
          
          if hubo_cambio_coord:
            sql_update = """
                          UPDATE "Usuarios"."levantamientos" 
                          SET "medidorId" = :medidorId, serie = :serie, toma = :toma, 
                              domicilio = :domicilio, colonia = :colonia, latitud = :latitud, 
                              longitud = :longitud, "precisionGps" = :precisionGps, 
                              "ajusteManual" = :ajusteManual, observaciones = :observaciones, 
                              activo = :activo, "Predio_Viv" = :Predio_Viv, 
                              "Latitud" = :Latitud, "Longitud" = :Longitud, 
                              "fechaModificacion" = :fechaModificacion, 
                              geom_ant = COALESCE(geom_ant, ST_SetSRID(ST_MakePoint(:orig_x, :orig_y), 32613)),
                              geom = ST_SetSRID(ST_MakePoint(:coord_x, :coord_y), 32613)
                          WHERE fid = :fid
                      """
          else:
            sql_update = """
                          UPDATE "Usuarios"."levantamientos" 
                          SET "medidorId" = :medidorId, serie = :serie, toma = :toma, 
                              domicilio = :domicilio, colonia = :colonia, latitud = :latitud, 
                              longitud = :longitud, "precisionGps" = :precisionGps, 
                              "ajusteManual" = :ajusteManual, observaciones = :observaciones, 
                              activo = :activo, "Predio_Viv" = :Predio_Viv, 
                              "Latitud" = :Latitud, "Longitud" = :Longitud, 
                              "fechaModificacion" = :fechaModificacion, 
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
                  "coord_x": nuevo_x,
                  "coord_y": nuevo_y,
                  "orig_x": db_original_x,
                  "orig_y": db_original_y,
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

# 09 -------------------------------------------------------------------------------------- PIE DE PÁGINA --------------------------------------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align: center; color: #94A3B8; font-size: 0.8rem; margin-top: 30px;">
        MIAA - Sistema de Gestión de Levantamientos de Predios © 2026
    </div>
    """,
    unsafe_allow_html=True,
)
