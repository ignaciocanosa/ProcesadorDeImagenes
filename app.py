from flask import Flask, render_template, jsonify, request, send_file
import ee
import logging
from PIL import Image
from dotenv import load_dotenv
import os
import io
import json
import tempfile


load_dotenv()

# Configurar el registro de errores
logging.basicConfig(level=logging.DEBUG)

# Cargar el contenido de la variable de entorno
service_account_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

if not service_account_json:
    raise ValueError("La variable de entorno GOOGLE_APPLICATION_CREDENTIALS_JSON no está configurada.")

# Crear un archivo temporal con el contenido del JSON
with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_cred_file:
    temp_cred_file.write(service_account_json.encode())  # Escribir el contenido
    temp_cred_file_path = temp_cred_file.name  # Obtener la ruta del archivo

# Autenticar usando ServiceAccountCredentials
try:
    credentials = ee.ServiceAccountCredentials(None, temp_cred_file_path)
    ee.Initialize(credentials)
finally:
    # Eliminar el archivo temporal después de la inicialización
    os.remove(temp_cred_file_path)

# ee.Authenticate()
# ee.Initialize()

# Obtener la API Key de las variables de entorno
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html', google_api_key=GOOGLE_API_KEY)

# Función para calcular NDVI promedio punto por punto
def get_mean_ndvi_images(polygon_coords, start_date, end_date): 
    try:
        polygon = ee.Geometry.Polygon(polygon_coords)
        
        # Filtrar la colección de Sentinel-2
        sentinel_images = ee.ImageCollection('COPERNICUS/S2') \
            .filterDate(start_date, end_date) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 5)) \
            .filterBounds(polygon) \
            .select(['B8', 'B4'])

        # Calcular NDVI
        def add_ndvi(image):
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            return image.addBands(ndvi).clip(polygon)

        # Calcular NDVI y mapearlo
        with_ndvi = sentinel_images.map(add_ndvi)

        # Promedio NDVI punto por punto
        mean_ndvi_image = with_ndvi.mean().select('NDVI')

        # Obtener el valor del promedio de NDVI
        mean_ndvi = mean_ndvi_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=polygon,
            scale=10
        ).get('NDVI').getInfo()

        # Establecer la visualización con los colores deseados
        visualization_params = {
            'bands': ['NDVI'],
            'min': -1,
            'max': 1,
            'palette': ['blue', 'white', 'green']
        }

        # Visualización para la imagen TIFF
        ndvi_visualized = mean_ndvi_image.visualize(**visualization_params)

        # Generar URL de descarga para TIFF
        tiff_url = ndvi_visualized.getDownloadURL({
            'scale': 10,
            'region': polygon,
            'format': 'GeoTIFF'
        })

        # Generar la URL de la imagen PNG
        url_png = ndvi_visualized.getThumbURL({
            'dimensions': '1024x1024',
            'format': 'png'
        })

        # Fecha para el nombre del archivo
        date = start_date.replace('-', '')  # Generar una fecha base para el nombre del archivo
        filename = f"ndvi_{date}.tif"

        return url_png, tiff_url, filename, mean_ndvi

    except Exception as e:
        logging.error(f"Error al obtener la imagen NDVI: {e}")
        return None, None, None, None
    
# Función para calcular NDVI y seleccionar las imágenes con el máximo NDVI en el rango de fechas especificado
def get_max_ndvi_images(polygon_coords, start_date, end_date): 
    try:
        polygon = ee.Geometry.Polygon(polygon_coords)
        
        # Filtrar la colección de Sentinel-2
        sentinel_images = ee.ImageCollection('COPERNICUS/S2') \
            .filterDate(start_date, end_date) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 5)) \
            .filterBounds(polygon) \
            .select(['B8', 'B4'])

        # Calcular NDVI
        def add_ndvi(image):
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            return image.addBands(ndvi).clip(polygon)

        # Calcular NDVI y mapearlo
        with_ndvi = sentinel_images.map(add_ndvi)

        # Función para calcular la suma de NDVI dentro del polígono
        def add_ndvi_sum(image):
            ndvi_sum = image.select('NDVI').reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=polygon,
                scale=10
            ).get('NDVI')
            return image.set('NDVI_SUM', ndvi_sum)

        # Añadir la suma de NDVI a cada imagen
        with_ndvi_sum = with_ndvi.map(add_ndvi_sum)

        # Ordenar imágenes por la suma de NDVI y seleccionar la mejor
        max_ndvi_image = with_ndvi_sum.sort('NDVI_SUM', False).first()

        # Obtener el valor del promedio de NDVI
        mean_ndvi = max_ndvi_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=polygon,
            scale=10
        ).get('NDVI').getInfo()

        # Establecer la visualización con los colores deseados
        visualization_params = {
            'bands': ['NDVI'],
            'min': -1,
            'max': 1,
            'palette': ['blue', 'white', 'green']
        }

        # Visualización para la imagen TIFF
        ndvi_visualized = max_ndvi_image.visualize(**visualization_params)

        # Generar URL de descarga para TIFF
        tiff_url = ndvi_visualized.getDownloadURL({
            'scale': 10,
            'region': polygon,
            'format': 'GeoTIFF'
        })

        # Generar la URL de la imagen PNG
        url_png = ndvi_visualized.getThumbURL({
            'dimensions': '1024x1024',
            'format': 'png'
        })

        # Fecha para el nombre del archivo
        date = start_date.replace('-', '')  # Generar una fecha base para el nombre del archivo
        filename = f"ndvi_{date}.tif"

        return url_png, tiff_url, filename, mean_ndvi

    except Exception as e:
        logging.error(f"Error al obtener la imagen NDVI: {e}")
        return None, None, None, None



@app.route('/get-ndvi', methods=['POST'])
def fetch_ndvi():
    try:
        data = request.json
        logging.debug(f"Datos recibidos: {data}")
        campo_lote = data['field_name']+"_"+data['lot_name']
        polygon_coords = data['polygon']
        periods = data['periods']  # Cambiado para recibir una lista de períodos

        results = []
        logging.debug(f"Datos recibidos: {results}")
        for period in periods:
            start_date = period['start_date']
            end_date = period['end_date']
            png_url, tiff_url, filename, mean_ndvi = get_max_ndvi_images(polygon_coords, start_date, end_date)

            if png_url and tiff_url and filename:
                results.append({
                    'start_date': start_date,
                    'end_date': end_date,
                    'image_url': png_url,
                    'download_url': tiff_url,
                    'file_name': campo_lote+"_"+filename,
                    'mean_ndvi': mean_ndvi  # Promedio de NDVI
                })
            else:
                results.append({
                    
                    'start_date': start_date,
                    'end_date': end_date,
                    'error': 'No se pudo generar la imagen NDVI.'
                })
            logging.debug(f"Datos recibidos: {results}")
        return jsonify({'results': results})    
    except Exception as e:
        logging.error(f"Error en la solicitud /get-ndvi: {e}")
        return jsonify({'error': 'Error interno del servidor.'}), 500
    
@app.route('/get-ndvi-promedio', methods=['POST'])
def fetch_ndvi_promedio():
    try:
        data = request.json
        logging.debug(f"Datos recibidos: {data}")
        campo_lote = data['field_name']+"_"+data['lot_name']
        polygon_coords = data['polygon']
        periods = data['periods']  # Cambiado para recibir una lista de períodos

        results = []
        logging.debug(f"Datos recibidos: {results}")
        for period in periods:
            start_date = period['start_date']
            end_date = period['end_date']
            png_url, tiff_url, filename, mean_ndvi = get_mean_ndvi_images(polygon_coords, start_date, end_date)

            if png_url and tiff_url and filename:
                results.append({
                    'start_date': start_date,
                    'end_date': end_date,
                    'image_url': png_url,
                    'download_url': tiff_url,
                    'file_name': campo_lote+"_"+filename,
                    'mean_ndvi': mean_ndvi  # Promedio de NDVI
                })
            else:
                results.append({
                    
                    'start_date': start_date,
                    'end_date': end_date,
                    'error': 'No se pudo generar la imagen NDVI.'
                })
            logging.debug(f"Datos recibidos: {results}")
        return jsonify({'results': results})    
    except Exception as e:
        logging.error(f"Error en la solicitud /get-ndvi: {e}")
        return jsonify({'error': 'Error interno del servidor.'}), 500

if __name__ == '__main__':
    app.run(debug=True)