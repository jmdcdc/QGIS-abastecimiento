from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessingFeatureSource,
    QgsSpatialIndex,
    QgsFeature,
    QgsGeometry,
    QgsFields,
    QgsField,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsWkbTypes
)
from PyQt5.QtCore import QVariant

class VentosasPuntoAltoAlgorithm(QgsProcessingAlgorithm):
    
    TRAMOS = 'TRAMOS'
    CAMPO_POLIGONO = 'CAMPO_POLIGONO'
    VERTICES_ALTIMETRICOS = 'VERTICES_ALTIMETRICOS'
    CAMPO_COTA = 'CAMPO_COTA'
    VENTOSAS = 'VENTOSAS'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return string

    def createInstance(self):
        return VentosasPuntoAltoAlgorithm()

    def name(self):
        return 'ventosas_punto_mas_alto_en_cada_poligono_de_corte'

    def displayName(self):
        return self.tr('Ventosas – Punto mas alto en cada polígono de corte')

    def group(self):
        return self.tr('Aquavall - Abastecimiento')

    def groupId(self):
        return 'aquavall_abastecimiento'

    def shortHelpString(self):
        return self.tr(
            "<h3>Descripción</h3>"
            "Este algoritmo identifica el punto geográfico más alto para cada polígono de corte.<br><br>"
            "<h3>Funcionamiento</h3>"
            "1. Agrupa tramos y extrae vértices de forma unívoca por polígono de corte.<br>"
            "2. Resuelve conflictos en nodos compartidos analizando la topología del tramo.<br>"
            "3. Si hay empate en la cota máxima, prioriza la coincidencia con una ventosa existente."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.TRAMOS, self.tr('Tema de tramos de red (Multilíneas)'),
            [QgsProcessing.TypeVectorLine]))
        
        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_POLIGONO, self.tr('Campo identificador del polígono de corte'),
            parentLayerParameterName=self.TRAMOS))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.VERTICES_ALTIMETRICOS, self.tr('Tema de vértices altimétricos (Puntos)'),
            [QgsProcessing.TypeVectorPoint]))

        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_COTA, self.tr('Campo con el valor numérico de la cota'),
            parentLayerParameterName=self.VERTICES_ALTIMETRICOS, type=QgsProcessingParameterField.Numeric))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.VENTOSAS, self.tr('Tema de ventosas / válvulas de aire (Puntos)'),
            [QgsProcessing.TypeVectorPoint]))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Puntos más altos por polígono de corte')))

    def processAlgorithm(self, parameters, context, feedback):
        tramos_source = self.parameterAsSource(parameters, self.TRAMOS, context)
        campo_poligono = self.parameterAsString(parameters, self.CAMPO_POLIGONO, context)
        vertices_source = self.parameterAsSource(parameters, self.VERTICES_ALTIMETRICOS, context)
        campo_cota = self.parameterAsString(parameters, self.CAMPO_COTA, context)
        ventosas_source = self.parameterAsSource(parameters, self.VENTOSAS, context)
        
        fields = QgsFields()
        fields.append(QgsField(campo_poligono, QVariant.String))
        fields.append(QgsField(campo_cota, QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, 
            QgsWkbTypes.Point, tramos_source.sourceCrs()
        )

        # Índices espaciales
        feedback.pushInfo("Construyendo índice espacial para vértices altimétricos...")
        idx_vertices = QgsSpatialIndex(vertices_source.getFeatures())

        feedback.pushInfo("Construyendo índice espacial para ventosas...")
        idx_ventosas = QgsSpatialIndex()
        dict_ventosas = {}
        for feat_v in ventosas_source.getFeatures():
            idx_ventosas.addFeature(feat_v)
            dict_ventosas[feat_v.id()] = feat_v.geometry()

        # Almacenamiento intermedio indexado por coordenadas para evitar duplicados erróneos
        poligonos_puntos = {}

        feedback.pushInfo("Analizando geometría de tramos de red...")
        for feature_tramo in tramos_source.getFeatures():
            if feedback.isCanceled():
                break

            id_poligono = str(feature_tramo.attribute(campo_poligono))
            geom_tramo = feature_tramo.geometry()

            if geom_tramo.isNull():
                continue

            if id_poligono not in poligonos_puntos:
                poligonos_puntos[id_poligono] = {}

            # Extraer puntos del tramo actual
            vertices_geom = []
            if geom_tramo.isMultipart():
                for line in geom_tramo.asMultiPolyline():
                    for pt in line:
                        vertices_geom.append(pt)
            else:
                for pt in geom_tramo.asPolyline():
                    vertices_geom.append(pt)

            for pt in vertices_geom:
                # Clave única por coordenada para evitar almacenar duplicados en el mismo polígono
                coord_key = (round(pt.x(), 4), round(pt.y(), 4))
                
                if coord_key in poligonos_puntos[id_poligono]:
                    continue  # Ya procesado para este polígono

                v_geom = QgsGeometry.fromPointXY(pt)
                ids_cercanos = idx_vertices.nearestNeighbor(pt, 1)
                
                valor_cota = 0.0
                if ids_cercanos:
                    # CORRECCIÓN: Se extrae el primer elemento de la lista utilizando [0]
                    feat_iterator = vertices_source.getFeatures(QgsFeatureRequest().setFilterFid(ids_cercanos[0]))
                    try:
                        feat_vertice = next(feat_iterator)
                        valor_cota = float(feat_vertice.attribute(campo_cota))
                    except (StopIteration, ValueError, TypeError):
                        valor_cota = 0.0

                poligonos_puntos[id_poligono][coord_key] = {
                    'geom': v_geom,
                    'cota': valor_cota
                }

        ## --------------------------------------------------------------------
        ## BLOQUE: SELECCIÓN DEL PUNTO MÁS ALTO CON DISCRIMINACIÓN
        ## --------------------------------------------------------------------
        feedback.pushInfo("Filtrando el punto más alto por polígono de corte...")
        
        for id_poligono, dict_puntos in poligonos_puntos.items():
            lista_puntos = list(dict_puntos.values())
            if not lista_puntos:
                continue

            # 1. Ordenar descendente por cota
            lista_puntos.sort(key=lambda x: x['cota'], reverse=True)
            cota_maxima = lista_puntos[0]['cota']

            # 2. Quedarse con todos los que tengan la cota máxima real de este polígono
            puntos_maximos = [p for p in lista_puntos if p['cota'] == cota_maxima]

            punto_final = None

            # 3. Si hay empate, aplicar discriminación por la capa de ventosas
            if len(puntos_maximos) > 1:
                for p_max in puntos_maximos:
                    ids_ventosas_cercanas = idx_ventosas.intersects(p_max['geom'].boundingBox())
                    for v_id in ids_ventosas_cercanas:
                        geom_ventosa = dict_ventosas[v_id]
                        if p_max['geom'].equals(geom_ventosa):
                            punto_final = p_max
                            break
                    if punto_final:
                        break

            # 4. Si no hubo empate o ningún punto en empate coincidió con una ventosa
            if not punto_final:
                punto_final = puntos_maximos[0]

            # Registro de salida
            feat_max = QgsFeature()
            feat_max.setGeometry(punto_final['geom'])
            feat_max.setAttributes([id_poligono, punto_final['cota']])
            sink.addFeature(feat_max, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}
