# =========================================================================================
# SCRIPT DIDÁCTICO DE PYQGIS: DETECTOR DE ZONAS DE SOMBRA EN REDES DE INCENDIOS (VERSIÓN BLINDADA)
# Nivel: Básico / Intermedio - Uso de geometrías nativas en memoria
# =========================================================================================

from qgis.processing import alg
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm, 
                       QgsProcessingParameterFeatureSource, 
                       QgsProcessingParameterVectorDestination,
                       QgsGeometry,
                       QgsFeature,
                       QgsFields,
                       QgsVectorLayer,
                       QgsWkbTypes)
import processing

class SombraBocasIncendio(QgsProcessingAlgorithm):
    BOCAS = 'BOCAS'
    RED = 'RED'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        # Configuración de los parámetros de la interfaz gráfica
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BOCAS,
                'Capa de bocas de incendio (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.RED,
                'Capa de red de abastecimiento (Líneas)',
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                'Zonas sin cobertura (Nuevas bocas necesarias)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # ---------------------------------------------------------------------------------
        # PASO 1 Y 2: BUFFER Y DISOLUCIÓN DE BOCAS DE INCENDIO
        # ---------------------------------------------------------------------------------
        feedback.pushInfo("1/4: Generando áreas de cobertura de 180m...")
        buffer_bocas = processing.run("native:buffer", {
            'INPUT': parameters[self.BOCAS],
            'DISTANCE': 180,
            'SEGMENTS': 25,
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        feedback.pushInfo("2/4: Agrupando y disolviendo coberturas...")
        coobertura_total = processing.run("native:dissolve", {
            'INPUT': buffer_bocas,
            'FIELD': [],
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']

        # ---------------------------------------------------------------------------------
        # PASO 3: ENVOLVENTE CONVEXA PURA EN MEMORIA (BLINDADA CONTRA ERRORES)
        # ---------------------------------------------------------------------------------
        feedback.pushInfo("3/4: Calculando área de cobertura global de la red en memoria...")
        
        # Accedemos directamente a la capa de líneas proporcionada por el usuario
        red_layer = self.parameterAsSource(parameters, self.RED, context)
        
        # Inicializamos un objeto de geometría vacío que servirá como contenedor global
        geometria_combinada = QgsGeometry()
        
        # Recorremos todas las líneas (tuberías) de la red una a una mediante un bucle iterador
        for feature in red_layer.getFeatures():
            if feature.hasGeometry():
                # Vamos fusionando matemáticamente la geometría de cada línea en nuestro contenedor
                if geometria_combinada.isEmpty():
                    geometria_combinada = QgsGeometry(feature.geometry())
                else:
                    geometria_combinada = geometria_combinada.combine(feature.geometry())
        
        # Una vez unificadas todas las líneas en una única entidad geométrica gigante,
        # calculamos su envolvente convexa global (Convex Hull) directamente con funciones matemáticas de la API.
        envolvente_convexa = geometria_combinada.convexHull()
        
        # Para poder pasarle este polígono al siguiente algoritmo de corte de QGIS, 
        # creamos una capa vectorial temporal en memoria ("memory") de tipo Polígono 
        # que comparta el mismo Sistema de Referencia Espacial (CRS) de la red de agua.
        crs_red = red_layer.sourceCrs().authid()
        capa_memoria_red = QgsVectorLayer(f"Polygon?crs={crs_red}", "area_servicio_temporal", "memory")
        proveedor_datos = capa_memoria_red.dataProvider()
        
        # Creamos un objeto espacial formal, le asignamos la geometría calculada y la inyectamos en la capa temporal
        objeto_envolvente = QgsFeature()
        objeto_envolvente.setGeometry(envolvente_convexa)
        proveedor_datos.addFeatures([objeto_envolvente])

        # ---------------------------------------------------------------------------------
        # PASO 4: CALCULO DE LA DIFERENCIA (ZONAS DE SOMBRA)
        # ---------------------------------------------------------------------------------
        feedback.pushInfo("4/4: Calculando zonas sin cobertura (Resta)...")
        
        # Ejecutamos la resta final comparando nuestra capa en memoria contra los buffers disueltos
        resultado = processing.run("native:difference", {
            'INPUT': capa_memoria_red,             # La capa de polígono que creamos dinámicamente con Python
            'OVERLAY': coobertura_total,
            'GRID_SIZE': None,
            'OUTPUT': parameters[self.OUTPUT]
        }, context=context, feedback=feedback)

        return {self.OUTPUT: resultado['OUTPUT']}

    def name(self):
        return 'hidrantes_zonasombrabocasincendio'

    def displayName(self):
        return 'Hidrantes - Detectar zona sin bocas de incendio'

    def group(self):
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        return 'aquavall_abastecimiento'

    def createInstance(self):
        return SombraBocasIncendio()
