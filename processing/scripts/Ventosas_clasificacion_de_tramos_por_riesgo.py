from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessing,
    QgsFeatureRequest,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsSpatialIndex,
    QgsFeatureSink
)
from PyQt5.QtCore import QVariant
from collections import Counter

## =========================================================================
## CONFIGURACIÓN DE LA HERRAMIENTA EN LA CAJA DE PROCESOS
## =========================================================================

class ClasificacionRiesgoVentosas(QgsProcessingAlgorithm):
    INPUT_TRAMOS = 'INPUT_TRAMOS'
    FIELD_TRAMOS_ID = 'FIELD_TRAMOS_ID'
    INPUT_PUNTOS_ALTOS = 'INPUT_PUNTOS_ALTOS'
    FIELD_PUNTOS_ALTOS_ID = 'FIELD_PUNTOS_ALTOS_ID'
    INPUT_VENTOSAS = 'INPUT_VENTOSAS'
    OUTPUT_TRAMOS_RIESGO = 'OUTPUT_TRAMOS_RIESGO'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_TRAMOS,
            'Capa de tramos de red (Multilínea)',
            [QgsProcessing.TypeVectorLine]
        ))
        
        self.addParameter(QgsProcessingParameterField(
            self.FIELD_TRAMOS_ID,
            'Campo ID Polígono de Corte en Tramos',
            parentLayerParameterName=self.INPUT_TRAMOS
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_PUNTOS_ALTOS,
            'Capa de puntos altos (Vértice más alto)',
            [QgsProcessing.TypeVectorPoint]
        ))

        self.addParameter(QgsProcessingParameterField(
            self.FIELD_PUNTOS_ALTOS_ID,
            'Campo ID Polígono de Corte en Puntos Altos',
            parentLayerParameterName=self.INPUT_PUNTOS_ALTOS
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_VENTOSAS,
            'Capa de ventosas o válvulas de aire (Puntos)',
            [QgsProcessing.TypeVectorPoint]
        ))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_TRAMOS_RIESGO,
            'Capa de tramos clasificados por riesgo'
        ))

    def name(self):
        return 'ventosas_clasificacion_tramos_riesgo'

    def displayName(self):
        return 'Ventosas – Clasificacion de tramos por riesgo'

    def group(self):
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        return 'aquavall_abastecimiento'

    def createInstance(self):
        return ClasificacionRiesgoVentosas()

## =========================================================================
## AYUDA CONTEXTUAL DE LA HERRAMIENTA
## =========================================================================

    def shortHelpString(self):
        return """<h3>Asignación de riesgo en tramos según la presencia de ventosas</h3>
        Este algoritmo clasifica los tramos de red en función del riesgo ante vaciados y llenados por averías:
        <ul>
        <li><b>Bajo:</b> Polígonos de corte con 2 o más ventosas instaladas, o con una única ventosa instalada exactamente en su punto más alto.</li>
        <li><b>Medio:</b> Polígonos de corte que disponen de una única ventosa, pero esta no se encuentra en el punto más alto del polígono.</li>
        <li><b>Alto:</b> Polígonos de corte que carecen por completo de ventosas, implicando mayores tiempos de evacuación y llenado de aire.</li>
        </ul>
        Las búsquedas espaciales operan con un umbral de tolerancia estricto de 10 centímetros."""

## =========================================================================
## NÚCLEO DEL ALGORITMO / EJECUCIÓN
## =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        tramos_source = self.parameterAsSource(parameters, self.INPUT_TRAMOS, context)
        id_campo_tramos = self.parameterAsString(parameters, self.FIELD_TRAMOS_ID, context)
        
        puntos_altos_source = self.parameterAsSource(parameters, self.INPUT_PUNTOS_ALTOS, context)
        id_campo_puntos = self.parameterAsString(parameters, self.FIELD_PUNTOS_ALTOS_ID, context)
        
        ventosas_source = self.parameterAsSource(parameters, self.INPUT_VENTOSAS, context)

        fields = QgsFields()
        fields.append(QgsField(id_campo_tramos, tramos_source.fields().field(id_campo_tramos).type()))
        fields.append(QgsField('rie_vent', QVariant.String, len=10))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_TRAMOS_RIESGO,
            context,
            fields,
            tramos_source.wkbType(),
            tramos_source.sourceCrs()
        )

        ## =================================================================
        ## CONSTRUCCIÓN DE ÍNDICES ESPACIALES
        ## =================================================================
        feedback.pushInfo("Construyendo índices espaciales...")
        
        index_ventosas = QgsSpatialIndex(ventosas_source.getFeatures())
        index_tramos = QgsSpatialIndex(tramos_source.getFeatures())

        ## =================================================================
        ## ENLACE ESPACIAL: CONTABILIZAR VENTOSAS POR POLÍGONO DE CORTE
        ## =================================================================
        feedback.pushInfo("Contabilizando ventosas por polígono de corte...")
        contador_ventosas_poligono = Counter()

        for ventosa in ventosas_source.getFeatures():
            geom_ventosa = ventosa.geometry()
            if not geom_ventosa or geom_ventosa.isEmpty():
                continue
            
            tramos_cercanos_ids = index_tramos.nearestNeighbor(geom_ventosa, 1, 0.1)
            if tramos_cercanos_ids:
                # CORRECCIÓN: Extraer el primer elemento entero de la lista devuelta por el índice
                request = tramos_source.getFeatures(QgsFeatureRequest().setFilterFid(tramos_cercanos_ids[0]))
                tramo_asociado = next(request, None)
                if tramo_asociado:
                    id_poligono = str(tramo_asociado[id_campo_tramos])
                    contador_ventosas_poligono[id_poligono] += 1

        ## =================================================================
        ## ENLACE ESPACIAL: COINCIDENCIA DE PUNTO ALTO CON VENTOSA
        ## =================================================================
        feedback.pushInfo("Evaluando coincidencia de puntos altos con ventosas...")
        poligonos_con_ventosa_en_punto_alto = set()

        for pt_alto in puntos_altos_source.getFeatures():
            geom_pto = pt_alto.geometry()
            if not geom_pto or geom_pto.isEmpty():
                continue
            
            ventosas_cercanas = index_ventosas.nearestNeighbor(geom_pto, 1, 0.1)
            if ventosas_cercanas:
                id_poligono = str(pt_alto[id_campo_puntos])
                poligonos_con_ventosa_en_punto_alto.add(id_poligono)

        ## =================================================================
        ## PROCESAMIENTO FINAL Y CLASIFICACIÓN DE RIESGOS
        ## =================================================================
        feedback.pushInfo("Asignando niveles de riesgo según cantidad y posición...")
        
        for tramo in tramos_source.getFeatures():
            geom_tramo = tramo.geometry()
            if not geom_tramo or geom_tramo.isEmpty():
                continue

            nuevo_tramo = QgsFeature()
            nuevo_tramo.setGeometry(geom_tramo)
            
            id_actual_raw = tramo[id_campo_tramos]
            id_actual_str = str(id_actual_raw)
            
            num_ventosas = contador_ventosas_poligono.get(id_actual_str, 0)
            tiene_ventosa_en_punto_alto = id_actual_str in poligonos_con_ventosa_en_punto_alto
            
            if num_ventosas >= 2 or (num_ventosas == 1 and tiene_ventosa_en_punto_alto):
                riesgo = 'Bajo'
            elif num_ventosas == 1:
                riesgo = 'Medio'
            else:
                riesgo = 'Alto'
            
            nuevo_tramo.setAttributes([id_actual_raw, riesgo])
            sink.addFeature(nuevo_tramo, QgsFeatureSink.FastInsert)

        return {self.OUTPUT_TRAMOS_RIESGO: dest_id}
