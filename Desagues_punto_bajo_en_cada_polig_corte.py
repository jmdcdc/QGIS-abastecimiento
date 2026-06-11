from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsFeatureRequest,
    QgsWkbTypes,
    QgsFeature,
    QgsGeometry,
    QgsFields,
    QgsField,
    QgsSpatialIndex,
    QgsPointXY,
    QgsFeatureSink
)
from PyQt5.QtCore import QVariant

## =========================================================================
## DEFINICIÓN DE LA CLASE DEL ALGORITMO
## =========================================================================
class PuntoMasBajoPoligonoCorte(QgsProcessingAlgorithm):
    
    # Definición de constantes para identificar los parámetros de entrada y salida
    INPUT_TRAMOS = 'INPUT_TRAMOS'
    FIELD_ID_CORTE = 'FIELD_ID_CORTE'
    INPUT_VERTICES = 'INPUT_VERTICES'
    FIELD_COTA = 'FIELD_COTA'
    INPUT_VALVULAS = 'INPUT_VALVULAS'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        """
        Aquí se definen los parámetros de entrada que solicitará la interfaz gráfica
        y los elementos de salida del algoritmo.
        """
        ## PARÁMETROS DE ENTRADA
        # 1. Capa de tramos de red (Líneas / Multilíneas)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_TRAMOS,
                'Tema de tramos de red (Multilíneas)',
                [QgsProcessing.TypeVectorLine]
            )
        )
        
        # 2. Campo identificador del polígono de corte en la capa de tramos
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_ID_CORTE,
                'Campo ID de Polígono de Corte (en Tramos)',
                parentLayerParameterName=self.INPUT_TRAMOS,
                type=QgsProcessingParameterField.Any
            )
        )

        # 3. Capa de vértices altimétricos (Puntos)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_VERTICES,
                'Tema de vértices altimétricos (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )

        # 4. Campo de la cota altimétrica en la capa de vértices
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_COTA,
                'Campo con el valor de Cota Altimétrica',
                parentLayerParameterName=self.INPUT_VERTICES,
                type=QgsProcessingParameterField.Numeric
            )
        )

        # 5. Capa de válvulas de desagüe (Puntos)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_VALVULAS,
                'Tema de válvulas de desagüe (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )

        ## PARÁMETRO DE SALIDA
        # 6. Definición de la capa final que contendrá los puntos más bajos
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                'Punto más bajo por polígono de corte'
            )
        )

    ## =========================================================================
    ## METADATOS Y AYUDA CONTEXTUAL
    ## =========================================================================
    def name(self):
        return 'punto_mas_bajo_poligono_corte'

    def displayName(self):
        return 'Desagues – Punto mas bajo en cada polígono de corte'

    def group(self):
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        return 'aquavall_abastecimiento'

    def shortHelpString(self):
        """
        Texto de ayuda contextual que aparece en el panel lateral derecho.
        """
        return """<b>Descripción de la herramienta:</b><br>
        Este algoritmo procesa los tramos de red y extrae sus vértices geométricos estructurándolos por Polígono de Corte.<br><br>
        <b>Funcionamiento:</b><br>
        1. Extrae los vértices de los tramos de red heredando el ID del Polígono de Corte.<br>
        2. Realiza un enlace espacial con la capa de vértices altimétricos para rescatar el valor de la cota.<br>
        3. Evalúa y selecciona únicamente el punto con la cota más baja de cada Polígono de Corte.<br><br>
        <i>Nota: Se generan índices espaciales automáticos de no existir para optimizar el proceso.</i>"""

    def createInstance(self):
        return PuntoMasBajoPoligonoCorte()

    ## =========================================================================
    ## PROCESAMIENTO PRINCIPAL
    ## =========================================================================
    def processAlgorithm(self, parameters, context, feedback):
        # Obtención de los objetos de las capas y campos a partir de los parámetros
        tramos_source = self.parameterAsSource(parameters, self.INPUT_TRAMOS, context)
        id_corte_field = self.parameterAsString(parameters, self.FIELD_ID_CORTE, context)
        
        vertices_source = self.parameterAsSource(parameters, self.INPUT_VERTICES, context)
        cota_field = self.parameterAsString(parameters, self.FIELD_COTA, context)
        
        # Capa de válvulas requerida por la interfaz
        valvulas_source = self.parameterAsSource(parameters, self.INPUT_VALVULAS, context)

        ## 1. CONSTRUCCIÓN DE ÍNDICES ESPACIALES (Optimización)
        feedback.pushInfo("Inicializando índices espaciales...")
        # Inicializa el índice espacial de los vértices altimétricos
        index_vertices = QgsSpatialIndex(vertices_source.getFeatures())
        
        # Inicializa también el índice de tramos solicitado por el enunciado
        index_tramos = QgsSpatialIndex(tramos_source.getFeatures())

        ## 2. ORDENACIÓN Y EXTRACCIÓN DE VÉRTICES POR POLÍGONO DE CORTE
        feedback.pushInfo("Extrayendo vértices de los tramos de red...")
        
        # Diccionario para agrupar los puntos según su ID de Polígono de Corte
        puntos_por_grupo = {}

        # Configuramos la solicitud para ordenar los tramos por el campo del ID de corte
        request = QgsFeatureRequest()
        request.setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause(id_corte_field, ascending=True)]))

        # Recorremos los tramos de red ordenados por el campo especificado
        for feature_tramo in tramos_source.getFeatures(request):
            if feedback.isCanceled():
                return {}

            id_corte = feature_tramo.attribute(id_corte_field)
            geom_linea = feature_tramo.geometry()

            if geom_linea.isNull():
                continue

            # Extraemos todos los vértices de la geometría (líneas y multilíneas)
            for punto_geom in geom_linea.vertices():
                pt_xy = QgsPointXY(punto_geom)
                
                ## 3. ENLACE ESPACIAL CON VÉRTICES ALTIMÉTRICOS
                # Obtiene el ID del vecino más cercano
                ids_cercanos = index_vertices.nearestNeighbor(pt_xy, 1)
                
                cota_detectada = None
                if ids_cercanos:
                    req_fid = QgsFeatureRequest().setFilterFid(ids_cercanos[0])
                    for feat_vert in vertices_source.getFeatures(req_fid):
                        cota_detectada = feat_vert.attribute(cota_field)
                
                # Si no se encuentra cota o es nula, omitimos el punto
                if cota_detectada is None or cota_detectada == QVariant():
                    continue
                
                try:
                    cota_float = float(cota_detectada)
                except ValueError:
                    continue 

                # Clasificamos el punto y su cota en el diccionario
                if id_corte not in puntos_por_grupo:
                    puntos_por_grupo[id_corte] = []
                
                puntos_por_grupo[id_corte].append((pt_xy, cota_float))

        ## 4. CREACIÓN DE LA CAPA DE SALIDA (SINK)
        fields = QgsFields()
        
        idx_campo_origen = tramos_source.fields().indexFromName(id_corte_field)
        if idx_campo_origen >= 0:
            tipo_id_corte = tramos_source.fields().at(idx_campo_origen).type()
        else:
            tipo_id_corte = QVariant.String
            
        fields.append(QgsField(id_corte_field, tipo_id_corte))
        fields.append(QgsField(cota_field, QVariant.Double))

        # Corrección: Uso correcto de parameterAsSink en lugar de addFeatureToSink
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.Point,
            tramos_source.sourceCrs()
        )

        ## 5. SELECCIÓN DEL PUNTO MÁS BAJO POR CADA GRUPO
        feedback.pushInfo("Filtrando el punto más bajo para cada polígono de corte...")
        
        for id_corte, lista_puntos in puntos_por_grupo.items():
            if feedback.isCanceled():
                return {}

            # Ordenamos la lista usando estrictamente el índice de la cota float
            lista_puntos.sort(key=lambda x: x[1])
            
            # Extraemos el primer elemento (punto con menor valor de cota)
            punto_mas_bajo, menor_cota = lista_puntos[0]

            nueva_feature = QgsFeature(fields)
            nueva_feature.setGeometry(QgsGeometry.fromPointXY(punto_mas_bajo))
            nueva_feature.setAttribute(id_corte_field, id_corte)
            nueva_feature.setAttribute(cota_field, menor_cota)

            sink.addFeature(nueva_feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}
