import os
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

from qgis.core import (
    QgsProcessing,  # <--- IMPORTACIÓN CORREGIDA
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSink,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsWkbTypes,
    QgsFeatureSink
)
from PyQt5.QtCore import QVariant

class ExtractLoggersAlgorithm(QgsProcessingAlgorithm):
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return string

    def createInstance(self):
        return ExtractLoggersAlgorithm()

    def name(self):
        return 'extraer_loggers_api_multiformato'

    def displayName(self):
        return self.tr('Fugas - Extraer estado loggers API Hidromejoras')

    def group(self):
        return self.tr('Aquavall - Abastecimiento')

    def groupId(self):
        return 'aquavall_abastecimiento'

    def shortHelpString(self):
        return self.tr('Consulta la API, calcula coordenadas EPSG:25830 y guarda el resultado en el formato elegido (GeoPackage, Shapefile, etc.) cargándolo en el mapa.')

    def flags(self):
        # Fuerza a QGIS a ejecutar el script en el hilo principal para evitar bloqueos silenciosos
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def initAlgorithm(self, config=None):
        # Corrección del tipo de parámetro usando la clase QgsProcessing correcta
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Capa de salida (Vacio para capa temporal / clic ... para elegir archivo o GDB)'),
                type=QgsProcessing.TypeVectorPoint
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        try:
            # 1. Cargar variables de entorno locales
            ruta_al_env = r"D:\_Jupyter\Gestion fugas localizadores\API HWE Hidromejoras\.env"
            if os.path.exists(ruta_al_env):
                load_dotenv(ruta_al_env, override=True)
            else:
                raise Exception(f"No se encontró el archivo .env en: {ruta_al_env}")

            api_user = os.getenv("API_USER")
            api_password = os.getenv("API_PASSWORD")

            if not api_user or not api_password:
                raise Exception("Error: Credenciales API_USER o API_PASSWORD ausentes en el .env.")

            # 2. Petición HTTP
            url = "https://api.permanetweb-grupomejoras.com/datagate/api/loggerapi.ashx"
            payload = {
                'action': 'getloggers',
                'username': api_user,
                'password': api_password,
                'software': 'APIDocumentation'
            }

            feedback.pushInfo("Conectando con la API externa...")
            response = requests.get(url, params=payload, timeout=30)

            if response.status_code != 200:
                raise Exception(f"Error en la petición API. Código HTTP: {response.status_code}")

            # 3. Parsing XML
            try:
                root = ET.fromstring(response.text)
            except Exception as xml_err:
                feedback.reportError(f"Contenido recibido no es XML válido: {response.text[:300]}")
                raise Exception(f"Fallo al parsear XML: {xml_err}")

            # 4. Procesamiento de elementos del XML
            lista_loggers = []
            todas_las_columnas = set()

            for logger in root.findall('logger'):
                fila_logger = {}
                for child in logger:
                    if child.tag != 'channels':
                        fila_logger[child.tag] = child.text if child.text is not None else ""
                
                channels_node = logger.find('channels')
                if channels_node is not None:
                    for channel in channels_node.findall('channel'):
                        ch_num = channel.attrib.get('number', '')
                        last_val = channel.find('lastValue')
                        fila_logger[f'ch_{ch_num}_val'] = last_val.text if (last_val is not None and last_val.text) else ""
                
                if 'latitude' in fila_logger and 'longitude' in fila_logger:
                    lista_loggers.append(fila_logger)
                    todas_las_columnas.update(fila_logger.keys())

            if not lista_loggers:
                feedback.pushInfo("La API respondió correctamente pero no se encontraron loggers con coordenadas válidas.")
                return {self.OUTPUT: None}

            todas_las_columnas.discard('latitude')
            todas_las_columnas.discard('longitude')
            columnas_ordenadas = sorted(list(todas_las_columnas))

            # 5. Configurar Reproyección a EPSG:25830
            crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            crs_utm30n = QgsCoordinateReferenceSystem("EPSG:25830")
            transformacion = QgsCoordinateTransform(crs_wgs84, crs_utm30n, QgsProject.instance())

            # 6. Definición de la estructura de campos
            fields = QgsFields()
            fields.append(QgsField('latitude', QVariant.Double))
            fields.append(QgsField('longitude', QVariant.Double))
            fields.append(QgsField('X', QVariant.Double))
            fields.append(QgsField('Y', QVariant.Double))
            
            for col in columnas_ordenadas:
                fields.append(QgsField(col, QVariant.String))

            # 7. Inicializar el sumidero físico/temporal de QGIS
            (sink, dest_id) = self.parameterAsSink(
                parameters,
                self.OUTPUT,
                context,
                fields,
                QgsWkbTypes.Point,
                crs_utm30n
            )

            if sink is None:
                raise Exception("Error interno de QGIS: No se pudo crear el almacén de destino (Sink).")

            # 8. Rellenar entidades geográficas
            for item in lista_loggers:
                try:
                    lat = float(item.get('latitude', 0))
                    lon = float(item.get('longitude', 0))
                except (ValueError, TypeError):
                    continue

                # Transformar geometría
                punto_wgs84 = QgsPointXY(lon, lat)
                punto_utm30n = transformacion.transform(punto_wgs84)

                # Construir objeto Feature
                feature = QgsFeature()
                feature.setGeometry(QgsGeometry.fromPointXY(punto_utm30n))
                
                # Asignar atributos emparejados
                atributos = [lat, lon, punto_utm30n.x(), punto_utm30n.y()]
                for col in columnas_ordenadas:
                    atributos.append(str(item.get(col, '')))
                
                feature.setAttributes(atributos)
                sink.addFeature(feature, QgsFeatureSink.FastInsert)

            feedback.pushInfo(f"¡Éxito! Se han procesado e insertado {len(lista_loggers)} loggers en la capa.")
            return {self.OUTPUT: dest_id}

        except Exception as e:
            feedback.reportError(f"ERROR CRÍTICO DURANTE LA EJECUCIÓN: {str(e)}", fatal=True)
            raise e