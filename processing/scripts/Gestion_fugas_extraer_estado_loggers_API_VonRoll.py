import os
import requests
import json
from dotenv import load_dotenv

from qgis.core import (
    QgsProcessing,
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


class ExtractLoggersInfraportAlgorithm(QgsProcessingAlgorithm):

    OUTPUT = "OUTPUT"

    def tr(self, string):
        return string

    def createInstance(self):
        return ExtractLoggersInfraportAlgorithm()

    def name(self):
        return "extraer_loggers_infraport"

    def displayName(self):
        return self.tr("Fugas - Extraer estado loggers API VonRoll")

    def group(self):
        return self.tr("Aquavall - Abastecimiento")

    def groupId(self):
        return "aquavall_abastecimiento"

    def shortHelpString(self):
        return self.tr("Consulta la API de Infraport, reproyecta coordenadas a EPSG:25830 y genera una capa de puntos.")

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Capa de salida (vacío = capa temporal)"),
                type=QgsProcessing.TypeVectorPoint
            )
        )

    def processAlgorithm(self, parameters, context, feedback):

        try:
            # 1. Cargar .env
            ruta_env = r"D:\_Jupyter\Gestion fugas localizadores\API Infraport VonRoll\.env"
            if os.path.exists(ruta_env):
                load_dotenv(ruta_env, override=True)
                
            else:
                raise Exception(f"No se encontró archivo .env en: {ruta_env}")

            api_user = os.getenv("API_USER")
            api_password = os.getenv("API_PASSWORD")
            customer_id = os.getenv("API_CUSTOMER")

            if not api_user or not api_password or not customer_id:
                raise Exception("Faltan API_USER, API_PASSWORD o API_CUSTOMER en el .env")

            base_url = "https://api.infraport.world/ifp/v1"
            login_url = f"{base_url}/api/sf/auth/login"

            # 2. LOGIN → obtener token
            feedback.pushInfo("Solicitando token de acceso a Infraport...")

            login_payload = {
                "username": api_user,
                "password": api_password
            }

            # login_response = requests.post(login_url, json=login_payload, timeout=30)
            # login_response = requests.post(login_url, data=login_payload, timeout=30)
            # login_response = requests.post(login_url, files=login_payload, timeout=30)
            
            headers_login = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            login_response = requests.post(
                login_url,
                data=json.dumps(login_payload),   # JSON manual
                headers=headers_login,
                timeout=30
            )
            
            
            if login_response.status_code != 200:
                raise Exception(f"Error autenticación: {login_response.status_code} → {login_response.text}")

            login_data = login_response.json()
            token_info = login_data.get("token", {})
            access_token = token_info.get("access_token")

            if not access_token:
                raise Exception("No se pudo extraer access_token del login.")

            # 3. Consulta de loggers
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            devices_url = f"{base_url}/api/sf/customer/{customer_id}/loggers/list/compact"

            feedback.pushInfo("Consultando lista de loggers...")

            devices_response = requests.get(devices_url, headers=headers, timeout=30)

            if devices_response.status_code != 200:
                raise Exception(f"Error al obtener loggers: {devices_response.status_code}")

            loggers = devices_response.json()

            if not isinstance(loggers, list) or len(loggers) == 0:
                feedback.pushInfo("La API respondió correctamente pero no hay loggers.")
                return {self.OUTPUT: None}

            # 4. Detectar columnas dinámicas
            columnas = set()
            for item in loggers:
                columnas.update(item.keys())

            # Campos obligatorios
            columnas_latlon = ["latitude", "longitude"]
            for c in columnas_latlon:
                if c not in columnas:
                    raise Exception(f"El JSON no contiene el campo obligatorio: {c}")

            columnas = sorted(list(columnas))

            # 5. Reproyección
            crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            crs_utm30 = QgsCoordinateReferenceSystem("EPSG:25830")
            transform = QgsCoordinateTransform(crs_wgs84, crs_utm30, QgsProject.instance())

            # 6. Crear estructura de campos
            fields = QgsFields()
            fields.append(QgsField("latitude", QVariant.Double))
            fields.append(QgsField("longitude", QVariant.Double))
            fields.append(QgsField("X", QVariant.Double))
            fields.append(QgsField("Y", QVariant.Double))

            for col in columnas:
                if col not in ["latitude", "longitude"]:
                    fields.append(QgsField(col, QVariant.String))

            # 7. Crear capa destino
            (sink, dest_id) = self.parameterAsSink(
                parameters,
                self.OUTPUT,
                context,
                fields,
                QgsWkbTypes.Point,
                crs_utm30
            )

            if sink is None:
                raise Exception("No se pudo crear la capa de salida.")

            # 8. Insertar entidades
            for item in loggers:

                try:
                    lat = float(item.get("latitude"))
                    lon = float(item.get("longitude"))
                except:
                    continue

                p_wgs = QgsPointXY(lon, lat)
                p_utm = transform.transform(p_wgs)

                feat = QgsFeature()
                feat.setGeometry(QgsGeometry.fromPointXY(p_utm))

                atributos = [lat, lon, p_utm.x(), p_utm.y()]

                for col in columnas:
                    if col not in ["latitude", "longitude"]:
                        atributos.append(str(item.get(col, "")))

                feat.setAttributes(atributos)
                sink.addFeature(feat, QgsFeatureSink.FastInsert)

            feedback.pushInfo(f"¡Éxito! Se han procesado {len(loggers)} loggers de Infraport.")
            return {self.OUTPUT: dest_id}

        except Exception as e:
            # feedback.reportError(f"ERROR: {str(e)}", fatal=True)
            feedback.reportError(f"ERROR: {str(e)}")
            raise e