# =========================================================================================
# SCRIPT DIDÁCTICO DE PYQGIS: MAPA DE COBERTURA DE BOCAS DE INCENDIO (ENFOQUE OPTIMIZADO)
# Nivel: Básico - Generación directa de áreas de servicio continuas sin sobrecoste de red
# =========================================================================================

from qgis.processing import alg
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm, 
                       QgsProcessingParameterFeatureSource, 
                       QgsProcessingParameterVectorDestination)
import processing

class CoberturaBocasIncendio(QgsProcessingAlgorithm):
    BOCAS = 'BOCAS'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        # ---------------------------------------------------------------------------------
        # CONFIGURACIÓN DE LA INTERFAZ GRÁFICA SIMPLIFICADA
        # ---------------------------------------------------------------------------------
        # Ahora solo necesitamos un desplegable para los puntos y un buscador para la salida.
        
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BOCAS,
                'Capa de bocas de incendio (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                'Superficie final con cobertura de bomberos (Polígonos)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # ---------------------------------------------------------------------------------
        # EL NUEVO MOTOR DEL GEOPROCESO: RÁPIDO Y DIRECTO
        # ---------------------------------------------------------------------------------
        
        # PASO 1: Generar las áreas de influencia individuales de 180 metros.
        feedback.pushInfo("1/2: Calculando radios de cobertura de 180 metros alrededor de cada boca...")
        
        # Nota didáctica: Volvemos a usar 'TEMPORARY_OUTPUT' porque este buffer intermedio 
        # con círculos solapados no es nuestro producto final.
        buffer_bocas = processing.run("native:buffer", {
            'INPUT': parameters[self.BOCAS],       # Capa de hidrantes del alumno
            'DISTANCE': 180,                       # Radio de acción estándar para mangueras
            'SEGMENTS': 25,                        # Definición geométrica de las curvas
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': False,                     # Dejamos en falso para procesar rápido en paralelo
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        # PASO 2: Disolución global. 
        feedback.pushInfo("2/2: Fusionando solapes para crear las superficies de acceso...")
        
        # Este paso toma todos los círculos que se solapan y los fusiona en polígonos continuos.
        # Las zonas aisladas quedarán como islas de cobertura independientes.
        # Nota didáctica: Dirigimos el resultado directamente a parameters[self.OUTPUT] para volcar
        # los datos en el archivo Shapefile definitivo del alumno.
        resultado = processing.run("native:dissolve", {
            'INPUT': buffer_bocas,
            'FIELD': [],                           # Disuelve todo sin importar los atributos
            'OUTPUT': parameters[self.OUTPUT]      # Archivo final del alumno
        }, context=context, feedback=feedback)

        # Retornamos el diccionario para que QGIS cargue la capa automáticamente en el panel de capas.
        return {self.OUTPUT: resultado['OUTPUT']}

    def name(self):
        return 'hidrantes_coberturabocas'

    def displayName(self):
        return 'Hidrantes - Calcular cobertura bocas de incendio general'

    def group(self):
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        return 'aquavall_abastecimiento'

    def createInstance(self):
        return CoberturaBocasIncendio()
