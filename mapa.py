import streamlit as st
import pandas as pd
import folium
import requests
import io
import simplekml
from streamlit_folium import st_folium
from datetime import datetime, timedelta

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Catastro de Relaves", layout="wide")

if 'data' not in st.session_state:
    st.session_state.data = None

# --- CABECERA ---
st.title("🏛️ Catastro Nacional de Depósitos de Relaves")
st.subheader("Análisis de Vulnerabilidad Climática y Estado Operativo")

# DESCRIPCIÓN DE LA PLATAFORMA
st.markdown("""
> *Esta plataforma automatiza la evaluación del riesgo meteorológico en depósitos de relaves a lo largo de Chile. 
Cruza la base de datos oficial del Servicio Nacional de Geología y Minería (Sernageomin) con pronósticos climáticos 
avanzados para identificar, de manera geoespacial, las instalaciones bajo alerta por precipitaciones críticas.*
""")

# 1. TÍTULO CORREGIDO
st.markdown(f"""
    **Desarrollador:**  
    **© 2026 Leonardo Díaz Vergara** | Ingeniero Civil en Minas (USACH) | Ingeniero Geomensor (UDEC)  
    📧 [leonardodiazvergara@gmail.com](mailto:leonardodiazvergara@gmail.com)
""")

st.info("""
    📌 **FUENTES DE INFORMACIÓN Y MODELACIÓN:**
    *   **Archivo Base:** `CATASTRO_RELAVES_CHILE_OCT2025.xlsx` (Sernageomin)
    *   **Modelo Meteorológico:** ECMWF (European Centre for Medium-Range Weather Forecasts) - *High Resolution*
""")
st.markdown("---")

# --- CARGAR DATOS ---
@st.cache_data(ttl=3600)
def cargar_datos():
    df = pd.read_excel("RELAVES_CHILE_OCT2025.xlsx", header=6)
    return df.dropna(subset=['LATITUD', 'LONGITUD']).copy()

df_raw = cargar_datos()

# 2. FUNCIÓN DE CÁLCULO DE ESTADO OPERATIVO
def calcular_estado_operativo(row):
    res_cierre = str(row.get('RES_PDC_APRUEBA', '')).strip()
    fecha_cierre = str(row.get('FECHA_RES_PDC', '')).strip()
    
    # Regla de Cierre
    if (res_cierre and res_cierre.lower() not in ['nan', 'none', 'nat']) or \
       (fecha_cierre and fecha_cierre.lower() not in ['nan', 'none', 'nat']):
        return "En Cierre / Cerrado"
    
    # Regla de Capacidad
    try:
        vol_actual = float(row.get('VOL_ACTUAL', 0))
        vol_autor = float(row.get('VOL_AUTORIZADO', 0))
        
        if vol_autor > 0:
            porcentaje = (vol_actual / vol_autor) * 100
            if porcentaje >= 100:
                return "Inactivo (Capacidad Alcanzada)"
            else:
                return f"Operativo ({porcentaje:.1f}% llenado)"
        else:
            return "Sin Información de Volumen"
    except:
        return "Sin Información"

# --- FILTROS ---
col1, col2, col3 = st.columns(3)
regiones = ["Todas"] + sorted(df_raw['REGION'].dropna().unique().tolist())
sel_reg = col1.selectbox("Región:", regiones)
df_temp = df_raw if sel_reg == "Todas" else df_raw[df_raw['REGION'] == sel_reg]

provincias = ["Todas"] + sorted(df_temp['PROVINCIA'].dropna().unique().tolist())
sel_prov = col2.selectbox("Provincia:", provincias)
df_temp = df_temp if sel_prov == "Todas" else df_temp[df_temp['PROVINCIA'] == sel_prov]

comunas = ["Todas"] + sorted(df_temp['COMUNA'].dropna().unique().tolist())
sel_com = col3.selectbox("Comuna:", comunas)
df_temp = df_temp if sel_com == "Todas" else df_temp[df_temp['COMUNA'] == sel_com]

seleccion_final = st.multiselect("Seleccione Depósitos:", sorted(df_temp['NOMBRE_INSTALACION'].unique().tolist()))
col_f1, col_f2 = st.columns(2)
f_ini = col_f1.date_input("Fecha Inicio", datetime.now())
f_fin = col_f2.date_input("Fecha Fin", datetime.now() + timedelta(days=5))

# --- EJECUCIÓN ---
if st.button("🚀 Ejecutar Análisis", type="primary"):
    if not seleccion_final:
        st.error("⚠️ Debe seleccionar al menos un depósito.")
    else:
        with st.spinner("Procesando datos climáticos y calculando estados..."):
            df_res = df_raw[df_raw['NOMBRE_INSTALACION'].isin(seleccion_final)].copy()
            lluvias = []
            alertas = []
            
            # Aplicar cálculo de estado operativo
            df_res['ESTADO_OPERATIVO'] = df_res.apply(calcular_estado_operativo, axis=1)
            
            for _, fila in df_res.iterrows():
                url = f"https://api.open-meteo.com/v1/forecast?latitude={fila['LATITUD']}&longitude={fila['LONGITUD']}&daily=precipitation_sum&start_date={f_ini.strftime('%Y-%m-%d')}&end_date={f_fin.strftime('%Y-%m-%d')}"
                try:
                    res = requests.get(url).json()
                    val = round(sum([x for x in res.get('daily', {}).get('precipitation_sum', [0]) if x is not None]), 2)
                    lluvias.append(val)
                    alertas.append('CRÍTICO' if val > 15 else ('PRECAUCIÓN' if val > 0 else 'NORMAL'))
                except:
                    lluvias.append(0.0)
                    alertas.append('NORMAL')
            
            df_res['LLUVIA_MM'] = lluvias
            df_res['NIVEL_ALERTA'] = alertas
            df_res['FECHA_INICIO'] = f_ini.strftime('%Y-%m-%d')
            df_res['FECHA_FIN'] = f_fin.strftime('%Y-%m-%d')
            st.session_state.data = df_res

# --- VISUALIZACIÓN ---
if st.session_state.data is not None:
    df_res = st.session_state.data
    
    # MAPA POPUP
    coords = df_res[['LATITUD', 'LONGITUD']].values.tolist()
    mapa = folium.Map(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr='Esri World Imagery')
    
    for _, fila in df_res.iterrows():
        val = fila['LLUVIA_MM']
        col = "red" if val > 15 else ("orange" if val > 0 else "blue")
        estado_txt = fila['ESTADO_OPERATIVO']
        
        popup_html = f"""
        <div style="width:280px; font-family: Arial, sans-serif; font-size:12px;">
            <h4 style="margin-top:0; color:#2C3E50;">{fila.get('NOMBRE_INSTALACION', '-')}</h4>
            <b>Empresa:</b> {fila.get('NOMBRE_EMPRESA_O_PRODUCTOR_MINERO', '-')}<br>
            <b>Faena:</b> {fila.get('NOMBRE_FAENA', '-')}<br>
            <b>Tipo:</b> {fila.get('TIPO_DEPOSITO', '-')}<br>
            <b>Estado:</b> <span style="color:#00509E; font-weight:bold;">{estado_txt}</span><br>
            <b>Ubicación:</b> {fila.get('REGION', '-')}, {fila.get('PROVINCIA', '-')}, {fila.get('COMUNA', '-')}<br>
            <b>UTM Norte:</b> {fila.get('UTM_NORTE', '-')}<br>
            <b>UTM Este:</b> {fila.get('UTM_ESTE', '-')}<br>
            <b>Datum / Huso:</b> {fila.get('DATUM', '-')} / {fila.get('HUSO', '-')}<br>
            <hr style="margin:8px 0;">
            <div style="background-color:#f8f9fa; padding:5px; border-radius:5px;">
                <b style="color:{col}; font-size:14px;">Lluvia: {val} mm ({fila['NIVEL_ALERTA']})</b><br>
                <b>Análisis:</b> {fila['FECHA_INICIO']} al {fila['FECHA_FIN']}
            </div>
        </div>
        """
        folium.CircleMarker([fila['LATITUD'], fila['LONGITUD']], radius=10, color=col, fill=True, popup=folium.Popup(popup_html, max_width=320)).add_to(mapa)
    
    if coords: mapa.fit_bounds(coords, padding=(50, 50))
    st_folium(mapa, width=1200, height=450)
    
    st.markdown("""
    <div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #454d66; color: white;">
        <b>Leyenda de Riesgo:</b> 
        <span style="color:#FF4B4B;">●</span> > 15mm (Crítico) | 
        <span style="color:#FFA500;">●</span> 0.1-15mm (Precaución) | 
        <span style="color:#1C83E1;">●</span> 0mm (Normal)
    </div>
    """, unsafe_allow_html=True)
    
    # ORDENAR COLUMNAS PRIORITARIAS (Lluvia, Alerta, Fechas, Estado Calculado)
    cols_priority = ['LLUVIA_MM', 'NIVEL_ALERTA', 'ESTADO_OPERATIVO', 'FECHA_INICIO', 'FECHA_FIN']
    cols_rest = [c for c in df_res.columns if c not in cols_priority]
    df_export = df_res[cols_priority + cols_rest]
    
    st.subheader("Detalle del Análisis")
    st.dataframe(df_export, use_container_width=True)
    
    # EXPORTACIÓN
    c1, c2 = st.columns(2)
    
    # EXCEL FORMATO "FICHAS"
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Reporte Vulnerabilidad')
        
        titulo_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'font_color': 'white', 'bg_color': '#1F4E78', 'valign': 'vcenter'})
        subtitulo_fmt = workbook.add_format({'bold': True, 'font_size': 10, 'font_color': '#2C3E50'})
        header_fmt = workbook.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#2C3E50', 'border': 1})
        val_fmt = workbook.add_format({'border': 1})
        
        fmt_critico = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True, 'border': 1})
        fmt_precau = workbook.add_format({'bg_color': '#FFEB9C', 'font_color': '#9C6500', 'bold': True, 'border': 1})
        fmt_normal = workbook.add_format({'bg_color': '#BDD7EE', 'font_color': '#003366', 'bold': True, 'border': 1})
        
        worksheet.write(0, 0, "🏛️ CATASTRO NACIONAL DE DEPÓSITOS DE RELAVES", titulo_fmt)
        worksheet.set_row(0, 22)
        worksheet.write(1, 0, "Desarrollador: Leonardo Díaz Vergara | Ing. Civil en Minas | Ing. Geomensor", subtitulo_fmt)
        worksheet.write(2, 0, "Fuentes: CATASTRO_RELAVES_CHILE_OCT2025.xlsx | Modelo: ECMWF (IFS - High Resolution)", subtitulo_fmt)
        
        fila_actual = 4
        for idx, row in df_export.iterrows():
            worksheet.merge_range(fila_actual, 0, fila_actual, 4, f"▶ INSTALACIÓN: {row['NOMBRE_INSTALACION']}", titulo_fmt)
            fila_actual += 1
            
            items = list(row.items())
            max_filas = 20
            chunks = [items[i:i + max_filas] for i in range(0, len(items), max_filas)]
            fila_inicio_bloque = fila_actual
            
            for chunk_idx, chunk in enumerate(chunks):
                col_offset = chunk_idx * 3
                worksheet.write(fila_inicio_bloque, col_offset, "PARÁMETRO", header_fmt)
                worksheet.write(fila_inicio_bloque, col_offset + 1, "VALOR", header_fmt)
                
                for r_idx, (col_name, val) in enumerate(chunk):
                    r_pos = fila_inicio_bloque + 1 + r_idx
                    worksheet.write(r_pos, col_offset, str(col_name), header_fmt)
                    
                    if col_name in ['LLUVIA_MM', 'NIVEL_ALERTA']:
                        alerta = row['NIVEL_ALERTA']
                        if alerta == 'CRÍTICO': worksheet.write(r_pos, col_offset + 1, str(val), fmt_critico)
                        elif alerta == 'PRECAUCIÓN': worksheet.write(r_pos, col_offset + 1, str(val), fmt_precau)
                        else: worksheet.write(r_pos, col_offset + 1, str(val), fmt_normal)
                    else:
                        val_str = str(val) if pd.notna(val) else "Sin Información"
                        worksheet.write(r_pos, col_offset + 1, val_str, val_fmt)
                        
            max_chunk_len = max([len(c) for c in chunks])
            fila_actual = fila_inicio_bloque + max_chunk_len + 2 
            
        for c in range(15):
            if c % 3 != 2: worksheet.set_column(c, c, 35)
            else: worksheet.set_column(c, c, 2)
            
    c1.download_button("📥 Descargar Excel Profesional", output.getvalue(), "Reporte_Relaves.xlsx", use_container_width=True)
    
    # 4. KML CON METADATOS ORGANIZADOS
    kml = simplekml.Kml()
    kml.document.name = "Análisis Vulnerabilidad Relaves"
    kml.document.description = "Desarrollador: Leonardo Díaz Vergara\nFuentes: CATASTRO_RELAVES_CHILE_OCT2025.xlsx | ECMWF"
    
    for _, fila in df_res.iterrows():
        pnt = kml.newpoint(name=str(fila['NOMBRE_INSTALACION']), coords=[(fila['LONGITUD'], fila['LATITUD'])])
        
        # INYECTAR EN ORDEN (Análisis, Estado Calculado, Fechas)
        pnt.extendeddata.newdata(name="1. Lluvia (mm)", value=str(fila['LLUVIA_MM']))
        pnt.extendeddata.newdata(name="2. Alerta Climática", value=str(fila['NIVEL_ALERTA']))
        pnt.extendeddata.newdata(name="3. Estado Operativo", value=str(fila['ESTADO_OPERATIVO']))
        pnt.extendeddata.newdata(name="4. Fecha Inicio Analisis", value=str(fila['FECHA_INICIO']))
        pnt.extendeddata.newdata(name="5. Fecha Fin Analisis", value=str(fila['FECHA_FIN']))
        
        for col in df_res.columns:
            if col not in ['LLUVIA_MM', 'NIVEL_ALERTA', 'ESTADO_OPERATIVO', 'FECHA_INICIO', 'FECHA_FIN']:
                val_str = str(fila[col]) if pd.notna(fila[col]) else "-"
                pnt.extendeddata.newdata(name=str(col), value=val_str)
                
    c2.download_button("📍 Descargar KML (Google Earth)", kml.kml(), "Reporte_Relaves.kml", use_container_width=True)
