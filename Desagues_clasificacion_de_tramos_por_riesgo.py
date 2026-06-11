# -*- coding: utf-8 -*-

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsSpatialIndex,
    QgsGeometry,
    QgsProcessing,
    QgsFeatureSink
)
from PyQt5.QtCore import QVariant

## =========================================================================
## BLOQUE 1: DEFINICIÓN DE LA ESTRUCTURA Y CONFIGURACIÓN DEL ALGORITMO
## =========================================================================

class ClasificacionRiesgoDesaguesAlgo(QgsProcessingAlgorithm):
    
    INPUT_TRAMOS = 'INPUT_TRAMOS'
    FIELD_TRAMOS_ID = 'FIELD_TRAMOS_ID'
    INPUT_PTOS_BAJOS = 'INPUT_PTOS_BAJOS'
    FIELD_PTOS_BAJOS_ID = 'FIELD_PTOS_BAJOS_ID'
    INPUT_VALVULAS = 'INPUT_VALVULAS'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'clasificacion_tramos_riesgo_desagues'

    def displayName(self):
        return 'Desagues – Clasificacion de tramos por riesgo'

    def group(self):
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        return 'aquavall_abastecimiento'

    def shortHelpString(self):
        return (
            "<h3>Descripción</h3>"
            "Este algoritmo clasifica los tramos de red según el riesgo de vaciado:<br>"
            "<ul>"
            "<li><b>Bajo:</b> Polígonos de corte con desagüe situado exactamente en su punto más bajo.</li>"
            "<li><b>Medio:</b> Polígonos de corte con desagüe, pero no situado en el punto más bajo.</li>"
            "<li><b>Alto:</b> Polígonos de corte que carecen de desagüe (requieren bombeo o más tiempo).</li>"
            "</ul>"
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_TRAMOS,
            'Tema de tramos de red (Multilíneas)',
            [QgsProcessing.TypeVectorLine]
        ))
        
        self.addParameter(QgsProcessingParameterField(
            self.FIELD_TRAMOS_ID,
            'Campo ID Polígono Corte (Tramos)',
            parentLayerParameterName=self.INPUT_TRAMOS
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_PTOS_BAJOS,
            'Tema de puntos bajos (Puntos)',
            [QgsProcessing.TypeVectorPoint]
        ))
        
        self.addParameter(QgsProcessingParameterField(
            self.FIELD_PTOS_BAJOS_ID,
            'Campo ID Polígono Corte (Puntos Bajos)',
            parentLayerParameterName=self.INPUT_PTOS_BAJOS
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_VALVULAS,
            'Tema de válvulas de desagüe (Puntos)',
            [QgsProcessing.TypeVectorPoint]
        ))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            'Resultado de la clasificación de tramos'
        ))

    def createInstance(self):
        return ClasificacionRiesgoDesaguesAlgo()

## =========================================================================
## BLOQUE 2: EJECUCIÓN LÓGICA DEL PROCESO Y ANÁLISIS ESPACIAL
## =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        tramos_source = self.parameterAsSource(parameters, self.INPUT_TRAMOS, context)
        campo_tramos_id = self.parameterAsString(parameters, self.FIELD_TRAMOS_ID, context)
        
        ptos_bajos_source = self.parameterAsSource(parameters, self.INPUT_PTOS_BAJOS, context)
        campo_ptos_bajos_id = self.parameterAsString(parameters, self.FIELD_PTOS_BAJOS_ID, context)
        
        valvulas_source = self.parameterAsSource(parameters, self.INPUT_VALVULAS, context)

        # -----------------------------------------------------------------
        # COMPROBACIÓN Y CONSTRUCCIÓN DE ÍNDICES ESPACIALES
        # -----------------------------------------------------------------
        feedback.pushInfo("Evaluando y construyendo índices espaciales...")
        
        index_tramos = QgsSpatialIndex(tramos_source.getFeatures())
        index_valvulas = QgsSpatialIndex(valvulas_source.getFeatures())

        # -----------------------------------------------------------------
        # ARREGLO: CACHEADO DE VÁLVULAS EN MEMORIA
        # -----------------------------------------------------------------
        # Mapeamos los IDs a geometrías para prescindir de llamadas directas a la fuente
        dict_valvulas = {v.id(): v.geometry() for v in valvulas_source.getFeatures()}

        # -----------------------------------------------------------------
        # PREPARACIÓN DE LA ESTRUCTURA DE LA CAPA DE SALIDA
        # -----------------------------------------------------------------
        fields = QgsFields()
        fields.append(tramos_source.fields().field(campo_tramos_id))
        fields.append(QgsField("rie_desg", QVariant.String, len=10))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, 
            tramos_source.wkbType(), tramos_source.sourceCrs()
        )

        dict_tramos = {}
        idx_original_id = tramos_source.fields().indexOf(campo_tramos_id)
        
        for feat in tramos_source.getFeatures():
            id_poligono = feat.attribute(idx_original_id)
            nueva_feat = QgsFeature(fields)
            nueva_feat.setGeometry(feat.geometry())
            nueva_feat.setAttributes([id_poligono, ""])
            dict_tramos[feat.id()] = {
                'feature': nueva_feat,
                'id_poligono': id_poligono
            }

        poligonos_riesgo_bajo = set()
        poligonos_riesgo_medio = set()
        tolerancia = 0.1 

        # -----------------------------------------------------------------
        # PROCESAMIENTO 1: ENLACE ESPACIAL VÁLVULAS -> TRAMOS (RIESGO MEDIO)
        # -----------------------------------------------------------------
        feedback.pushInfo("Buscando válvulas de desagüe cercanas a los tramos de red...")
        for v_id, geom_valvula in dict_valvulas.items():
            ids_candidatos = index_tramos.intersects(geom_valvula.boundingBox().buffered(tolerancia))
            
            for tramo_id in ids_candidatos:
                geom_tramo = dict_tramos[tramo_id]['feature'].geometry()
                if geom_tramo.distance(geom_valvula) <= tolerancia:
                    id_pol = dict_tramos[tramo_id]['id_poligono']
                    poligonos_riesgo_medio.add(id_pol)

        # -----------------------------------------------------------------
        # PROCESAMIENTO 2: ENLACE ESPACIAL PUNTOS BAJOS + VÁLVULAS -> TRAMOS (RIESGO BAJO)
        # -----------------------------------------------------------------
        feedback.pushInfo("Filtrando puntos bajos que coinciden con válvulas de desagüe...")
        for pto_bajo in ptos_bajos_source.getFeatures():
            geom_pto_bajo = pto_bajo.geometry()
            valvulas_candidatas = index_valvulas.intersects(geom_pto_bajo.boundingBox().buffered(tolerancia))
            
            coincide_con_desague = False
            for v_id in valvulas_candidatas:
                # Corrección: Consultamos el diccionario indexado en memoria en lugar de la fuente de datos
                geom_valvula = dict_valvulas.get(v_id)
                if geom_valvula and geom_pto_bajo.distance(geom_valvula) <= tolerancia:
                    coincide_con_desague = True
                    break
            
            if coincide_con_desague:
                tramos_candidatos_bajo = index_tramos.intersects(geom_pto_bajo.boundingBox().buffered(tolerancia))
                for tramo_id in tramos_candidatos_bajo:
                    geom_tramo = dict_tramos[tramo_id]['feature'].geometry()
                    if geom_tramo.distance(geom_pto_bajo) <= tolerancia:
                        id_pol = dict_tramos[tramo_id]['id_poligono']
                        poligonos_riesgo_bajo.add(id_pol)

## =========================================================================
## BLOQUE 3: ASIGNACIÓN FINAL DE RIESGOS Y ESCRITURA EN CAPA DE SALIDA
## =========================================================================

        feedback.pushInfo("Asignando clasificaciones finales de riesgo a los tramos...")
        
        for tramo_id, info in dict_tramos.items():
            id_pol = info['id_poligono']
            
            if id_pol in poligonos_riesgo_bajo:
                valor_riesgo = "Bajo"
            elif id_pol in poligonos_riesgo_medio:
                valor_riesgo = "Medio"
            else:
                valor_riesgo = "Alto"
            
            info['feature'].setAttribute(1, valor_riesgo)
            # CORRECCIÓN: Se cambia la clase a QgsFeatureSink
            sink.addFeature(info['feature'], QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}
